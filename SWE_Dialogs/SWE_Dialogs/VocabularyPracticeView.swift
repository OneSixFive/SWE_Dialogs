import SwiftUI

struct VocabularyHomeView: View {
    @EnvironmentObject private var appSessionStore: AppSessionStore
    @StateObject private var store = VocabularyPracticeStore()
    @State private var path: [String] = []

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(spacing: 12) {
                    HStack {
                        SvenskaWordmark(size: 34)
                        Spacer()
                    }
                    .padding(.bottom, 2)

                    Button {
                        Task {
                            if let practice = await store.generate() {
                                path.append(practice.id)
                            }
                        }
                    } label: {
                        HStack(spacing: 10) {
                            if store.isGenerating {
                                ProgressView().tint(Retro.paper)
                            } else {
                                Image(systemName: "plus")
                                    .font(.system(size: 18, weight: .bold))
                            }
                            Text("NY ÖVNING")
                                .font(RetroFont.label(17))
                                .tracking(1.4)
                        }
                    }
                    .buttonStyle(RetroKeyStyle(tint: .orange, edge: 5))
                    .frame(height: 68)
                    .disabled(store.isGenerating)
                    .padding(.bottom, 6)

                    if let errorMessage = store.errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(Retro.paper)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                            .background(Retro.orange.opacity(0.85))
                            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                    }

                    if store.isLoading && store.practices.isEmpty {
                        ProgressView()
                            .tint(Retro.amber)
                            .padding(.top, 60)
                    } else if store.practices.isEmpty {
                        Text("Inga övningar ännu. Tryck på NY ÖVNING för fem meningar att översätta.")
                            .font(RetroFont.label(13, weight: .medium))
                            .foregroundStyle(Retro.labelOnDarkSoft)
                            .multilineTextAlignment(.center)
                            .padding(.top, 50)
                            .padding(.horizontal, 20)
                    } else {
                        ForEach(store.practices) { practice in
                            Button {
                                path.append(practice.id)
                            } label: {
                                VocabularyPracticeHistoryRow(practice: practice)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 6)
                .padding(.bottom, 20)
            }
            .refreshable { await store.refresh() }
            .retroScreenBackground()
            .toolbar(.hidden, for: .navigationBar)
            .retroTabBar()
            .navigationDestination(for: String.self) { practiceID in
                VocabularyPracticeDetailView(practiceID: practiceID, store: store)
            }
            .onAppear {
                store.configure(userID: appSessionStore.user?.id)
            }
            .onChange(of: appSessionStore.user?.id) { _, userID in
                store.configure(userID: userID)
            }
        }
    }
}

/// A practice printed as an adding-machine slip: date, score, stamp.
private struct VocabularyPracticeHistoryRow: View {
    let practice: VocabularyPracticeSummary

    var body: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text(Self.dayFormatter.string(from: practice.createdAt).uppercased())
                    .font(RetroFont.digits(14))
                    .foregroundStyle(Retro.ink)
                Text(practice.createdAt.formatted(date: .omitted, time: .shortened))
                    .font(RetroFont.digits(11))
                    .foregroundStyle(Retro.inkSoft)
            }
            .frame(width: 70, alignment: .leading)

            AmberReadout(text: "\(practice.answeredCount)/5", size: 16)

            Spacer(minLength: 8)

            VocabularyStamp(status: practice.status)
        }
        .padding(.leading, 26)
        .padding(.trailing, 16)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity)
        .background(
            ZStack(alignment: .leading) {
                Retro.paper
                VStack(spacing: 9) {
                    ForEach(0..<3, id: \.self) { _ in
                        Circle().fill(Retro.paperShade).frame(width: 7, height: 7)
                    }
                }
                .padding(.leading, 9)
            }
        )
        .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
        .shadow(color: .black.opacity(0.35), radius: 3, y: 2)
        .accessibilityElement(children: .combine)
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "sv_SE")
        formatter.setLocalizedDateFormatFromTemplate("d MMM")
        return formatter
    }()
}

private struct VocabularyStamp: View {
    let status: VocabularyPracticeStatus

    var body: some View {
        Text(title)
            .font(RetroFont.label(11))
            .tracking(1)
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(color, lineWidth: 1.5))
            .rotationEffect(.degrees(-7))
            .opacity(0.85)
    }

    private var title: String {
        switch status {
        case .completed: return "GODKÄND"
        case .active, .generating: return "PÅGÅR"
        case .abandoned: return "AVBRUTEN"
        case .failed: return "FEL"
        }
    }

    private var color: Color {
        switch status {
        case .completed: return Retro.olive
        case .active, .generating: return Retro.inkOrange
        case .abandoned, .failed: return Retro.inkSoft
        }
    }
}

