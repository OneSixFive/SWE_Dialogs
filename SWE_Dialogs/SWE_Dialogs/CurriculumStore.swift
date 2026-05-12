import Combine
import Foundation

private final class BundleAnchor {}

struct CurriculumResource: Codable {
    let schemaVersion: Int
    let generatedFrom: String
    let lessonCount: Int
    let lessons: [LessonPayload]
}

@MainActor
final class CurriculumStore: ObservableObject {
    @Published private(set) var lessons: [LessonPayload] = []
    @Published private(set) var errorMessage: String?

    private var lessonsByID: [String: LessonPayload] = [:]

    init() {
        load()
    }

    var availableLevels: [LessonLevel] {
        LessonLevel.allCases.filter { level in
            lessons.contains { $0.courseLevel == level }
        }
    }

    func stages(for level: LessonLevel) -> [Int] {
        uniqueSorted(lessons.filter { $0.courseLevel == level }.map { $0.coursePosition.stage })
    }

    func weeks(level: LessonLevel, stage: Int) -> [Int] {
        uniqueSorted(
            lessons
                .filter { $0.courseLevel == level && $0.coursePosition.stage == stage }
                .map { $0.coursePosition.week }
        )
    }

    func days(level: LessonLevel, stage: Int, week: Int) -> [LessonPayload] {
        lessons
            .filter {
                $0.courseLevel == level &&
                $0.coursePosition.stage == stage &&
                $0.coursePosition.week == week
            }
            .sorted { $0.coursePosition.day < $1.coursePosition.day }
    }

    func lesson(id: String) -> LessonPayload? {
        lessonsByID[id]
    }

    func firstIncompleteLesson(level: LessonLevel, sessionStore: LessonSessionStore) -> LessonPayload? {
        lessons
            .filter { $0.courseLevel == level }
            .sorted(by: lessonOrder)
            .first { !sessionStore.state(for: $0.id).isCompleted }
    }

    private func load() {
        do {
            let resource = try CurriculumStore.loadCurriculumResource()
            let duplicateIDs = Dictionary(grouping: resource.lessons, by: \.id)
                .filter { $0.value.count > 1 }
                .map(\.key)
            guard duplicateIDs.isEmpty else {
                throw CurriculumStoreError.duplicateLessonIDs(duplicateIDs.sorted())
            }

            lessons = resource.lessons.sorted(by: lessonOrder)
            lessonsByID = Dictionary(uniqueKeysWithValues: lessons.map { ($0.id, $0) })
            errorMessage = nil
        } catch {
            lessons = []
            lessonsByID = [:]
            errorMessage = error.localizedDescription
        }
    }

    private func uniqueSorted(_ values: [Int]) -> [Int] {
        Array(Set(values)).sorted()
    }

    private func lessonOrder(_ lhs: LessonPayload, _ rhs: LessonPayload) -> Bool {
        if lhs.courseLevel.rawValue != rhs.courseLevel.rawValue {
            return lhs.courseLevel.rawValue < rhs.courseLevel.rawValue
        }
        if lhs.coursePosition.stage != rhs.coursePosition.stage {
            return lhs.coursePosition.stage < rhs.coursePosition.stage
        }
        if lhs.coursePosition.week != rhs.coursePosition.week {
            return lhs.coursePosition.week < rhs.coursePosition.week
        }
        return lhs.coursePosition.day < rhs.coursePosition.day
    }

    static func loadCurriculumResource() throws -> CurriculumResource {
        let url = try ResourceLoader.url(
            forResource: "curriculum",
            withExtension: "json",
            subdirectory: "Resources"
        )
        let data = try Data(contentsOf: url)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let resource = try decoder.decode(CurriculumResource.self, from: data)

        guard resource.lessonCount == resource.lessons.count else {
            throw CurriculumStoreError.lessonCountMismatch(expected: resource.lessonCount, actual: resource.lessons.count)
        }

        return resource
    }
}

enum ResourceLoader {
    static var bundle: Bundle {
        Bundle(for: BundleAnchor.self)
    }

    static func url(forResource name: String, withExtension ext: String, subdirectory: String?) throws -> URL {
        if let url = bundle.url(forResource: name, withExtension: ext, subdirectory: subdirectory) {
            return url
        }

        if let url = bundle.url(forResource: name, withExtension: ext) {
            return url
        }

        throw CurriculumStoreError.missingResource("\(subdirectory.map { "\($0)/" } ?? "")\(name).\(ext)")
    }

    static func prompt(named name: String) throws -> String {
        let url = try url(forResource: name, withExtension: "md", subdirectory: "Resources/TutorPrompts")
        return try String(contentsOf: url, encoding: .utf8)
    }
}

enum CurriculumStoreError: LocalizedError {
    case missingResource(String)
    case lessonCountMismatch(expected: Int, actual: Int)
    case duplicateLessonIDs([String])

    var errorDescription: String? {
        switch self {
        case .missingResource(let resource):
            return "Missing bundled resource: \(resource)."
        case .lessonCountMismatch(let expected, let actual):
            return "Curriculum lesson count mismatch: expected \(expected), found \(actual)."
        case .duplicateLessonIDs(let ids):
            return "Duplicate lesson IDs in curriculum: \(ids.joined(separator: ", "))."
        }
    }
}
