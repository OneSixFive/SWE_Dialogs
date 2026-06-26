import Foundation

protocol LessonSessionUploading {
    func upsertLessonSession(
        lessonID: String,
        state: LessonState,
        generatedLesson: GeneratedLesson?,
        messages: [LessonChatMessage],
        baseServerUpdatedAt: String?,
        resetGeneration: Bool
    ) async throws -> BackendLessonSession
}

final class BackendClient {
    static let shared = BackendClient()

    private let baseURL: URL
    private let session: URLSession
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(baseURL: URL = BackendConfig.baseURL) {
        self.baseURL = baseURL

        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 180
        configuration.timeoutIntervalForResource = 300
        self.session = URLSession(configuration: configuration)

        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom(Self.decodeDate)
        self.decoder = decoder
    }

    func exchangeAppleToken(idToken: String, nonce: String?) async throws -> BackendAuthResponse {
        let request = AppleAuthRequest(idToken: idToken, nonce: nonce)
        return try await sendJSON(path: "/auth/apple", body: request, requiresAuth: false)
    }

    func currentUser() async throws -> BackendUser {
        try await sendJSON(path: "/me", queryItems: [], requiresAuth: true)
    }

    func lessonSessions(summaryOnly: Bool) async throws -> [BackendLessonSession] {
        let response: BackendLessonSessionsResponse = try await sendJSON(
            path: "/me/lesson-sessions",
            queryItems: [
                URLQueryItem(name: "summary_only", value: summaryOnly ? "true" : "false")
            ],
            requiresAuth: true
        )
        return response.sessions
    }

    func syncCompletedLessonProgress(lessonIDs: [String]) async throws -> BackendLessonProgressSyncResponse {
        try await sendJSON(
            path: "/me/lesson-progress/sync",
            body: LessonProgressSyncRequest(completedLessonIDs: lessonIDs),
            requiresAuth: true
        )
    }

    func upsertLessonSession(
        lessonID: String,
        state: LessonState,
        generatedLesson: GeneratedLesson?,
        messages: [LessonChatMessage],
        baseServerUpdatedAt: String?,
        resetGeneration: Bool
    ) async throws -> BackendLessonSession {
        let request = LessonSessionUpsertRequest(
            state: state,
            generatedLesson: generatedLesson,
            messages: messages,
            clientUpdatedAt: state.updatedAt,
            baseServerUpdatedAt: baseServerUpdatedAt,
            resetGeneration: resetGeneration
        )
        return try await sendJSON(
            path: "/me/lesson-sessions/\(lessonID)",
            method: "PUT",
            body: request,
            requiresAuth: true
        )
    }

    func generateLesson(
        payload: LessonPayload,
        model: String,
        reasoningEffort: String
    ) async throws -> GeneratedLesson {
        let request = LessonGenerateRequest(
            payload: payload,
            model: model,
            reasoningEffort: reasoningEffort
        )
        return try await sendJSON(path: "/lessons/generate", body: request, requiresAuth: true)
    }

    func sendLessonMessage(
        payload: LessonPayload,
        generatedLesson: GeneratedLesson,
        state: LessonState,
        chatHistory: [LessonChatMessage],
        latestUserMessage: String,
        model: String,
        reasoningEffort: String,
        translationLookup: TranslationLookupMetadata? = nil
    ) async throws -> InteractorResponse {
        let request = LessonMessageRequest(
            payload: payload,
            generatedLesson: generatedLesson,
            state: state,
            chatHistory: chatHistory,
            latestUserMessage: latestUserMessage,
            model: model,
            reasoningEffort: reasoningEffort,
            translationLookup: translationLookup
        )
        return try await sendJSON(path: "/lessons/message", body: request, requiresAuth: true)
    }

    func vocabularyPractices() async throws -> [VocabularyPracticeSummary] {
        let response: VocabularyPracticesEnvelope = try await sendJSON(
            path: "/me/vocabulary-practices",
            queryItems: [],
            requiresAuth: true
        )
        return response.practices
    }

    func vocabularyPractice(id: String) async throws -> VocabularyPractice {
        try await sendJSON(
            path: "/me/vocabulary-practices/\(id)",
            queryItems: [],
            requiresAuth: true
        )
    }

    func createVocabularyPractice() async throws -> VocabularyPractice {
        try await sendJSON(
            path: "/me/vocabulary-practices",
            method: "POST",
            requiresAuth: true
        )
    }

    func sendVocabularyPracticeMessage(
        id: String,
        message: String,
        translationLookup: TranslationLookupMetadata? = nil
    ) async throws -> VocabularyPractice {
        try await sendJSON(
            path: "/me/vocabulary-practices/\(id)/messages",
            body: VocabularyPracticeMessageRequest(
                latestUserMessage: message,
                translationLookup: translationLookup
            ),
            requiresAuth: true
        )
    }

    func advanceVocabularyPractice(id: String) async throws -> VocabularyPractice {
        try await sendJSON(
            path: "/me/vocabulary-practices/\(id)/next",
            method: "POST",
            requiresAuth: true
        )
    }

