import SwiftUI
import UIKit

struct LessonsHomeView: View {
    @StateObject private var curriculumStore = CurriculumStore()
    @StateObject private var generationStore = LessonGenerationStore()
    @StateObject private var sessionStore = LessonSessionStore()
    @StateObject private var lessonAudioPlayer = AudioPlayerController()

    @AppStorage("lessons_selected_level") private var selectedLevelRaw = LessonLevel.b2.rawValue
    @AppStorage("lessons_selected_stage") private var selectedStage = 1
    @AppStorage("lessons_selected_week") private var selectedWeek = 1

    @State private var path: [String] = []

    private var selectedLevel: LessonLevel {
        LessonLevel(rawValue: selectedLevelRaw) ?? .b2
    }

    private var availableLevels: [LessonLevel] {
        let levels = curriculumStore.availableLevels
        return levels.isEmpty ? LessonLevel.allCases : levels
    }

    private var availableStages: [Int] {
        let stages = curriculumStore.stages(for: selectedLevel)
        return stages.isEmpty ? [1] : stages
    }

    private var availableWeeks: [Int] {
        let weeks = curriculumStore.weeks(level: selectedLevel, stage: selectedStage)
        return weeks.isEmpty ? [1] : weeks
    }

    private var selectedLessons: [LessonPayload] {
        curriculumStore.days(level: selectedLevel, stage: selectedStage, week: selectedWeek)
    }

    private var continueLesson: LessonPayload? {
        curriculumStore.firstIncompleteLesson(level: selectedLevel, sessionStore: sessionStore)
    }

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if let errorMessage = curriculumStore.errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(.red)
                    }
                }

                Section {
                    Button {
                        if let continueLesson {
                            path.append(continueLesson.id)
                        }
                    } label: {
                        Label("Continue", systemImage: "play.fill")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(continueLesson == nil)

                    if let continueLesson {
                        Text(lessonSubtitle(continueLesson))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Choose Lesson") {
                    Picker("Level", selection: $selectedLevelRaw) {
                        ForEach(availableLevels) { level in
                            Text(level.rawValue).tag(level.rawValue)
                        }
                    }
                    .pickerStyle(.menu)

                    Picker("Stage", selection: $selectedStage) {
                        ForEach(availableStages, id: \.self) { stage in
                            Text("Stage \(stage)").tag(stage)
                        }
                    }
                    .pickerStyle(.menu)

                    Picker("Week", selection: $selectedWeek) {
                        ForEach(availableWeeks, id: \.self) { week in
                            Text("Week \(week)").tag(week)
                        }
                    }
                    .pickerStyle(.menu)
                }

                Section("Week \(selectedWeek)") {
                    if selectedLessons.isEmpty {
                        Text("No lessons found for this selection.")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(selectedLessons) { lesson in
                            NavigationLink(value: lesson.id) {
                                LessonRow(
                                    lesson: lesson,
                                    generatedLesson: generationStore.generatedLesson(for: lesson.id),
                                    state: sessionStore.state(for: lesson.id)
                                )
                            }
                        }
                    }
                }
            }
            .navigationTitle("Lessons")
            .navigationDestination(for: String.self) { lessonID in
                if let lesson = curriculumStore.lesson(id: lessonID) {
                    LessonDetailView(
                        payload: lesson,
                        generationStore: generationStore,
                        sessionStore: sessionStore,
                        audioPlayer: lessonAudioPlayer
                    )
                } else {
                    Text("Lesson not found.")
                        .foregroundStyle(.secondary)
                }
            }
            .onChange(of: selectedLevelRaw) { _, _ in
                normalizeSelection()
            }
            .onChange(of: selectedStage) { _, _ in
                normalizeSelection()
            }
            .onAppear {
                normalizeSelection()
            }
        }
    }

    private func normalizeSelection() {
        let stages = availableStages
        if !stages.contains(selectedStage) {
            selectedStage = stages.first ?? 1
        }

        let weeks = availableWeeks
        if !weeks.contains(selectedWeek) {
            selectedWeek = weeks.first ?? 1
        }
    }

    private func lessonSubtitle(_ lesson: LessonPayload) -> String {
        "\(lesson.courseLevel.rawValue), Stage \(lesson.coursePosition.stage), Week \(lesson.coursePosition.week), Day \(lesson.coursePosition.day)"
    }
}

