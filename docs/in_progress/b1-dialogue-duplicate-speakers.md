# B1 Stage 1 Week 1 Day 3 duplicate speakers

## Problem

On 2026-08-28 at approximately 10:14:56 Stockholm time, the generation for
`b1_stage_1_week_1_day_3` produced consecutive turns by the same speaker:

```text
Anna, Erik, Erik, Anna, Anna, Erik, Erik, Anna, Anna, Erik, Erik, Anna, ...
```

The duplicate boundaries occurred at lines 2–3, 4–5, 6–7, 8–9, and 10–11.
The generated lesson was stored as artifact
`e165eb0f-8ce2-4570-866b-ca1c622ef877` and the user's session was attached to
that artifact. The artifact has `scope = shared`, so the malformed dialogue
can also be served to other users resolving the same lesson with the same
recipe.

## Cause

The model output was structurally valid but failed an implicit conversational
invariant.

- `Materials/Generator_prompt.md` requires exactly 20 lines and restricts the
  speakers to Anna and Erik, but does not require strict alternation or forbid
  consecutive turns by one speaker.
- The Responses API JSON schema restricts `speaker` to `Anna` or `Erik`, but
  cannot express the relationship between adjacent array items.
- The backend validator checks the lesson ID, line count, non-empty text,
  stage directions, and comprehension questions, but does not check speaker
  order.
- The iOS `LessonValidator` has the same omission.
- `build_generated_lesson` and session persistence preserve the generated
  array unchanged; the stored artifact JSON and attached session JSON are
  identical. This is therefore a generation/validation gap, not a display or
  TTS reordering problem.

The behavior appears intermittent: other recent artifacts generated with the
same model were clean, while the recent B1 Stage 1 Week 1 Day 2 artifact also
contained repeated speaker boundaries. The missing validation allowed a
stochastic bad output to be published and cached.

## Proposed solution

1. Make turn order explicit in `Materials/Generator_prompt.md`: line 1 starts
   with Anna and every subsequent line alternates strictly between Anna and
   Erik. State that consecutive lines must never have the same speaker.
2. Add a server-side validation error for repeated adjacent speakers in
   `validate_generated_lesson_draft`. Reject the draft before publishing an
   artifact or recording it in a lesson session.
3. Add the same invariant to the iOS `LessonValidator` as defense in depth for
   legacy/direct generation paths.
4. Add backend and iOS tests covering a repeated speaker, including the exact
   failure pattern seen here, and a valid 20-line alternating dialogue.
5. Invalidate or regenerate the current shared artifact after the validation
   fix. Do not silently rewrite its dialogue, because its content hash and any
   associated audio must remain consistent.

No live data was modified during this investigation.
