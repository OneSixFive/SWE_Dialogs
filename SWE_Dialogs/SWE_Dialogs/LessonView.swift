import SwiftUI
import UIKit

struct LessonsHomeView: View {
    @StateObject private var curriculumStore = CurriculumStore()
    @StateObject private var generationStore = LessonGenerationStore()
    @StateObject private var sessionStore = LessonSessionStore()
    @StateObject private var lessonAudioPlayer = AudioPlayerController()

    @State private var path: [String] = []
    @State private var visibleWeekID: String?
    @State private var didInitialScroll = false

    var body: some View {
        NavigationStack(path: $path) {
            GeometryReader { geometry in
                ScrollViewReader { proxy in
                    ZStack(alignment: .top) {
                        ScrollView {
                            LazyVStack(spacing: 0) {
                                if let errorMessage = curriculumStore.errorMessage {
                                    Text(errorMessage)
                                        .font(.footnote)
                                        .foregroundStyle(.red)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding()
                                        .background(LessonPathStyle.panel)
                                        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                                        .padding(.horizontal, 16)
                                        .padding(.bottom, 18)
                                }

                                if displayWeeks.isEmpty, curriculumStore.errorMessage == nil {
                                    Text("No lessons found.")
                                        .font(.body)
                                        .foregroundStyle(LessonPathStyle.secondaryText)
                                        .frame(maxWidth: .infinity, alignment: .center)
                                        .padding(.top, 180)
                                } else {
                                    ForEach(displayWeeks) { week in
                                        LessonPathWeekSection(
                                            week: week,
                                            isFirstChronologicalWeek: week.id == lessonWeeks.first?.id,
                                            activeLessonID: activeLesson?.id,
                                            generationStore: generationStore,
                                            sessionStore: sessionStore,
                                            onLessonTap: { lesson in
                                                path.append(lesson.id)
                                            }
                                        )
                                        .id(week.id)
                                    }
                                }
                            }
                            .padding(.top, LessonPathStyle.headerHeight + 22)
                            .padding(.bottom, 104)
                        }
                        .background(LessonPathStyle.background)
                        .coordinateSpace(name: LessonPathStyle.scrollCoordinateSpace)
                        .onPreferenceChange(LessonVisibleWeekPreferenceKey.self) { frames in
                            updateVisibleWeek(from: frames, viewportHeight: geometry.size.height)
                        }

                        LessonPathHeader(week: currentWeek)
                            .padding(.horizontal, 16)
                            .padding(.top, 8)
                            .background(
                                VStack(spacing: 0) {
                                    LessonPathStyle.background
                                        .frame(height: LessonPathStyle.headerHeight + 28)

                                    LinearGradient(
                                        colors: [
                                            LessonPathStyle.background,
                                            LessonPathStyle.background.opacity(0.0)
                                        ],
                                        startPoint: .top,
                                        endPoint: .bottom
                                    )
                                    .frame(height: 32)
                                }
                                .frame(maxWidth: .infinity)
                                .ignoresSafeArea(edges: .top),
                                alignment: .top
                            )

                        VStack {
                            Spacer()
                            HStack {
                                Button {
                                    scrollToActiveLesson(with: proxy)
                                } label: {
                                    Image(systemName: "arrow.down")
                                        .font(.system(size: 22, weight: .bold))
                                        .foregroundStyle(Color.white)
                                        .frame(width: 58, height: 58)
                                        .background(LessonPathStyle.control)
                                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                                        .overlay {
                                            RoundedRectangle(cornerRadius: 18, style: .continuous)
                                                .stroke(LessonPathStyle.panelStroke, lineWidth: 1)
                                        }
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel("Jump to first incomplete lesson")

                                Spacer()
                            }
                            .padding(.leading, 16)
                            .padding(.bottom, 16)
                        }
                    }
                    .background(LessonPathStyle.background.ignoresSafeArea())
                    .onAppear {
                        visibleWeekID = visibleWeekID ?? lessonWeeks.first?.id
                        scrollToBeginningIfNeeded(with: proxy)
                    }
                    .onChange(of: firstLessonID) { _, _ in
                        visibleWeekID = visibleWeekID ?? lessonWeeks.first?.id
                        scrollToBeginningIfNeeded(with: proxy)
                    }
                }
            }
            .toolbar(.hidden, for: .navigationBar)
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
        }
    }

    private var lessonWeeks: [LessonPathWeek] {
        LessonPathWeek.makeWeeks(from: curriculumStore.lessons.sorted(by: lessonComesBefore))
    }

    private var displayWeeks: [LessonPathWeek] {
        Array(lessonWeeks.reversed())
    }

    private var currentWeek: LessonPathWeek? {
        guard let visibleWeekID else { return lessonWeeks.first }
        return lessonWeeks.first { $0.id == visibleWeekID } ?? lessonWeeks.first
    }

    private var firstLessonID: String? {
        lessonWeeks.first?.lessons.first?.id
    }

    private var firstWeekID: String? {
        lessonWeeks.first?.id
    }

    private var activeLesson: LessonPayload? {
        let orderedLessons = lessonWeeks.flatMap(\.lessons)
        return orderedLessons.first { !sessionStore.state(for: $0.id).isCompleted } ?? orderedLessons.first
    }

    private func scrollToBeginningIfNeeded(with proxy: ScrollViewProxy) {
        guard !didInitialScroll, let firstWeekID else { return }
        didInitialScroll = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            proxy.scrollTo(firstWeekID, anchor: .bottom)
        }
    }

