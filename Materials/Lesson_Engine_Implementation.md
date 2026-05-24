# Lesson Engine Next Steps

The durable architecture, implemented files, runtime resources, and confirmed user-flow decisions live in `RUNBOOK.md`.

## Remaining Build Steps

1. Verify in Xcode
   - Run the simulator build on macOS.
   - Run the unit tests for bundled curriculum decoding.
   - Fix any Swift/Xcode resource bundling issues that do not surface in this Windows workspace.

2. Smoke-test the lesson flow
   - Open `Lessons`.
   - Use `Continue` or select a B2 day.
   - Generate a lesson with the OpenAI key/model.
   - Confirm the app reuses the saved generated lesson.

3. Smoke-test audio
   - Confirm audio auto-generates when a Gemini key exists.
   - Confirm `Regenerate Audio` works.
   - Confirm lesson audio reloads after leaving and reopening the lesson.

4. Smoke-test Interactor state
   - Answer comprehension questions in any order.
   - Confirm accepted questions get checkmarks.
   - Confirm Next after the final comprehension question opens the dialog-reading clarification stage.
   - Start the quiz and verify exactly 5 English sentences appear.

5. Polish after real-device testing
   - Tune layout if the lesson screen feels too long.
   - Decide whether to keep the old `Create`, `History`, and generic `Chats` tabs long term.
   - Remove or archive the legacy `Stage4Plan*` flow after the new Lessons flow is stable.
