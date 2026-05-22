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

    static func generateWav(dialog: String, model: TTSModel) async throws -> Data {
        try await BackendClient.shared.generateWav(dialog: dialog, model: model.rawValue)
    }
}
