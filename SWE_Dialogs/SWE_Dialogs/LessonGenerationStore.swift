import Combine
import Foundation

@MainActor
final class LessonGenerationStore: ObservableObject {
    @Published private(set) var lessonsByID: [String: GeneratedLesson] = [:]

    private let generatedLessonsURL = FileStorage.documentsDirectory.appendingPathComponent("generated_lessons.json")

    init() {
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
        do {
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
