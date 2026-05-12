# Lesson Engine Implementation

This document describes the corrected implementation approach for packing the current external ChatGPT + Gemini workflow into the iOS app.

The key design decision is to treat the app as a structured lesson engine:

- `lesson_payload.json` files are the static curriculum source of truth.
- OpenAI generates lesson material from one selected payload.
- Gemini receives only the generated dialogue rendered as speaker-prefixed TTS text.
- OpenAI then acts as the lesson interactor using the payload, generated lesson, current state, and latest user message.
- The app owns lesson state and progress. The model proposes state changes, but the app validates and persists them.

## Current Material Layout

The project now has 224 lesson payloads:

- `Materials/Lessons/B1/Lesson_brief_JSONs/*.json`
- `Materials/Lessons/B2/Lesson_brief_JSONs/*.json`

The prompt files are:

- `Materials/Shared_base_prompt.md`
- `Materials/Generator_prompt.md`
- `Materials/Interactor_prompt.md`

The app does not currently bundle `Materials/` into the iOS target. These files must either be copied into app resources or converted into generated Swift/static resource files before the app can load them at runtime.

## Target Flow

1. User selects level, stage, week, and day.
2. App loads the matching `lesson_payload`.
3. If no generated lesson exists, app calls the Generator.
4. Generator returns structured `generated_lesson`.
5. App validates the lesson:
   - exactly 20 dialogue lines
   - only speakers `Anna` and `Erik`
   - exactly 3 comprehension questions
   - matching `lesson_id`
6. App renders `tts_text` from `generated_lesson.dialogue`.
7. App sends only that rendered TTS text to Gemini.
8. User listens, reads, and chats.
9. Every user message goes to the Interactor with:
   - `lesson_payload`
   - `generated_lesson`
   - `lesson_state`
   - `latest_user_message`
10. Interactor returns:
   - visible assistant text
   - structured state patch
11. App applies valid state changes and persists them.
12. When the lesson is complete, progress is marked done.

## Corrected Data Ownership

Do not let the Generator own `tts_text` as independent content.

Correct:

```json
{
  "lesson_id": "b1_stage_1_week_1_day_1",
  "dialogue": [
    { "speaker": "Anna", "text": "Hej, jag heter Anna." },
    { "speaker": "Erik", "text": "Trevligt att träffas." }
  ],
  "comprehension_questions": [
    { "id": "q1", "question_sv": "..." }
  ]
}
```

Then the app computes:

```swift
let ttsText = generatedLesson.dialogue
    .map { "\($0.speaker): \($0.text)" }
    .joined(separator: "\n")
```

This prevents the displayed dialogue and spoken audio from drifting apart.

## Runtime Files

Static bundled resources:

- `Resources/TutorPrompts/Shared_base_prompt.md`
- `Resources/TutorPrompts/Generator_prompt.md`
- `Resources/TutorPrompts/Interactor_prompt.md`
- `Resources/Lessons/B1/Lesson_brief_JSONs/*.json`
- `Resources/Lessons/B2/Lesson_brief_JSONs/*.json`

Documents directory runtime data:

- `generated_lessons.json`
- `lesson_sessions.json`
- `lesson_audio/*.wav`
- existing `history.json`, if manual audio history is kept

## Swift Modules

Add these files under `SWE_Dialogs/SWE_Dialogs/`:

- `LessonModels.swift`
- `CurriculumStore.swift`
- `LessonGenerationStore.swift`
- `LessonSessionStore.swift`
- `OpenAITutorService.swift`
- `LessonEngine.swift`
- `LessonView.swift`

The existing manual TTS screen can stay as a fallback during migration.

## Core Models

```swift
struct LessonPayload: Codable, Identifiable {
    let id: String
    let coursePosition: CoursePosition
    let lessonIntent: LessonIntent
    let dialogueTask: DialogueTask
    let grammarTarget: GrammarTarget
    let vocabularyTarget: VocabularyTarget
    let dialogueShape: DialogueShape
    let comprehensionQuestions: ComprehensionQuestionFocus
    let translationQuiz: TranslationQuizFocus
}

struct GeneratedLesson: Codable, Identifiable {
    var id: String { lessonID }
    let lessonID: String
    let dialogue: [DialogueLine]
    let comprehensionQuestions: [GeneratedQuestion]
    let generatedAt: Date
    let model: String
    let schemaVersion: Int
}

struct DialogueLine: Codable, Hashable {
    let speaker: Speaker
    let text: String
}

enum Speaker: String, Codable {
    case Anna
    case Erik
}

struct GeneratedQuestion: Codable, Identifiable, Hashable {
    let id: String
    let questionSV: String
}
```