    private func scrollToActiveLesson(with proxy: ScrollViewProxy) {
        guard let activeLesson,
              let week = lessonWeeks.first(where: { $0.lessons.contains(activeLesson) }) else {
            guard let firstWeekID else { return }
            withAnimation(.snappy(duration: 0.35)) {
                proxy.scrollTo(firstWeekID, anchor: .bottom)
            }
            return
        }

        withAnimation(.snappy(duration: 0.35)) {
            proxy.scrollTo(week.id, anchor: anchor(for: activeLesson, in: week))
        }
    }

    private func anchor(for lesson: LessonPayload, in week: LessonPathWeek) -> UnitPoint {
        guard let chronologicalIndex = week.lessons.firstIndex(of: lesson), !week.lessons.isEmpty else {
            return .center
        }

        let displayIndex = week.lessons.count - chronologicalIndex - 1
        let centerFraction = (CGFloat(displayIndex) + 0.5) / CGFloat(week.lessons.count)
        let clampedFraction = min(max(centerFraction, 0.24), 0.76)
        return UnitPoint(x: 0.5, y: clampedFraction)
    }

    private func updateVisibleWeek(from frames: [LessonVisibleWeekFrame], viewportHeight: CGFloat) {
        let visibleAreaTop = LessonPathStyle.headerHeight + 16
        let visibleAreaBottom = viewportHeight - 96

        guard let bestFrame = frames.max(by: { lhs, rhs in
            visibleOverlap(for: lhs, top: visibleAreaTop, bottom: visibleAreaBottom) <
                visibleOverlap(for: rhs, top: visibleAreaTop, bottom: visibleAreaBottom)
        }) else {
            return
        }

        guard bestFrame.id != visibleWeekID else { return }
        visibleWeekID = bestFrame.id
    }

    private func visibleOverlap(for frame: LessonVisibleWeekFrame, top: CGFloat, bottom: CGFloat) -> CGFloat {
        max(0, min(frame.maxY, bottom) - max(frame.minY, top))
    }

    private func lessonComesBefore(_ lhs: LessonPayload, _ rhs: LessonPayload) -> Bool {
        if lhs.courseLevel.rawValue != rhs.courseLevel.rawValue {
            return lhs.courseLevel.rawValue < rhs.courseLevel.rawValue
        }
        if lhs.coursePosition.stage != rhs.coursePosition.stage {
            return lhs.coursePosition.stage < rhs.coursePosition.stage
        }
        if lhs.coursePosition.week != rhs.coursePosition.week {
            return lhs.coursePosition.week < rhs.coursePosition.week
        }
        return lhs.coursePosition.day < rhs.coursePosition.day
    }
}

private struct LessonPathWeek: Identifiable, Equatable {
    let level: LessonLevel
    let stage: Int
    let week: Int
    let stageName: String
    let lessons: [LessonPayload]

    var id: String {
        "\(level.rawValue)-stage-\(stage)-week-\(week)"
    }

    var title: String {
        "\(level.rawValue), Stage \(stage), Week \(week)"
    }

