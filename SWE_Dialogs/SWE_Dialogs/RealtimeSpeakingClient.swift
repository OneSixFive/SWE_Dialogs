import AVFoundation
import Foundation
import WebRTC

enum RealtimeSpeakingEvent: Equatable {
    case connected
    case userSpeechStarted
    case userSpeechStopped
    case assistantSpeechStarted
    case assistantSpeechStopped
    case practiceCompleted
    case failed(String)
}

protocol RealtimeSpeakingTransport: AnyObject {
    var eventHandler: ((RealtimeSpeakingEvent) -> Void)? { get set }

    func start(lessonID: String) async throws -> TimeInterval
    func stop() async
}

enum RealtimeSpeakingClientError: LocalizedError {
    case alreadyStarted
    case peerConnectionUnavailable
    case offerFailed
    case localDescriptionFailed
    case remoteDescriptionFailed

    var errorDescription: String? {
        switch self {
        case .alreadyStarted:
            return "Speaking practice is already starting."
        case .peerConnectionUnavailable:
            return "A realtime audio connection could not be created."
        case .offerFailed, .localDescriptionFailed, .remoteDescriptionFailed:
            return "The realtime audio connection could not be negotiated."
        }
    }
}

final class RealtimeSpeakingClient: NSObject, RealtimeSpeakingTransport {
    var eventHandler: ((RealtimeSpeakingEvent) -> Void)?

    private static let factory: RTCPeerConnectionFactory = {
        RTCInitializeSSL()
        // This client negotiates audio and data only. Passing nil video
        // factories avoids initializing WebRTC's camera/video pipeline.
        return RTCPeerConnectionFactory(encoderFactory: nil, decoderFactory: nil)
    }()

    private var peerConnection: RTCPeerConnection?
    private var dataChannel: RTCDataChannel?
    private var audioTrack: RTCAudioTrack?
    private var lessonID: String?
    private var speakingSessionID: String?
    private var hasSentOpeningResponse = false
    private var isAwaitingOpeningPlayback = false
    private let openingResponseLock = NSLock()
    private var isAssistantAudioPlaying = false
    private var isPracticeEndPending = false
    private var hasEmittedPracticeEnd = false
    private let responseStateLock = NSLock()
    private var isStopping = false

    func start(lessonID: String) async throws -> TimeInterval {
        guard peerConnection == nil else {
            throw RealtimeSpeakingClientError.alreadyStarted
        }
        isStopping = false
        resetOpeningState()
        resetResponseState()
        self.lessonID = lessonID

        do {
            try configureAudioSession()
            let peerConnection = try makePeerConnection()
            self.peerConnection = peerConnection
            let offer = try await createOffer(on: peerConnection)
            try await setLocalDescription(offer, on: peerConnection)
            try Task.checkCancellation()
            let answer = try await BackendClient.shared.createSpeakingRealtimeCall(
                lessonID: lessonID,
                sdpOffer: offer.sdp
            )
            speakingSessionID = answer.speakingSessionID
            let remote = RTCSessionDescription(type: .answer, sdp: answer.sdp)
            try await setRemoteDescription(remote, on: peerConnection)
            try forceBuiltInSpeakerIfNeeded()
            return TimeInterval(max(answer.timeoutSeconds, 1))
        } catch {
            await stop()
            throw error
        }
    }

    func stop() async {
        guard !isStopping else { return }
        isStopping = true

        let cleanupLessonID = lessonID
        let cleanupSessionID = speakingSessionID
        lessonID = nil
        speakingSessionID = nil
        resetOpeningState()
        resetResponseState()

        dataChannel?.delegate = nil
        dataChannel?.close()
        dataChannel = nil
        audioTrack?.isEnabled = false
        audioTrack = nil
        peerConnection?.delegate = nil
        peerConnection?.close()
        peerConnection = nil
        deactivateAudioSession()

        if let cleanupLessonID, let cleanupSessionID {
            await BackendClient.shared.endSpeakingRealtimeCall(
                lessonID: cleanupLessonID,
                speakingSessionID: cleanupSessionID
            )
        }
        isStopping = false
    }

