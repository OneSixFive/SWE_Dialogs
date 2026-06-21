import Foundation

struct VocabularyPracticeSummary: Codable, Identifiable, Hashable {
    let id: String
    let courseLevel: String
    let stageNumber: Int
    let status: VocabularyPracticeStatus
    let currentQuestionIndex: Int
    let answeredCount: Int
    let createdAt: Date
    let updatedAt: Date
    let completedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case courseLevel = "course_level"
        case stageNumber = "stage_number"
        case status
        case currentQuestionIndex = "current_question_index"
        case answeredCount = "answered_count"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case completedAt = "completed_at"
    }
}

enum VocabularyPracticeStatus: String, Codable, Hashable {
    case generating
    case active
    case completed
    case abandoned
    case failed

    var title: String {
        switch self {
        case .generating: return "Generating"
        case .active: return "In progress"
        case .completed: return "Completed"
        case .abandoned: return "Ended"
        case .failed: return "Failed"
        }
    }
}

struct VocabularyPractice: Codable, Identifiable, Hashable {
    let id: String
    let courseLevel: String
    let stageNumber: Int
    let status: VocabularyPracticeStatus
    let currentQuestionIndex: Int
    let answeredCount: Int
    let createdAt: Date
    let updatedAt: Date
    let completedAt: Date?
    let progressCutoffAbsoluteDay: Int
    let quiz: VocabularyPracticeQuiz?
    let state: VocabularyPracticeState
    let messages: [VocabularyPracticeMessage]

    enum CodingKeys: String, CodingKey {
        case id
        case courseLevel = "course_level"
        case stageNumber = "stage_number"
        case status
        case currentQuestionIndex = "current_question_index"
        case answeredCount = "answered_count"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case completedAt = "completed_at"
        case progressCutoffAbsoluteDay = "progress_cutoff_absolute_day"
        case quiz
        case state
        case messages
    }

    var summary: VocabularyPracticeSummary {
        VocabularyPracticeSummary(
            id: id,
            courseLevel: courseLevel,
            stageNumber: stageNumber,
            status: status,
            currentQuestionIndex: currentQuestionIndex,
            answeredCount: answeredCount,
            createdAt: createdAt,
            updatedAt: updatedAt,
            completedAt: completedAt
        )
    }

    var activeQuestion: VocabularyPracticeQuestion? {
        guard let questions = quiz?.questions,
              questions.indices.contains(state.currentQuestionIndex) else { return nil }
        return questions[state.currentQuestionIndex]
    }

    var canAdvance: Bool {
        guard status == .active, let question = activeQuestion else { return false }
        return state.answeredQuestionIDs.contains(question.id)
    }
}

struct VocabularyPracticeQuiz: Codable, Hashable {
    let openingText: String?
    let questions: [VocabularyPracticeQuestion]

    enum CodingKeys: String, CodingKey {
        case openingText = "opening_text"
        case questions
    }
}

struct VocabularyPracticeQuestion: Codable, Identifiable, Hashable {
    let id: String
    let sentenceEN: String

    enum CodingKeys: String, CodingKey {
        case id
        case sentenceEN = "sentence_en"
    }
}

struct VocabularyPracticeState: Codable, Hashable {
    let currentQuestionIndex: Int
    let answeredQuestionIDs: [String]
    let completed: Bool?

    enum CodingKeys: String, CodingKey {
        case currentQuestionIndex = "current_question_index"
        case answeredQuestionIDs = "answered_question_ids"
        case completed
    }
}

struct VocabularyPracticeMessage: Codable, Identifiable, Hashable {
    let id: UUID
    let role: LessonChatMessage.Role
    let content: String
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case role
        case content
        case createdAt = "created_at"
    }

    func lessonChatMessage(practiceID: String) -> LessonChatMessage {
        LessonChatMessage(
            id: id,
            lessonID: practiceID,
            role: role,
            content: content,
            createdAt: createdAt
        )
    }
}

struct VocabularyPracticesEnvelope: Decodable {
    let practices: [VocabularyPracticeSummary]
}