    func abandonVocabularyPractice(id: String) async throws -> VocabularyPractice {
        try await sendJSON(
            path: "/me/vocabulary-practices/\(id)/abandon",
            method: "POST",
            requiresAuth: true
        )
    }

    func generateWav(dialog: String, model: String) async throws -> Data {
        let request = TTSRequest(dialog: dialog, model: model)
        return try await sendData(path: "/tts/dialogue", body: request, requiresAuth: true)
    }

    private func sendJSON<Response: Decodable, Body: Encodable>(
        path: String,
        body: Body,
        requiresAuth: Bool
    ) async throws -> Response {
        let data = try await sendData(path: path, method: "POST", queryItems: [], body: body, requiresAuth: requiresAuth)
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw BackendError.decodeFailed(error.localizedDescription)
        }
    }

    private func sendJSON<Response: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body,
        requiresAuth: Bool
    ) async throws -> Response {
        let data = try await sendData(path: path, method: method, queryItems: [], body: body, requiresAuth: requiresAuth)
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw BackendError.decodeFailed(error.localizedDescription)
        }
    }

    private func sendJSON<Response: Decodable>(
        path: String,
        queryItems: [URLQueryItem],
        requiresAuth: Bool
    ) async throws -> Response {
        let data = try await sendData(path: path, method: "GET", queryItems: queryItems, bodyData: nil, requiresAuth: requiresAuth)
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw BackendError.decodeFailed(error.localizedDescription)
        }
    }

    private func sendJSON<Response: Decodable>(
        path: String,
        method: String,
        requiresAuth: Bool
    ) async throws -> Response {
        let data = try await sendData(
            path: path,
            method: method,
            queryItems: [],
            bodyData: nil,
            requiresAuth: requiresAuth
        )
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw BackendError.decodeFailed(error.localizedDescription)
        }
    }

    private func sendData<Body: Encodable>(
        path: String,
        method: String = "POST",
        queryItems: [URLQueryItem] = [],
        body: Body,
        requiresAuth: Bool
    ) async throws -> Data {
        let bodyData = try encoder.encode(body)
        return try await sendData(path: path, method: method, queryItems: queryItems, bodyData: bodyData, requiresAuth: requiresAuth)
    }

    private func sendData(
        path: String,
        method: String,
        queryItems: [URLQueryItem],
        bodyData: Data?,
        requiresAuth: Bool
    ) async throws -> Data {
        var url = baseURL.appending(path: path)
        if !queryItems.isEmpty,
           var components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            components.queryItems = queryItems
            if let queryURL = components.url {
                url = queryURL
            }
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        if let bodyData {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = bodyData
        }

        if requiresAuth {
            guard let token = KeychainStore.loadSessionToken(), !token.isEmpty else {
                throw BackendError.missingSession
            }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BackendError.invalidResponse
        }

        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 409,
               let conflict = try? decoder.decode(BackendLessonSessionConflictEnvelope.self, from: data) {
                throw BackendError.lessonSessionConflict(conflict.detail.current)
            }
            throw BackendError.apiError(status: http.statusCode, message: errorMessage(from: data))
        }
        return data
    }

    private func errorMessage(from data: Data) -> String {
        if let envelope = try? decoder.decode(BackendErrorEnvelope.self, from: data) {
            return envelope.detail.description
        }
        return String(data: data, encoding: .utf8) ?? "Unknown backend error."
    }

    private static func decodeDate(from decoder: Decoder) throws -> Date {
        let container = try decoder.singleValueContainer()
        let value = try container.decode(String.self)

        if let date = fractionalDateFormatter.date(from: value) ?? standardDateFormatter.date(from: value) {
            return date
        }

        throw DecodingError.dataCorruptedError(
            in: container,
            debugDescription: "Invalid ISO-8601 date: \(value)"
        )
    }

    private static let fractionalDateFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let standardDateFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()
}

extension BackendClient: LessonSessionUploading {}

struct BackendAuthResponse: Decodable {
    let sessionToken: String
    let user: BackendUser

    enum CodingKeys: String, CodingKey {
        case sessionToken = "session_token"
        case user
    }
}

struct BackendUser: Codable {
    let id: Int
    let appleSub: String?
    let email: String?

    enum CodingKeys: String, CodingKey {
        case id
        case appleSub = "apple_sub"
        case email
    }
}

struct BackendLessonSessionsResponse: Decodable {
    let sessions: [BackendLessonSession]
}

struct BackendLessonSession: Decodable {
    let lessonID: String
    let status: String
    let isCompleted: Bool
    let completedAt: Date?
    let clientUpdatedAt: Date
    // This is an opaque optimistic-concurrency token. Preserve it byte-for-byte.
    let serverUpdatedAt: String
    let state: LessonState?
    let generatedLesson: GeneratedLesson?
    let messages: [LessonChatMessage]?
    let stateSchemaVersion: Int?
    let contentSchemaVersion: Int?

