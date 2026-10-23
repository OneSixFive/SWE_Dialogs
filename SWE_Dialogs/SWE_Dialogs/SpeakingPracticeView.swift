import SwiftUI
import UIKit

struct SpeakingPracticeView: View {
    let payload: LessonPayload

    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var viewModel: SpeakingPracticeViewModel

    init(
        payload: LessonPayload,
        generatedLesson: GeneratedLesson,
        sessionStore: LessonSessionStore
    ) {
        self.payload = payload
        _viewModel = StateObject(
            wrappedValue: SpeakingPracticeViewModel(
                lessonID: payload.id,
                generatedLesson: generatedLesson,
                lessonSynchronizer: sessionStore
            )
        )
    }

    var body: some View {
        VStack(spacing: 14) {
            HStack {
                Button {
                    endAndDismiss()
                } label: {
                    RetroKeyLabel(title: usesCloseLabel ? "Stäng" : "Avsluta", titleSize: 12)
                }
                .buttonStyle(RetroKeyStyle(tint: .graphite, cornerRadius: 6))
                .frame(width: 110, height: 48)

                Spacer()

                AmberReadout(text: statusTitle.uppercased(), size: 13)
            }

            operatorStage

            // Always two lines tall, so the scene above keeps its size as the
            // hint changes from phase to phase.
            Text(statusDetail ?? "")
                .font(RetroFont.label(12, weight: .medium))
                .foregroundStyle(Retro.labelOnDarkSoft)
                .multilineTextAlignment(.center)
                .lineLimit(2, reservesSpace: true)
                .minimumScaleFactor(0.75)
                .padding(.horizontal, 12)

            tutorTextReveal

            if viewModel.connectionState == .idle {
                startKey("Starta", tint: .accent) {
                    Task { await viewModel.start() }
                }
            } else if viewModel.microphoneDenied {
                startKey("Öppna inställningar", tint: .graphite) {
                    guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
                    UIApplication.shared.open(url)
                }
            } else if viewModel.canRetry {
                startKey("Försök igen", tint: .graphite) {
                    Task { await viewModel.retry() }
                }
            }
        }
        .padding(20)
        .retroScreenBackground()
        .onChange(of: scenePhase) { _, phase in
            guard phase == .background else { return }
            endAndDismiss()
        }
        .onDisappear {
            Task { await viewModel.end() }
        }
        .interactiveDismissDisabled()
    }