private struct LessonRow: View {
    let lesson: LessonPayload
    let generatedLesson: GeneratedLesson?
    let state: LessonState

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Day \(lesson.coursePosition.day)")
                    .font(.headline)
                Spacer()
                Text(statusText)
                    .font(.caption)
                    .foregroundStyle(statusColor)
            }

            Text(lesson.lessonIntent.oneSentenceGoal)
                .font(.subheadline)
                .foregroundStyle(.primary)
                .lineLimit(2)

            Text(lesson.grammarTarget.mainFocus.name)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(.vertical, 4)
    }

    private var statusText: String {
        if state.isCompleted { return "Done" }
        if state.audioFileName != nil { return "Audio" }
        if generatedLesson != nil { return "Generated" }
        return "New"
    }

    private var statusColor: Color {
        if state.isCompleted { return .green }
        if state.audioFileName != nil { return .blue }
        if generatedLesson != nil { return .orange }
        return .secondary
    }
}

struct LessonDetailView: View {
    let payload: LessonPayload
    @ObservedObject var generationStore: LessonGenerationStore
    @ObservedObject var sessionStore: LessonSessionStore
    @ObservedObject var audioPlayer: AudioPlayerController

    @AppStorage("openai_api_key") private var openAIAPIKey = ""
    @AppStorage("gemini_api_key") private var geminiAPIKey = ""
    @AppStorage("tts_model_raw") private var selectedTTSModelRaw = GeminiTTSService.TTSModel.flash31.rawValue

    @State private var isGeneratingLesson = false
    @State private var isGeneratingAudio = false
    @State private var isSending = false
    @State private var draft = ""
    @State private var errorMessage: String?
    @State private var showRegenerateConfirmation = false
    @FocusState private var isChatFocused: Bool

    private var generatedLesson: GeneratedLesson? {
        generationStore.generatedLesson(for: payload.id)
    }

    private var lessonState: LessonState {
        sessionStore.state(for: payload.id)
    }

    private var messages: [LessonChatMessage] {
        sessionStore.messages(for: payload.id)
    }

    private var selectedTTSModel: GeminiTTSService.TTSModel {
        GeminiTTSService.TTSModel(rawValue: selectedTTSModelRaw) ?? .flash31
    }

    private var shouldOfferTranslationQuiz: Bool {
        guard let generatedLesson else { return false }
        return lessonState.acceptedQuestionIDs.count == generatedLesson.comprehensionQuestions.count &&
            lessonState.translationQuiz == nil &&
            !lessonState.isCompleted
    }

    private var isComprehensionComplete: Bool {
        guard let generatedLesson else { return false }
        return lessonState.acceptedQuestionIDs.count == generatedLesson.comprehensionQuestions.count
    }

