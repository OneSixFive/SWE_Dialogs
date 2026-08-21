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
                        Label("End", systemImage: "xmark")
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

                ZStack {
                    Circle()
                        .fill(statusColor.opacity(0.16))
                        .frame(width: 190, height: 190)
                    Circle()
                        .stroke(statusColor.opacity(0.4), lineWidth: 2)
                        .frame(width: 150, height: 150)
                    Image(systemName: statusImage)
                        .font(.system(size: 54, weight: .medium))
                        .foregroundStyle(statusColor)
                        .symbolEffect(.pulse, options: .repeating, isActive: isSessionActive)
                }

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

                if viewModel.microphoneDenied {
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

                Button("End practice", role: .destructive) {
                    endAndDismiss()
                }
                .buttonStyle(.bordered)
            }
            .padding(24)
            .foregroundStyle(.white)
        }
        .task {
            await viewModel.start()
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase != .active else { return }
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

    private var isSessionActive: Bool {
        viewModel.connectionState == .active
    }

    private var statusColor: Color {
        switch viewModel.connectionState {
        case .failed:
            return .red
        case .active:
            return viewModel.activity == .assistantSpeaking ? .cyan : .green
        default:
            return .orange
        }
    }

    private var statusImage: String {
        switch viewModel.connectionState {
        case .failed:
            return "exclamationmark.triangle.fill"
        case .active:
            return viewModel.activity == .assistantSpeaking ? "waveform" : "mic.fill"
        case .preparing, .connecting:
            return "ellipsis"
        case .ending, .idle:
            return "mic.slash.fill"
        }
    }

    private var statusTitle: String {
        switch viewModel.connectionState {
        case .idle:
            return "Ready"
        case .preparing:
            return "Preparing…"
        case .connecting:
            return "Connecting…"
        case .active:
            switch viewModel.activity {
            case .assistantSpeaking:
                return "Speaking…"
            case .learnerSpeaking:
                return "Listening to you…"
            case .waiting, .listening:
                return "Listening…"
            }
        case .ending:
            return "Ending…"
        case .failed:
            return "Couldn’t start"
        }
    }

    private var statusDetail: String? {
        if case .failed(let message) = viewModel.connectionState {
            return message
        }
        if viewModel.connectionState == .active {
            return "Answer naturally in Swedish. The tutor will guide the conversation."
        }
        return nil
    }

    private func endAndDismiss() {
        Task {
            await viewModel.end()
            dismiss()
        }
    }
}
