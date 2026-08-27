import Foundation

struct LessonRegenerationResult {
    let lesson: GeneratedLesson
    let session: BackendLessonSession
}

enum OpenAITutorService {
    static func generateLesson(
        payload: LessonPayload,
        model: String,
        reasoningEffort: String,
        privateAlternative: Bool = false
    ) async throws -> GeneratedLesson {
        let lesson = try await BackendClient.shared.generateLesson(
            payload: payload,
            model: model,
            reasoningEffort: reasoningEffort,
            privateAlternative: privateAlternative
        )
        let draft = GeneratedLessonDraft(
            lessonID: lesson.lessonID,
            dialogue: lesson.dialogue,
            comprehensionQuestions: lesson.comprehensionQuestions
        )
        try LessonValidator.validate(draft: draft, payload: payload)
        return lesson
    }

    static func regenerateLesson(
        payload: LessonPayload,
        operationKey: String,
        baseServerUpdatedAt: String
    ) async throws -> LessonRegenerationResult {
        let response = try await BackendClient.shared.regenerateLesson(
            payload: payload,
            operationKey: operationKey,
            baseServerUpdatedAt: baseServerUpdatedAt
        )
        guard let lesson = response.artifact?.generatedLesson,
              let session = response.session else {
            throw BackendError.invalidResponse
        }
        let draft = GeneratedLessonDraft(
            lessonID: lesson.lessonID,
            dialogue: lesson.dialogue,
            comprehensionQuestions: lesson.comprehensionQuestions
        )
        try LessonValidator.validate(draft: draft, payload: payload)
        return LessonRegenerationResult(lesson: lesson, session: session)
    }

    static func sendLessonMessage(
        payload: LessonPayload,
        generatedLesson: GeneratedLesson,
        state: LessonState,
        chatHistory: [LessonChatMessage],
        latestUserMessage: String,
        model: String,
        reasoningEffort: String,
        translationLookup: TranslationLookupMetadata? = nil
    ) async throws -> InteractorResponse {
        let response = try await BackendClient.shared.sendLessonMessage(
            payload: payload,
            generatedLesson: generatedLesson,
            state: state,
            chatHistory: chatHistory,
            latestUserMessage: latestUserMessage,
            model: model,
            reasoningEffort: reasoningEffort,
            translationLookup: translationLookup
        )
        try LessonValidator.validate(response: response, generatedLesson: generatedLesson)
        return response
    }
}