    var stageNote: String {
        let trimmed = stageName.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Stage note placeholder." : trimmed
    }

    static func makeWeeks(from lessons: [LessonPayload]) -> [LessonPathWeek] {
        var weeks: [LessonPathWeek] = []
        var currentLessons: [LessonPayload] = []
        var currentKey: (level: LessonLevel, stage: Int, week: Int, stageName: String)?

        func flushCurrentWeek() {
            guard let key = currentKey, !currentLessons.isEmpty else { return }
            weeks.append(
                LessonPathWeek(
                    level: key.level,
                    stage: key.stage,
                    week: key.week,
                    stageName: key.stageName,
                    lessons: currentLessons
                )
            )
        }

        for lesson in lessons {
            let key = (
                level: lesson.courseLevel,
                stage: lesson.coursePosition.stage,
                week: lesson.coursePosition.week,
                stageName: lesson.coursePosition.stageName
            )

            if let currentKey,
               currentKey.level == key.level,
               currentKey.stage == key.stage,
               currentKey.week == key.week {
                currentLessons.append(lesson)
            } else {
                flushCurrentWeek()
                currentKey = key
                currentLessons = [lesson]
            }
        }

        flushCurrentWeek()
        return weeks
    }
}

private enum LessonPathStyle {
    static let background = Color.black
    static let panel = Color(red: 0.06, green: 0.06, blue: 0.06)
    static let panelRaised = Color(red: 0.12, green: 0.12, blue: 0.12)
    static let panelStroke = Color.white.opacity(0.10)
    static let control = Color.white.opacity(0.12)
    static let primaryText = Color.white
    static let secondaryText = Color.white.opacity(0.60)
    static let tertiaryText = Color.white.opacity(0.38)
    static let headerHeight: CGFloat = 118
    static let scrollCoordinateSpace = "lesson-path-scroll"
}

private struct LessonPathHeader: View {
    let week: LessonPathWeek?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(week?.title ?? "Lessons")
                .font(.title3.weight(.semibold))
                .foregroundStyle(LessonPathStyle.primaryText)
                .lineLimit(1)

            Text(week?.stageNote ?? "Stage note placeholder.")
                .font(.footnote)
                .foregroundStyle(LessonPathStyle.secondaryText)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .background(LessonPathStyle.panel)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .stroke(LessonPathStyle.panelStroke, lineWidth: 1)
        }
    }
}

private struct LessonPathWeekSection: View {
    let week: LessonPathWeek
    let isFirstChronologicalWeek: Bool
    let activeLessonID: String?
    @ObservedObject var generationStore: LessonGenerationStore
    @ObservedObject var sessionStore: LessonSessionStore
    let onLessonTap: (LessonPayload) -> Void

    var body: some View {
        VStack(spacing: 0) {
            LessonPathWeekBlock(
                week: week,
                activeLessonID: activeLessonID,
                generationStore: generationStore,
                sessionStore: sessionStore,
                onLessonTap: onLessonTap
            )

            if !isFirstChronologicalWeek {
                LessonWeekSeparator(week: week)
                    .padding(.top, 8)
                    .padding(.bottom, 24)
            }
        }
        .background {
            GeometryReader { proxy in
                Color.clear.preference(
                    key: LessonVisibleWeekPreferenceKey.self,
                    value: [
                        LessonVisibleWeekFrame(
                            id: week.id,
                            minY: proxy.frame(in: .named(LessonPathStyle.scrollCoordinateSpace)).minY,
                            maxY: proxy.frame(in: .named(LessonPathStyle.scrollCoordinateSpace)).maxY
                        )
                    ]
                )
            }
        }
    }
}

private struct LessonPathWeekBlock: View {
    let week: LessonPathWeek
    let activeLessonID: String?
    @ObservedObject var generationStore: LessonGenerationStore
    @ObservedObject var sessionStore: LessonSessionStore
    let onLessonTap: (LessonPayload) -> Void

    private let rowHeight: CGFloat = 138

