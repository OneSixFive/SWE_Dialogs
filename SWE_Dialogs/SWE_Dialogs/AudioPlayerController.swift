import AVFoundation
import Combine
import Foundation
import MediaPlayer

final class AudioPlayerController: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published private(set) var isPlaying = false
    @Published private(set) var isScrubbing = false
    @Published private(set) var currentTime: TimeInterval = 0
    @Published private(set) var duration: TimeInterval = 0
    @Published private(set) var currentURL: URL?

    private static weak var activeController: AudioPlayerController?
    private static var didConfigureRemoteCommands = false

    private var player: AVAudioPlayer?
    private var timer: Timer?
    private var shouldResumeAfterScrub = false

    override init() {
        super.init()
        configureRemoteCommandsIfNeeded()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleAudioSessionInterruption),
            name: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance()
        )
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    func load(url: URL) {
        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.playback, mode: .default)
            try audioSession.setActive(true)

            player = try AVAudioPlayer(contentsOf: url)
            player?.delegate = self
            player?.prepareToPlay()

            currentURL = url
            currentTime = 0
            duration = player?.duration ?? 0
            isPlaying = false
            isScrubbing = false
            shouldResumeAfterScrub = false
            stopTimer()
            updateNowPlayingInfo()
        } catch {
            player = nil
            currentURL = nil
            currentTime = 0
            duration = 0
            isPlaying = false
            isScrubbing = false
            shouldResumeAfterScrub = false
            stopTimer()
            MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
        }
    }

    func togglePlayback() {
        guard let player else { return }

        if player.isPlaying {
            player.pause()
            isPlaying = false
            stopTimer()
            updateNowPlayingInfo()
        } else {
            Self.activeController = self
            activateAudioSessionIfNeeded()
            player.play()
            isPlaying = true
            startTimer()
            updateNowPlayingInfo()
        }
    }

    func stopPlayback() {
        pause()
    }

    func seek(to time: TimeInterval) {
        guard let player else { return }
        let clamped = max(0, min(time, player.duration))
        player.currentTime = clamped
        currentTime = clamped
        updateNowPlayingInfo()
    }

    func beginScrubbing() {
        guard let player else { return }
        guard !isScrubbing else { return }

        shouldResumeAfterScrub = player.isPlaying
        isScrubbing = true

        if player.isPlaying {
            player.pause()
            isPlaying = false
            stopTimer()
            updateNowPlayingInfo()
        }
    }

    func scrub(to time: TimeInterval) {
        seek(to: time)
    }

    func endScrubbing() {
        guard let player else { return }
        guard isScrubbing else { return }

        isScrubbing = false

        if shouldResumeAfterScrub {
            Self.activeController = self
            activateAudioSessionIfNeeded()
            player.play()
            isPlaying = true
            startTimer()
        }

        shouldResumeAfterScrub = false
        updateNowPlayingInfo()
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        isPlaying = false
        stopTimer()
        currentTime = player.currentTime
        updateNowPlayingInfo()
    }

    private func startTimer() {
        stopTimer()
        timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            guard let self, let player = self.player else { return }
            self.currentTime = player.currentTime
            self.duration = player.duration
            self.updateNowPlayingInfo()
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    private func play() {
        guard let player else { return }
        Self.activeController = self
        if !player.isPlaying {
            activateAudioSessionIfNeeded()
            player.play()
            isPlaying = true
            startTimer()
            updateNowPlayingInfo()
        }
    }

    private func pause() {
        guard let player else { return }
        if player.isPlaying {
            player.pause()
            isPlaying = false
            stopTimer()
            updateNowPlayingInfo()
        }
    }

    private func configureRemoteCommandsIfNeeded() {
        guard !Self.didConfigureRemoteCommands else { return }
        Self.didConfigureRemoteCommands = true

        let commandCenter = MPRemoteCommandCenter.shared()

        commandCenter.playCommand.isEnabled = true
        commandCenter.pauseCommand.isEnabled = true
        commandCenter.togglePlayPauseCommand.isEnabled = true
        commandCenter.changePlaybackPositionCommand.isEnabled = true

        commandCenter.playCommand.addTarget { _ in
            guard let controller = Self.activeController else { return .commandFailed }
            controller.play()
            return .success
        }

        commandCenter.pauseCommand.addTarget { _ in
            guard let controller = Self.activeController else { return .commandFailed }
            controller.pause()
            return .success
        }

        commandCenter.togglePlayPauseCommand.addTarget { _ in
            guard let controller = Self.activeController else { return .commandFailed }
            controller.togglePlayback()
            return .success
        }

        commandCenter.changePlaybackPositionCommand.addTarget { event in
            guard
                let controller = Self.activeController,
                let positionEvent = event as? MPChangePlaybackPositionCommandEvent
            else {
                return .commandFailed
            }
            controller.seek(to: positionEvent.positionTime)
            return .success
        }
    }

    private func updateNowPlayingInfo() {
        guard let currentURL else { return }

        var info: [String: Any] = [
            MPMediaItemPropertyTitle: currentURL.deletingPathExtension().lastPathComponent,
            MPMediaItemPropertyArtist: "SWE Dialogs",
            MPMediaItemPropertyPlaybackDuration: duration,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: currentTime,
            MPNowPlayingInfoPropertyPlaybackRate: isPlaying ? 1.0 : 0.0
        ]

        if #available(iOS 16.0, *) {
            info[MPNowPlayingInfoPropertyMediaType] = MPNowPlayingInfoMediaType.audio.rawValue
        }

        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func activateAudioSessionIfNeeded() {
        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.playback, mode: .default)
            try audioSession.setActive(true)
        } catch {
            // Leave playback attempt to AVAudioPlayer even if activation fails.
        }
    }

    @objc
    private func handleAudioSessionInterruption(_ notification: Notification) {
        guard
            let userInfo = notification.userInfo,
            let typeValue = userInfo[AVAudioSessionInterruptionTypeKey] as? UInt,
            let type = AVAudioSession.InterruptionType(rawValue: typeValue)
        else {
            return
        }

        switch type {
        case .began:
            if isPlaying {
                pause()
            }
        case .ended:
            let optionsRaw = userInfo[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            let options = AVAudioSession.InterruptionOptions(rawValue: optionsRaw)
            if options.contains(.shouldResume) {
                play()
            }
        @unknown default:
            break
        }
    }
}
