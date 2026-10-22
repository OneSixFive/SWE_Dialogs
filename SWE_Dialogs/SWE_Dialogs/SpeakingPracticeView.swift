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
        VStack(spacing: 20) {
            HStack {
                Button {
                    endAndDismiss()
                } label: {
                    RetroKeyLabel(title: usesCloseLabel ? "Stäng" : "Avsluta", titleSize: 12)
                }
                .buttonStyle(RetroKeyStyle(tint: .beige))
                .frame(width: 110, height: 48)

                Spacer()

                AmberReadout(text: "TALA", size: 13)
            }

            VUMeterView(isActive: isSoundActive)
                .padding(.horizontal, 20)

            AmberReadout(text: statusTitle.uppercased(), size: 15)

            Spacer(minLength: 8)

            talkButton

            if let detail = statusDetail {
                Text(detail)
                    .font(RetroFont.label(12, weight: .medium))
                    .foregroundStyle(Retro.labelOnDarkSoft)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 12)
            }

            tutorTextReveal

            Spacer(minLength: 8)

            if viewModel.connectionState == .idle {
                startKey("Starta", tint: .orange) {
                    Task { await viewModel.start() }
                }
            } else if viewModel.microphoneDenied {
                startKey("Öppna inställningar", tint: .mustard) {
                    guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
                    UIApplication.shared.open(url)
                }
            } else if viewModel.canRetry {
                startKey("Försök igen", tint: .mustard) {
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

    private var isSoundActive: Bool {
        viewModel.connectionState == .active
            && (viewModel.phase == .recording || viewModel.phase == .tutorSpeaking)
    }

    private static let wellSize = CGSize(width: 190, height: 290)

    private var talkButton: some View {
        let isRecording = viewModel.connectionState == .active && viewModel.phase == .recording
        let isWaiting = viewModel.connectionState == .active && viewModel.phase == .waitingForTutor
            || viewModel.connectionState == .preparing
        return Button {
            viewModel.talkButtonTapped()
        } label: {
            ZStack {
                // The handset sits in a well cut into the wood, ringed by a
                // light. State colours switch instantly; only the recording
                // ring moves.
                Capsule()
                    .fill(ringColor.opacity(viewModel.isTalkButtonEnabled ? 0.4 : 0.12))
                    .frame(width: Self.wellSize.width + 16, height: Self.wellSize.height + 16)
                    .blur(radius: 16)
                    .transaction { $0.animation = nil }
                Capsule()
                    .fill(Retro.walnutDeep.mix(with: .black, by: 0.4).shadow(.inner(color: .black.opacity(0.9), radius: 10, y: 6)))
                    .frame(width: Self.wellSize.width, height: Self.wellSize.height)
                Capsule()
                    .strokeBorder(ringColor.opacity(viewModel.isTalkButtonEnabled ? 0.95 : 0.3), lineWidth: 4)
                    .frame(width: Self.wellSize.width, height: Self.wellSize.height)
                    .shadow(color: ringColor.opacity(viewModel.isTalkButtonEnabled ? 0.8 : 0), radius: 6)
                    .transaction { $0.animation = nil }
                if isRecording {
                    RecordingBreathRing(color: ringColor, size: Self.wellSize)
                }
                HandsetView(finish: handsetFinish, height: Self.wellSize.height - 34)
                    .saturation(viewModel.isTalkButtonEnabled ? 1 : 0.8)
                    .brightness(viewModel.isTalkButtonEnabled ? 0 : -0.06)
                    .transaction { $0.animation = nil }
                if isWaiting {
                    ProgressView()
                        .controlSize(.large)
                        .tint(Retro.paper)
                } else if let statusImage {
                    Image(systemName: statusImage)
                        .font(.system(size: 26, weight: .bold))
                        .foregroundStyle(Retro.paper)
                        .offset(y: 72)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(!viewModel.isTalkButtonEnabled)
        .accessibilityLabel(statusTitle)
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
                .buttonStyle(RetroKeyStyle(tint: .beige, isLatched: viewModel.isTutorTextRevealed))
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

    /// Light ring: olive when it is the learner's turn, orange while recording.
    private var ringColor: Color {
        switch viewModel.connectionState {
        case .failed:
            return Retro.pencilRed
        case .completed:
            return Retro.olive
        case .active:
            switch viewModel.phase {
            case .learnerTurn:
                return Retro.olive.mix(with: .green, by: 0.35)
            case .recording:
                return Retro.orange
            case .tutorSpeaking:
                return Retro.amber
            case .waitingForTutor:
                return Retro.mustard
            }
        default:
            return Retro.brassDark
        }
    }

    private var handsetFinish: HandsetView.Finish {
        if viewModel.connectionState == .active && viewModel.phase == .learnerTurn {
            return .olive
        }
        return .orange
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
