import AVFoundation
import Foundation
import OSLog

struct SpeakingRecording {
    let wavData: Data
    let duration: TimeInterval
}

struct SpeakingTurnResult: Equatable {
    let practiceComplete: Bool
}

enum SpeakingTurnClientError: LocalizedError {
    case notStarted
    case recordingFailed
    case interrupted(String)

    var errorDescription: String? {
        switch self {
        case .notStarted:
            return "Speaking practice has not started."
        case .recordingFailed:
            return "The microphone recording could not be started."
        case .interrupted(let message):
            return message
        }
    }
}

struct SpeakingStartInfo: Equatable {
    /// The session's hard time limit.
    let timeLimit: TimeInterval
    /// How long the tutor's opening is expected to take, when the server knows.
    let expectedWait: TimeInterval?
}

protocol SpeakingTurnTransport: AnyObject {
    /// Opens a server practice session and prepares audio.
    func start(lessonID: String) async throws -> SpeakingStartInfo
    func startRecording() throws
    func finishRecording() -> SpeakingRecording?
    /// Sends a recording (nil for the tutor's opening) and returns after the tutor's reply has finished playing.
    /// `beforeSpeech` runs once the reply's first audio arrives and holds playback until it returns.
    /// `onTutorSpeechStarted` receives the written reply as buffered playback starts.
    func performTurn(
        audio: Data?,
        beforeSpeech: (() async -> Void)?,
        onTutorSpeechStarted: @escaping (String) -> Void
    ) async throws -> SpeakingTurnResult
    /// Plays the last tutor reply again from the cached audio; returns when it has finished playing.
    func replayLastTutorSpeech() async
    /// Asks the server's Replier for a reply the learner could give to the tutor's latest line.
    func suggestReply() async throws -> String
    func stop() async
}

