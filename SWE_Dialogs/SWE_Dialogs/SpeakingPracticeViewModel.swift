import AVFoundation
import Combine
import Foundation

enum SpeakingConnectionState: Equatable {
    case idle
    case preparing
    case connecting
    case active
    case ending
    case completed
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
    private let transportFactory: @MainActor () -> any RealtimeSpeakingTransport
    private let microphonePermissionProvider: () async -> Bool
    private let connectionTimeoutSeconds: TimeInterval
    private var transport: (any RealtimeSpeakingTransport)?
    private var timeoutTask: Task<Void, Never>?
    private var connectionTimeoutTask: Task<Void, Never>?

    init(
        lessonID: String,
        generatedLesson: GeneratedLesson,
        lessonSynchronizer: any LessonSynchronizing,
        transportFactory: @escaping @MainActor () -> any RealtimeSpeakingTransport = { RealtimeSpeakingClient() },
        microphonePermissionProvider: @escaping () async -> Bool = SpeakingMicrophonePermission.request,
        connectionTimeoutSeconds: TimeInterval = 25
    ) {
        self.lessonID = lessonID
        self.generationIdentity = LessonGenerationIdentity(generatedLesson)
        self.lessonSynchronizer = lessonSynchronizer
        self.transportFactory = transportFactory
        self.microphonePermissionProvider = microphonePermissionProvider
        self.connectionTimeoutSeconds = connectionTimeoutSeconds
    }

    var canRetry: Bool {
        if case .failed = connectionState { return !microphoneDenied }
        return false
    }

    func start() async {
        guard connectionState == .idle || canRetry else { return }
        cancelTimeoutTasks()
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
            scheduleConnectionTimeout()
        } catch is CancellationError {
            cancelTimeoutTasks()
            await stopTransport()
            connectionState = .idle
        } catch {
            cancelTimeoutTasks()
            await stopTransport()
            connectionState = .failed(error.localizedDescription)
        }
    }

    func retry() async {
        await end()
        await start()
    }

    func end() async {
        guard connectionState != .ending, connectionState != .completed else { return }
        connectionState = .ending
        activity = .waiting
        cancelTimeoutTasks()
        await stopTransport()
        connectionState = .idle
    }

    private func handle(_ event: RealtimeSpeakingEvent) async {
        guard connectionState != .ending, connectionState != .completed else { return }
        switch event {
        case .connected:
            guard connectionState == .connecting else { return }
            connectionTimeoutTask?.cancel()
            connectionTimeoutTask = nil
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
        case .practiceCompleted:
            connectionState = .ending
            cancelTimeoutTasks()
            activity = .waiting
            await stopTransport()
            connectionState = .completed
        case .failed(let message):
            connectionState = .ending
            cancelTimeoutTasks()
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
            self.connectionState = .ending
            await self.stopTransport()
            self.connectionState = .failed("This Speaking practice reached the 10-minute safety limit.")
            self.activity = .waiting
        }
    }

    private func scheduleConnectionTimeout() {
        connectionTimeoutTask?.cancel()
        connectionTimeoutTask = Task { [weak self] in
            guard let self else { return }
            let boundedSeconds = min(max(self.connectionTimeoutSeconds, 0.01), 60)
            let nanoseconds = UInt64(boundedSeconds * 1_000_000_000)
            try? await Task.sleep(nanoseconds: nanoseconds)
            guard !Task.isCancelled, self.connectionState == .connecting else { return }
            self.connectionState = .ending
            await self.stopTransport()
            self.timeoutTask?.cancel()
            self.timeoutTask = nil
            self.connectionState = .failed("The realtime audio connection did not open. Please try again.")
            self.activity = .waiting
        }
    }

    private func cancelTimeoutTasks() {
        timeoutTask?.cancel()
        timeoutTask = nil
        connectionTimeoutTask?.cancel()
        connectionTimeoutTask = nil
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
