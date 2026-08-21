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

    func testVocabularyPracticeNextRequiresActiveQuestionAssessment() {
        let unanswered = Self.sampleVocabularyPractice(answeredQuestionIDs: [])
        let answered = Self.sampleVocabularyPractice(answeredQuestionIDs: ["q1"])

        XCTAssertFalse(unanswered.canAdvance)
        XCTAssertTrue(answered.canAdvance)
        XCTAssertEqual(answered.activeQuestion?.sentenceEN, "Sentence 1")
    }

    func testCompletedVocabularyPracticeIsReadOnlyForProgression() {
        let completed = Self.sampleVocabularyPractice(
            status: .completed,
            answeredQuestionIDs: ["q1", "q2", "q3", "q4", "q5"]
        )

        XCTAssertFalse(completed.canAdvance)
        XCTAssertEqual(completed.summary.status, .completed)
        XCTAssertEqual(completed.summary.answeredCount, 5)
    }

    func testLessonAudioContentHashMatchesBackendCanonicalIdentity() {
        XCTAssertEqual(
            LessonAudioContentIdentity.hash(for: Self.sampleGeneratedLesson()),
            "d0e8ad2687295eed5e079524f5855c698c2beea9974efcc36042975ce32e2963"
        )
    }

    @MainActor
    func testSpeakingViewModelDoesNotSyncOrConnectWhenMicrophoneIsDenied() async {
        let synchronizer = FakeLessonSynchronizer()
        let transport = FakeRealtimeSpeakingTransport()
        let viewModel = SpeakingPracticeViewModel(
            lessonID: Self.sampleGeneratedLesson().lessonID,
            generatedLesson: Self.sampleGeneratedLesson(),
            lessonSynchronizer: synchronizer,
            transportFactory: { transport },
            microphonePermissionProvider: { false }
        )

        await viewModel.start()

        XCTAssertEqual(synchronizer.ensureCallCount, 0)
        XCTAssertEqual(transport.startCallCount, 0)
        XCTAssertTrue(viewModel.microphoneDenied)
        guard case .failed = viewModel.connectionState else {
            return XCTFail("Expected microphone denial to fail startup.")
        }
    }

    @MainActor
    func testSpeakingViewModelSyncsHandlesEventsAndCleansUp() async {
        let generatedLesson = Self.sampleGeneratedLesson()
        let synchronizer = FakeLessonSynchronizer()
        let transport = FakeRealtimeSpeakingTransport()
        let viewModel = SpeakingPracticeViewModel(
            lessonID: generatedLesson.lessonID,
            generatedLesson: generatedLesson,
            lessonSynchronizer: synchronizer,
            transportFactory: { transport },
            microphonePermissionProvider: { true }
        )

        await viewModel.start()
        XCTAssertEqual(synchronizer.ensureCallCount, 1)
        XCTAssertEqual(transport.startCallCount, 1)
        XCTAssertEqual(viewModel.connectionState, .connecting)

        transport.eventHandler?(.connected)
        await Task.yield()
        XCTAssertEqual(viewModel.connectionState, .active)
        XCTAssertEqual(viewModel.activity, .listening)

        transport.eventHandler?(.assistantSpeechStarted)
        await Task.yield()
        XCTAssertEqual(viewModel.activity, .assistantSpeaking)

        await viewModel.end()
        XCTAssertEqual(transport.stopCallCount, 1)
        XCTAssertEqual(viewModel.connectionState, .idle)
    }

    @MainActor
    func testSpeakingViewModelStopsWhenDataChannelNeverConnects() async {
        let generatedLesson = Self.sampleGeneratedLesson()
        let synchronizer = FakeLessonSynchronizer()
        let transport = FakeRealtimeSpeakingTransport()
        let viewModel = SpeakingPracticeViewModel(
            lessonID: generatedLesson.lessonID,
            generatedLesson: generatedLesson,
            lessonSynchronizer: synchronizer,
            transportFactory: { transport },
            microphonePermissionProvider: { true },
            connectionTimeoutSeconds: 0.01
        )

        await viewModel.start()
        try? await Task.sleep(nanoseconds: 50_000_000)

        XCTAssertEqual(transport.stopCallCount, 1)
        guard case .failed(let message) = viewModel.connectionState else {
            return XCTFail("Expected connection establishment to time out.")
        }
        XCTAssertTrue(message.contains("did not open"))
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

    private static func sampleVocabularyPractice(
        status: VocabularyPracticeStatus = .active,
        answeredQuestionIDs: [String]
    ) -> VocabularyPractice {
        let questions = (1...5).map { index in
            VocabularyPracticeQuestion(id: "q\(index)", sentenceEN: "Sentence \(index)")
        }
        return VocabularyPractice(
            id: "practice-1",
            courseLevel: "B1",
            stageNumber: 1,
            status: status,
            currentQuestionIndex: 0,
            answeredCount: answeredQuestionIDs.count,
            createdAt: Date(timeIntervalSince1970: 0),
            updatedAt: Date(timeIntervalSince1970: 0),
            completedAt: status == .completed ? Date(timeIntervalSince1970: 1) : nil,
            progressCutoffAbsoluteDay: 1,
            quiz: VocabularyPracticeQuiz(openingText: "Start", questions: questions),
            state: VocabularyPracticeState(
                currentQuestionIndex: 0,
                answeredQuestionIDs: answeredQuestionIDs,
                completed: status == .completed
            ),
            messages: []
        )
    }
}

@MainActor
private final class FakeLessonSynchronizer: LessonSynchronizing {
    private(set) var ensureCallCount = 0

    func ensureLessonSynced(
        lessonID: String,
        expectedGenerationIdentity: LessonGenerationIdentity
    ) async throws {
        ensureCallCount += 1
    }
}

private final class FakeRealtimeSpeakingTransport: RealtimeSpeakingTransport {
    var eventHandler: ((RealtimeSpeakingEvent) -> Void)?
    private(set) var startCallCount = 0
    private(set) var stopCallCount = 0

    func start(lessonID: String) async throws -> TimeInterval {
        startCallCount += 1
        return 600
    }

    func stop() async {
        stopCallCount += 1
    }
}
