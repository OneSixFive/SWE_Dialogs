# Bead: Vocabulary Practice Consistency and Grading Contracts

## Status

Deferred follow-up. This bead documents the problem and implementation plan only. It does not change Vocabulary Interactor or Evaluator behavior yet.

## Problem

Vocabulary practice currently gives the model a bounded set of target definitions and the generated quiz, but it does not give every later model call a frozen, target-specific grading contract. It also does not pass enough detail about why an active target was selected for repetition.

That leaves several decisions to be recreated independently:

- which Swedish construction the English question is intended to elicit;
- which alternative translations are natural and acceptable;
- whether a correct translation actually demonstrates the selected target;
- which learner form caused the Evaluator to keep a target active;
- which corrective rule should remain consistent across the lesson, review feedback, and post-review evaluation.

The observed `byta ... mot` / `byta till` sequence demonstrates the failure mode:

1. The lesson explained that `byta den mot X` is idiomatic with a direct object, while `byta till X` works when focusing on the destination without that object.
2. The lesson Evaluator activated `Kan jag byta till en annan storlek?` after partial evidence.
3. Vocabulary selection passed the expression and mastery counters, but not the exact corrective distinction.
4. The quiz generated English sentences with direct objects even though the canonical target used the objectless `byta till` pattern.
5. Later Vocabulary Interactor calls reconstructed the rule differently and contradicted the lesson.

This is not just unavoidable model randomness. Perfect linguistic consistency is impossible, but the application currently asks separate calls to make decisions that should instead be fixed once and reused.

## Goals

- Keep learner-facing feedback internally consistent within a practice.
- Carry the actual reason for repetition from Evaluator into practice generation.
- Generate questions that naturally elicit the selected target construction.
- Accept natural alternative translations without falsely calling them wrong.
- Distinguish translation correctness from evidence that the learner demonstrated the intended target.
- Give the post-practice Evaluator the same contract used by the Interactor.
- Preserve current prompt-cache ordering and keep hidden grading metadata off the client.

## Non-goals

- Eliminate every subjective language judgment.
- Build a complete Swedish grammar engine.
- Store exhaustive answer keys for the entire curriculum.
- Expose reference answers, target IDs, or mastery notes in the iOS API.
- Replace the Evaluator with deterministic grading.

## Root Causes

### 1. Active targets lose remediation context

`user_learning_targets` stores current counters and status. Detailed evidence remains in `learning_evidence_events.evidence_json`, but target selection currently returns the target definition and counters without the most relevant evidence reason or corrective rule.

The practice generator therefore knows that an expression is weak, but not what was weak about it.

### 2. Quiz generation has no frozen answer contract

The generated quiz stores English sentences and target attribution. It does not store backend-only canonical answers, accepted variants, target realization requirements, or usage notes.

Every answer-feedback request must infer these again.

### 3. Correctness and target evidence are conflated

A learner can provide a natural translation that avoids the selected word or expression. That answer can be linguistically correct while providing no evidence for the intended target.

The current `correct` / `partial` / `incorrect` assessment cannot express both facts cleanly. This can make feedback artificially strict and can contaminate mastery evidence.

### 4. Question wording can fight the target

An English question may require a direct object, tense, register, or sentence structure that does not naturally map to the selected Swedish expression. Once generated, later calls are forced to choose between the target and the best translation.

## Proposed Architecture

### A. Enrich active target selection with remediation context

When selecting an active target, load its latest relevant evidence event and add a bounded backend-only remediation object:

```json
{
  "target_key": "vocabulary:expression:kan jag byta till en annan storlek?",
  "display_text": "Kan jag byta till en annan storlek?",
  "latest_evidence": {
    "outcome": "partial",
    "evidence_strength": "production",
    "reason": "The learner mixed the direct-object and objectless exchange constructions.",
    "learner_form": "byta den till en annan storlek",
    "preferred_form": "byta den mot en annan storlek",
    "remediation_rule": "Use byta X mot Y with a direct object; use byta till Y without it."
  }
}
```