final class SpeakingTurnClient: SpeakingTurnTransport {
    private static let playbackFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32,
        sampleRate: 24_000,
        channels: 1,
        interleaved: false
    )!
    private static let startupBufferMilliseconds = 250
    private static let startupBufferBytes = Int(playbackFormat.sampleRate) * startupBufferMilliseconds / 1_000
        * MemoryLayout<Int16>.size
    private static let logger = Logger(subsystem: "dima.SWE-Dialogs", category: "SpeakingPlayback")

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var lessonID: String?
    private var sessionID: String?
    private var pendingBuffers = 0
    private var turnGeneration = 0
    private var streamFinished = false
    private var playbackContinuation: CheckedContinuation<Void, Never>?
    private var tutorStartupTask: Task<Void, Never>?
    private var lastTutorAudio: [Data] = []

    init() {
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: Self.playbackFormat)
    }

    func start(lessonID: String) async throws -> SpeakingStartInfo {
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try audioSession.setActive(true)
        try engine.start()

        let session = try await BackendClient.shared.startSpeakingSession(lessonID: lessonID)
        self.lessonID = lessonID
        sessionID = session.sessionID
        return SpeakingStartInfo(
            timeLimit: TimeInterval(max(session.timeoutSeconds, 1)),
            expectedWait: session.expectedWaitSeconds.map { TimeInterval(max($0, 1)) }
        )
    }

    func startRecording() throws {
        let url = FileManager.default.temporaryDirectory.appending(path: "speaking-turn-\(UUID().uuidString).wav")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        guard recorder.record() else {
            throw SpeakingTurnClientError.recordingFailed
        }
        self.recorder = recorder
        recordingURL = url
    }

    func finishRecording() -> SpeakingRecording? {
        guard let recorder, let recordingURL else { return nil }
        let duration = recorder.currentTime
        recorder.stop()
        self.recorder = nil
        self.recordingURL = nil
        defer { try? FileManager.default.removeItem(at: recordingURL) }
        guard let data = try? Data(contentsOf: recordingURL) else { return nil }
        return SpeakingRecording(wavData: data, duration: duration)
    }

    func performTurn(
        audio: Data?,
        beforeSpeech: (() async -> Void)?,
        onTutorSpeechStarted: @escaping (String) -> Void
    ) async throws -> SpeakingTurnResult {
        guard let lessonID, let sessionID else {
            throw SpeakingTurnClientError.notStarted
        }
        try preparePlayback()
        lastTutorAudio = []

        var practiceComplete = false
        var tutorText = ""
        var tutorStarted = false
        var queuedBytes = 0
        let clock = ContinuousClock()

        func startTutorSpeech() {
            guard !tutorStarted, pendingBuffers > 0 else { return }
            tutorStarted = true
            tutorStartupTask?.cancel()
            tutorStartupTask = nil
            player.play()
            onTutorSpeechStarted(tutorText)
        }

        do {
            let events = BackendClient.shared.speakingTurnEvents(lessonID: lessonID, sessionID: sessionID, audio: audio)
            for try await event in events {
                switch event {
                case .turn(let say, let complete):
                    tutorText = say
                    practiceComplete = complete
                case .audio(let pcm):
                    guard pcm.count >= MemoryLayout<Int16>.size else { continue }
                    let startupDeadline = lastTutorAudio.isEmpty
                        ? clock.now.advanced(by: .milliseconds(Self.startupBufferMilliseconds))
                        : nil
                    if startupDeadline != nil, let beforeSpeech {
                        // Later audio queues in the event stream meanwhile.
                        await beforeSpeech()
                    }
                    try Task.checkCancellation()
                    lastTutorAudio.append(pcm)
                    schedule(pcm)
                    guard !tutorStarted else { continue }
                    queuedBytes += pcm.count
                    if queuedBytes >= Self.startupBufferBytes {
                        startTutorSpeech()
                    } else if let startupDeadline {
                        tutorStartupTask = Task {
                            try? await clock.sleep(until: startupDeadline)
                            guard !Task.isCancelled else { return }
                            startTutorSpeech()
                        }
                    }
                case .done:
                    try Task.checkCancellation()
                    startTutorSpeech()
                case .interrupted(let message):
                    throw SpeakingTurnClientError.interrupted(message)
                }
            }
            try Task.checkCancellation()
            startTutorSpeech()
        } catch {
            tutorStartupTask?.cancel()
            tutorStartupTask = nil
            player.stop()
            throw error
        }
        await waitForPlayback()
        return SpeakingTurnResult(practiceComplete: practiceComplete)
    }

    func replayLastTutorSpeech() async {
        guard !lastTutorAudio.isEmpty, (try? preparePlayback()) != nil else { return }
        for pcm in lastTutorAudio {
            schedule(pcm)
        }
        player.play()
        await waitForPlayback()
    }

    func suggestReply() async throws -> String {
        guard let lessonID, let sessionID else {
            throw SpeakingTurnClientError.notStarted
        }
        return try await BackendClient.shared.speakingReplyHint(lessonID: lessonID, sessionID: sessionID)
    }

    func stop() async {
        tutorStartupTask?.cancel()
        tutorStartupTask = nil
        lastTutorAudio = []
        recorder?.stop()
        recorder = nil
        if let recordingURL {
            try? FileManager.default.removeItem(at: recordingURL)
        }
        recordingURL = nil
        await fadeOutOutput()
        player.stop()
        engine.stop()
        engine.mainMixerNode.outputVolume = 1
        resumePlaybackWaiter()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

        if let lessonID, let sessionID {
            self.lessonID = nil
            self.sessionID = nil
            await BackendClient.shared.endSpeakingSession(lessonID: lessonID, sessionID: sessionID)
        }
    }

    /// Ramps the output down and lets the hardware play out what it already
    /// holds, so stopping the engine and releasing the session neither cuts
    /// the last word nor clicks.
    private func fadeOutOutput() async {
        guard engine.isRunning else { return }
        let mixer = engine.mainMixerNode
        let steps = 8
        for step in 1...steps {
            mixer.outputVolume = 1 - Float(step) / Float(steps)
            try? await Task.sleep(for: .milliseconds(15))
        }
        try? await Task.sleep(for: .milliseconds(150))
    }

    private func preparePlayback() throws {
        turnGeneration += 1
        player.stop()
        pendingBuffers = 0
        streamFinished = false
        if !engine.isRunning {
            try engine.start()
        }
    }

    private func schedule(_ pcm: Data) {
        let frameCount = pcm.count / MemoryLayout<Int16>.size
        guard frameCount > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: Self.playbackFormat, frameCapacity: AVAudioFrameCount(frameCount)),
              let samples = buffer.floatChannelData?[0] else {
            return
        }
        buffer.frameLength = AVAudioFrameCount(frameCount)
        pcm.withUnsafeBytes { raw in
            let source = raw.bindMemory(to: Int16.self)
            for index in 0..<frameCount {
                samples[index] = Float(Int16(littleEndian: source[index])) / 32_768
            }
        }
        if pendingBuffers == 0, player.isPlaying {
            Self.logger.notice("Speaking audio resumed after the playback queue drained")
        }
        pendingBuffers += 1
        let generation = turnGeneration
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor [weak self] in
                // Buffers flushed by stopping an earlier turn must not count against the current one.
                guard let self, self.turnGeneration == generation else { return }
                self.pendingBuffers -= 1
                if self.streamFinished && self.pendingBuffers <= 0 {
                    self.resumePlaybackWaiter()
                }
            }
        }
    }

    private func waitForPlayback() async {
        streamFinished = true
        guard pendingBuffers > 0, player.isPlaying else { return }
        await withCheckedContinuation { continuation in
            playbackContinuation = continuation
        }
    }

    private func resumePlaybackWaiter() {
        let continuation = playbackContinuation
        playbackContinuation = nil
        continuation?.resume()
    }
}
