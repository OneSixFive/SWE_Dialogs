import Foundation

enum GeminiTTSService {
    static func generateWav(dialog: String) async throws -> Data {
        try await BackendClient.shared.generateWav(dialog: dialog)
    }
}
