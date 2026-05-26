import Foundation

enum FileStorage {
    static let documentsDirectory: URL = {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }()

    static let lessonAudioDirectory: URL = {
        documentsDirectory.appendingPathComponent("lesson_audio", isDirectory: true)
    }()

    static func userDirectory(userID: Int) -> URL {
        documentsDirectory
            .appendingPathComponent("users", isDirectory: true)
            .appendingPathComponent(String(userID), isDirectory: true)
    }

    static func userLessonAudioDirectory(userID: Int) -> URL {
        userDirectory(userID: userID).appendingPathComponent("lesson_audio", isDirectory: true)
    }

    static func migrateLegacyFileIfNeeded(fileName: String, toUserID userID: Int) {
        let source = documentsDirectory.appendingPathComponent(fileName)
        let destination = userDirectory(userID: userID).appendingPathComponent(fileName)
        guard FileManager.default.fileExists(atPath: source.path),
              !FileManager.default.fileExists(atPath: destination.path) else {
            return
        }

        do {
            try FileManager.default.createDirectory(
                at: destination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try FileManager.default.copyItem(at: source, to: destination)
        } catch {
            // Keep the app usable if legacy cache migration fails.
        }
    }

    static func migrateLegacyLessonAudioIfNeeded(toUserID userID: Int) {
        let source = lessonAudioDirectory
        let destination = userLessonAudioDirectory(userID: userID)
        guard FileManager.default.fileExists(atPath: source.path),
              !FileManager.default.fileExists(atPath: destination.path) else {
            return
        }

        do {
            try FileManager.default.createDirectory(
                at: destination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try FileManager.default.copyItem(at: source, to: destination)
        } catch {
            // Lesson audio can be regenerated if this cache migration fails.
        }
    }

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

    static func saveLessonWavFile(data: Data, lessonID: String, userID: Int) throws -> URL {
        let directory = userLessonAudioDirectory(userID: userID)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let safeLessonID = lessonID.replacingOccurrences(of: "/", with: "_")
        let name = "\(safeLessonID)-\(formatter.string(from: .now)).wav"
        let url = directory.appendingPathComponent(name)
        try data.write(to: url, options: [.atomic])
        return url
    }

    static func lessonAudioURL(fileName: String) -> URL {
        lessonAudioDirectory.appendingPathComponent(fileName)
    }

    static func lessonAudioURL(fileName: String, userID: Int) -> URL {
        userLessonAudioDirectory(userID: userID).appendingPathComponent(fileName)
    }
}
