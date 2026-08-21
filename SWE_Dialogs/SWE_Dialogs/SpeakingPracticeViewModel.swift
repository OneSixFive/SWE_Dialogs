import AVFoundation
import Foundation

enum SpeakingConnectionState: Equatable {
    case idle
    case preparing
    case connecting
    case active
    case ending
    case failed(String)
}

enum SpeakingActivity: Equatable {
    case waiting
    case listening
    case learnerSpeaking
    case assistantSpeaking
}

@MainActor
final class SpeakingPracticeViewModel: ObservableObject {
    @Published private(set) var connectionState: SpeakingConnectionState = .idle
    @Published private(set) var activity: SpeakingActivity = .waiting
    @Published private(set) var microphoneDenied = false

    private let lessonID: String
    private let generationIdentity: LessonGenerationIdentity
    private let lessonSynchronizer: any LessonSynchronizing
    private let transportFactory: () -> any RealtimeSpeakingTransport
    private let microphonePermissionProvider: () async -> Bool
    private var transport: (any RealtimeSpeakingTransport)?
    private var timeoutTask: Task<Void, Never>?

    init(
        lessonID: String,
        generatedLesson: GeneratedLesson,
        lessonSynchronizer: any LessonSynchronizing,
        transportFactory: @escaping () -> any RealtimeSpeakingTransport = { RealtimeSpeakingClient() },
        microphonePermissionProvider: @escaping () async -> Bool = SpeakingMicrophonePermission.request
    ) {
        self.lessonID = lessonID
        self.generationIdentity = LessonGenerationIdentity(generatedLesson)
        self.lessonSynchronizer = lessonSynchronizer
        self.transportFactory = transportFactory
        self.microphonePermissionProvider = microphonePermissionProvider
    }

    var canRetry: Bool {
        if case .failed = connectionState { return !microphoneDenied }
        return false
    }

    func start() async {
        guard connectionState == .idle || canRetry else { return }
        timeoutTask?.cancel()
        microphoneDenied = false
        connectionState = .preparing
        activity = .waiting

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
            connectionState = .connecting
            let transport = transportFactory()
            transport.eventHandler = { [weak self] event in
                Task { @MainActor in
                    await self?.handle(event)
                }
            }
            self.transport = transport
            let timeout = try await transport.start(lessonID: lessonID)
            try Task.checkCancellation()
            scheduleTimeout(after: timeout)
        } catch is CancellationError {
            await stopTransport()
            connectionState = .idle
        } catch {
            await stopTransport()
            connectionState = .failed(error.localizedDescription)
        }
    }

    func retry() async {
        await end()
        await start()
    }

    func end() async {
        guard connectionState != .ending else { return }
        connectionState = .ending
        activity = .waiting
        timeoutTask?.cancel()
        timeoutTask = nil
        await stopTransport()
        connectionState = .idle
    }

    private func handle(_ event: RealtimeSpeakingEvent) async {
        guard connectionState != .ending else { return }
        switch event {
        case .connected:
            connectionState = .active
            activity = .listening
        case .userSpeechStarted:
            activity = .learnerSpeaking
        case .userSpeechStopped:
            activity = .waiting
        case .assistantSpeechStarted:
            activity = .assistantSpeaking
        case .assistantSpeechStopped:
            activity = .listening
        case .failed(let message):
            timeoutTask?.cancel()
            timeoutTask = nil
            await stopTransport()
            connectionState = .failed(message)
            activity = .waiting
        }
    }

    private func scheduleTimeout(after seconds: TimeInterval) {
        timeoutTask?.cancel()
        timeoutTask = Task { [weak self] in
            let boundedSeconds = min(max(seconds, 1), 600)
            let nanoseconds = UInt64(boundedSeconds * 1_000_000_000)
            try? await Task.sleep(nanoseconds: nanoseconds)
            guard !Task.isCancelled, let self else { return }
            await self.stopTransport()
            self.connectionState = .failed("This Speaking practice reached the 10-minute safety limit.")
            self.activity = .waiting
        }
    }

    private func stopTransport() async {
        let activeTransport = transport
        transport = nil
        activeTransport?.eventHandler = nil
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
