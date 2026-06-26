import SwiftUI

struct VocabularyHomeView: View {
    @EnvironmentObject private var appSessionStore: AppSessionStore
    @StateObject private var store = VocabularyPracticeStore()
    @State private var path: [String] = []

    var body: some View {
        NavigationStack(path: $path) {
            VStack(spacing: 0) {
                Button {
                    Task {
                        if let practice = await store.generate() {
                            path.append(practice.id)
                        }
                    }
                } label: {
                    HStack(spacing: 10) {
                        if store.isGenerating {
                            ProgressView().tint(.black)
                        } else {
                            Image(systemName: "plus")
                        }
                        Text("Generate practice")
                            .fontWeight(.semibold)
                    }
                    .foregroundStyle(.black)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 15)
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(store.isGenerating)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 16)

                if let errorMessage = store.errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16)
                        .padding(.bottom, 10)
                }

                if store.isLoading && store.practices.isEmpty {
                    Spacer()
                    ProgressView().tint(.white)
                    Spacer()
                } else if store.practices.isEmpty {
                    Spacer()
                    ContentUnavailableView(
                        "No vocabulary practices",
                        systemImage: "character.book.closed",
                        description: Text("Generate a five-sentence translation practice based on your progress.")
                    )
                    .foregroundStyle(.white)
                    Spacer()
                } else {
                    List(store.practices) { practice in
                        Button {
                            path.append(practice.id)
                        } label: {
                            VocabularyPracticeHistoryRow(practice: practice)
                        }
                        .buttonStyle(.plain)
                        .listRowBackground(LessonChatStyle.panel)
                    }
                    .scrollContentBackground(.hidden)
                    .refreshable { await store.refresh() }
                }
            }
            .background(Color.black.ignoresSafeArea())
            .navigationTitle("Vocabulary")
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

private struct VocabularyPracticeHistoryRow: View {
    let practice: VocabularyPracticeSummary

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: practice.status == .completed ? "checkmark.circle.fill" : "text.bubble")
                .font(.title2)
                .foregroundStyle(practice.status == .completed ? .green : .white)

            VStack(alignment: .leading, spacing: 5) {
                Text("\(practice.courseLevel), Stage \(practice.stageNumber)")
                    .font(.headline)
                    .foregroundStyle(.white)
                Text(practice.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(LessonChatStyle.secondaryText)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 5) {
                Text(practice.status.title)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)
                Text("\(practice.answeredCount)/5")
                    .font(.caption)
                    .foregroundStyle(LessonChatStyle.secondaryText)
            }
        }
        .padding(.vertical, 8)
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
                ProgressView().tint(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Color.black.ignoresSafeArea())
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .task {
            _ = await store.load(id: practiceID)
        }
        .confirmationDialog("End this practice?", isPresented: $showEndConfirmation) {
            Button("End practice", role: .destructive) {
                Task {
                    _ = await store.abandon(id: practiceID)
                    dismiss()
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The unfinished practice will remain in history as ended.")
        }
    }

    private func practiceContent(_ practice: VocabularyPractice) -> some View {
        VStack(spacing: 0) {
            VStack(spacing: 12) {
                topControls
                if let selectedPanel {
                    expandedPanel(selectedPanel, practice: practice)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 10)
            .padding(.bottom, 12)
            .background(Color.black)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 22) {
                        if let errorMessage = store.errorMessage {
                            Text(errorMessage)
                                .font(.footnote)
                                .foregroundStyle(.red)
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

                        Color.clear.frame(height: 12).id("vocabulary-chat-bottom")
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 14)
                    .padding(.bottom, 18)
                }
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
                    canAdvanceLessonStep: practice.canAdvance,
                    nextStepAccessibilityLabel: practice.state.currentQuestionIndex == 4 ? "Finish practice" : "Next question",
                    isFocused: $isChatFocused,
                    onNextQuestion: { Task { await advance() } },
                    onSend: { Task { await send() } }
                )
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Color.black)
            }
        }
    }

    private var topControls: some View {
        HStack(spacing: 10) {
            LessonTopControlButton(
                systemImage: "chevron.left",
                isSelected: false,
                isFlashing: false,
                accessibilityLabel: "Back",
                action: { dismiss() }
            )
            LessonTopControlButton(
                systemImage: "list.number",
                isSelected: selectedPanel == .questions,
                isFlashing: false,
                accessibilityLabel: "Question list",
                action: { toggle(.questions) }
            )
            LessonTopControlButton(
                systemImage: "ellipsis",
                isSelected: selectedPanel == .menu,
                isFlashing: false,
                accessibilityLabel: "Menu",
                action: { toggle(.menu) }
            )
        }
    }

    @ViewBuilder
    private func expandedPanel(_ panel: VocabularyPracticePanel, practice: VocabularyPractice) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            switch panel {
            case .questions:
                Text("Questions").font(.headline).foregroundStyle(.white)
                ForEach(Array((practice.quiz?.questions ?? []).enumerated()), id: \.element.id) { index, question in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: questionIcon(index: index, practice: practice))
                            .foregroundStyle(questionColor(index: index, practice: practice))
                        Text("\(index + 1). \(question.sentenceEN)")
                            .foregroundStyle(.white)
                    }
                }
            case .menu:
                if practice.status == .active {
                    Button(role: .destructive) { showEndConfirmation = true } label: {
                        Label("End practice", systemImage: "xmark.circle")
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                } else {
                    Text("This completed practice is read-only.")
                        .foregroundStyle(LessonChatStyle.secondaryText)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(LessonChatStyle.panel)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(LessonChatStyle.panelStroke, lineWidth: 1)
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
        guard let question = practice.quiz?.questions[index] else { return .secondary }
        if practice.state.answeredQuestionIDs.contains(question.id) { return .green }
        return index == practice.state.currentQuestionIndex ? .white : LessonChatStyle.tertiaryText
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