Use explicit `CodingKeys` where JSON uses snake case.

## Lesson State

The app should persist lesson state separately from generated lesson content.

```swift
struct LessonState: Codable, Identifiable {
    var id: String { lessonID }
    let lessonID: String
    var phase: LessonPhase
    var currentQuestionID: String?
    var acceptedQuestionIDs: Set<String>
    var comprehensionAnswers: [ComprehensionAnswer]
    var translationQuiz: TranslationQuiz?
    var translationAttempts: [TranslationAttempt]
    var mistakeNotes: [MistakeNote]
    var audioFileName: String?
    var isCompleted: Bool
    var updatedAt: Date
}

enum LessonPhase: String, Codable {
    case notStarted
    case generated
    case listening
    case comprehension
    case discussion
    case translation
    case completed
}
```

The important part is that the app, not the chat transcript alone, knows where the learner is.

## Interactor Output

The Interactor should return structured JSON, not just free text.

```json
{
  "assistant_text": "Bra. Du förstod huvudidén. En liten korrigering: ...",
  "state_patch": {
    "phase": "comprehension",
    "current_question_id": "q2",
    "accepted_question_ids_add": ["q1"],
    "mistake_notes_add": [
      {
        "category": "word_order",
        "note": "Learner put inte after the verb in an om-clause."
      }
    ]
  },
  "translation_quiz": null
}
```

State patches should be additive and conservative. The model can suggest a change, but the app should reject impossible changes, for example accepting a question ID that does not exist in the generated lesson.

## OpenAI Calls

Use the existing OpenAI key from settings, but add a tutor-specific service instead of overloading the basic chat service.

Generator call:

```text
instructions =
  Shared_base_prompt
  + "\n\n"
  + Generator_prompt

input =
  lesson_payload JSON
```

Interactor call:

```text
instructions =
  Shared_base_prompt
  + "\n\n"
  + Interactor_prompt

input =
  {
    "lesson_payload": ...,
    "generated_lesson": ...,
    "lesson_state": ...,
    "latest_user_message": "..."
  }
```

Both calls should request structured JSON output. The Generator schema should decode directly into `GeneratedLessonDraft`. The Interactor schema should decode into `InteractorResponse`.

Keep the old `ChatStore` separate until the lesson flow is stable. General chat and lesson interaction have different state models.

## Gemini TTS

Keep `GeminiTTSService.generateWav(dialog:apiKey:model:)`, but call it from the lesson flow with computed dialogue text:

```swift
let ttsText = generatedLesson.ttsText
let wavData = try await GeminiTTSService.generateWav(
    dialog: ttsText,
    apiKey: geminiKey,
    model: selectedTTSModel
)
```

Add a deterministic lesson audio filename so regenerated audio can be reused:

```text
lesson_audio/b1_stage_1_week_1_day_1-20260512-153000.wav
```

Store the filename in `LessonState.audioFileName`.

## Curriculum Loading

Preferred approach:

1. Keep `Materials/` as authoring source.
2. Copy prompt and lesson files into the app target under `Resources/`.
3. Add them to Copy Bundle Resources.
4. `CurriculumStore` loads JSON files from the bundle.
5. `CurriculumStore` exposes:

```swift
func levels() -> [LessonLevel]
func stages(for level: LessonLevel) -> [Int]
func weeks(level: LessonLevel, stage: Int) -> [Int]
func days(level: LessonLevel, stage: Int, week: Int) -> [LessonPayload]
func lesson(id: String) -> LessonPayload?
```

For faster runtime loading, later create a generated `curriculum_manifest.json` that lists every payload file and its level, stage, week, and day. That avoids crawling bundle folders on app launch.

## UI Shape

Replace the current `Dialogs` tab with a `Lessons` tab.

Top-level list:

- Level picker: B1, B2
- Stage picker: 1-4
- Week picker: 1-4
- Day rows with status:
  - not generated
  - generated
  - audio ready
  - in progress
  - completed

Lesson detail:

- compact lesson target summary
- Generate Lesson button
- Generate Audio button
- player
- dialogue text
- 3 comprehension questions
- lesson chat
- translation quiz area once available
- complete/reset controls

The app should make the daily workflow one screen:

1. Generate or open lesson.
2. Listen.
3. Answer questions.
4. Ask grammar/vocabulary questions.
5. Do translation quiz.
6. Mark complete.

## Validation Rules

Generator validation:

- `lessonID == payload.id`
- `dialogue.count == 20`
- every `speaker` is `Anna` or `Erik`
- every line has non-empty `text`
- no stage directions in `text`
- `comprehensionQuestions.count == 3`
- question IDs are unique
- no question asks "what did Anna/Erik say"

Interactor validation:

- `assistant_text` must be non-empty
- accepted question IDs must exist
- phase transitions must be valid
- mistake notes must stay compact
- translation quiz must contain exactly 5 English sentences when present

Payload validation:

- all JSON payloads decode
- no duplicate `id`
- filename position matches JSON position
- each level has expected stage/week/day counts

## Implementation Phases

### Phase 1: Resource and Model Foundation

- Move/copy prompts and lesson payloads into the iOS target resources.
- Add `LessonModels.swift`.
- Add `CurriculumStore`.
- Add unit tests that decode all bundled payloads.
- Add duplicate ID and stage/week/day consistency tests.

### Phase 2: Generator

- Add `OpenAITutorService.generateLesson`.
- Add structured output decoding.
- Add generated lesson validation.
- Add `LessonGenerationStore`.
- Build a basic lesson detail screen that can generate and display a dialogue/questions.

### Phase 3: Audio

- Add computed `GeneratedLesson.ttsText`.
- Call existing `GeminiTTSService`.
- Save lesson audio filename into `LessonState`.
- Reuse existing `AudioPlayerController`.
- Keep manual Create/History tab during this phase.

### Phase 4: Interactor

- Add `OpenAITutorService.sendLessonMessage`.
- Add `LessonSessionStore`.
- Add structured `InteractorResponse` and `LessonStatePatch`.
- Build the lesson chat UI.
- Apply validated state patches after every assistant response.

### Phase 5: Progress and Polish

- Replace `DialogProgressStore` with lesson-state-derived progress.
- Show progress per level/stage/week.
- Add reset/regenerate controls.
- Add tests for valid phase transitions.
- Remove or demote the old hardcoded `Stage4Plan` workflow after the new flow is stable.

## Migration From Current App

Current files to preserve:

- `GeminiTTSService.swift`
- `AudioPlayerController.swift`
- `FileStorage.swift`
- existing API key settings in `ContentView.swift`

Current files to replace or phase out:

- `Stage4Plan.swift`
- `Stage4PlanView.swift`
- `Stage4ProgressStore.swift`

Current files to keep separate:

- `ChatStore` and generic chat UI, unless you decide the lesson interactor fully replaces general chat.

## Prompt Adjustments

Keep the current three-prompt split, but update the output contract:

- Generator should output dialogue and questions only.
- Generator should not output `tts_text`.
- Interactor should output structured JSON with `assistant_text` and `state_patch`.
- The app should render only `assistant_text` to the learner.

Recommended generator output:

```json
{
  "lesson_id": "b1_stage_1_week_1_day_1",
  "dialogue": [
    { "speaker": "Anna", "text": "..." }
  ],
  "comprehension_questions": [
    { "id": "q1", "question_sv": "..." },
    { "id": "q2", "question_sv": "..." },
    { "id": "q3", "question_sv": "..." }
  ]
}
```

Recommended interactor output:

```json
{
  "assistant_text": "...",
  "state_patch": {
    "phase": "translation",
    "current_question_id": null,
    "accepted_question_ids_add": ["q3"],
    "mistake_notes_add": []
  },
  "translation_quiz": {
    "sentences_en": [
      "..."
    ]
  }
}
```

## Practical Recommendation

Build this in parallel with the current manual flow. Do not delete the paste-to-TTS screen until the new lesson flow can:

- load B1 and B2 payloads
- generate a valid lesson
- generate audio from that lesson
- run a comprehension chat
- generate a translation quiz
- persist progress

Once those are working, the app becomes the full learning workflow instead of a TTS helper plus external ChatGPT sessions.
