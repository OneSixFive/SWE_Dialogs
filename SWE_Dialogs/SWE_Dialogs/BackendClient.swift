import Foundation

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
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    func exchangeAppleToken(idToken: String, nonce: String?) async throws -> BackendAuthResponse {
        let request = AppleAuthRequest(idToken: idToken, nonce: nonce)
        return try await sendJSON(path: "/auth/apple", body: request, requiresAuth: false)
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
        reasoningEffort: String
    ) async throws -> InteractorResponse {
        let request = LessonMessageRequest(
            payload: payload,
            generatedLesson: generatedLesson,
            state: state,
            chatHistory: chatHistory,
            latestUserMessage: latestUserMessage,
            model: model,
            reasoningEffort: reasoningEffort
        )
        return try await sendJSON(path: "/lessons/message", body: request, requiresAuth: true)
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
        let data = try await sendData(path: path, body: body, requiresAuth: requiresAuth)
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw BackendError.decodeFailed(error.localizedDescription)
        }
    }

    private func sendData<Body: Encodable>(
        path: String,
        body: Body,
        requiresAuth: Bool
    ) async throws -> Data {
        let url = baseURL.appending(path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(body)

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
}

struct BackendAuthResponse: Decodable {
    let sessionToken: String
    let user: BackendUser

    enum CodingKeys: String, CodingKey {
        case sessionToken = "session_token"
        case user
    }
}

struct BackendUser: Decodable {
    let id: Int
    let appleSub: String
    let email: String?

    enum CodingKeys: String, CodingKey {
        case id
        case appleSub = "apple_sub"
        case email
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

    enum CodingKeys: String, CodingKey {
        case payload
        case generatedLesson = "generated_lesson"
        case state
        case chatHistory = "chat_history"
        case latestUserMessage = "latest_user_message"
        case model
        case reasoningEffort = "reasoning_effort"
    }
}

private struct TTSRequest: Encodable {
    let dialog: String
    let model: String
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
    case apiError(status: Int, message: String)
    case decodeFailed(String)

    var errorDescription: String? {
        switch self {
        case .missingSession:
            return "Sign in with Apple first."
        case .invalidResponse:
            return "Invalid backend response."
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