    private func startKey(_ title: String, tint: RetroKeyTint, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            RetroKeyLabel(title: title, titleSize: 15)
        }
        .buttonStyle(RetroKeyStyle(tint: tint))
        .frame(height: 60)
        .padding(.horizontal, 30)
    }

    private var operatorPose: OperatorSceneView.Pose {
        switch viewModel.connectionState {
        case .preparing:
            return .working
        case .active:
            switch viewModel.phase {
            case .waitingForTutor:
                return .working
            case .tutorSpeaking:
                return .talking
            case .learnerTurn, .recording:
                return .listening
            }
        case .idle, .completed:
            // Welcomes the learner before the call and sees them off after.
            return .listening
        case .ending, .failed:
            return .resting
        }
    }

    private static let talkKeySize: CGFloat = 96

    private var operatorStage: some View {
        OperatorStage(pose: operatorPose) {
            talkButton
        }
    }

    private var talkButton: some View {
        let isRecording = viewModel.connectionState == .active && viewModel.phase == .recording
        let isWaiting = viewModel.connectionState == .active && viewModel.phase == .waitingForTutor
            || viewModel.connectionState == .preparing
        let size = Self.talkKeySize
        return Button {
            viewModel.talkButtonTapped()
        } label: {
            ZStack {
                if isWaiting {
                    ProgressView()
                        .controlSize(.regular)
                        .tint(Retro.paper)
                } else {
                    RetroKeyLabel(title: "Tala", systemImage: statusImage ?? "mic.fill", titleSize: 11, imageSize: 26)
                }
            }
        }
        .buttonStyle(RetroKeyStyle(tint: talkKeyTint, cornerRadius: size / 2, edge: 6))
        .frame(width: size, height: size)
        // The key sits in a lit collar: state colours switch instantly; only
        // the recording ring moves.
        .background {
            ZStack {
                Circle()
                    .fill(ringColor.opacity(viewModel.isTalkButtonEnabled ? 0.45 : 0.1))
                    .frame(width: size + 34, height: size + 34)
                    .blur(radius: 14)
                Circle()
                    .fill(Retro.inset.shadow(.inner(color: .black.opacity(0.9), radius: 6, y: 4)))
                    .frame(width: size + 16, height: size + 16)
                Circle()
                    .strokeBorder(ringColor.opacity(viewModel.isTalkButtonEnabled ? 0.95 : 0.3), lineWidth: 3)
                    .frame(width: size + 16, height: size + 16)
                    .shadow(color: ringColor.opacity(viewModel.isTalkButtonEnabled ? 0.8 : 0), radius: 5)
                if isRecording {
                    RecordingBreathRing(color: ringColor, size: CGSize(width: size + 16, height: size + 16))
                }
            }
            .transaction { $0.animation = nil }
        }
        .disabled(!viewModel.isTalkButtonEnabled)
        .accessibilityLabel(statusTitle)
    }

    private var talkKeyTint: RetroKeyTint {
        guard viewModel.connectionState == .active else { return .graphite }
        switch viewModel.phase {
        case .recording:
            return .accent
        case .learnerTurn:
            return .olive
        case .waitingForTutor, .tutorSpeaking:
            return .graphite
        }
    }

    @ViewBuilder
    private var tutorTextReveal: some View {
        if let text = viewModel.latestTutorText,
           viewModel.connectionState == .active || viewModel.connectionState == .completed {
            VStack(spacing: 10) {
                Button {
                    viewModel.isTutorTextRevealed.toggle()
                } label: {
                    RetroKeyLabel(title: viewModel.isTutorTextRevealed ? "Dölj texten" : "Visa lärarens ord", titleSize: 11)
                }
                .buttonStyle(RetroKeyStyle(tint: .bone, isLatched: viewModel.isTutorTextRevealed))
                .frame(width: 200, height: 44)
                if viewModel.isTutorTextRevealed {
                    PaperSheet {
                        Text(text)
                            .font(RetroFont.reading())
                            .foregroundStyle(Retro.ink)
                            .textSelection(.enabled)
                    }
                }
            }
        }
    }

    /// Light ring: green when it is the learner's turn, rust while recording.
    private var ringColor: Color {
        switch viewModel.connectionState {
        case .failed:
            return Retro.pencilRed
        case .completed:
            return Retro.olive
        case .active:
            switch viewModel.phase {
            case .learnerTurn:
                return Color(red: 0.45, green: 0.62, blue: 0.38)
            case .recording:
                return Retro.accent
            case .tutorSpeaking:
                return Retro.amber
            case .waitingForTutor:
                return Retro.ochre
            }
        default:
            return Retro.brassDark
        }
    }

    private var statusImage: String? {
        switch viewModel.connectionState {
        case .failed:
            return "exclamationmark.triangle.fill"
        case .completed:
            return "checkmark"
        case .active:
            switch viewModel.phase {
            case .learnerTurn:
                return "mic.fill"
            case .recording:
                return "stop.fill"
            case .tutorSpeaking, .waitingForTutor:
                return nil
            }
        case .preparing, .ending, .idle:
            return nil
        }
    }

    private var statusTitle: String {
        switch viewModel.connectionState {
        case .idle:
            return "Redo"
        case .preparing:
            return "Förbereder…"
        case .active:
            switch viewModel.phase {
            case .learnerTurn:
                return "Din tur"
            case .recording:
                return "Lyssnar…"
            case .waitingForTutor:
                return "Läraren tänker…"
            case .tutorSpeaking:
                return "Läraren talar"
            }
        case .ending:
            return "Avslutar…"
        case .completed:
            return "Klart!"
        case .failed:
            return "Fel"
        }
    }

    private var statusDetail: String? {
        if case .failed(let message) = viewModel.connectionState {
            return message
        }
        if viewModel.connectionState == .active {
            if let notice = viewModel.notice {
                return notice
            }
            switch viewModel.phase {
            case .learnerTurn:
                return "Tryck på luren, svara på svenska och tryck igen när du är klar."
            case .recording:
                return "Tryck igen när du är klar."
            case .waitingForTutor, .tutorSpeaking:
                return nil
            }
        }
        if viewModel.connectionState == .idle {
            return "Mikrofonen startar först när du trycker på Starta."
        }
        if viewModel.connectionState == .completed {
            return "Läraren har avslutat övningen."
        }
        return nil
    }

    private var usesCloseLabel: Bool {
        viewModel.connectionState == .idle || viewModel.connectionState == .completed
    }

    private func endAndDismiss() {
        Task {
            await viewModel.end()
            dismiss()
        }
    }
}

/// A slow, single-colour ring that breathes while the learner is recording.
private struct RecordingBreathRing: View {
    let color: Color
    let size: CGSize
    @State private var expanded = false

    var body: some View {
        Capsule()
            .stroke(color.opacity(0.5), lineWidth: 3)
            .frame(width: size.width, height: size.height)
            .scaleEffect(expanded ? 1.06 : 1)
            .onAppear {
                withAnimation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true)) {
                    expanded = true
                }
            }
    }
}
