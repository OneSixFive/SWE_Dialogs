# Bead: End-of-Lesson Evaluator

## Problem

The current lesson engine has two model roles:

- `Generator`: creates the fixed lesson dialogue and comprehension questions.
- `Interactor`: chats with the learner during the lesson and updates immediate lesson state.

The app also needs durable learner intelligence:

- vocabulary the learner encountered or struggled with
- grammar concepts the learner handled well or poorly
- evidence-backed estimates of strengths and weak points
- optional lesson/chat summaries for future personalization

Putting that work into `Interactor` would mix learner-facing tutoring with backend assessment. That creates objective conflict: the model must both produce a good chat response and reliably emit structured learning analytics. The structured analytics are likely to degrade first.

## Goal

Add a third model role, `Evaluator`, that runs after a lesson interaction is finished and converts the full lesson transcript into validated backend events.

For v1, run it at end-of-lesson only. Do not use evaluator output to steer the active conversation.

## Non-Goals

- Do not change live Interactor behavior.
- Do not create multiple evaluator roles yet.
- Do not require real-time learner adaptation.
- Do not make evaluator output user-visible by default.
- Do not treat evaluator scores as final truth without validation and future tuning.

## Proposed Flow

1. Learner completes or exits a lesson.
2. Backend receives or already has the lesson context and chat transcript.
3. Backend calls `Evaluator` with:
- course context
- lesson payload
- generated lesson
- full learner/tutor chat transcript
- current lesson state
4. `Evaluator` returns strict JSON only.
5. Backend validates the JSON.
6. Backend writes normalized vocabulary and grammar events under the authenticated `user_id`.
7. Backend stores evaluator metadata so the lesson can be re-evaluated later with a newer prompt/model.

## Model Responsibility

`Evaluator` should answer only this question:

> What durable learning signals can be inferred from this completed lesson transcript?

It should not:

- chat with the learner
- generate new exercises
- mark the lesson complete
- invent evidence not present in the transcript
- update database rows directly

## Single Evaluator vs Split Evaluators

Start with one evaluator that outputs both vocabulary and grammar events.

Split later only if measured quality shows a real problem:

- vocabulary extraction is useful but grammar scoring is noisy
- grammar evidence is useful but vocabulary extraction is noisy
- the combined schema becomes unstable
- different model/cost/cadence requirements appear

The backend should validate vocabulary and grammar sections independently so they can be split later without changing storage.

## Expected Output Shape

Top-level JSON:

```json
{
  "evaluation_version": "v1",
  "lesson_summary": {
    "learner_performance_summary": "short internal summary",
    "completed_lesson_goal": true
  },
  "vocabulary_events": [
    {
      "lemma": "example",
      "surface_form": "example",
      "translation_hint": "example",
      "event_type": "encountered|used_correctly|used_incorrectly|asked_about",
      "confidence": 0.0,
      "evidence": "short quote or paraphrase from transcript"
    }
  ],
  "grammar_events": [
    {
      "skill_code": "subordinate_clause_word_order",
      "event_type": "demonstrated|struggled|asked_about|corrected",
      "confidence": 0.0,
      "evidence": "short quote or paraphrase from transcript"
    }
  ],
  "suggested_next_focus": [
    {
      "kind": "vocabulary|grammar",
      "code_or_lemma": "subordinate_clause_word_order",
      "reason": "short internal reason"
    }
  ]
}
```

## Backend Persistence

Write evaluator output as events, not direct truth.

Recommended tables from the user-scoped storage plan:

- `vocabulary_items`
- `vocabulary_reviews` or `vocabulary_events`
- `grammar_skills`
- `user_grammar_stats`
- optional `lesson_evaluations`

Add `lesson_evaluations`:

- `id`
- `user_id`
- `lesson_id`
- `evaluation_version`
- `model`
- `input_hash`
- `raw_output_json`
- `created_at`

Use `input_hash` for idempotency so retrying the same evaluation does not duplicate events.

## Prompt Caching Strategy

Structure evaluator input so stable text appears first:

1. evaluator system/developer prompt
2. course context
3. lesson payload
4. generated lesson
5. transcript
6. final instruction to emit JSON

This layout gives repeated evaluations a better chance of benefiting from prompt caching for shared prefixes. It also makes re-evaluation cheaper when the same lesson context is reused.

Do not over-optimize for caching in v1. The bigger win is correct architecture and idempotent storage.

## API Shape

Preferred v1 endpoint:

- `POST /me/lessons/{lesson_id}/evaluate`

Rules:

- derive `user_id` from auth token
- never accept `user_id` from client
- accept lesson/transcript payload only if backend does not already store it
- return evaluation status and stored event counts

Example response:

```json
{
  "evaluation_id": 123,
  "status": "stored",
  "vocabulary_event_count": 8,
  "grammar_event_count": 3
}
```

## Validation Rules

Backend should reject or partially discard invalid evaluator sections:

- unknown `event_type`
- confidence outside `0.0...1.0`
- missing evidence
- vocabulary item with no lemma/surface form
- grammar skill not in catalog unless explicitly allowed as `uncategorized`
- output larger than expected

Store raw output for debugging, but only validated events should affect learner stats.

## Testing

Backend tests:

- evaluator output validates against schema
- retry with same `input_hash` is idempotent
- user A cannot evaluate/write events for user B
- invalid vocabulary section does not corrupt grammar events
- invalid grammar section does not corrupt vocabulary events

Prompt tests / fixtures:

- short successful lesson
- lesson with learner grammar mistakes
- lesson with mostly comprehension answers and little free production
- lesson where learner asks in English
- lesson where evaluator should output no strong grammar conclusions

## Acceptance Criteria

- `Interactor` remains focused on learner-facing chat.
- `Evaluator` runs after lesson completion or explicit lesson exit.
- Evaluator output is strict JSON and validated before persistence.
- Vocabulary and grammar events are stored under internal `user_id`.
- Re-running the same evaluation does not duplicate durable events.
- Future split into vocabulary and grammar evaluators remains possible.

## Open Decisions

- Whether to trigger evaluation only on explicit lesson completion or also on abandon/exit.
- Whether transcripts should be stored permanently or only summarized after evaluation.
- Whether `grammar_skills` should be fully pre-seeded from curriculum concepts or grown gradually.
- Which model to use for v1 evaluator after cost/quality testing.