The existing short `reason` can remain. Add the three structured remediation fields to Evaluator output for `struggled` and `partial` results. Validate their lengths and store them inside the existing bounded `evidence_json`; a database migration is not required unless later querying needs dedicated columns.

For old evidence lacking structured remediation, pass the short reason and allow quiz generation to derive a contract conservatively.

### B. Generate a backend-only grading contract once

Extend each generated question's internal representation:

```json
{
  "id": "q1",
  "sentence_en": "Can I change to a different size?",
  "target_keys": ["vocabulary:expression:kan jag byta till en annan storlek?"],
  "grading_contract": {
    "reference_answers_sv": [
      "Kan jag byta till en annan storlek?"
    ],
    "accepted_variants_sv": [
      "Går det att byta till en annan storlek?"
    ],
    "target_realizations": [
      {
        "target_key": "vocabulary:expression:kan jag byta till en annan storlek?",
        "required_or_equivalent": "byta till en annan storlek"
      }
    ],
    "usage_notes": [
      "This question intentionally has no direct object. Do not introduce byta X mot Y as a correction."
    ]
  }
}
```

This contract is produced only when the practice is generated. It is immutable for the lifetime of that practice and is passed to every Vocabulary Interactor call and the final Evaluator snapshot.

The public practice response must continue to strip:

- `target_keys`;
- grading contracts;
- reference answers;
- remediation notes;
- mastery state.

The iOS app should still receive only learner-visible question data and messages.

### C. Validate target-question compatibility

Strengthen quiz validation before activating a practice:

- exactly five questions and valid selected target keys, as now;
- every selected target covered by at least one question;
- every question has at least one non-empty reference answer;
- every attributed target has a target realization entry;
- bounded counts and string lengths for all grading fields;
- an expression target must appear exactly or through an explicitly declared equivalent in at least one reference answer;
- a remediation rule must not be contradicted by a question's usage notes;
- English wording should not force a structure explicitly excluded by the target contract.

The last two checks need a bounded model repair pass rather than pretending deterministic string validation can solve semantics. If validation fails:

1. Send the generated quiz, selected targets, and validation errors to one correction call.
2. Request corrected JSON only.
3. Validate once more.
4. Fail practice generation if it remains invalid.

Do not silently activate a structurally inconsistent quiz.

### D. Separate answer correctness from target demonstration

Extend Vocabulary Interactor output conceptually to:

```json
{
  "assistant_text": "Din mening är naturlig, men den tränar inte uttrycket vi fokuserar på här.",
  "turn_kind": "answer_feedback",
  "translation_assessment": "correct",
  "active_question_answered": true,
  "target_assessments": [
    {
      "target_key": "vocabulary:word:jobbar",
      "outcome": "not_demonstrated"
    }
  ]
}
```

Recommended semantics:

- `translation_assessment`: `correct`, `partial`, or `incorrect` for the sentence as Swedish;
- per-target outcome: `demonstrated`, `partial`, `not_demonstrated`, or `not_applicable`;
- a natural synonym can yield `translation_assessment = correct` and `target outcome = not_demonstrated`;
- `Next` may still unlock after a correctly assessed answer; mastery evidence does not need to be positive merely because progression is allowed.

For API compatibility, implementation may temporarily retain `answer_assessment` as a derived field while iOS migrates. Backend validation should own the mapping.

### E. Use the same contract in final evaluation

The practice Evaluator should receive:

- selected target definitions;
- latest remediation context used at generation time;
- immutable grading contracts;
- numbered learner and assistant turns;
- Interactor target assessments as supporting evidence, not unquestioned truth;
- current mastery state.

The Evaluator remains responsible for the final bounded evidence judgment. It must not invent a new preferred construction that conflicts with the frozen contract. If the transcript exposes a genuinely valid alternative missing from the contract, it may judge the learner fairly but should flag `contract_issue` for logging rather than rewrite the teaching rule mid-practice.

## Prompt and Cache Ordering

Preserve the cache invariant: stable context first, append-only history next, per-turn state last.

Recommended Vocabulary Interactor order:

1. `course_and_progression_context_json`
2. `selected_target_definitions_and_remediation_json`
3. `full_quiz_and_grading_contracts_json`
4. `prior_practice_chat_history_json`
5. `active_question_json`
6. `practice_state_json`
7. `latest_user_message`

