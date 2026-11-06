import AVFoundation
import Combine
import Foundation

enum SpeakingConnectionState: Equatable {
    case idle
    case preparing
    case active
    case ending
    case completed
    case failed(String)
}

enum SpeakingTurnPhase: Equatable {
    case waitingForTutor
    case tutorSpeaking
    case learnerTurn
    case recording
}

@MainActor
final class SpeakingPracticeViewModel: ObservableObject {
    static let minimumRecordingSeconds: TimeInterval = 0.5
    static let maximumRecordingSeconds: TimeInterval = 60

    @Published private(set) var connectionState: SpeakingConnectionState = .idle
    @Published private(set) var phase: SpeakingTurnPhase = .waitingForTutor
    @Published private(set) var notice: String?
    @Published private(set) var latestTutorText: String?
    @Published var isTutorTextRevealed = false
    @Published private(set) var microphoneDenied = false
    /// Set from Starta until the tutor's opening is ready, for the loading line.
    @Published private(set) var openingWaitStartedAt: Date?
    @Published private(set) var expectedOpeningWait: TimeInterval = SpeakingPracticeViewModel.defaultOpeningWait
    /// 3, 2, 1 in the talk key once the opening has arrived, so the tutor does not start speaking unannounced.
    @Published private(set) var countdown: Int?
    /// The creator model has already written this lesson's speaking plan, so it can be recreated.
    @Published private(set) var hasSpeakingPlan = false
    @Published private(set) var isRecreatingPlan = false
    /// A new plan was requested; the next Starta waits for it.
    @Published private(set) var planRecreated = false
    @Published private(set) var planNotice: String?

    static let defaultOpeningWait: TimeInterval = 6

    private let lessonID: String
    private let generationIdentity: LessonGenerationIdentity
    private let lessonSynchronizer: any LessonSynchronizing
    private let transportFactory: @MainActor () -> any SpeakingTurnTransport
    private let microphonePermissionProvider: () async -> Bool
    private let planStatusProvider: (String) async throws -> SpeakingPlanStatus
    private let planRegenerator: (String) async throws -> Void
    private var transport: (any SpeakingTurnTransport)?
    private var turnTask: Task<Void, Never>?
    private var timeoutWorkItem: DispatchWorkItem?
    private var recordingLimitWorkItem: DispatchWorkItem?

    init(
        lessonID: String,
        generatedLesson: GeneratedLesson,
        lessonSynchronizer: any LessonSynchronizing,
        transportFactory: @escaping @MainActor () -> any SpeakingTurnTransport = { SpeakingTurnClient() },
        microphonePermissionProvider: @escaping () async -> Bool = SpeakingMicrophonePermission.request,
        planStatusProvider: @escaping (String) async throws -> SpeakingPlanStatus = {
            try await BackendClient.shared.speakingPlanStatus(lessonID: $0)
        },
        planRegenerator: @escaping (String) async throws -> Void = {
            try await BackendClient.shared.regenerateSpeakingPlan(lessonID: $0)
        }
    ) {
        self.lessonID = lessonID
        self.generationIdentity = LessonGenerationIdentity(generatedLesson)
        self.lessonSynchronizer = lessonSynchronizer
        self.transportFactory = transportFactory
        self.microphonePermissionProvider = microphonePermissionProvider
        self.planStatusProvider = planStatusProvider
        self.planRegenerator = planRegenerator
    }

    /// The recreate key shows only before Starta, once the creator model has written this lesson's plan.
    var showsRecreatePlan: Bool {
        connectionState == .idle && (hasSpeakingPlan || isRecreatingPlan)
    }

    var canRecreatePlan: Bool {
        connectionState == .idle && hasSpeakingPlan && !isRecreatingPlan
    }

    func loadPlanStatus() async {
        guard let status = try? await planStatusProvider(lessonID) else { return }
        hasSpeakingPlan = status.exists && !status.generating
    }

    func recreatePlan() async {
        guard canRecreatePlan else { return }
        isRecreatingPlan = true
        planNotice = nil
        defer { isRecreatingPlan = false }
        do {
            try await planRegenerator(lessonID)
            hasSpeakingPlan = false
            planRecreated = true
        } catch {
            planNotice = "Planen kunde inte skapas om: \(error.localizedDescription)"
        }
    }

    deinit {
        timeoutWorkItem?.cancel()
        recordingLimitWorkItem?.cancel()
        turnTask?.cancel()
    }

    var canRetry: Bool {
        if case .failed = connectionState { return !microphoneDenied }
        return false
    }

    var canReplayTutor: Bool {
        connectionState == .active && phase == .learnerTurn && latestTutorText != nil
    }

    var isTalkButtonEnabled: Bool {
        connectionState == .active && (phase == .learnerTurn || phase == .recording)
    }

    var isPreparingOpening: Bool {
        openingWaitStartedAt != nil && (connectionState == .preparing || connectionState == .active)
    }

    func start() async {
        guard connectionState == .idle || canRetry else { return }
        cancelTimers()
        microphoneDenied = false
        notice = nil
        latestTutorText = nil
        isTutorTextRevealed = false
        connectionState = .preparing
        phase = .waitingForTutor
        openingWaitStartedAt = Date()
        expectedOpeningWait = Self.defaultOpeningWait
        countdown = nil

        guard await microphonePermissionProvider() else {
            microphoneDenied = true
            connectionState = .failed("Microphone access is required for Speaking practice.")
            return
        }

        do {
            try Task.checkCancellation()
            try await lessonSynchronizer.ensureLessonSynced(
                lessonID: lessonID,
                expectedGenerationIdentity: generationIdentity
            )
            try Task.checkCancellation()
            let transport = transportFactory()
            self.transport = transport
            let info = try await transport.start(lessonID: lessonID)
            try Task.checkCancellation()
            scheduleTimeout(after: info.timeLimit)
            if let expectedWait = info.expectedWait {
                expectedOpeningWait = expectedWait
            }
            connectionState = .active
            runTurn(audio: nil)
        } catch is CancellationError {
            await stopTransport()
            clearOpeningState()
            connectionState = .idle
        } catch {
            await stopTransport()
            clearOpeningState()
            connectionState = .failed(error.localizedDescription)
        }
    }

