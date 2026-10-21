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
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 28) {
                HStack {
                    Button {
                        endAndDismiss()
                    } label: {
                        Label(usesCloseLabel ? "Close" : "End", systemImage: "xmark")
                            .font(.headline)
                    }
                    .foregroundStyle(.white)
                    Spacer()
                }

                VStack(alignment: .leading, spacing: 18) {
                    Text("Speaking practice")
                        .font(.largeTitle.bold())

                    speakingContext(title: "Situation", text: payload.lessonIntent.realLifeContext)
                    speakingContext(title: "Goal", text: payload.lessonIntent.oneSentenceGoal)
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                Spacer()

                talkButton

                VStack(spacing: 10) {
                    Text(statusTitle)
                        .font(.title2.bold())
                    if let detail = statusDetail {
                        Text(detail)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                }

                Spacer()

                if viewModel.connectionState == .idle {
                    Button("Start practice") {
                        Task { await viewModel.start() }
                    }
                    .buttonStyle(.borderedProminent)
                } else if viewModel.microphoneDenied {
                    Button("Open Settings") {
                        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
                        UIApplication.shared.open(url)
                    }
                    .buttonStyle(.borderedProminent)
                } else if viewModel.canRetry {
                    Button("Try again") {
                        Task { await viewModel.retry() }
                    }
                    .buttonStyle(.borderedProminent)
                }

                Button(usesCloseLabel ? "Close" : "End practice", role: .destructive) {
                    endAndDismiss()
                }
                .buttonStyle(.bordered)
            }
            .padding(24)
            .foregroundStyle(.white)
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .background else { return }
            endAndDismiss()
        }
        .onDisappear {
            Task { await viewModel.end() }
        }
        .interactiveDismissDisabled()
    }

    private func speakingContext(title: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title.uppercased())
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(text)
                .font(.body)
        }
    }

    private var talkButton: some View {
        let isRecording = viewModel.connectionState == .active && viewModel.phase == .recording
        return Button {
            viewModel.talkButtonTapped()
        } label: {
            ZStack {
                Circle()
                    .fill(statusColor.opacity(0.18))
                    .frame(width: 200, height: 200)
                    .scaleEffect(isRecording ? 1.12 : 1)
                    .animation(
                        isRecording ? .easeInOut(duration: 0.55).repeatForever(autoreverses: true) : .default,
                        value: isRecording
                    )
                Circle()
                    .fill(statusColor.opacity(viewModel.isTalkButtonEnabled ? 0.9 : 0.35))
                    .frame(width: 150, height: 150)
                    .rotationEffect(.degrees(isRecording ? 4 : 0))
                    .animation(
                        isRecording ? .easeInOut(duration: 0.18).repeatForever(autoreverses: true) : .default,
                        value: isRecording
                    )
                if viewModel.connectionState == .active && viewModel.phase == .waitingForTutor
                    || viewModel.connectionState == .preparing {
                    ProgressView()
                        .controlSize(.large)
                        .tint(.white)
                } else {
                    Image(systemName: statusImage)
                        .font(.system(size: 54, weight: .medium))
                        .foregroundStyle(.white)
                        .symbolEffect(.variableColor.iterative, options: .repeating, isActive: isTutorSpeaking)
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(!viewModel.isTalkButtonEnabled)
        .accessibilityLabel(statusTitle)
    }

    private var isTutorSpeaking: Bool {
        viewModel.connectionState == .active && viewModel.phase == .tutorSpeaking
    }

    private var statusColor: Color {
        switch viewModel.connectionState {
        case .failed:
            return .red
        case .completed:
            return .green
        case .active:
            switch viewModel.phase {
            case .learnerTurn:
                return .green
            case .recording:
                return .red
            case .tutorSpeaking:
                return .cyan
            case .waitingForTutor:
                return .orange
            }
        default:
            return .gray
        }
    }

    private var statusImage: String {
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
                return "waveform"
            }
        case .preparing, .ending, .idle:
            return "mic.slash.fill"
        }
    }

    private var statusTitle: String {
        switch viewModel.connectionState {
        case .idle:
            return "Ready"
        case .preparing:
            return "Preparing…"
        case .active:
            switch viewModel.phase {
            case .learnerTurn:
                return "Your turn"
            case .recording:
                return "Listening…"
            case .waitingForTutor:
                return "Tutor is thinking…"
            case .tutorSpeaking:
                return "Tutor is speaking"
            }
        case .ending:
            return "Ending…"
        case .completed:
            return "Practice complete"
        case .failed:
            return "Couldn’t continue"
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
                return "Tap the button, answer in Swedish, then tap again when you’re done."
            case .recording:
                return "Tap again when you’re done. Everything you said is sent to the tutor."
            case .waitingForTutor, .tutorSpeaking:
                return nil
            }
        }
        if viewModel.connectionState == .idle {
            return "Start when you’re ready. Microphone access begins only after you tap the button."
        }
        if viewModel.connectionState == .completed {
            return "The tutor has ended this practice."
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
