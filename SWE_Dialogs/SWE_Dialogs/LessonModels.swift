import Foundation

enum LessonLevel: String, CaseIterable, Codable, Identifiable {
    case b1 = "B1"
    case b2 = "B2"

    var id: String { rawValue }

    static func fromLessonID(_ id: String) -> LessonLevel? {
        let lowercased = id.lowercased()
        if lowercased.hasPrefix("b1_") { return .b1 }
        if lowercased.hasPrefix("b2_") { return .b2 }
        return nil
    }
}

struct LessonPayload: Codable, Identifiable, Hashable {
    let id: String
    let coursePosition: CoursePosition
    let lessonIntent: LessonIntent
    let dialogueTask: DialogueTask
    let grammarTarget: GrammarTarget
    let vocabularyTarget: VocabularyTarget
    let dialogueShape: DialogueShape
    let comprehensionQuestions: ComprehensionQuestionFocus
    let translationQuiz: TranslationQuizFocus

    var courseLevel: LessonLevel {
        LessonLevel.fromLessonID(id) ?? .b1
    }
}

struct CoursePosition: Codable, Hashable {
    let stage: Int
    let week: Int
    let day: Int
    let absoluteDay: Int
    let level: String
    let stageName: String
}

struct LessonIntent: Codable, Hashable {
    let oneSentenceGoal: String
    let realLifeContext: String
    let communicativeFunction: String
}

struct DialogueTask: Codable, Hashable {
    let scenario: String
    let difficulty: String
}

struct GrammarTarget: Codable, Hashable {
    let mainFocus: GrammarMainFocus
    let allowedSupportingGrammar: [String]
    let avoidGrammar: [String]
}

struct GrammarMainFocus: Codable, Hashable {
    let name: String
    let description: String
    let modelExamples: [String]
    let desiredPresence: String
}

struct VocabularyTarget: Codable, Hashable {
    let theme: String
    let activeWords: [String]
    let usefulChunks: [String]
    let desiredPresence: String
}

struct DialogueShape: Codable, Hashable {
    let opening: String
    let middle: String
    let ending: String
    let targetComplexity: TargetComplexity
}

struct TargetComplexity: Codable, Hashable {
    let averageSentenceLength: String
    let maxNewConcepts: Int
    let repetition: String
}

struct ComprehensionQuestionFocus: Codable, Hashable {
    let focus: [String]
}

struct TranslationQuizFocus: Codable, Hashable {
    let sentenceFocus: [String]
}

struct GeneratedLesson: Codable, Identifiable, Hashable {
    var id: String { lessonID }

    let lessonID: String
    let dialogue: [DialogueLine]
    let comprehensionQuestions: [GeneratedQuestion]
    let generatedAt: Date
    let model: String
    let schemaVersion: Int

    enum CodingKeys: String, CodingKey {
        case lessonID = "lesson_id"
        case dialogue
        case comprehensionQuestions = "comprehension_questions"
        case generatedAt = "generated_at"
        case model
        case schemaVersion = "schema_version"
    }

    var ttsText: String {
        dialogue
            .map { "\($0.speaker.rawValue): \($0.text)" }
            .joined(separator: "\n")
    }
}

struct GeneratedLessonDraft: Codable, Hashable {
    let lessonID: String
    let dialogue: [DialogueLine]
    let comprehensionQuestions: [GeneratedQuestion]

    enum CodingKeys: String, CodingKey {
        case lessonID = "lesson_id"
        case dialogue
        case comprehensionQuestions = "comprehension_questions"
    }

    func finalized(model: String) -> GeneratedLesson {
        GeneratedLesson(
            lessonID: lessonID,
            dialogue: dialogue,
            comprehensionQuestions: comprehensionQuestions,
            generatedAt: Date(),
            model: model,
            schemaVersion: 1
        )
    }
}

struct DialogueLine: Codable, Hashable {
    let speaker: LessonSpeaker
    let text: String
}

enum LessonSpeaker: String, Codable, Hashable {
    case Anna
    case Erik
}

struct GeneratedQuestion: Codable, Identifiable, Hashable {
    let id: String
    let questionSV: String

    enum CodingKeys: String, CodingKey {
        case id
        case questionSV = "question_sv"
    }
}

struct LessonState: Codable, Identifiable, Hashable {
    var id: String { lessonID }