    /// Runs inside the opening turn once its audio has arrived; the tutor speaks when it returns.
    private func countDownToOpening() async {
        openingWaitStartedAt = nil
        for value in [3, 2, 1] {
            guard !Task.isCancelled else { break }
            countdown = value
            try? await Task.sleep(for: .seconds(1))
        }
        countdown = nil
    }

    private func clearOpeningState() {
        openingWaitStartedAt = nil
        countdown = nil
    }

    func retry() async {
        await end()
        await start()
    }

    /// The single big button: start recording on the learner's turn, send it on the second tap.
    func talkButtonTapped() {
        guard connectionState == .active, let transport else { return }
        switch phase {
        case .learnerTurn:
            do {
                try transport.startRecording()
                notice = nil
                phase = .recording
                scheduleRecordingLimit()
            } catch {
                notice = error.localizedDescription
            }
        case .recording:
            finishRecording()
        case .waitingForTutor, .tutorSpeaking:
            break
        }
    }

    /// Plays the tutor's last reply again; the learner's turn resumes once it has finished.
    func replayTutorTapped() {
        guard canReplayTutor, let transport else { return }
        notice = nil
        phase = .tutorSpeaking
        turnTask = Task { [weak self] in
            await transport.replayLastTutorSpeech()
            guard let self, !Task.isCancelled, self.connectionState == .active else { return }
            self.phase = .learnerTurn
        }
    }

    func end() async {
        guard connectionState != .ending, connectionState != .completed else { return }
        connectionState = .ending
        cancelTimers()
        turnTask?.cancel()
        turnTask = nil
        await stopTransport()
        clearOpeningState()
        phase = .waitingForTutor
        connectionState = .idle
    }

    private func finishRecording() {
        recordingLimitWorkItem?.cancel()
        recordingLimitWorkItem = nil
        guard let recording = transport?.finishRecording(),
              recording.duration >= Self.minimumRecordingSeconds else {
            notice = "That was too short. Tap, speak, then tap again."
            phase = .learnerTurn
            return
        }
        runTurn(audio: recording.wavData)
    }

    private func runTurn(audio: Data?) {
        guard let transport else { return }
        phase = .waitingForTutor
        var beforeSpeech: (() async -> Void)?
        if audio == nil {
            beforeSpeech = { [weak self] in await self?.countDownToOpening() }
        }
        turnTask = Task { [weak self, beforeSpeech] in
            do {
                let result = try await transport.performTurn(audio: audio, beforeSpeech: beforeSpeech) { [weak self] text in
                    guard let self else { return }
                    self.latestTutorText = text.isEmpty ? nil : text
                    self.isTutorTextRevealed = false
                    self.phase = .tutorSpeaking
                }
                guard let self, !Task.isCancelled, self.connectionState == .active else { return }
                if result.practiceComplete {
                    await self.completePractice()
                } else {
                    self.phase = .learnerTurn
                }
            } catch {
                guard let self, !Task.isCancelled, self.connectionState == .active else { return }
                self.handleTurnFailure(error, wasOpening: audio == nil)
            }
        }
    }

    private func handleTurnFailure(_ error: Error, wasOpening: Bool) {
        if case BackendError.apiError(let status, _) = error, status == 404 {
            Task { await failPractice("This Speaking practice has ended. Please start again.") }
            return
        }
        if wasOpening {
            Task { await failPractice(error.localizedDescription) }
            return
        }
        // A failed learner turn keeps the practice going; the learner simply tries again.
        notice = error.localizedDescription
        phase = .learnerTurn
    }

    private func completePractice() async {
        // Straight to completed: an `.ending` step in between would turn the
        // operator away and back and blink the tutor-text keys while the
        // server session closes.
        connectionState = .completed
        cancelTimers()
        await stopTransport()
    }

    private func failPractice(_ message: String) async {
        connectionState = .ending
        cancelTimers()
        await stopTransport()
        clearOpeningState()
        phase = .waitingForTutor
        connectionState = .failed(message)
    }

    private func scheduleTimeout(after seconds: TimeInterval) {
        timeoutWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            Task { @MainActor [weak self] in
                await self?.failPractice("This Speaking practice reached the 10-minute safety limit.")
            }
        }
        timeoutWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + min(max(seconds, 1), 600), execute: workItem)
    }

    private func scheduleRecordingLimit() {
        recordingLimitWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            Task { @MainActor [weak self] in
                guard let self, self.phase == .recording else { return }
                self.finishRecording()
            }
        }
        recordingLimitWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + Self.maximumRecordingSeconds, execute: workItem)
    }

    private func cancelTimers() {
        timeoutWorkItem?.cancel()
        timeoutWorkItem = nil
        recordingLimitWorkItem?.cancel()
        recordingLimitWorkItem = nil
    }

    private func stopTransport() async {
        let activeTransport = transport
        transport = nil
        await activeTransport?.stop()
    }
}

enum SpeakingMicrophonePermission {
    static func request() async -> Bool {
        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            return true
        case .denied:
            return false
        case .undetermined:
            return await withCheckedContinuation { continuation in
                AVAudioApplication.requestRecordPermission { granted in
                    continuation.resume(returning: granted)
                }
            }
        @unknown default:
            return false
        }
    }
}
