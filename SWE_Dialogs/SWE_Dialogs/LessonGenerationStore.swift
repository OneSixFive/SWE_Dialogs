import Combine
import Foundation

@MainActor
final class LessonGenerationStore: ObservableObject {
    @Published private(set) var lessonsByID: [String: GeneratedLesson] = [:]

    private var generatedLessonsURL: URL?
    private var configuredUserID: Int?

    func configure(userID: Int?) {
        guard configuredUserID != userID else { return }
        configuredUserID = userID

        guard let userID else {
            generatedLessonsURL = nil
            lessonsByID = [:]
            return
        }

        FileStorage.migrateLegacyFileIfNeeded(fileName: "generated_lessons.json", toUserID: userID)
        generatedLessonsURL = FileStorage.userDirectory(userID: userID).appendingPathComponent("generated_lessons.json")
        lessonsByID = [:]
        load()
    }

    func generatedLesson(for lessonID: String) -> GeneratedLesson? {
        lessonsByID[lessonID]
    }

    func save(_ lesson: GeneratedLesson) {
        lessonsByID[lesson.lessonID] = lesson
        persist()
    }

    func remove(lessonID: String) {
        lessonsByID[lessonID] = nil
        persist()
    }

    private func load() {
        guard let generatedLessonsURL else {
            lessonsByID = [:]
            return
        }
        guard let data = try? Data(contentsOf: generatedLessonsURL) else { return }

        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            lessonsByID = try decoder.decode([String: GeneratedLesson].self, from: data)
        } catch {
            lessonsByID = [:]
        }
    }

    private func persist() {
        guard let generatedLessonsURL else { return }
        do {
            try FileManager.default.createDirectory(
                at: generatedLessonsURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            encoder.dateEncodingStrategy = .iso8601
            let data = try encoder.encode(lessonsByID)
            try data.write(to: generatedLessonsURL, options: [.atomic])
        } catch {
            // Keep the lesson UI usable if local persistence fails.
        }
    }
}