    var body: some View {
        GeometryReader { proxy in
            let displayLessons = Array(week.lessons.reversed())
            let blobWidth = min(276, max(228, proxy.size.width * 0.66))

            ZStack {
                LessonDashedConnector(
                    points: displayLessons.enumerated().map { index, lesson in
                        CGPoint(
                            x: proxy.size.width / 2 + horizontalOffset(for: lesson.coursePosition.day, width: proxy.size.width),
                            y: rowHeight / 2 + CGFloat(index) * rowHeight
                        )
                    }
                )
                .stroke(
                    Color.white.opacity(0.24),
                    style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round, dash: [7, 10])
                )

                VStack(spacing: 0) {
                    ForEach(displayLessons) { lesson in
                        LessonPathNode(
                            lesson: lesson,
                            generatedLesson: generationStore.generatedLesson(for: lesson.id),
                            state: sessionStore.state(for: lesson.id),
                            isActive: lesson.id == activeLessonID,
                            horizontalOffset: horizontalOffset(for: lesson.coursePosition.day, width: proxy.size.width),
                            blobWidth: blobWidth,
                            onTap: {
                                onLessonTap(lesson)
                            }
                        )
                        .id(lesson.id)
                        .frame(height: rowHeight)
                    }
                }
            }
        }
        .frame(height: rowHeight * CGFloat(max(week.lessons.count, 1)))
    }

    private func horizontalOffset(for day: Int, width: CGFloat) -> CGFloat {
        let clampedWidth = min(width, 430)
        let offsets: [CGFloat] = [
            0.00,
            -0.10,
            0.11,
            -0.03,
            0.13,
            -0.12,
            0.04
        ]
        let index = max(0, min(day - 1, offsets.count - 1))
        return offsets[index] * clampedWidth
    }
}

private struct LessonPathNode: View {
    let lesson: LessonPayload
    let generatedLesson: GeneratedLesson?
    let state: LessonState
    let isActive: Bool
    let horizontalOffset: CGFloat
    let blobWidth: CGFloat
    let onTap: () -> Void

    private var foregroundColor: Color {
        isActive ? Color.black : LessonPathStyle.primaryText
    }

    private var secondaryColor: Color {
        isActive ? Color.black.opacity(0.62) : LessonPathStyle.secondaryText
    }

    private var fillColor: Color {
        if isActive { return Color.white }
        if state.isCompleted { return Color.white.opacity(0.18) }
        return LessonPathStyle.panelRaised
    }

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Text("Day \(lesson.coursePosition.day)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(secondaryColor)

                    Spacer(minLength: 8)

                    if let statusImage {
                        Image(systemName: statusImage)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(secondaryColor)
                    }
                }

                Text(lesson.lessonIntent.oneSentenceGoal)
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(foregroundColor)
                    .lineLimit(4)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .frame(width: blobWidth, alignment: .leading)
            .frame(minHeight: 108, alignment: .leading)
            .background(fillColor)
            .clipShape(RoundedRectangle(cornerRadius: 30, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 30, style: .continuous)
                    .stroke(borderColor, lineWidth: isActive ? 0 : 1)
            }
            .shadow(color: Color.black.opacity(isActive ? 0.26 : 0.16), radius: 12, x: 0, y: 8)
            .offset(x: horizontalOffset)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Day \(lesson.coursePosition.day), \(lesson.lessonIntent.oneSentenceGoal)")
    }

    private var borderColor: Color {
        state.isCompleted ? Color.white.opacity(0.18) : LessonPathStyle.panelStroke
    }

    private var statusImage: String? {
        if state.isCompleted { return "checkmark.circle.fill" }
        if state.audioFileName != nil { return "waveform" }
        if generatedLesson != nil { return "sparkles" }
        return nil
    }
}

private struct LessonDashedConnector: Shape {
    let points: [CGPoint]

    func path(in rect: CGRect) -> Path {
        var path = Path()
        guard let firstPoint = points.first else { return path }

        path.move(to: firstPoint)
        for point in points.dropFirst() {
            path.addLine(to: point)
        }

        return path
    }
}

private struct LessonWeekSeparator: View {
    let week: LessonPathWeek

    var body: some View {
        HStack(spacing: 12) {
            Rectangle()
                .fill(LessonPathStyle.panelStroke)
                .frame(height: 1)

            VStack(spacing: 4) {
                Text("\(week.level.rawValue) · Stage \(week.stage) · Week \(week.week)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(LessonPathStyle.secondaryText)
                    .lineLimit(1)

                Text("Week description placeholder")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(LessonPathStyle.primaryText)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: 210)

            Rectangle()
                .fill(LessonPathStyle.panelStroke)
                .frame(height: 1)
        }
        .padding(.horizontal, 18)
    }
}

private struct LessonVisibleWeekFrame: Equatable {
    let id: String
    let minY: CGFloat
    let maxY: CGFloat
}

private struct LessonVisibleWeekPreferenceKey: PreferenceKey {
    static var defaultValue: [LessonVisibleWeekFrame] = []

