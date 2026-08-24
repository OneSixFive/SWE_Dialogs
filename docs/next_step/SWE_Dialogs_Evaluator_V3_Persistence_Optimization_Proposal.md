# Evaluator v3: Persistence-Oriented Optimization

Date: 2026-08-24 (Stockholm)

## Recommendation

My preferred optimization would be a persistence-oriented evaluator v3.

The evaluator currently returns a result for every candidate, even when most results cannot change persisted learning state. Evaluator v3 should instead prove that every candidate was checked, while emitting detailed results only for candidates whose persisted state could change.

## Proposed response contract

```json
{
  "evaluation_version": "v3",
  "checked_target_keys": [
    "target_a",
    "target_b"
  ],
  "updates": [
    {
      "target_key": "target_b",
      "outcome": "partial",
      "evidence_strength": "production",
      "confidence": 0.84,
      "evidence_turn_ids": ["turn_17"],
      "reason": "The learner attempted the target but used an incorrect form."
    }
  ]
}
```

- `checked_target_keys` must contain every supplied candidate key exactly once. This preserves completeness and makes omissions detectable.
- `updates` contains only results that can affect persistence.
- A candidate with `no_evidence` is omitted from `updates`.
- A positive result for an untracked target is omitted because the current persistence layer deliberately ignores it.
- A positive result for a tracked target remains eligible for `updates`, because it can advance the target's success streak.
- The backend derives target kind and other trusted metadata from the supplied candidate set rather than accepting repeated model output.

For the latest inspected lesson, the current evaluator produced 21 detailed results: 13 `demonstrated`, 6 `no_evidence`, and 2 `partial`. Only the two `partial` results changed persisted state; all 13 demonstrated targets were untracked and were deliberately ignored by the persistence layer. The raw evaluator response was 6,595 characters. A simulated v3 response containing complete checked keys and only the two actionable updates was 1,576 characters, an estimated **76% reduction** in serialized output for that lesson. This is a one-lesson measurement, not a guaranteed token or cost reduction.

## Additional optimization

1. **Slim the candidate projection.** Each candidate repeats lesson ID, stage, absolute day, level and subtype. The model mainly needs key, kind, display text, description and tracked state. A minimal projection reduced this lesson’s candidate block from 5,712 to 3,195 characters—**44% smaller**.

## Validation requirements

Before applying any updates, the backend should enforce that:

- `checked_target_keys` exactly matches the candidate keys sent to the evaluator, with no missing, unknown, or duplicate keys.
- Every `updates[].target_key` belongs to that candidate set and appears at most once.
- Evidence turn IDs refer only to turns supplied to the evaluator.
- Outcomes and evidence strengths are allowed for the candidate's source kind.
- An omitted update means “checked, no state change,” not “evaluation missing.”

## Implementation touchpoints

- Update the evaluator response schema and request construction in `backend/app/openai_client.py`, including the evaluator prompt/cache version.
- Add v3 completeness and update validation in `backend/app/db.py` before applying results.
- Update `Materials/Evaluator_prompt.md` to define the complete checked-key list, actionable-update rules, and omission semantics.
- Produce the slim candidate projection from `backend/app/learning_service.py` while keeping authoritative metadata server-side.
- Preserve the current evaluator as a fallback during rollout and log validation failures without applying partial v3 output.

## Rollout and verification

1. Run v2 and v3 in shadow mode on representative completed lessons.
2. Compare the exact database mutations each version would produce, not merely their textual classifications.
3. Require zero persistence deltas across tracked-target streaks, lookup outcomes, and partial or struggled evidence before enabling v3 writes.
4. Record input, output, cached-input, latency, validation-failure, and persisted-update counts separately.
5. Enable v3 gradually, retaining a fast fallback to v2 until production parity is established.
