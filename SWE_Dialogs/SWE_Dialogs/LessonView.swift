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
    @State private var expandedPanel: LessonPanel?
    @State private var isRequestingTranslationQuiz = false
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
        Group {
            if let generatedLesson {
                generatedLessonExperience(generatedLesson)
            } else {
                preGenerationView
            }
        }
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
        .task(id: shouldOfferTranslationQuiz) {
            guard shouldOfferTranslationQuiz else { return }
            await requestTranslationQuizIfNeeded()
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

    private var preGenerationView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                LessonTargetView(payload: payload)

                lessonActionSection

                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
        .scrollDismissesKeyboard(.interactively)
    }

    private func generatedLessonExperience(_ generatedLesson: GeneratedLesson) -> some View {
        VStack(spacing: 0) {
            VStack(spacing: 12) {
                LessonTopControlBar(selection: $expandedPanel)

                LessonInlineAudioPlayer(audioPlayer: audioPlayer, fileURL: currentAudioURL)
            }
            .padding(.horizontal, 16)
            .padding(.top, 10)
            .padding(.bottom, 12)
            .background(Color.black)

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 22) {
                        if let expandedPanel {
                            LessonExpandedPanel(
                                panel: expandedPanel,
                                payload: payload,
                                generatedLesson: generatedLesson,
                                lessonState: lessonState,
                                isGeneratingLesson: isGeneratingLesson,
                                isGeneratingAudio: isGeneratingAudio,
                                isSending: isSending || isRequestingTranslationQuiz,
                                isRequestingTranslationQuiz: isRequestingTranslationQuiz,
                                onRegenerate: {
                                    showRegenerateConfirmation = true
                                },
                                onRegenerateAudio: {
                                    Task {
                                        await generateAudio()
                                    }
                                },
                                onResetProgress: {
                                    resetChatAndProgress()
                                },
                                onMarkComplete: {
                                    sessionStore.markCompleted(lessonID: payload.id)
                                }
                            )
                            .transition(.opacity.combined(with: .move(edge: .top)))
                        }

                        if let errorMessage {
                            Text(errorMessage)
                                .font(.footnote)
                                .foregroundStyle(.red)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        if messages.isEmpty {
                            LessonAssistantOpening()
                        }

                        ForEach(messages) { message in
                            LessonChatMessageRow(message: message)
                                .id(message.id)
                        }

                        Color.clear
                            .frame(height: 12)
                            .id("lesson-chat-bottom")
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 14)
                    .padding(.bottom, 18)
                }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: messages.count) { _, _ in
                    withAnimation {
                        proxy.scrollTo("lesson-chat-bottom", anchor: .bottom)
                    }
                }
            }
        }
        .background(Color.black.ignoresSafeArea())
        .safeAreaInset(edge: .bottom) {
            LessonChatInputBar(
                draft: $draft,
                isSending: isSending || isRequestingTranslationQuiz,
                isFocused: $isChatFocused,
                onSend: {
                    Task {
                        await sendTutorMessage(draft)
                    }
                }
            )
            .padding(.horizontal, 14)
            .padding(.top, 8)
            .padding(.bottom, 8)
            .background(Color.black)
        }
        .toolbar(.hidden, for: .tabBar)
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
        let trimmedTTSKey = geminiAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = OpenAIModelDefaults.lessonGenerator.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonGeneratorReasoningEffort

        guard !trimmedKey.isEmpty else {
            errorMessage = "Add your OpenAI API key in Settings."
            return
        }

        guard !trimmedTTSKey.isEmpty else {
            errorMessage = "Add your Gemini API key in Settings so the lesson audio can be prepared before opening."
            return
        }

        isGeneratingLesson = true
        isGeneratingAudio = true
        errorMessage = nil
        defer {
            isGeneratingLesson = false
            isGeneratingAudio = false
        }

        do {
            let lesson = try await OpenAITutorService.generateLesson(
                payload: payload,
                apiKey: trimmedKey,
                model: model,
                reasoningEffort: reasoningEffort
            )
            let fileURL = try await generateAudioFile(for: lesson, apiKey: trimmedTTSKey)

            generationStore.save(lesson)
            if replacingExisting {
                sessionStore.resetForRegeneratedLesson(lessonID: payload.id)
            } else {
                sessionStore.markGenerated(lessonID: payload.id)
            }
            sessionStore.setAudioFileName(fileURL.lastPathComponent, lessonID: lesson.lessonID)
            audioPlayer.load(url: fileURL)
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
            let fileURL = try await generateAudioFile(for: lesson, apiKey: trimmedKey)
            sessionStore.setAudioFileName(fileURL.lastPathComponent, lessonID: lesson.lessonID)
            audioPlayer.load(url: fileURL)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func generateAudioFile(for lesson: GeneratedLesson, apiKey: String) async throws -> URL {
        let wavData = try await GeminiTTSService.generateWav(
            dialog: lesson.ttsText,
            apiKey: apiKey,
            model: selectedTTSModel
        )
        return try FileStorage.saveLessonWavFile(data: wavData, lessonID: lesson.lessonID)
    }

    private func resetChatAndProgress() {
        sessionStore.resetChatAndProgressForGeneratedLesson(lessonID: payload.id)
        draft = ""
        errorMessage = nil
    }

    private func sendTutorMessage(_ message: String, allowsAutoQuizRequest: Bool = true) async {
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
        isSending = false

        if allowsAutoQuizRequest {
            await requestTranslationQuizIfNeeded()
        }
    }

    private func requestTranslationQuizIfNeeded() async {
        guard shouldOfferTranslationQuiz, !isRequestingTranslationQuiz, !isSending else { return }
        guard let generatedLesson else { return }

        let trimmedKey = openAIAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = OpenAIModelDefaults.lessonInteractor.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonInteractorReasoningEffort

        guard !trimmedKey.isEmpty else { return }

        let latestUserMessage = "Start the translation quiz."
        let syntheticHistory = sessionStore.messages(for: payload.id) + [
            LessonChatMessage(lessonID: payload.id, role: .user, content: latestUserMessage)
        ]

        isRequestingTranslationQuiz = true
        isSending = true
        defer {
            isRequestingTranslationQuiz = false
            isSending = false
        }

        do {
            let response = try await OpenAITutorService.sendLessonMessage(
                payload: payload,
                generatedLesson: generatedLesson,
                state: lessonState,
                chatHistory: syntheticHistory,
                latestUserMessage: latestUserMessage,
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

private enum LessonPanel: CaseIterable, Identifiable, Hashable {
    case whereWeAre
    case dialogue
    case practice
    case menu

    var id: Self { self }

    var title: String {
        switch self {
        case .whereWeAre:
            return "Where we are"
        case .dialogue:
            return "Dialog"
        case .practice:
            return "Practice"
        case .menu:
            return "Menu"
        }
    }

    var systemImage: String {
        switch self {
        case .whereWeAre:
            return "map"
        case .dialogue:
            return "text.bubble"
        case .practice:
            return "questionmark.circle"
        case .menu:
            return "ellipsis"
        }
    }
}

private enum LessonChatStyle {
    static let panel = Color(red: 0.06, green: 0.06, blue: 0.06)
    static let panelStroke = Color.white.opacity(0.10)
    static let control = Color.white.opacity(0.10)
    static let controlSelected = Color.white.opacity(0.18)
    static let primaryText = Color.white
    static let secondaryText = Color.white.opacity(0.58)
    static let tertiaryText = Color.white.opacity(0.42)
}

private struct LessonTopControlBar: View {
    @Binding var selection: LessonPanel?

    var body: some View {
        HStack(spacing: 10) {
            ForEach(LessonPanel.allCases) { panel in
                Button {
                    withAnimation(.snappy(duration: 0.22)) {
                        selection = selection == panel ? nil : panel
                    }
                } label: {
                    Image(systemName: panel.systemImage)
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundStyle(LessonChatStyle.primaryText)
                        .frame(maxWidth: .infinity)
                        .frame(height: 52)
                        .background(selection == panel ? LessonChatStyle.controlSelected : LessonChatStyle.control)
                        .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
                        .overlay {
                            RoundedRectangle(cornerRadius: 26, style: .continuous)
                                .stroke(LessonChatStyle.panelStroke, lineWidth: 1)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(panel.title)
            }
        }
    }
}

private struct LessonInlineAudioPlayer: View {
    @ObservedObject var audioPlayer: AudioPlayerController
    let fileURL: URL?

    private var hasAudio: Bool {
        fileURL != nil
    }

    var body: some View {
        HStack(spacing: 12) {
            Button {
                audioPlayer.togglePlayback()
            } label: {
                Image(systemName: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(hasAudio ? Color.black : LessonChatStyle.tertiaryText)
                    .frame(width: 38, height: 38)
                    .background(hasAudio ? Color.white : LessonChatStyle.control)
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(!hasAudio)
            .accessibilityLabel(audioPlayer.isPlaying ? "Pause audio" : "Play audio")

            VStack(alignment: .leading, spacing: 4) {
                Slider(
                    value: Binding(
                        get: { audioPlayer.currentTime },
                        set: { audioPlayer.seek(to: $0) }
                    ),
                    in: 0...max(audioPlayer.duration, 1)
                )
                .tint(.white)
                .disabled(!hasAudio)

                HStack {
                    Text(hasAudio ? "Lesson audio" : "Audio pending")
                    Spacer()
                    Text("\(audioPlayer.currentTime.lessonClockText) / \(audioPlayer.duration.lessonClockText)")
                }
                .font(.caption)
                .foregroundStyle(LessonChatStyle.secondaryText)
            }

            if let fileURL {
                ShareLink(item: fileURL) {
                    Image(systemName: "square.and.arrow.up")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(LessonChatStyle.primaryText)
                        .frame(width: 38, height: 38)
                        .background(LessonChatStyle.control)
                        .clipShape(Circle())
                }
                .accessibilityLabel("Share audio")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(LessonChatStyle.panel)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .stroke(LessonChatStyle.panelStroke, lineWidth: 1)
        }
    }
}

private struct LessonExpandedPanel: View {
    let panel: LessonPanel
    let payload: LessonPayload
    let generatedLesson: GeneratedLesson
    let lessonState: LessonState
    let isGeneratingLesson: Bool
    let isGeneratingAudio: Bool
    let isSending: Bool
    let isRequestingTranslationQuiz: Bool
    let onRegenerate: () -> Void
    let onRegenerateAudio: () -> Void
    let onResetProgress: () -> Void
    let onMarkComplete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Label(panel.title, systemImage: panel.systemImage)
                .font(.headline)
                .foregroundStyle(LessonChatStyle.primaryText)

            content
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(LessonChatStyle.panel)
        .clipShape(RoundedRectangle(cornerRadius: 30, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 30, style: .continuous)
                .stroke(LessonChatStyle.panelStroke, lineWidth: 1)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch panel {
        case .whereWeAre:
            whereWeAreContent
        case .dialogue:
            dialogueContent
        case .practice:
            practiceContent
        case .menu:
            menuContent
        }
    }

    private var whereWeAreContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("\(payload.courseLevel.rawValue), Stage \(payload.coursePosition.stage), Week \(payload.coursePosition.week), Day \(payload.coursePosition.day)")
                .font(.title3)
                .foregroundStyle(LessonChatStyle.secondaryText)

            Text(payload.lessonIntent.oneSentenceGoal)
                .font(.title2.weight(.bold))
                .foregroundStyle(LessonChatStyle.primaryText)
                .fixedSize(horizontal: false, vertical: true)

            Text(payload.grammarTarget.mainFocus.name)
                .font(.title3)
                .foregroundStyle(LessonChatStyle.primaryText)
                .fixedSize(horizontal: false, vertical: true)

            Text(payload.dialogueTask.scenario)
                .font(.body)
                .foregroundStyle(LessonChatStyle.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
        }
        .textSelection(.enabled)
    }

    private var dialogueContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(generatedLesson.dialogue.enumerated()), id: \.offset) { _, line in
                HStack(alignment: .top, spacing: 10) {
                    Text(line.speaker.rawValue)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(line.speaker == .Anna ? Color.blue.opacity(0.9) : Color.green.opacity(0.9))
                        .frame(width: 48, alignment: .leading)

                    Text(line.text)
                        .font(.body)
                        .foregroundStyle(LessonChatStyle.primaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .textSelection(.enabled)
    }

    private var practiceContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let quiz = lessonState.translationQuiz {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Translation")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(LessonChatStyle.secondaryText)

                    ForEach(Array(quiz.sentencesEN.enumerated()), id: \.offset) { index, sentence in
                        Text("\(index + 1). \(sentence)")
                            .font(.body)
                            .foregroundStyle(LessonChatStyle.primaryText)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            } else if lessonState.acceptedQuestionIDs.count == generatedLesson.comprehensionQuestions.count || isRequestingTranslationQuiz {
                HStack(spacing: 10) {
                    ProgressView()
                        .tint(.white)
                    Text("Preparing translation quiz")
                        .font(.subheadline)
                        .foregroundStyle(LessonChatStyle.secondaryText)
                }
            }

            VStack(alignment: .leading, spacing: 10) {
                Text("Comprehension")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(LessonChatStyle.secondaryText)

                ForEach(generatedLesson.comprehensionQuestions) { question in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: lessonState.acceptedQuestionIDs.contains(question.id) ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(lessonState.acceptedQuestionIDs.contains(question.id) ? .green : LessonChatStyle.tertiaryText)

                        Text(question.questionSV)
                            .font(.body)
                            .foregroundStyle(LessonChatStyle.primaryText)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
        .textSelection(.enabled)
    }

    private var menuContent: some View {
        VStack(spacing: 10) {
            Button(action: onRegenerate) {
                menuActionLabel("Regenerate Lesson", systemImage: "arrow.clockwise", tint: LessonChatStyle.control)
            }
            .buttonStyle(.plain)
            .disabled(isGeneratingLesson)

            Button(action: onRegenerateAudio) {
                menuActionLabel(lessonState.audioFileName == nil ? "Generate Audio" : "Regenerate Audio", systemImage: "waveform", tint: LessonChatStyle.control)
            }
            .buttonStyle(.plain)
            .disabled(isGeneratingAudio || isGeneratingLesson)

            Button(role: .destructive, action: onResetProgress) {
                menuActionLabel("Debug: Reset Chat & Progress", systemImage: "trash", tint: Color.red.opacity(0.28))
            }
            .buttonStyle(.plain)
            .disabled(isSending || isGeneratingLesson)

            Button(action: onMarkComplete) {
                menuActionLabel(
                    lessonState.isCompleted ? "Completed" : "Mark complete",
                    systemImage: lessonState.isCompleted ? "checkmark.circle.fill" : "checkmark.circle",
                    tint: lessonState.isCompleted ? Color.green.opacity(0.55) : Color.accentColor
                )
            }
            .buttonStyle(.plain)
            .disabled(lessonState.isCompleted)
        }
    }

    private func menuActionLabel(_ title: String, systemImage: String, tint: Color) -> some View {
        Label(title, systemImage: systemImage)
            .font(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 14)
            .background(tint)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(LessonChatStyle.panelStroke, lineWidth: 1)
        }
    }
}

private struct LessonAssistantOpening: View {
    var body: some View {
        Text("Listen to the lesson audio, then answer the comprehension questions here. You can also ask about words or grammar from the dialog.")
            .font(.body)
            .foregroundStyle(LessonChatStyle.primaryText)
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled)
    }
}

private struct LessonChatMessageRow: View {
    let message: LessonChatMessage

    var body: some View {
        HStack(alignment: .bottom) {
            if message.role == .user {
                Spacer(minLength: 56)
            }

            MarkdownChatText(content: message.content)
                .font(.body)
                .foregroundStyle(LessonChatStyle.primaryText)
                .padding(.horizontal, message.role == .user ? 16 : 0)
                .padding(.vertical, message.role == .user ? 12 : 0)
                .background(message.role == .user ? Color.white.opacity(0.14) : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .frame(maxWidth: message.role == .user ? nil : .infinity, alignment: .leading)
                .textSelection(.enabled)

            if message.role == .assistant {
                Spacer(minLength: 56)
            }
        }
    }
}

private struct LessonChatInputBar: View {
    @Binding var draft: String
    let isSending: Bool
    var isFocused: FocusState<Bool>.Binding
    let onSend: () -> Void

    private var canSend: Bool {
        !isSending && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Ask or answer", text: $draft, axis: .vertical)
                .font(.body)
                .foregroundStyle(LessonChatStyle.primaryText)
                .tint(.white)
                .lineLimit(1...4)
                .focused(isFocused)
                .disabled(isSending)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)

            Button(action: onSend) {
                Group {
                    if isSending {
                        ProgressView()
                            .controlSize(.small)
                            .tint(.black)
                    } else {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 17, weight: .bold))
                    }
                }
                .foregroundStyle(.black)
                .frame(width: 38, height: 38)
                .background(canSend || isSending ? Color.white : Color.white.opacity(0.35))
                .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
            .padding(.trailing, 7)
            .padding(.bottom, 7)
            .accessibilityLabel("Send")
        }
        .background(LessonChatStyle.panel)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(LessonChatStyle.panelStroke, lineWidth: 1)
        }
    }
}

private extension TimeInterval {
    var lessonClockText: String {
        let seconds = Int(self)
        let minutesPart = seconds / 60
        let secondsPart = seconds % 60
        return String(format: "%02d:%02d", minutesPart, secondsPart)
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