    private func makePeerConnection() throws -> RTCPeerConnection {
        let configuration = RTCConfiguration()
        configuration.sdpSemantics = .unifiedPlan
        configuration.bundlePolicy = .maxBundle
        configuration.continualGatheringPolicy = .gatherOnce
        let constraints = RTCMediaConstraints(
            mandatoryConstraints: nil,
            optionalConstraints: ["DtlsSrtpKeyAgreement": kRTCMediaConstraintsValueTrue]
        )
        guard let peerConnection = Self.factory.peerConnection(
            with: configuration,
            constraints: constraints,
            delegate: self
        ) else {
            throw RealtimeSpeakingClientError.peerConnectionUnavailable
        }

        let audioSource = Self.factory.audioSource(
            with: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)
        )
        let audioTrack = Self.factory.audioTrack(with: audioSource, trackId: "speaking-audio")
        // Do not let audio-session startup transients become a false learner turn.
        // The microphone is enabled after the tutor's opening audio has finished.
        audioTrack.isEnabled = false
        peerConnection.add(audioTrack, streamIds: ["speaking-stream"])
        self.audioTrack = audioTrack

        let dataConfiguration = RTCDataChannelConfiguration()
        guard let dataChannel = peerConnection.dataChannel(
            forLabel: "oai-events",
            configuration: dataConfiguration
        ) else {
            peerConnection.close()
            throw RealtimeSpeakingClientError.peerConnectionUnavailable
        }
        dataChannel.delegate = self
        self.dataChannel = dataChannel
        return peerConnection
    }

    private func createOffer(on peerConnection: RTCPeerConnection) async throws -> RTCSessionDescription {
        let constraints = RTCMediaConstraints(
            mandatoryConstraints: [kRTCMediaConstraintsOfferToReceiveAudio: kRTCMediaConstraintsValueTrue],
            optionalConstraints: nil
        )
        return try await withCheckedThrowingContinuation { continuation in
            peerConnection.offer(for: constraints) { description, error in
                if let description {
                    continuation.resume(returning: description)
                } else {
                    continuation.resume(throwing: error ?? RealtimeSpeakingClientError.offerFailed)
                }
            }
        }
    }

    private func setLocalDescription(
        _ description: RTCSessionDescription,
        on peerConnection: RTCPeerConnection
    ) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            peerConnection.setLocalDescription(description) { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: ())
                }
            }
        }
    }

    private func setRemoteDescription(
        _ description: RTCSessionDescription,
        on peerConnection: RTCPeerConnection
    ) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            peerConnection.setRemoteDescription(description) { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: ())
                }
            }
        }
    }

    private func configureAudioSession() throws {
        let audioSession = RTCAudioSession.sharedInstance()
        audioSession.lockForConfiguration()
        defer { audioSession.unlockForConfiguration() }
        try audioSession.setCategory(
            .playAndRecord,
            mode: .voiceChat,
            options: [.defaultToSpeaker, .allowBluetoothHFP]
        )
        try audioSession.setActive(true)
        try forceBuiltInSpeakerIfNeeded(audioSession: audioSession, alreadyLocked: true)
    }

    private func forceBuiltInSpeakerIfNeeded(
        audioSession: RTCAudioSession = .sharedInstance(),
        alreadyLocked: Bool = false
    ) throws {
        if !alreadyLocked {
            audioSession.lockForConfiguration()
        }
        defer {
            if !alreadyLocked {
                audioSession.unlockForConfiguration()
            }
        }
        let outputs = audioSession.currentRoute.outputs
        let usesOnlyBuiltInAudio = outputs.isEmpty || outputs.allSatisfy {
            $0.portType == .builtInReceiver || $0.portType == .builtInSpeaker
        }
        if usesOnlyBuiltInAudio {
            try audioSession.overrideOutputAudioPort(.speaker)
        }
    }

    private func deactivateAudioSession() {
        let audioSession = RTCAudioSession.sharedInstance()
        audioSession.lockForConfiguration()
        defer { audioSession.unlockForConfiguration() }
        try? audioSession.overrideOutputAudioPort(.none)
        try? audioSession.setActive(false)
    }

    private func sendOpeningResponseIfNeeded() {
        openingResponseLock.lock()
        guard !hasSentOpeningResponse,
              let dataChannel,
              dataChannel.readyState == .open else {
            openingResponseLock.unlock()
            return
        }
        let data = Data(#"{"type":"response.create"}"#.utf8)
        let didSend = dataChannel.sendData(RTCDataBuffer(data: data, isBinary: false))
        if didSend {
            hasSentOpeningResponse = true
            isAwaitingOpeningPlayback = true
        }
        openingResponseLock.unlock()
        guard didSend else { return }
        emit(.connected)
    }

    private func enableMicrophoneAfterOpeningIfNeeded() {
        openingResponseLock.lock()
        let shouldEnable = isAwaitingOpeningPlayback
        isAwaitingOpeningPlayback = false
        openingResponseLock.unlock()
        if shouldEnable {
            audioTrack?.isEnabled = true
        }
    }

    private func resetOpeningState() {
        openingResponseLock.lock()
        hasSentOpeningResponse = false
        isAwaitingOpeningPlayback = false
        openingResponseLock.unlock()
    }

    private func resetResponseState() {
        responseStateLock.lock()
        isAssistantAudioPlaying = false
        isPracticeEndPending = false
        hasEmittedPracticeEnd = false
        responseStateLock.unlock()
    }

    private func markAssistantAudioPlaying() {
        responseStateLock.lock()
        isAssistantAudioPlaying = true
        responseStateLock.unlock()
    }

    private func requestPracticeEnd() {
        responseStateLock.lock()
        isPracticeEndPending = true
        let shouldEmit = !isAssistantAudioPlaying && !hasEmittedPracticeEnd
        if shouldEmit {
            hasEmittedPracticeEnd = true
        }
        responseStateLock.unlock()

        audioTrack?.isEnabled = false
        if shouldEmit {
            emit(.practiceCompleted)
        }
    }

    private func handleAssistantAudioStopped() {
        responseStateLock.lock()
        isAssistantAudioPlaying = false
        let shouldEnd = isPracticeEndPending && !hasEmittedPracticeEnd
        if shouldEnd {
            hasEmittedPracticeEnd = true
        }
        responseStateLock.unlock()

        if shouldEnd {
            audioTrack?.isEnabled = false
            emit(.practiceCompleted)
        } else {
            enableMicrophoneAfterOpeningIfNeeded()
            emit(.assistantSpeechStopped)
        }
    }

    private func containsPracticeEndCall(_ object: [String: Any]) -> Bool {
        guard let response = object["response"] as? [String: Any],
              let output = response["output"] as? [[String: Any]] else {
            return false
        }
        return output.contains { item in
            item["type"] as? String == "function_call"
                && item["name"] as? String == "end_speaking_practice"
        }
    }

    private func handleRealtimeEvent(_ data: Data) {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = object["type"] as? String else {
            return
        }
        switch type {
        case "input_audio_buffer.speech_started":
            emit(.userSpeechStarted)
        case "input_audio_buffer.speech_stopped":
            emit(.userSpeechStopped)
        case "response.created":
            emit(.assistantSpeechStarted)
        case "output_audio_buffer.started", "response.audio.delta", "response.output_audio.delta":
            markAssistantAudioPlaying()
            emit(.assistantSpeechStarted)
        case "output_audio_buffer.stopped":
            handleAssistantAudioStopped()
        case "response.done":
            if containsPracticeEndCall(object) {
                requestPracticeEnd()
            }
        case "error":
            emit(.failed("The realtime service reported a session error."))
        default:
            break
        }
    }

    private func emit(_ event: RealtimeSpeakingEvent) {
        DispatchQueue.main.async { [weak self] in
            self?.eventHandler?(event)
        }
    }
}

extension RealtimeSpeakingClient: RTCDataChannelDelegate {
    func dataChannelDidChangeState(_ dataChannel: RTCDataChannel) {
        if dataChannel.readyState == .open {
            try? forceBuiltInSpeakerIfNeeded()
            sendOpeningResponseIfNeeded()
        }
    }

    func dataChannel(_ dataChannel: RTCDataChannel, didReceiveMessageWith buffer: RTCDataBuffer) {
        handleRealtimeEvent(buffer.data)
    }
}

extension RealtimeSpeakingClient: RTCPeerConnectionDelegate {
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
    func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {
        switch newState {
        case .failed:
            if !isStopping {
                emit(.failed("The realtime audio connection was lost."))
            }
        default:
            break
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {
        self.dataChannel?.delegate = nil
        self.dataChannel = dataChannel
        dataChannel.delegate = self
        sendOpeningResponseIfNeeded()
    }
}