    static func reduce(value: inout [LessonVisibleWeekFrame], nextValue: () -> [LessonVisibleWeekFrame]) {
        value.append(contentsOf: nextValue())
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
        GeometryReader { geometry in
            VStack(spacing: 0) {
                VStack(spacing: 12) {
                    LessonTopControlBar(selection: $expandedPanel)
                        .simultaneousGesture(TapGesture().onEnded {
                            dismissKeyboard()
                        })

                    LessonInlineAudioPlayer(audioPlayer: audioPlayer, fileURL: currentAudioURL)
                        .simultaneousGesture(TapGesture().onEnded {
                            dismissKeyboardAndCollapseExpandedPanel()
                        })

                    if let expandedPanel {
                        lessonExpandedPanel(
                            expandedPanel,
                            generatedLesson: generatedLesson,
                            maxHeight: max(430, geometry.size.height * 0.58)
                        )
                        .simultaneousGesture(TapGesture().onEnded {
                            dismissKeyboard()
                        })
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
                            if let errorMessage {
                                Text(errorMessage)
                                    .font(.footnote)
                                    .foregroundStyle(.red)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }

                            if messages.isEmpty {
                                LessonAssistantOpening(firstQuestion: generatedLesson.comprehensionQuestions.first)
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
                    .contentShape(Rectangle())
                    .simultaneousGesture(TapGesture().onEnded {
                        dismissKeyboardAndCollapseExpandedPanel()
                    })
                    .scrollDismissesKeyboard(.interactively)
                    .onChange(of: messages.count) { _, _ in
                        withAnimation {
                            proxy.scrollTo("lesson-chat-bottom", anchor: .bottom)
                        }
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
            .simultaneousGesture(TapGesture().onEnded {
                collapseExpandedPanel()
            })
        }
        .toolbar(.hidden, for: .tabBar)
    }

    private func lessonExpandedPanel(_ panel: LessonPanel, generatedLesson: GeneratedLesson, maxHeight: CGFloat) -> some View {
        LessonExpandedPanel(
            panel: panel,
            payload: payload,
            generatedLesson: generatedLesson,
            lessonState: lessonState,
            maxHeight: maxHeight,
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
    }

    private func collapseExpandedPanel() {
        guard expandedPanel != nil else { return }
        withAnimation(.snappy(duration: 0.22)) {
            expandedPanel = nil
        }
    }

    private func dismissKeyboard() {
        isChatFocused = false
    }

    private func dismissKeyboardAndCollapseExpandedPanel() {
        dismissKeyboard()
        collapseExpandedPanel()
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
    let maxHeight: CGFloat
    let isGeneratingLesson: Bool
    let isGeneratingAudio: Bool
    let isSending: Bool
    let isRequestingTranslationQuiz: Bool
    let onRegenerate: () -> Void
    let onRegenerateAudio: () -> Void
    let onResetProgress: () -> Void
    let onMarkComplete: () -> Void

    var body: some View {
        let shouldUseTallScrollArea = panel == .dialogue

        VStack(alignment: .leading, spacing: 18) {
            Label(panel.title, systemImage: panel.systemImage)
                .font(.headline)
                .foregroundStyle(LessonChatStyle.primaryText)

            if shouldUseTallScrollArea {
                ScrollView {
                    content
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: max(360, maxHeight - 88))
                .scrollIndicators(.visible)
            } else {
                content
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(height: shouldUseTallScrollArea ? maxHeight : nil, alignment: .topLeading)
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
        SelectableLessonTextView(text: dialogueText)
    }

    private var practiceContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let quiz = lessonState.translationQuiz {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Translation")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(LessonChatStyle.secondaryText)

                    SelectableLessonTextView(text: translationText(quiz))
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

                SelectableLessonTextView(text: comprehensionText)
            }
        }
    }

    private var dialogueText: String {
        generatedLesson.dialogue
            .map { "\($0.speaker.rawValue): \($0.text)" }
            .joined(separator: "\n")
    }

    private var comprehensionText: String {
        generatedLesson.comprehensionQuestions
            .enumerated()
            .map { index, question in "\(index + 1). \(question.questionSV)" }
            .joined(separator: "\n")
    }

    private func translationText(_ quiz: TranslationQuiz) -> String {
        quiz.sentencesEN
            .enumerated()
            .map { index, sentence in "\(index + 1). \(sentence)" }
            .joined(separator: "\n")
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
    let firstQuestion: GeneratedQuestion?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Listen to the lesson audio, then answer the comprehension questions here. You can also ask about words or grammar from the dialog.")

            if let firstQuestion {
                (Text("Fråga 1: ").bold() + Text(firstQuestion.questionSV))
            }
        }
        .font(.body)
        .foregroundStyle(LessonChatStyle.primaryText)
        .frame(maxWidth: .infinity, alignment: .leading)
        .textSelection(.enabled)
    }
}

private struct SelectableLessonTextView: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.isEditable = false
        textView.isSelectable = true
        textView.isScrollEnabled = false
        textView.backgroundColor = .clear
        textView.textColor = .white
        textView.textContainerInset = .zero
        textView.textContainer.lineFragmentPadding = 0
        textView.textContainer.widthTracksTextView = true
        textView.adjustsFontForContentSizeCategory = true
        textView.font = UIFont.preferredFont(forTextStyle: .body)
        textView.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        uiView.text = text
        uiView.textColor = .white
        uiView.font = UIFont.preferredFont(forTextStyle: .body)
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        let targetWidth = proposal.width
            ?? uiView.window?.windowScene?.screen.bounds.width
            ?? uiView.bounds.width
        let fittingSize = uiView.sizeThatFits(CGSize(width: targetWidth, height: .greatestFiniteMagnitude))
        return CGSize(width: targetWidth, height: fittingSize.height)
    }
}

private struct SelectableChatTextView: UIViewRepresentable {
    let content: String

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.isEditable = false
        textView.isSelectable = true
        textView.isScrollEnabled = false
        textView.backgroundColor = .clear
        textView.textColor = .white
        textView.textContainerInset = .zero
        textView.textContainer.lineFragmentPadding = 0
        textView.textContainer.widthTracksTextView = true
        textView.adjustsFontForContentSizeCategory = true
        textView.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        uiView.attributedText = content.lessonChatAttributedString()
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        let targetWidth = proposal.width
            ?? uiView.window?.windowScene?.screen.bounds.width
            ?? uiView.bounds.width
        let fittingSize = uiView.sizeThatFits(CGSize(width: targetWidth, height: .greatestFiniteMagnitude))
        return CGSize(width: targetWidth, height: fittingSize.height)
    }
}

private extension String {
    func lessonChatAttributedString() -> NSAttributedString {
        let baseFont = UIFont.preferredFont(forTextStyle: .body)
        let boldDescriptor = baseFont.fontDescriptor.withSymbolicTraits(.traitBold) ?? baseFont.fontDescriptor
        let boldFont = UIFont(descriptor: boldDescriptor, size: baseFont.pointSize)
        let result = NSMutableAttributedString()
        var index = startIndex
        var isBold = false

        while index < endIndex {
            if self[index...].hasPrefix("**") {
                isBold.toggle()
                index = self.index(index, offsetBy: 2)
                continue
            }

            let nextIndex = self.index(after: index)
            result.append(
                NSAttributedString(
                    string: String(self[index]),
                    attributes: [
                        .font: isBold ? boldFont : baseFont,
                        .foregroundColor: UIColor.white
                    ]
                )
            )
            index = nextIndex
        }

        return result
    }
}

private struct LessonChatMessageRow: View {
    let message: LessonChatMessage

    var body: some View {
        HStack(alignment: .bottom) {
            if message.role == .user {
                Spacer(minLength: 56)
            }

            messageContent

            if message.role == .assistant {
                Spacer(minLength: 56)
            }
        }
    }

    @ViewBuilder
    private var messageContent: some View {
        if message.role == .user {
            SelectableChatTextView(content: message.content)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(Color.white.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        } else {
            SelectableChatTextView(content: message.content)
                .padding(.leading, 2)
                .frame(maxWidth: .infinity, alignment: .leading)
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
