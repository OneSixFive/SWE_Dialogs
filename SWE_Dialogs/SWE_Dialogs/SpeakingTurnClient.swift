import AVFoundation
import Foundation

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

protocol SpeakingTurnTransport: AnyObject {
    /// Opens a server practice session and prepares audio; returns the session time limit.
    func start(lessonID: String) async throws -> TimeInterval
    func startRecording() throws
    func finishRecording() -> SpeakingRecording?
    /// Sends a recording (nil for the tutor's opening) and returns after the tutor's reply has finished playing.
    /// `onTutorSpeechStarted` receives the written reply when its audio starts.
    func performTurn(audio: Data?, onTutorSpeechStarted: @escaping (String) -> Void) async throws -> SpeakingTurnResult
    /// Plays the last tutor reply again from the cached audio; returns when it has finished playing.
    func replayLastTutorSpeech() async
    func stop() async
}

final class SpeakingTurnClient: SpeakingTurnTransport {
    private static let playbackFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32,
        sampleRate: 24_000,
        channels: 1,
        interleaved: false
    )!

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
    private var lastTutorAudio: [Data] = []

    init() {
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: Self.playbackFormat)
    }

    func start(lessonID: String) async throws -> TimeInterval {
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try audioSession.setActive(true)
        try engine.start()

        let session = try await BackendClient.shared.startSpeakingSession(lessonID: lessonID)
        self.lessonID = lessonID
        sessionID = session.sessionID
        return TimeInterval(max(session.timeoutSeconds, 1))
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

    func performTurn(audio: Data?, onTutorSpeechStarted: @escaping (String) -> Void) async throws -> SpeakingTurnResult {
        guard let lessonID, let sessionID else {
            throw SpeakingTurnClientError.notStarted
        }
        try beginPlayback()
        lastTutorAudio = []

        var practiceComplete = false
        var tutorText = ""
        var tutorStarted = false
        do {
            let events = BackendClient.shared.speakingTurnEvents(lessonID: lessonID, sessionID: sessionID, audio: audio)
            for try await event in events {
                switch event {
                case .turn(let say, let complete):
                    tutorText = say
                    practiceComplete = complete
                case .audio(let pcm):
                    lastTutorAudio.append(pcm)
                    schedule(pcm)
                    if !tutorStarted {
                        tutorStarted = true
                        onTutorSpeechStarted(tutorText)
                    }
                case .done:
                    break
                case .interrupted(let message):
                    throw SpeakingTurnClientError.interrupted(message)
                }
            }
        } catch {
            player.stop()
            throw error
        }
        await waitForPlayback()
        return SpeakingTurnResult(practiceComplete: practiceComplete)
    }

    func replayLastTutorSpeech() async {
        guard !lastTutorAudio.isEmpty, (try? beginPlayback()) != nil else { return }
        for pcm in lastTutorAudio {
            schedule(pcm)
        }
        await waitForPlayback()
    }

    func stop() async {
        lastTutorAudio = []
        recorder?.stop()
        recorder = nil
        if let recordingURL {
            try? FileManager.default.removeItem(at: recordingURL)
        }
        recordingURL = nil
        player.stop()
        engine.stop()
        resumePlaybackWaiter()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

        if let lessonID, let sessionID {
            self.lessonID = nil
            self.sessionID = nil
            await BackendClient.shared.endSpeakingSession(lessonID: lessonID, sessionID: sessionID)
        }
    }

    private func beginPlayback() throws {
        turnGeneration += 1
        pendingBuffers = 0
        streamFinished = false
        if !engine.isRunning {
            try engine.start()
        }
        player.play()
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
