import Foundation

enum FileStorage {
    static let documentsDirectory: URL = {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }()

    static let lessonAudioDirectory: URL = {
        documentsDirectory.appendingPathComponent("lesson_audio", isDirectory: true)
    }()

    static func saveWavFile(data: Data) throws -> URL {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let name = "dialog-\(formatter.string(from: .now)).wav"
        let url = documentsDirectory.appendingPathComponent(name)
        try data.write(to: url, options: [.atomic])
        return url
    }

    static func saveLessonWavFile(data: Data, lessonID: String) throws -> URL {
        try FileManager.default.createDirectory(at: lessonAudioDirectory, withIntermediateDirectories: true)

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let safeLessonID = lessonID.replacingOccurrences(of: "/", with: "_")
        let name = "\(safeLessonID)-\(formatter.string(from: .now)).wav"
        let url = lessonAudioDirectory.appendingPathComponent(name)
        try data.write(to: url, options: [.atomic])
        return url
    }

    static func lessonAudioURL(fileName: String) -> URL {
        lessonAudioDirectory.appendingPathComponent(fileName)
    }
}
