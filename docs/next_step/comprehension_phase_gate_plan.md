# Comprehension Phase Gate Hardening Plan

## Issue Being Addressed

During comprehension, the assistant can output discussion-stage language such as “you can now reread the dialog” before the learner taps `Next` and before all comprehension flow steps are intentionally completed.

From the learner perspective, this looks like stage bleed (discussion prompt appearing inside comprehension).

## Why This Is Happening

Current architecture has two progression authorities:

1. UI progression (`Next` button) in the app.
2. Interactor-provided `state_patch` from backend model output.

Even though the intended flow is UI-driven, the interactor can currently:

- patch `phase` directly (including transitions that should be UI-owned), and
- accept multiple comprehension question IDs in one turn.

This can cause premature state advancement or state/text mismatch.

There is an important distinction:

- Local iOS phase hardening prevents bad persisted state.
- Backend response validation must prevent bad `assistant_text` from reaching the learner.

The screenshot issue is visible text from the model response, not the app's local discussion prompt. Therefore iOS-side phase ignoring alone is not sufficient.

## Goal

Make progression prevention-first and deterministic:

- `Next` (and explicit UI action command) is the sole stage-transition mechanism.
- Interactor can evaluate only the currently active comprehension question.
- Multi-question acceptance in one turn is rejected.
- Invalid stage-bleed model output is rejected before it is returned to the app.

No client-side suppression/replacement of assistant text is used as a workaround.

## Non-Goal

- Do not add UI-level “hide this text” filters.
- Do not redesign lesson flow or prompt strategy in this change.

## Change Plan

### 1) iOS: Make Stage Progression Locally Owned

File: `/Users/dima/Downloads/computing/Svenska_new/SWE_Dialogs/SWE_Dialogs/LessonModels.swift`

Planned behavior:

- In lesson state patch application, do not allow interactor `state_patch.phase` to drive progression into `discussion`, `translation`, or `completed`.
- Stage transitions remain UI-owned:
  - first visible comprehension answer establishes local `comprehension` state if the lesson is still `listening` or `generated`
  - comprehension -> discussion via `Next` flow (`startDiscussion`)
  - discussion -> translation via explicit UI action (`SYSTEM_UI_ACTION: start_translation_quiz`)
  - translation -> completed via local translation step completion logic

Implementation note:

- Do not blindly apply `response.statePatch.phase`.
- Keep transition into `translation` tied to an accepted `translation_quiz` response from the app-controlled quiz request path.
- Preserve or add a local first-question transition so ignoring phase patches does not leave the first accepted comprehension answer in `listening`.
- Treat `state_patch.phase` as informational at most; runtime progression must come from local methods such as `setCurrentQuestion`, `startDiscussion`, quiz creation, translation index advancement, and completion.

### 2) Backend: Validate Against Current State

File: `/Users/dima/Downloads/computing/Svenska_new/backend/app/openai_client.py`

Planned signature change:

- Change `validate_interactor_response(response, generated_lesson)` to include the current request state and latest user message, e.g.:
  - `validate_interactor_response(response, generated_lesson, state, latest_user_message)`
- Update `send_lesson_message(...)` to pass those values.

Planned behavior:

- Resolve active comprehension question from current state/context (same selection logic used for active question exposure).
- If `accepted_question_ids_add` is non-empty:
  - it must contain exactly one ID,
  - that ID must equal the active question ID,
  - that ID must not already be accepted,
  - otherwise reject as invalid interactor response.
- During comprehension, reject any interactor response that attempts to set `phase` to `discussion` or `translation`.
- During comprehension, reject any `current_question_id` patch that jumps away from the active question in the same turn.
- Reject `translation_quiz` unless the latest user message is `SYSTEM_UI_ACTION: start_translation_quiz`, the current state phase is `discussion`, and all comprehension questions are already accepted.

This prevents:

- multi-ID jumps in one turn,
- accepting non-active questions,
- early “all questions accepted” state from a single answer.
- returning discussion-stage text after an invalid phase advance attempt.

### 3) Backend: Retry Or Fail Invalid Model Output

File: `/Users/dima/Downloads/computing/Svenska_new/backend/app/openai_client.py`

Planned behavior:

- If model output fails the new interactor validation, do not return its `assistant_text` to the app.
- Prefer one structured retry with a concise corrective instruction, preserving the same request context.
- If the retry also fails, return a backend error rather than leaking invalid stage guidance.

This is the piece that prevents the screenshot-level bug. iOS ignoring `phase` alone would still display bad assistant text.

## Test Plan

### Backend tests

File: `/Users/dima/Downloads/computing/Svenska_new/backend/tests/test_contracts.py`

Add/adjust tests for `validate_interactor_response(...)`:

1. Reject `accepted_question_ids_add` with more than one ID.
2. Reject `accepted_question_ids_add` that does not match active question.
3. Accept single-ID patch when it matches active question.
4. Reject `phase: discussion` while current state is `comprehension` and only q1 is active/accepted.
5. Reject `phase: translation` while current state is `comprehension`.
6. Reject `translation_quiz` unless latest message is the explicit start-quiz UI command and state is `discussion`.
7. Verify invalid model output is retried or converted to an error before `assistant_text` is returned.

### iOS tests

File: `/Users/dima/Downloads/computing/Svenska_new/SWE_Dialogs/SWE_DialogsTests/SWE_DialogsTests.swift`

Add/adjust tests for state apply behavior:

1. Interactor patch containing `phase: discussion` does not move phase from comprehension.
2. Interactor patch containing `phase: translation` does not move phase from discussion/comprehension unless translation quiz is actually set by app-controlled path.
3. First visible comprehension answer can be accepted without relying on interactor `phase` to enter comprehension.
4. Completing q3 keeps phase `comprehension` until `Next`.
5. `Next` after all questions accepted enters `discussion` and appends the local discussion prompt.

## Verification Checklist

1. Start lesson and answer only first comprehension question.
2. Confirm phase is locally in `comprehension`, not advanced to `discussion`.
3. Confirm assistant text does not invite the learner to reread the dialog or start discussion.
4. Confirm `Next` moves from q1 to q2, not directly to discussion.
5. Confirm backend rejects any interactor response attempting multi-question acceptance.
6. Complete all three comprehension questions:
   - still remain in comprehension until `Next`,
   - after `Next`, move to discussion prompt,
   - after second `Next`, start translation quiz command path.
7. Confirm early explicit quiz requests during comprehension do not create a translation quiz.

## Expected Outcome

After this change, discussion-stage guidance cannot appear due to premature stage advancement mechanics or leaked model text. The app owns stage transitions, and the backend rejects invalid interactor responses before they reach the learner.
