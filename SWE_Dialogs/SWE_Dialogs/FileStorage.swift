import Foundation

enum FileStorage {
    static let documentsDirectory: URL = {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }()

    static func saveWavFile(data: Data) throws -> URL {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let name = "dialog-\(formatter.string(from: .now)).wav"
        let url = documentsDirectory.appendingPathComponent(name)
        try data.write(to: url, options: [.atomic])
        return url
    }
}
