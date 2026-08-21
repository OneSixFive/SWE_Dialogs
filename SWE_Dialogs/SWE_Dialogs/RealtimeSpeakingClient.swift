import AVFoundation
import Foundation
import WebRTC

enum RealtimeSpeakingEvent: Equatable {
    case connected
    case userSpeechStarted
    case userSpeechStopped
    case assistantSpeechStarted
    case assistantSpeechStopped
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
        return RTCPeerConnectionFactory(
            encoderFactory: RTCDefaultVideoEncoderFactory(),
            decoderFactory: RTCDefaultVideoDecoderFactory()
        )
    }()

    private var peerConnection: RTCPeerConnection?
    private var dataChannel: RTCDataChannel?
    private var audioTrack: RTCAudioTrack?
    private var lessonID: String?
    private var speakingSessionID: String?
    private var hasSentOpeningResponse = false
    private var isStopping = false

    func start(lessonID: String) async throws -> TimeInterval {
        guard peerConnection == nil else {
            throw RealtimeSpeakingClientError.alreadyStarted
        }
        isStopping = false
        self.lessonID = lessonID

        do {
            try configureAudioSession()
            let peerConnection = try makePeerConnection()
            self.peerConnection = peerConnection
            let offer = try await createOffer(on: peerConnection)
            try await setLocalDescription(offer, on: peerConnection)
            try await waitForInitialIceGathering(on: peerConnection)
            try Task.checkCancellation()
            let effectiveOffer = peerConnection.localDescription?.sdp ?? offer.sdp
            let answer = try await BackendClient.shared.createSpeakingRealtimeCall(
                lessonID: lessonID,
                sdpOffer: effectiveOffer
            )
            speakingSessionID = answer.speakingSessionID
            let remote = RTCSessionDescription(type: .answer, sdp: answer.sdp)
            try await setRemoteDescription(remote, on: peerConnection)
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
        hasSentOpeningResponse = false

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
        try await withCheckedThrowingContinuation { continuation in
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
        try await withCheckedThrowingContinuation { continuation in
            peerConnection.setRemoteDescription(description) { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: ())
                }
            }
        }
    }

    private func waitForInitialIceGathering(on peerConnection: RTCPeerConnection) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(5))
        while peerConnection.iceGatheringState != .complete, clock.now < deadline {
            try Task.checkCancellation()
            try await Task.sleep(nanoseconds: 50_000_000)
        }
    }

    private func configureAudioSession() throws {
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(
            .playAndRecord,
            mode: .voiceChat,
            options: [.defaultToSpeaker, .allowBluetoothHFP]
        )
        try audioSession.setActive(true)
    }

    private func deactivateAudioSession() {
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func sendOpeningResponseIfNeeded() {
        guard !hasSentOpeningResponse, dataChannel?.readyState == .open else { return }
        hasSentOpeningResponse = true
        let data = Data(#"{"type":"response.create"}"#.utf8)
        _ = dataChannel?.sendData(RTCDataBuffer(data: data, isBinary: false))
        emit(.connected)
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
        case "response.created", "output_audio_buffer.started", "response.audio.delta", "response.output_audio.delta":
            emit(.assistantSpeechStarted)
        case "response.done", "output_audio_buffer.stopped":
            emit(.assistantSpeechStopped)
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
