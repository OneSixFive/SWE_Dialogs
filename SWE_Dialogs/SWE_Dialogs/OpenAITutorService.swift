import Foundation

enum OpenAITutorService {
    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 180
        configuration.timeoutIntervalForResource = 240
        return URLSession(configuration: configuration)
    }()

    static func generateLesson(
        payload: LessonPayload,
        apiKey: String,
        model: String,
        reasoningEffort: String
    ) async throws -> GeneratedLesson {
        let sharedPrompt = try ResourceLoader.prompt(named: "Shared_base_prompt")
        let generatorPrompt = try ResourceLoader.prompt(named: "Generator_prompt")
        let instructions = [sharedPrompt, generatorPrompt].joined(separator: "\n\n")
        let input = try jsonString(from: payload, keyEncodingStrategy: .convertToSnakeCase)

        let draft: GeneratedLessonDraft = try await sendStructuredRequest(
            apiKey: apiKey,
            model: model,
            reasoningEffort: reasoningEffort,
            instructions: instructions,
            input: input,
            schema: generatorSchema,
            maxOutputTokens: 4_000
        )
        try LessonValidator.validate(draft: draft, payload: payload)
        return draft.finalized(model: model)
    }

    static func sendLessonMessage(
        payload: LessonPayload,
        generatedLesson: GeneratedLesson,
        state: LessonState,
        chatHistory: [LessonChatMessage],
        latestUserMessage: String,
        apiKey: String,
        model: String,
        reasoningEffort: String
    ) async throws -> InteractorResponse {
        let sharedPrompt = try ResourceLoader.prompt(named: "Shared_base_prompt")
        let interactorPrompt = try ResourceLoader.prompt(named: "Interactor_prompt")
        let instructions = [sharedPrompt, interactorPrompt].joined(separator: "\n\n")

        let input = try [
            responseInputItem(
                title: "lesson_payload_json",
                content: jsonString(from: payload, keyEncodingStrategy: .convertToSnakeCase)
            ),
            responseInputItem(
                title: "generated_lesson_json",
                content: jsonString(from: generatedLesson)
            ),
            responseInputItem(
                title: "full_lesson_chat_history_json",
                content: jsonString(fromJSONObject: chatMessageObjects(from: chatHistory))
            ),
            responseInputItem(
                title: "lesson_state_json",
                content: jsonString(from: state)
            ),
            responseInputItem(
                title: "latest_user_message",
                content: latestUserMessage
            )
        ]

        let response: InteractorResponse = try await sendStructuredRequest(
            apiKey: apiKey,
            model: model,
            reasoningEffort: reasoningEffort,
            instructions: instructions,
            input: input,
            schema: interactorSchema,
            maxOutputTokens: 2_000,
            promptCacheKey: "lesson_interactor_\(payload.id)"
        )
        try LessonValidator.validate(response: response, generatedLesson: generatedLesson)
        return response
    }

    private static func sendStructuredRequest<T: Decodable>(
        apiKey: String,
        model: String,
        reasoningEffort: String,
        instructions: String,
        input: Any,
        schema: [String: Any],
        maxOutputTokens: Int,
        promptCacheKey: String? = nil
    ) async throws -> T {
        guard let url = URL(string: "https://api.openai.com/v1/responses") else {
            throw OpenAITutorError.invalidRequest
        }

        var body: [String: Any] = [
            "model": model,
            "instructions": instructions,
            "input": input,
            "max_output_tokens": maxOutputTokens,
            "reasoning": [
                "effort": reasoningEffort
            ],
            "text": [
                "format": schema
            ]
        ]
        if let promptCacheKey {
            body["prompt_cache_key"] = promptCacheKey
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])

        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)

        let payload = try JSONDecoder().decode(TutorResponsePayload.self, from: data)
        if let refusal = payload.refusalText, !refusal.isEmpty {
            throw OpenAITutorError.refusal(refusal)
        }

        let outputText = payload.bestText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !outputText.isEmpty else {
            throw OpenAITutorError.parseError("No structured output text. Raw: \(rawSnippet(from: data))")
        }

        guard let outputData = outputText.data(using: .utf8) else {
            throw OpenAITutorError.parseError("Structured output was not UTF-8.")
        }

        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            return try decoder.decode(T.self, from: outputData)
        } catch {
            throw OpenAITutorError.parseError(
                "Failed to decode structured output: \(error.localizedDescription). Output: \(outputText)"
            )
        }
    }

    private static func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw OpenAITutorError.invalidResponse
        }

        guard (200...299).contains(http.statusCode) else {
            if let apiError = try? JSONDecoder().decode(TutorErrorEnvelope.self, from: data) {
                throw OpenAITutorError.apiError(apiError.error.message)
            }
            throw OpenAITutorError.apiError(String(data: data, encoding: .utf8) ?? "Unknown OpenAI error")
        }
    }

    private static func jsonObject<T: Encodable>(
        from value: T,
        keyEncodingStrategy: JSONEncoder.KeyEncodingStrategy = .useDefaultKeys
    ) throws -> Any {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        encoder.keyEncodingStrategy = keyEncodingStrategy
        let data = try encoder.encode(value)
        return try JSONSerialization.jsonObject(with: data, options: [])
    }

    private static func responseInputItem(title: String, content: String) -> [String: String] {
        [
            "role": "user",
            "content": "\(title):\n\(content)"
        ]
    }

    private static func chatMessageObjects(from messages: [LessonChatMessage]) -> [[String: String]] {
        messages.map { message in
            [
                "role": message.role.rawValue,
                "content": message.content
            ]
        }
    }

    private static func jsonString<T: Encodable>(
        from value: T,
        keyEncodingStrategy: JSONEncoder.KeyEncodingStrategy = .useDefaultKeys
    ) throws -> String {
        try jsonString(fromJSONObject: jsonObject(from: value, keyEncodingStrategy: keyEncodingStrategy))
    }

    private static func jsonString(fromJSONObject object: Any) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    private static func rawSnippet(from data: Data) -> String {
        let raw = String(data: data, encoding: .utf8) ?? "<non-utf8 response>"
        if raw.count > 700 {
            return String(raw.prefix(700)) + "..."
        }
        return raw
    }
}