    private var shouldShowCompletionAction: Bool {
        lessonState.isCompleted || (isComprehensionComplete && lessonState.translationQuiz != nil)
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    LessonTargetView(payload: payload)

                    lessonActionSection

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    if let audioURL = currentAudioURL {
                        PlayerSection(audioPlayer: audioPlayer, fileURL: audioURL)
                    }

                    if let generatedLesson {
                        DialogueSection(generatedLesson: generatedLesson)
                        QuestionsSection(generatedLesson: generatedLesson, acceptedQuestionIDs: lessonState.acceptedQuestionIDs)

                        if shouldOfferTranslationQuiz {
                            TranslationQuizPrompt {
                                Task {
                                    await sendTutorMessage("Start the translation quiz.")
                                }
                            }
                        }

                        if let quiz = lessonState.translationQuiz {
                            TranslationQuizSection(quiz: quiz)
                        }

                        chatSection

                if shouldShowCompletionAction {
                            Button {
                                sessionStore.markCompleted(lessonID: payload.id)
                            } label: {
                                Label("Mark Complete", systemImage: "checkmark.circle")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(lessonState.isCompleted)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
            }
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") {
                        isChatFocused = false
                    }
                }
            }
            .navigationTitle("Day \(payload.coursePosition.day)")
            .navigationBarTitleDisplayMode(.inline)
            .onAppear {
                loadExistingAudio()
            }
            .onChange(of: messages.count) { _, _ in
                guard let lastID = messages.last?.id else { return }
                withAnimation {
                    proxy.scrollTo(lastID, anchor: .bottom)
                }
            }
        }
        .confirmationDialog(
            "Regenerate this lesson?",
            isPresented: $showRegenerateConfirmation,
            titleVisibility: .visible
        ) {
            Button("Regenerate Lesson", role: .destructive) {
                Task {
                    await generateLesson(replacingExisting: true)
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This replaces the dialogue and questions. Old chat and audio will be reset for this lesson.")
        }
    }

    @ViewBuilder
    private var lessonActionSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            if generatedLesson == nil {
                Button {
                    Task {
                        await generateLesson(replacingExisting: false)
                    }
                } label: {
                    actionLabel(title: "Generate Lesson", isLoading: isGeneratingLesson)
                }
                .buttonStyle(.borderedProminent)
                .disabled(isGeneratingLesson)
            } else {
                VStack(spacing: 8) {
                    Button {
                        Task {
                            await generateAudio()
                        }
                    } label: {
                        actionLabel(title: lessonState.audioFileName == nil ? "Generate Audio" : "Regenerate Audio", isLoading: isGeneratingAudio)
                    }
                    .buttonStyle(.bordered)
                    .disabled(isGeneratingAudio || generatedLesson == nil)

                    Button("Regenerate Lesson") {
                        showRegenerateConfirmation = true
                    }
                    .buttonStyle(.bordered)
                    .disabled(isGeneratingLesson)

                    Button("Debug: Reset Chat & Progress", role: .destructive) {
                        resetChatAndProgress()
                    }
                    .buttonStyle(.bordered)
                    .disabled(isSending || isGeneratingLesson)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var chatSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Lesson Chat")
                .font(.headline)

            if messages.isEmpty {
                Text("Answer the comprehension questions here, or ask about words and grammar from the dialogue.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            ForEach(messages) { message in
                HStack {
                    if message.role == .assistant { Spacer(minLength: 36) }

                    MarkdownChatText(content: message.content)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        .background(message.role == .user ? Color.accentColor : Color.secondary.opacity(0.18))
                        .foregroundStyle(message.role == .user ? Color.white : Color.primary)
                        .clipShape(RoundedRectangle(cornerRadius: 12))

                    if message.role == .user { Spacer(minLength: 36) }
                }
                .id(message.id)
            }

            HStack(spacing: 8) {
                TextField("Type a message", text: $draft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...5)
                    .focused($isChatFocused)
                    .disabled(isSending)

                Button {
                    Task {
                        await sendTutorMessage(draft)
                    }
                } label: {
                    if isSending {
                        ProgressView()
                    } else {
                        Image(systemName: "paperplane.fill")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isSending || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private var currentAudioURL: URL? {
        guard let fileName = lessonState.audioFileName else { return nil }
        return FileStorage.lessonAudioURL(fileName: fileName)
    }

    private func actionLabel(title: String, isLoading: Bool) -> some View {
        HStack {
            if isLoading {
                ProgressView()
            }
            Text(title)
        }
        .frame(maxWidth: .infinity)
    }

    private func generateLesson(replacingExisting: Bool) async {
        let trimmedKey = openAIAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = OpenAIModelDefaults.lessonGenerator.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonGeneratorReasoningEffort

        guard !trimmedKey.isEmpty else {
            errorMessage = "Add your OpenAI API key in Settings."
            return
        }

        isGeneratingLesson = true
        errorMessage = nil
        defer { isGeneratingLesson = false }

        do {
            let lesson = try await OpenAITutorService.generateLesson(
                payload: payload,
                apiKey: trimmedKey,
                model: model,
                reasoningEffort: reasoningEffort
            )
            generationStore.save(lesson)
            if replacingExisting {
                sessionStore.resetForRegeneratedLesson(lessonID: payload.id)
            } else {
                sessionStore.markGenerated(lessonID: payload.id)
            }

            if !geminiAPIKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                await generateAudio(for: lesson)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func generateAudio() async {
        guard let generatedLesson else {
            errorMessage = "Generate the lesson first."
            return
        }
        await generateAudio(for: generatedLesson)
    }

    private func generateAudio(for lesson: GeneratedLesson) async {
        let trimmedKey = geminiAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedKey.isEmpty else {
            errorMessage = "Add your Gemini API key in Settings."
            return
        }

        isGeneratingAudio = true
        errorMessage = nil
        defer { isGeneratingAudio = false }

        do {
            let wavData = try await GeminiTTSService.generateWav(
                dialog: lesson.ttsText,
                apiKey: trimmedKey,
                model: selectedTTSModel
            )
            let fileURL = try FileStorage.saveLessonWavFile(data: wavData, lessonID: lesson.lessonID)
            sessionStore.setAudioFileName(fileURL.lastPathComponent, lessonID: lesson.lessonID)
            audioPlayer.load(url: fileURL)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func resetChatAndProgress() {
        sessionStore.resetChatAndProgressForGeneratedLesson(lessonID: payload.id)
        draft = ""
        errorMessage = nil
    }

    private func sendTutorMessage(_ message: String) async {
        let trimmedMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedKey = openAIAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = OpenAIModelDefaults.lessonInteractor.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonInteractorReasoningEffort

        guard let generatedLesson else {
            errorMessage = "Generate the lesson before chatting."
            return
        }

        guard !trimmedMessage.isEmpty else {
            return
        }

        guard !trimmedKey.isEmpty else {
            errorMessage = "Add your OpenAI API key in Settings."
            return
        }

        if trimmedMessage == draft.trimmingCharacters(in: .whitespacesAndNewlines) {
            draft = ""
        }
        errorMessage = nil
        isSending = true
        sessionStore.appendMessage(
            LessonChatMessage(lessonID: payload.id, role: .user, content: trimmedMessage)
        )
        let chatHistory = sessionStore.messages(for: payload.id)
        defer { isSending = false }

        do {
            let response = try await OpenAITutorService.sendLessonMessage(
                payload: payload,
                generatedLesson: generatedLesson,
                state: lessonState,
                chatHistory: chatHistory,
                latestUserMessage: trimmedMessage,
                apiKey: trimmedKey,
                model: model,
                reasoningEffort: reasoningEffort
            )
            try sessionStore.apply(response: response, generatedLesson: generatedLesson)
            sessionStore.appendMessage(
                LessonChatMessage(lessonID: payload.id, role: .assistant, content: response.assistantText)
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func loadExistingAudio() {
        guard let audioURL = currentAudioURL else { return }
        audioPlayer.load(url: audioURL)
    }
}

private struct MarkdownChatText: View {
    let content: String

    private var attributedContent: AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: content, options: options)) ?? AttributedString(content)
    }

    var body: some View {
        Text(attributedContent)
    }
}

private struct LessonTargetView: View {
    let payload: LessonPayload

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(payload.courseLevel.rawValue), Stage \(payload.coursePosition.stage), Week \(payload.coursePosition.week), Day \(payload.coursePosition.day)")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Text(payload.lessonIntent.oneSentenceGoal)
                .font(.headline)

            Text(payload.grammarTarget.mainFocus.name)
                .font(.subheadline)

            Text(payload.dialogueTask.scenario)
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }
}

private struct DialogueSection: View {
    let generatedLesson: GeneratedLesson

    private var transcriptText: String {
        generatedLesson.dialogue
            .map { "\($0.speaker.rawValue): \($0.text)" }
            .joined(separator: "\n")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Transcript")
                .font(.headline)

            SelectableTranscriptView(text: transcriptText)
        }
    }
}

private struct SelectableTranscriptView: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.isEditable = false
        textView.isSelectable = true
        textView.isScrollEnabled = false
        textView.backgroundColor = .clear
        textView.textContainerInset = .zero
        textView.textContainer.lineFragmentPadding = 0
        textView.textContainer.widthTracksTextView = true
        textView.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        textView.font = UIFont.preferredFont(forTextStyle: .body)
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        uiView.text = text
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        let targetWidth = proposal.width
            ?? uiView.window?.windowScene?.screen.bounds.width
            ?? uiView.bounds.width
        let fittingSize = uiView.sizeThatFits(CGSize(width: targetWidth, height: .greatestFiniteMagnitude))
        return CGSize(width: targetWidth, height: fittingSize.height)
    }
}

private struct QuestionsSection: View {
    let generatedLesson: GeneratedLesson
    let acceptedQuestionIDs: Set<String>

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Comprehension")
                .font(.headline)

            ForEach(generatedLesson.comprehensionQuestions) { question in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: acceptedQuestionIDs.contains(question.id) ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(acceptedQuestionIDs.contains(question.id) ? .green : .secondary)
                    Text(question.questionSV)
                        .textSelection(.enabled)
                }
            }
        }
    }
}

private struct TranslationQuizPrompt: View {
    let onStart: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Translation quiz is ready.")
                .font(.headline)
            Text("You can start it now or keep chatting about the dialogue.")
                .font(.footnote)
                .foregroundStyle(.secondary)
            Button("Start Translation Quiz", action: onStart)
                .buttonStyle(.borderedProminent)
        }
        .padding()
        .background(Color.secondary.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct TranslationQuizSection: View {
    let quiz: TranslationQuiz

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Translation Quiz")
                .font(.headline)

            ForEach(Array(quiz.sentencesEN.enumerated()), id: \.offset) { index, sentence in
                Text("\(index + 1). \(sentence)")
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
        }
    }
}

#Preview {
    LessonsHomeView()
}
