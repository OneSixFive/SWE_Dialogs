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

    func testInteractorCannotMarkLessonCompletedDirectly() throws {
        let response = InteractorResponse(
            assistantText: "Bra jobbat.",
            statePatch: LessonStatePatch(
                phase: .completed,
                currentQuestionID: nil,
                mistakeNotesAdd: []
            ),
            translationQuiz: nil
        )

        XCTAssertThrowsError(try LessonValidator.validate(response: response, generatedLesson: Self.sampleGeneratedLesson())) { error in
            guard case LessonValidationError.invalidPhasePatch(.completed) = error else {
                return XCTFail("Expected invalidPhasePatch(.completed), got \(error).")
            }
        }
    }

    @MainActor
    func testInteractorProgressionPatchDoesNotChangeQuestionState() throws {
        let generatedLesson = Self.sampleGeneratedLesson()
        var state = LessonState.fresh(lessonID: generatedLesson.lessonID)
        state.phase = .comprehension
        state.currentQuestionID = "q1"

        let response = InteractorResponse(
            assistantText: "Bra svar.",
            statePatch: LessonStatePatch(
                phase: .comprehension,
                currentQuestionID: "q2",
                mistakeNotesAdd: []
            ),
            translationQuiz: nil
        )

        try state.apply(response: response, generatedLesson: generatedLesson)

        XCTAssertEqual(state.currentQuestionID, "q1")
    }

    func testInteractorPhasePatchDoesNotStartDiscussion() throws {
        let generatedLesson = Self.sampleGeneratedLesson()
        var state = LessonState.fresh(lessonID: generatedLesson.lessonID)
        state.phase = .listening

        let response = InteractorResponse(
            assistantText: "Bra svar.",
            statePatch: LessonStatePatch(
                phase: .discussion,
                currentQuestionID: "q1",
                mistakeNotesAdd: []
            ),
            translationQuiz: nil
        )

        try state.apply(response: response, generatedLesson: generatedLesson)

        XCTAssertEqual(state.phase, .listening)
        XCTAssertNil(state.currentQuestionID)
    }

    func testInteractorPhasePatchDoesNotStartTranslationWithoutQuiz() throws {
        let generatedLesson = Self.sampleGeneratedLesson()
        var state = LessonState.fresh(lessonID: generatedLesson.lessonID)
        state.phase = .discussion

        let response = InteractorResponse(
            assistantText: "Vi fortsätter.",
            statePatch: LessonStatePatch(
                phase: .translation,
                currentQuestionID: nil,
                mistakeNotesAdd: []
            ),
            translationQuiz: nil
        )

        try state.apply(response: response, generatedLesson: generatedLesson)

        XCTAssertEqual(state.phase, .discussion)
        XCTAssertNil(state.translationQuiz)
    }

    func testTranslationQuizStartsAtFirstSentence() throws {
        let generatedLesson = Self.sampleGeneratedLesson()
        var state = LessonState.fresh(lessonID: generatedLesson.lessonID)
        state.phase = .discussion

        let response = InteractorResponse(
            assistantText: "Nu börjar övningen.",
            statePatch: LessonStatePatch(
                phase: nil,
                currentQuestionID: nil,
                mistakeNotesAdd: []
            ),
            translationQuiz: TranslationQuiz(
                sentencesEN: [
                    "They leave the package first.",
                    "Then they go to the pharmacy.",
                    "The store is on the other side.",
                    "She changes the order on the way.",
                    "He asks why it matters."
                ]
            )
        )

        try state.apply(response: response, generatedLesson: generatedLesson)

        XCTAssertEqual(state.phase, .translation)
        XCTAssertEqual(state.currentTranslationIndex, 0)
        XCTAssertEqual(state.translationQuiz?.sentencesEN.count, 5)
    }

    func testCompletingComprehensionWaitsForDiscussionStep() throws {
        let generatedLesson = Self.sampleGeneratedLesson()
        var state = LessonState.fresh(lessonID: generatedLesson.lessonID)
        state.phase = .comprehension
        state.currentQuestionID = "q3"

        let response = InteractorResponse(
            assistantText: "Bra svar.",
            statePatch: LessonStatePatch(
                phase: .discussion,
                currentQuestionID: "q3",
                mistakeNotesAdd: []
            ),
            translationQuiz: nil
        )

        try state.apply(response: response, generatedLesson: generatedLesson)

        XCTAssertEqual(state.phase, .comprehension)
        XCTAssertEqual(state.currentQuestionID, "q3")
    }

    private static func sampleGeneratedLesson() -> GeneratedLesson {
        GeneratedLesson(
            lessonID: "b1_stage_1_week_1_day_1",
            dialogue: (1...20).map { index in
                DialogueLine(speaker: index.isMultiple(of: 2) ? .Erik : .Anna, text: "Rad \(index)")
            },
            comprehensionQuestions: [
                GeneratedQuestion(id: "q1", questionSV: "Vad händer?"),
                GeneratedQuestion(id: "q2", questionSV: "Varför är det viktigt?"),
                GeneratedQuestion(id: "q3", questionSV: "Vad blir resultatet?")
            ],
            generatedAt: Date(timeIntervalSince1970: 0),
            model: "test",
            schemaVersion: 1
        )
    }
}