    enum CodingKeys: String, CodingKey {
        case lessonID = "lesson_id"
        case status
        case isCompleted = "is_completed"
        case completedAt = "completed_at"
        case clientUpdatedAt = "client_updated_at"
        case serverUpdatedAt = "server_updated_at"
        case state
        case generatedLesson = "generated_lesson"
        case messages
        case stateSchemaVersion = "state_schema_version"
        case contentSchemaVersion = "content_schema_version"
    }
}

private struct BackendLessonSessionConflictEnvelope: Decodable {
    let detail: Detail

    struct Detail: Decodable {
        let message: String
        let current: BackendLessonSession
    }
}

struct BackendLessonProgressSyncResponse: Decodable {
    let completedCount: Int
    let courseLevel: String
    let stageNumber: Int
    let currentLessonID: String

    enum CodingKeys: String, CodingKey {
        case completedCount = "completed_count"
        case courseLevel = "course_level"
        case stageNumber = "stage_number"
        case currentLessonID = "current_lesson_id"
    }
}

private struct AppleAuthRequest: Encodable {
    let idToken: String
    let nonce: String?

    enum CodingKeys: String, CodingKey {
        case idToken = "id_token"
        case nonce
    }
}

private struct LessonGenerateRequest: Encodable {
    let payload: LessonPayload
    let model: String
    let reasoningEffort: String

    enum CodingKeys: String, CodingKey {
        case payload
        case model
        case reasoningEffort = "reasoning_effort"
    }
}

private struct LessonMessageRequest: Encodable {
    let payload: LessonPayload
    let generatedLesson: GeneratedLesson
    let state: LessonState
    let chatHistory: [LessonChatMessage]
    let latestUserMessage: String
    let model: String
    let reasoningEffort: String
    let translationLookup: TranslationLookupMetadata?

    enum CodingKeys: String, CodingKey {
        case payload
        case generatedLesson = "generated_lesson"
        case state
        case chatHistory = "chat_history"
        case latestUserMessage = "latest_user_message"
        case model
        case reasoningEffort = "reasoning_effort"
        case translationLookup = "translation_lookup"
    }
}

private struct TTSRequest: Encodable {
    let dialog: String
    let model: String
}

private struct LessonSessionUpsertRequest: Encodable {
    let state: LessonState
    let generatedLesson: GeneratedLesson?
    let messages: [LessonChatMessage]
    let clientUpdatedAt: Date
    let baseServerUpdatedAt: String?
    let resetGeneration: Bool

    enum CodingKeys: String, CodingKey {
        case state
        case generatedLesson = "generated_lesson"
        case messages
        case clientUpdatedAt = "client_updated_at"
        case baseServerUpdatedAt = "base_server_updated_at"
        case resetGeneration = "reset_generation"
    }
}

private struct LessonProgressSyncRequest: Encodable {
    let completedLessonIDs: [String]

    enum CodingKeys: String, CodingKey {
        case completedLessonIDs = "completed_lesson_ids"
    }
}

struct TranslationLookupMetadata: Encodable, Hashable {
    let selectedText: String
    let sourceKind: String
    let sourceID: String
    let sourceSurface: String?
    let surroundingText: String?
    let visibleCourseLevel: String?
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case selectedText = "selected_text"
        case sourceKind = "source_kind"
        case sourceID = "source_id"
        case sourceSurface = "source_surface"
        case surroundingText = "surrounding_text"
        case visibleCourseLevel = "visible_course_level"
        case createdAt = "created_at"
    }
}

private struct VocabularyPracticeMessageRequest: Encodable {
    let latestUserMessage: String
    let translationLookup: TranslationLookupMetadata?

    enum CodingKeys: String, CodingKey {
        case latestUserMessage = "latest_user_message"
        case translationLookup = "translation_lookup"
    }
}

private struct BackendErrorEnvelope: Decodable {
    let detail: BackendErrorDetail
}

private enum BackendErrorDetail: Decodable, CustomStringConvertible {
    case string(String)
    case fallback(String)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(String.self) {
            self = .string(value)
        } else {
            self = .fallback("Backend request failed.")
        }
    }

    var description: String {
        switch self {
        case .string(let value), .fallback(let value):
            return value
        }
    }
}

enum BackendError: LocalizedError {
    case missingSession
    case invalidResponse
    case lessonSessionConflict(BackendLessonSession)
    case apiError(status: Int, message: String)
    case decodeFailed(String)

    var errorDescription: String? {
        switch self {
        case .missingSession:
            return "Sign in with Apple first."
        case .invalidResponse:
            return "Invalid backend response."
        case .lessonSessionConflict:
            return "Lesson session changed on the server."
        case .apiError(let status, let message):
            if status == 401 {
                return "Your session expired. Sign in again."
            }
            return "Backend error (\(status)): \(message)"
        case .decodeFailed(let message):
            return "Failed to read backend response: \(message)"
        }
    }
}