    let lessonID: String
    var phase: LessonPhase
    var currentQuestionID: String?
    var translationQuiz: TranslationQuiz?
    var currentTranslationIndex: Int?
    var translationAttempts: [TranslationAttempt]
    var mistakeNotes: [MistakeNote]
    var audioFileName: String?
    var isCompleted: Bool
    var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case lessonID = "lesson_id"
        case phase
        case currentQuestionID = "current_question_id"
        case translationQuiz = "translation_quiz"
        case currentTranslationIndex = "current_translation_index"
        case translationAttempts = "translation_attempts"
        case mistakeNotes = "mistake_notes"
        case audioFileName = "audio_file_name"
        case isCompleted = "is_completed"
        case updatedAt = "updated_at"
    }

    static func fresh(lessonID: String) -> LessonState {
        LessonState(
            lessonID: lessonID,
            phase: .notStarted,
            currentQuestionID: nil,
            translationQuiz: nil,
            currentTranslationIndex: nil,
            translationAttempts: [],
            mistakeNotes: [],
            audioFileName: nil,
            isCompleted: false,
            updatedAt: Date()
        )
    }

    mutating func apply(response: InteractorResponse, generatedLesson: GeneratedLesson) throws {
        try LessonValidator.validate(response: response, generatedLesson: generatedLesson)

        if !response.statePatch.mistakeNotesAdd.isEmpty {
            mistakeNotes.append(contentsOf: response.statePatch.mistakeNotesAdd)
            if mistakeNotes.count > 30 {
                mistakeNotes = Array(mistakeNotes.suffix(30))
            }
        }

        if let translationQuiz = response.translationQuiz {
            self.translationQuiz = translationQuiz
            currentTranslationIndex = 0
            phase = .translation
        }

        updatedAt = Date()
    }
}

enum LessonPhase: String, Codable, CaseIterable, Hashable {
    case notStarted
    case generated
    case listening
    case comprehension
    case discussion
    case translation
    case completed

    static let interactorPatchableCases: [LessonPhase] = [
        .generated,
        .listening,
        .comprehension,
        .discussion,
        .translation
    ]
}

struct TranslationQuiz: Codable, Hashable {
    let sentencesEN: [String]

    enum CodingKeys: String, CodingKey {
        case sentencesEN = "sentences_en"
    }
}

struct TranslationAttempt: Codable, Identifiable, Hashable {
    let id: UUID
    let sentenceIndex: Int
    let answer: String
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case sentenceIndex = "sentence_index"
        case answer
        case createdAt = "created_at"
    }

    init(id: UUID = UUID(), sentenceIndex: Int, answer: String, createdAt: Date = Date()) {
        self.id = id
        self.sentenceIndex = sentenceIndex
        self.answer = answer
        self.createdAt = createdAt
    }
}

struct MistakeNote: Codable, Hashable {
    let category: String
    let note: String
}

struct InteractorResponse: Codable, Hashable {
    let assistantText: String
    let statePatch: LessonStatePatch
    let translationQuiz: TranslationQuiz?

    enum CodingKeys: String, CodingKey {
        case assistantText = "assistant_text"
        case statePatch = "state_patch"
        case translationQuiz = "translation_quiz"
    }
}

struct LessonStatePatch: Codable, Hashable {
    let phase: LessonPhase?
    let currentQuestionID: String?
    let mistakeNotesAdd: [MistakeNote]

    enum CodingKeys: String, CodingKey {
        case phase
        case currentQuestionID = "current_question_id"
        case mistakeNotesAdd = "mistake_notes_add"
    }

    init(
        phase: LessonPhase?,
        currentQuestionID: String?,
        mistakeNotesAdd: [MistakeNote]
    ) {
        self.phase = phase
        self.currentQuestionID = currentQuestionID
        self.mistakeNotesAdd = mistakeNotesAdd
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        phase = try container.decodeIfPresent(LessonPhase.self, forKey: .phase)
        currentQuestionID = try container.decodeIfPresent(String.self, forKey: .currentQuestionID)
        mistakeNotesAdd = try container.decodeIfPresent([MistakeNote].self, forKey: .mistakeNotesAdd) ?? []
    }
}

struct LessonChatMessage: Codable, Identifiable, Hashable {
    enum Role: String, Codable, Hashable {
        case user
        case assistant
    }

