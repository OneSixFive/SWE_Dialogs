import Foundation

enum GeminiTTSService {
    enum TTSModel: String, CaseIterable, Identifiable {
        case flash25 = "gemini-2.5-flash-preview-tts"
        case pro25 = "gemini-2.5-pro-preview-tts"
        case flash31 = "gemini-3.1-flash-tts-preview"

        var id: String { rawValue }

        var title: String {
            switch self {
            case .flash25:
                return "2.5 Flash TTS"
            case .pro25:
                return "2.5 Pro TTS"
            case .flash31:
                return "3.1 Flash TTS"
            }
        }
    }

    private static let session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 180
        configuration.timeoutIntervalForResource = 300
        return URLSession(configuration: configuration)
    }()

    static func generateWav(dialog: String, apiKey: String, model: TTSModel) async throws -> Data {
        guard let encodedKey = apiKey.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) else {
            throw GeminiError.invalidAPIKey
        }

        guard let url = URL(string: "https://generativelanguage.googleapis.com/v1beta/models/\(model.rawValue):generateContent?key=\(encodedKey)") else {
            throw GeminiError.invalidRequest
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 180

        let body = RequestBody(
            contents: [
                Content(parts: [Part(text: dialog)])
            ],
            generationConfig: GenerationConfig(
                responseModalities: ["AUDIO"],
                speechConfig: SpeechConfig(
                    multiSpeakerVoiceConfig: MultiSpeakerVoiceConfig(
                        speakerVoiceConfigs: [
                            SpeakerVoiceConfig(
                                speaker: "Anna",
                                voiceConfig: VoiceConfig(
                                    prebuiltVoiceConfig: PrebuiltVoiceConfig(voiceName: "Aoede")
                                )
                            ),
                            SpeakerVoiceConfig(
                                speaker: "Erik",
                                voiceConfig: VoiceConfig(
                                    prebuiltVoiceConfig: PrebuiltVoiceConfig(voiceName: "Enceladus")
                                )
                            )
                        ]
                    )
                )
            )
        )

        request.httpBody = try JSONEncoder().encode(body)

        let dataAndResponse: (Data, URLResponse)
        do {
            dataAndResponse = try await session.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            throw GeminiError.timeout(model.title)
        }

        let (data, response) = dataAndResponse
        guard let httpResponse = response as? HTTPURLResponse else {
            throw GeminiError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw GeminiError.apiError(message)
        }

        let decoded = try JSONDecoder().decode(GeminiResponse.self, from: data)

        guard
            let b64 = decoded.candidates.first?.content.parts.first?.inlineData.data,
            let pcmData = Data(base64Encoded: b64)
        else {
            throw GeminiError.emptyAudio
        }

        return buildWavFromPCM(pcmData)
    }

    private static func buildWavFromPCM(_ pcmData: Data) -> Data {
        let sampleRate: UInt32 = 24_000
        let channels: UInt16 = 1
        let bitsPerSample: UInt16 = 16

        let byteRate = sampleRate * UInt32(channels) * UInt32(bitsPerSample / 8)
        let blockAlign = channels * (bitsPerSample / 8)
        let dataSize = UInt32(pcmData.count)
        let riffChunkSize = 36 + dataSize

        var wav = Data()
        wav.append("RIFF".data(using: .ascii)!)
        wav.appendLE(riffChunkSize)
        wav.append("WAVE".data(using: .ascii)!)
        wav.append("fmt ".data(using: .ascii)!)
        wav.appendLE(UInt32(16))
        wav.appendLE(UInt16(1))
        wav.appendLE(channels)
        wav.appendLE(sampleRate)
        wav.appendLE(byteRate)
        wav.appendLE(blockAlign)
        wav.appendLE(bitsPerSample)
        wav.append("data".data(using: .ascii)!)
        wav.appendLE(dataSize)
        wav.append(pcmData)
        return wav
    }
}

private struct RequestBody: Encodable {
    let contents: [Content]
    let generationConfig: GenerationConfig
}

private struct Content: Encodable {
    let parts: [Part]
}

private struct Part: Encodable {
    let text: String
}

private struct GenerationConfig: Encodable {
    let responseModalities: [String]
    let speechConfig: SpeechConfig
}

private struct SpeechConfig: Encodable {
    let multiSpeakerVoiceConfig: MultiSpeakerVoiceConfig
}

private struct MultiSpeakerVoiceConfig: Encodable {
    let speakerVoiceConfigs: [SpeakerVoiceConfig]
}

private struct SpeakerVoiceConfig: Encodable {
    let speaker: String
    let voiceConfig: VoiceConfig
}

private struct VoiceConfig: Encodable {
    let prebuiltVoiceConfig: PrebuiltVoiceConfig
}

private struct PrebuiltVoiceConfig: Encodable {
    let voiceName: String
}

private struct GeminiResponse: Decodable {
    let candidates: [Candidate]
}

private struct Candidate: Decodable {
    let content: CandidateContent
}

private struct CandidateContent: Decodable {
    let parts: [CandidatePart]
}

private struct CandidatePart: Decodable {
    let inlineData: InlineData
}

private struct InlineData: Decodable {
    let data: String
}

enum GeminiError: LocalizedError {
    case invalidAPIKey
    case invalidRequest
    case invalidResponse
    case timeout(String)
    case apiError(String)
    case emptyAudio

    var errorDescription: String? {
        switch self {
        case .invalidAPIKey:
            return "Invalid API key."
        case .invalidRequest:
            return "Failed to build request."
        case .invalidResponse:
            return "Invalid server response."
        case .timeout(let modelTitle):
            return "\(modelTitle) timed out. Please try again (it can be slower)."
        case .apiError(let message):
            return "Gemini API error: \(message)"
        case .emptyAudio:
            return "No audio returned by Gemini."
        }
    }
}

private extension Data {
    mutating func appendLE<T: FixedWidthInteger>(_ value: T) {
        var littleEndian = value.littleEndian
        Swift.withUnsafeBytes(of: &littleEndian) { bytes in
            append(contentsOf: bytes)
        }
    }
}