private extension OpenAITutorService {
    static var generatorSchema: [String: Any] {
        [
            "type": "json_schema",
            "name": "generated_lesson",
            "strict": true,
            "schema": [
                "type": "object",
                "additionalProperties": false,
                "required": ["lesson_id", "dialogue", "comprehension_questions"],
                "properties": [
                    "lesson_id": ["type": "string"],
                    "dialogue": [
                        "type": "array",
                        "items": [
                            "type": "object",
                            "additionalProperties": false,
                            "required": ["speaker", "text"],
                            "properties": [
                                "speaker": [
                                    "type": "string",
                                    "enum": ["Anna", "Erik"]
                                ],
                                "text": ["type": "string"]
                            ]
                        ]
                    ],
                    "comprehension_questions": [
                        "type": "array",
                        "items": [
                            "type": "object",
                            "additionalProperties": false,
                            "required": ["id", "question_sv"],
                            "properties": [
                                "id": ["type": "string"],
                                "question_sv": ["type": "string"]
                            ]
                        ]
                    ]
                ]
            ]
        ]
    }

    static var interactorSchema: [String: Any] {
        [
            "type": "json_schema",
            "name": "lesson_interaction",
            "strict": true,
            "schema": [
                "type": "object",
                "additionalProperties": false,
                "required": ["assistant_text", "state_patch", "translation_quiz"],
                "properties": [
                    "assistant_text": ["type": "string"],
                    "state_patch": [
                        "type": "object",
                        "additionalProperties": false,
                        "required": [
                            "phase",
                            "current_question_id",
                            "accepted_question_ids_add",
                            "mistake_notes_add"
                        ],
                        "properties": [
                            "phase": [
                                "anyOf": [
                                    [
                                        "type": "string",
                                        "enum": LessonPhase.interactorPatchableCases.map(\.rawValue)
                                    ],
                                    ["type": "null"]
                                ]
                            ],
                            "current_question_id": [
                                "anyOf": [
                                    ["type": "string"],
                                    ["type": "null"]
                                ]
                            ],
                            "accepted_question_ids_add": [
                                "type": "array",
                                "items": ["type": "string"]
                            ],
                            "mistake_notes_add": [
                                "type": "array",
                                "items": [
                                    "type": "object",
                                    "additionalProperties": false,
                                    "required": ["category", "note"],
                                    "properties": [
                                        "category": ["type": "string"],
                                        "note": ["type": "string"]
                                    ]
                                ]
                            ]
                        ]
                    ],
                    "translation_quiz": [
                        "anyOf": [
                            [
                                "type": "object",
                                "additionalProperties": false,
                                "required": ["sentences_en"],
                                "properties": [
                                    "sentences_en": [
                                        "type": "array",
                                        "items": ["type": "string"]
                                    ]
                                ]
                            ],
                            ["type": "null"]
                        ]
                    ]
                ]
            ]
        ]
    }
}

private struct TutorResponsePayload: Decodable {
    let outputText: String?
    let output: [TutorOutputItem]?

    enum CodingKeys: String, CodingKey {
        case outputText = "output_text"
        case output
    }

    var bestText: String {
        if let outputText, !outputText.isEmpty {
            return outputText
        }

        let chunks = output?.flatMap { item in
            item.content?.compactMap { content in
                content.text
            } ?? []
        } ?? []
        return chunks.joined(separator: "\n")
    }

    var refusalText: String? {
        let refusals = output?.flatMap { item in
            item.content?.compactMap(\.refusal) ?? []
        } ?? []
        return refusals.joined(separator: "\n")
    }
}

private struct TutorOutputItem: Decodable {
    let content: [TutorOutputContent]?
}

private struct TutorOutputContent: Decodable {
    let text: String?
    let refusal: String?
    let type: String?
}

private struct TutorErrorEnvelope: Decodable {
    struct APIError: Decodable {
        let message: String
    }

    let error: APIError
}

enum OpenAITutorError: LocalizedError {
    case invalidRequest
    case invalidResponse
    case apiError(String)
    case refusal(String)
    case parseError(String)

    var errorDescription: String? {
        switch self {
        case .invalidRequest:
            return "Failed to build OpenAI tutor request."
        case .invalidResponse:
            return "Invalid OpenAI tutor response."
        case .apiError(let message):
            return "OpenAI tutor API error: \(message)"
        case .refusal(let message):
            return "OpenAI refused the tutor request: \(message)"
        case .parseError(let details):
            return "OpenAI tutor response parse error: \(details)"
        }
    }
}
