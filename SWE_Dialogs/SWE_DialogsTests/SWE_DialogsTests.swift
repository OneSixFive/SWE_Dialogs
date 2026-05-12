import XCTest
@testable import SWE_Dialogs

final class SWE_DialogsTests: XCTestCase {
    @MainActor
    func testBundledCurriculumDecodesAllLessons() throws {
        let resource = try CurriculumStore.loadCurriculumResource()

        XCTAssertEqual(resource.lessons.count, 224)
        XCTAssertEqual(resource.lessonCount, 224)
    }

    @MainActor
    func testBundledCurriculumHasExpectedLevelCounts() throws {
        let resource = try CurriculumStore.loadCurriculumResource()
        let grouped = Dictionary(grouping: resource.lessons, by: \.courseLevel)

        XCTAssertEqual(grouped[.b1]?.count, 112)
        XCTAssertEqual(grouped[.b2]?.count, 112)
    }

    @MainActor
    func testBundledCurriculumHasNoDuplicateIDs() throws {
        let resource = try CurriculumStore.loadCurriculumResource()
        let ids = resource.lessons.map(\.id)

        XCTAssertEqual(Set(ids).count, ids.count)
    }

    @MainActor
    func testBundledCurriculumHasExpectedStageWeekDayGrid() throws {
        let resource = try CurriculumStore.loadCurriculumResource()

        for level in LessonLevel.allCases {
            let levelLessons = resource.lessons.filter { $0.courseLevel == level }

            for stage in 1...4 {
                for week in 1...4 {
                    let days = levelLessons
                        .filter { $0.coursePosition.stage == stage && $0.coursePosition.week == week }
                        .map { $0.coursePosition.day }
                        .sorted()

                    XCTAssertEqual(days, Array(1...7), "\(level.rawValue) stage \(stage), week \(week)")
                }
            }
        }
    }
}