The added remediation data and grading contracts are fixed for the practice, so they belong before chat history and should improve rather than damage cache reuse. Keep the existing vocabulary cache key and 24-hour retention unless prompt semantics require a version bump; the prompt version must change when the output contract changes.

Evaluator ordering should likewise keep evaluator instructions, candidate catalog, frozen contracts, and current mastery state before source-specific evidence turns.

## Curriculum Guidance Strategy

Use a hybrid source of truth:

1. Exact curriculum words and expressions remain canonical.
2. Structured remediation from the learner's latest evidence has priority for the current practice.
3. Add optional authored `usage_note`, `accepted_patterns`, and `avoid_patterns` only for genuinely ambiguous expressions or constructions.
4. Let quiz generation create question-specific reference answers and variants from those sources.

Do not require manual answer-key authoring for every vocabulary item. Add authored metadata incrementally where ambiguity repeatedly causes contract repairs or evaluator disagreement.

## Storage Changes

Minimal version:

- keep remediation fields inside `learning_evidence_events.evidence_json`;
- store full grading contracts inside the existing internal `quiz_json`;
- continue sanitizing public practice responses;
- add prompt/schema version fields to the selection snapshot as already done for generation metadata.

Possible later normalization:

- dedicated curriculum usage-guidance fields in Vocabulary JSON;
- a contract version column if practices must be migrated or re-evaluated;
- analytics for repeated `contract_issue` flags.

Normalization is not required for the first consistency pass.

## Implementation Sequence

1. Extend Evaluator schema and prompt with bounded remediation fields for partial/struggled evidence.
2. Validate and persist those fields in evidence JSON.
3. Include latest relevant remediation when active targets are selected.
4. Extend Vocabulary Interactor quiz-generation schema with hidden grading contracts.
5. Strengthen quiz validation and add one bounded repair attempt.
6. Ensure API response sanitization removes all hidden metadata.
7. Update answer-feedback output to separate translation and target assessments.
8. Update practice completion snapshots and Evaluator prompt to reuse the same contracts.
9. Version prompts and schemas; verify prompt-cache section ordering and cached-token logs.
10. Add contract-focused tests and run a live review using an ambiguous expression.

## Verification Cases

At minimum, cover:

- exact target use is accepted and marked demonstrated;
- natural synonym is accepted but marked not demonstrated for the selected target;
- spelling-only mistake can be translation-correct or partial according to the frozen contract without changing the target rule;
- free-form learner questions do not answer or advance the active quiz item;
- retry after correction is evaluated against the same contract;
- direct-object and objectless `byta` questions receive different compatible contracts;
- practice API never exposes hidden answer or mastery metadata;
- Evaluator cannot reference target IDs outside the selected set;
- an active target receives its latest remediation reason;
- cached input retains the stable target/contract prefix as history grows;
- invalid or contradictory quiz contracts are repaired once or rejected.

## Acceptance Criteria

- No learner-facing feedback within one practice contradicts its frozen grading contract.
- A correct natural translation is never labeled incorrect solely because it avoids the selected target.
- Target evidence explicitly records whether the selected item was demonstrated.
- The reason a weak target was selected is represented in the generated practice focus.
- Every generated question has a validated backend-only contract before activation.
- The final Evaluator uses the same contract and remediation context as the Interactor.
- Hidden metadata remains backend-only.
- Prompt-cache ordering and retention remain compliant with `docs/RUNBOOK.md`.

## Open Product Decisions

- Whether learner-facing feedback should explicitly say "correct, but try again using X" or allow Next immediately.
- Whether one correct synonym-only answer should count as answered for progression while recording no target demonstration. Recommended: yes.
- Whether `contract_issue` should automatically enqueue curriculum review after repeated occurrences. Recommended: log first; add workflow only if the signal is useful.
- Whether authored usage guidance belongs directly in Vocabulary JSON or in a separate reviewed guidance catalog. Recommended: optional fields in the existing level Vocabulary JSON unless the metadata becomes substantially larger.