    let id: UUID
    let lessonID: String
    let role: Role
    let content: String
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case lessonID = "lesson_id"
        case role
        case content
        case createdAt = "created_at"
    }

    init(id: UUID = UUID(), lessonID: String, role: Role, content: String, createdAt: Date = Date()) {
        self.id = id
        self.lessonID = lessonID
        self.role = role
        self.content = content
        self.createdAt = createdAt
    }
}

enum LessonValidationError: LocalizedError {
    case wrongLessonID(expected: String, actual: String)
    case wrongDialogueLineCount(Int)
    case emptyDialogueLine(Int)
    case stageDirection(Int)
    case wrongQuestionCount(Int)
    case duplicateQuestionIDs
    case disallowedSpeakerQuestion
    case invalidQuestionID(String)
    case invalidPhasePatch(LessonPhase)
    case emptyAssistantText
    case invalidTranslationQuizCount(Int)

    var errorDescription: String? {
        switch self {
        case .wrongLessonID(let expected, let actual):
            return "Generated lesson ID \(actual) does not match payload ID \(expected)."
        case .wrongDialogueLineCount(let count):
            return "Generated dialogue has \(count) lines. It must have exactly 20."
        case .emptyDialogueLine(let index):
            return "Generated dialogue line \(index + 1) is empty."
        case .stageDirection(let index):
            return "Generated dialogue line \(index + 1) appears to contain a stage direction."
        case .wrongQuestionCount(let count):
            return "Generated lesson has \(count) comprehension questions. It must have exactly 3."
        case .duplicateQuestionIDs:
            return "Generated comprehension question IDs must be unique."
        case .disallowedSpeakerQuestion:
            return "Comprehension questions must not ask what Anna or Erik said."
        case .invalidQuestionID(let id):
            return "Interactor referenced an unknown question ID: \(id)."
        case .invalidPhasePatch(let phase):
            return "Interactor cannot set lesson phase to \(phase.rawValue)."
        case .emptyAssistantText:
            return "Interactor returned an empty assistant response."
        case .invalidTranslationQuizCount(let count):
            return "Translation quiz has \(count) sentences. It must have exactly 5."
        }
    }
}

enum LessonValidator {
    static func validate(draft: GeneratedLessonDraft, payload: LessonPayload) throws {
        guard draft.lessonID == payload.id else {
            throw LessonValidationError.wrongLessonID(expected: payload.id, actual: draft.lessonID)
        }

        guard draft.dialogue.count == 20 else {
            throw LessonValidationError.wrongDialogueLineCount(draft.dialogue.count)
        }

        for (index, line) in draft.dialogue.enumerated() {
            let text = line.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else {
                throw LessonValidationError.emptyDialogueLine(index)
            }
            if text.hasPrefix("(") || text.hasPrefix("[") || text.hasPrefix("*") {
                throw LessonValidationError.stageDirection(index)
            }
        }

        guard draft.comprehensionQuestions.count == 3 else {
            throw LessonValidationError.wrongQuestionCount(draft.comprehensionQuestions.count)
        }

        let ids = draft.comprehensionQuestions.map(\.id)
        guard Set(ids).count == ids.count else {
            throw LessonValidationError.duplicateQuestionIDs
        }

        let disallowedPatterns = [
            "vad sa anna",
            "vad sa erik",
            "what did anna",
            "what did erik",
            "vem sa"
        ]
        let questions = draft.comprehensionQuestions.map { $0.questionSV.lowercased() }
        if questions.contains(where: { question in
            disallowedPatterns.contains { pattern in
                question.contains(pattern)
            }
        }) {
            throw LessonValidationError.disallowedSpeakerQuestion
        }
    }

    static func validate(response: InteractorResponse, generatedLesson: GeneratedLesson) throws {
        guard !response.assistantText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw LessonValidationError.emptyAssistantText
        }

        if let phase = response.statePatch.phase,
           !LessonPhase.interactorPatchableCases.contains(phase) {
            throw LessonValidationError.invalidPhasePatch(phase)
        }

        if let quiz = response.translationQuiz, quiz.sentencesEN.count != 5 {
            throw LessonValidationError.invalidTranslationQuizCount(quiz.sentencesEN.count)
        }
    }
}