private enum VocabularyPracticePanel: Equatable {
    case questions
    case menu
}

private struct VocabularyPracticeDetailView: View {
    let practiceID: String
    @ObservedObject var store: VocabularyPracticeStore

    @Environment(\.dismiss) private var dismiss
    @State private var draft = ""
    @State private var isSending = false
    @State private var selectedPanel: VocabularyPracticePanel?
    @State private var showEndConfirmation = false
    @FocusState private var isChatFocused: Bool

    private var practice: VocabularyPractice? {
        store.session(id: practiceID)
    }

    var body: some View {
        Group {
            if let practice {
                practiceContent(practice)
            } else {
                ProgressView().tint(Retro.amber)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .retroScreenBackground()
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .task {
            _ = await store.load(id: practiceID)
        }
        .confirmationDialog("Avsluta övningen?", isPresented: $showEndConfirmation) {
            Button("Avsluta övningen", role: .destructive) {
                Task {
                    _ = await store.abandon(id: practiceID)
                    dismiss()
                }
            }
            Button("Avbryt", role: .cancel) {}
        } message: {
            Text("Den ofärdiga övningen sparas i historiken som avbruten.")
        }
    }

    private func practiceContent(_ practice: VocabularyPractice) -> some View {
        VStack(spacing: 0) {
            VStack(spacing: 12) {
                topControls(practice)
                if let selectedPanel {
                    expandedPanel(selectedPanel, practice: practice)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 10)
            .padding(.bottom, 10)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        if let errorMessage = store.errorMessage {
                            Text(errorMessage)
                                .font(.footnote)
                                .foregroundStyle(Retro.pencilRed)
                        }

                        ForEach(practice.messages) { message in
                            LessonChatMessageRow(
                                message: message.lessonChatMessage(practiceID: practice.id),
                                onTranslateSelection: translateSelectionAction(for: practice)
                            )
                                .id(message.id)
                        }

                        if isSending {
                            LessonTypingIndicatorRow()
                        }

                        Color.clear.frame(height: 4).id("vocabulary-chat-bottom")
                    }
                    .modifier(PaperChatSurface())
                    .padding(.horizontal, 14)
                    .padding(.top, 2)
                    .padding(.bottom, 12)
                }
                .scrollIndicators(.hidden)
                .scrollDismissesKeyboard(.interactively)
                .onTapGesture {
                    isChatFocused = false
                    withAnimation { selectedPanel = nil }
                }
                .onChange(of: practice.messages.count) { _, _ in
                    withAnimation { proxy.scrollTo("vocabulary-chat-bottom", anchor: .bottom) }
                }
                .onChange(of: isChatFocused) { _, focused in
                    guard focused else { return }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
                        withAnimation { proxy.scrollTo("vocabulary-chat-bottom", anchor: .bottom) }
                    }
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            if practice.status == .active {
                LessonChatInputBar(
                    draft: $draft,
                    isSending: isSending,
                    isEnabled: true,
                    canAdvanceLessonStep: practice.canAdvance,
                    nextStepAccessibilityLabel: practice.state.currentQuestionIndex == 4 ? "Avsluta övningen" : "Nästa mening",
                    isFocused: $isChatFocused,
                    onNextQuestion: { Task { await advance() } },
                    onSend: { Task { await send() } }
                )
                .padding(.horizontal, 14)
                .padding(.top, 4)
                .padding(.bottom, 6)
                .retroBottomBacking()
            }
        }
    }

    private func topControls(_ practice: VocabularyPractice) -> some View {
        HStack(spacing: 8) {
            LessonTopControlButton(
                systemImage: "arrow.left",
                isSelected: false,
                isFlashing: false,
                accessibilityLabel: "Tillbaka",
                action: { dismiss() }
            )
            .frame(width: 58)

            Button {
                toggle(.questions)
            } label: {
                CounterWheels(
                    digits: (1...5).map(String.init),
                    highlighted: progressHighlights(practice),
                    size: 24
                )
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity)
            .accessibilityLabel("Meningar, \(practice.state.answeredQuestionIDs.count) av 5 klara")

            LessonTopControlButton(
                systemImage: "ellipsis",
                isSelected: selectedPanel == .menu,
                isFlashing: false,
                accessibilityLabel: "Meny",
                action: { toggle(.menu) }
            )
            .frame(width: 58)
        }
    }

    private func progressHighlights(_ practice: VocabularyPractice) -> Set<Int> {
        let questions = practice.quiz?.questions ?? []
        return Set(questions.indices.filter { index in
            practice.state.answeredQuestionIDs.contains(questions[index].id)
                || (practice.status == .active && index == practice.state.currentQuestionIndex)
        })
    }

    @ViewBuilder
    private func expandedPanel(_ panel: VocabularyPracticePanel, practice: VocabularyPractice) -> some View {
        switch panel {
        case .questions:
            PaperSheet {
                VStack(alignment: .leading, spacing: 10) {
                    PaperCaption(text: "Meningar")
                    ForEach(Array((practice.quiz?.questions ?? []).enumerated()), id: \.element.id) { index, question in
                        HStack(alignment: .firstTextBaseline, spacing: 10) {
                            Image(systemName: questionIcon(index: index, practice: practice))
                                .foregroundStyle(questionColor(index: index, practice: practice))
                            Text("\(index + 1). \(question.sentenceEN)")
                                .font(RetroFont.reading(.subheadline))
                                .foregroundStyle(Retro.ink)
                        }
                    }
                }
            }
        case .menu:
            Group {
                if practice.status == .active {
                    Button { showEndConfirmation = true } label: {
                        RetroKeyLabel(title: "Avsluta övningen", systemImage: "xmark", titleSize: 13)
                    }
                    .buttonStyle(RetroKeyStyle(tint: .dark))
                    .frame(height: 58)
                } else {
                    Text("Den här övningen är avslutad och kan bara läsas.")
                        .font(RetroFont.label(12, weight: .medium))
                        .foregroundStyle(Retro.labelOnDarkSoft)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .retroPanel(padding: 12)
        }
    }

    private func toggle(_ panel: VocabularyPracticePanel) {
        isChatFocused = false
        withAnimation(.snappy(duration: 0.22)) {
            selectedPanel = selectedPanel == panel ? nil : panel
        }
    }

    private func questionIcon(index: Int, practice: VocabularyPractice) -> String {
        guard let question = practice.quiz?.questions[index] else { return "circle" }
        if practice.state.answeredQuestionIDs.contains(question.id) { return "checkmark.circle.fill" }
        return index == practice.state.currentQuestionIndex ? "circle.inset.filled" : "circle"
    }

    private func questionColor(index: Int, practice: VocabularyPractice) -> Color {
        guard let question = practice.quiz?.questions[index] else { return Retro.inkSoft }
        if practice.state.answeredQuestionIDs.contains(question.id) { return Retro.olive }
        return index == practice.state.currentQuestionIndex ? Retro.inkOrange : Retro.inkSoft
    }

    private func send() async {
        await sendMessage(draft)
    }

    private func sendTranslationRequest(_ selection: String) {
        guard practice?.status == .active, !isSending else { return }
        let lookup = TranslationLookupMetadata(
            selectedText: selection.trimmingCharacters(in: .whitespacesAndNewlines),
            sourceKind: "vocabulary_practice",
            sourceID: practiceID,
            sourceSurface: "vocabulary_practice_message",
            surroundingText: nil,
            visibleCourseLevel: practice?.courseLevel,
            createdAt: Date()
        )
        Task {
            await sendMessage(
                translationRequestMessage(for: selection),
                translationLookup: lookup
            )
        }
    }

    private func translateSelectionAction(for practice: VocabularyPractice) -> ((String) -> Void)? {
        guard practice.status == .active else { return nil }
        return { selection in
            sendTranslationRequest(selection)
        }
    }

    private func sendMessage(
        _ rawMessage: String,
        translationLookup: TranslationLookupMetadata? = nil
    ) async {
        let message = rawMessage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, !isSending else { return }
        if message == draft.trimmingCharacters(in: .whitespacesAndNewlines) {
            draft = ""
        }
        isChatFocused = false
        isSending = true
        _ = await store.send(
            id: practiceID,
            message: message,
            translationLookup: translationLookup
        )
        isSending = false
    }

    private func advance() async {
        guard !isSending else { return }
        isSending = true
        _ = await store.advance(id: practiceID)
        isSending = false
    }
}
