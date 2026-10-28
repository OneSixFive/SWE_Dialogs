import SwiftUI
import UIKit

struct LessonsHomeView: View {
    @EnvironmentObject private var appSessionStore: AppSessionStore

    @StateObject private var curriculumStore = CurriculumStore()
    @StateObject private var generationStore = LessonGenerationStore()
    @StateObject private var sessionStore = LessonSessionStore()
    /// Held without observing: playback progress ticks several times a
    /// second and the path never shows it.
    @State private var lessonAudioPlayer = AudioPlayerController()

    @State private var path: [String] = []
    /// Only the jump direction is state; the scroll position feeding it is
    /// tracked outside SwiftUI so scrolling does not rebuild the path.
    @State private var jumpDirection: LessonPathJumpDirection = .down
    @State private var scrollTracking = LessonPathScrollTracking()
    @State private var didInitialScroll = false
    /// The user whose sessions were downloaded this launch. The download is
    /// large, so returning to the path does not repeat it.
    @State private var syncedUserID: Int?

    var body: some View {
        let activeLessonID = activeLesson?.id
        let lessonNumbers = curriculumStore.lessonNumbers
        let weekNumbers = curriculumStore.weekNumbers

        NavigationStack(path: $path) {
            GeometryReader { geometry in
                ScrollViewReader { proxy in
                    ZStack(alignment: .top) {
                        ScrollView {
                            LazyVStack(spacing: 0) {
                                if let errorMessage = curriculumStore.errorMessage {
                                    Text(errorMessage)
                                        .font(.footnote)
                                        .foregroundStyle(Retro.ink)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding()
                                        .background(Retro.paper)
                                        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                                        .padding(.horizontal, 16)
                                        .padding(.bottom, 18)
                                }

                                if displayWeeks.isEmpty, curriculumStore.errorMessage == nil {
                                    Text("Inga lektioner hittades.")
                                        .font(RetroFont.label(14, weight: .medium))
                                        .foregroundStyle(Retro.labelOnDarkSoft)
                                        .frame(maxWidth: .infinity, alignment: .center)
                                        .padding(.top, 180)
                                } else {
                                    ForEach(displayWeeks) { week in
                                        LessonPathWeekSection(
                                            week: week,
                                            weekNumber: weekNumbers[week.id],
                                            activeLessonID: activeLessonID,
                                            lessonNumbers: lessonNumbers,
                                            sessionStore: sessionStore,
                                            onLessonTap: { lesson in
                                                path.append(lesson.id)
                                            },
                                            onMarkLessonComplete: { lesson in
                                                sessionStore.markCompleted(lessonID: lesson.id)
                                            },
                                            onMarkWeekComplete: { week in
                                                for lesson in week.lessons {
                                                    sessionStore.markCompleted(lessonID: lesson.id)
                                                }
                                            }
                                        )
                                        .id(week.id)
                                    }
                                }
                            }
                            .padding(.top, LessonPathStyle.headerHeight + 6)
                            .padding(.bottom, 80)
                        }
                        .scrollIndicators(.hidden)
                        .coordinateSpace(name: LessonPathStyle.scrollCoordinateSpace)
                        .onPreferenceChange(LessonVisibleWeekPreferenceKey.self) { frames in
                            updateVisibleWeek(from: frames, viewportHeight: geometry.size.height)
                            refreshJumpDirection(viewportHeight: geometry.size.height)
                        }
                        .onPreferenceChange(LessonVisibleLessonPreferenceKey.self) { frames in
                            scrollTracking.activeLessonFrame = frames.first
                            refreshJumpDirection(viewportHeight: geometry.size.height)
                        }

                        LessonPathHeader(lessonNumber: activeLessonID.flatMap { lessonNumbers[$0] })
                            // One layer, so the digit glows are not
                            // recomposited while the path scrolls beneath.
                            .padding(4)
                            .drawingGroup()
                            .padding(-4)
                            .padding(.horizontal, 16)
                            .padding(.top, 6)
                            .padding(.bottom, 10)
                            .background(
                                // Faceplate strip the rows scroll under, with an engraved line.
                                FaceplateBackground()
                                    .overlay(alignment: .bottom) {
                                        VStack(spacing: 0) {
                                            Rectangle().fill(Color.black.opacity(0.55)).frame(height: 1)
                                            Rectangle().fill(Color.white.opacity(0.07)).frame(height: 1)
                                        }
                                        .padding(.horizontal, 16)
                                    }
                                    // A painted shade, not a drop shadow: the
                                    // strip stays still over moving rows.
                                    .overlay(alignment: .bottom) {
                                        LinearGradient(colors: [.black.opacity(0.3), .clear], startPoint: .top, endPoint: .bottom)
                                            .frame(height: 6)
                                            .offset(y: 6)
                                            .allowsHitTesting(false)
                                    }
                                    .ignoresSafeArea(edges: .top)
                            )

                        VStack {
                            Spacer()
                            HStack {
                                Button {
                                    scrollToActiveLesson(with: proxy)
                                } label: {
                                    RetroKeyLabel(systemImage: jumpArrowSystemImage)
                                }
                                .buttonStyle(RetroKeyStyle(tint: .graphite))
                                .frame(width: 56, height: 56)
                                .accessibilityLabel(jumpArrowAccessibilityLabel)

                                Spacer()
                            }
                            .padding(.leading, 16)
                            .padding(.bottom, 10)
                        }
                    }
                    .retroScreenBackground()
                    .onAppear {
                        configureStoresForCurrentUser()
                        scrollTracking.visibleWeekID = scrollTracking.visibleWeekID ?? firstWeekID
                        scrollToActiveLessonIfNeeded(with: proxy)
                    }
                    .onChange(of: appSessionStore.user?.id) { _, _ in
                        configureStoresForCurrentUser()
                    }
                    .onChange(of: firstLessonID) { _, _ in
                        scrollTracking.visibleWeekID = scrollTracking.visibleWeekID ?? firstWeekID
                        scrollToActiveLessonIfNeeded(with: proxy)
                    }
                }
            }
            .toolbar(.hidden, for: .navigationBar)
            .retroTabBar()
            .navigationDestination(for: String.self) { lessonID in
                if let lesson = curriculumStore.lesson(id: lessonID) {
                    LessonDetailView(
                        payload: lesson,
                        lessonNumber: curriculumStore.lessonNumbers[lesson.id],
                        generationStore: generationStore,
                        sessionStore: sessionStore,
                        audioPlayer: lessonAudioPlayer
                    )
                } else {
                    Text("Lektionen hittades inte.")
                        .foregroundStyle(Retro.labelOnDarkSoft)
                }
            }
        }
    }

    private var lessonWeeks: [LessonPathWeek] {
        curriculumStore.pathWeeks
    }

    /// Weeks read top to bottom, like rows on a sequencer.
    private var displayWeeks: [LessonPathWeek] {
        lessonWeeks
    }

    private var firstLessonID: String? {
        lessonWeeks.first?.lessons.first?.id
    }

    private var firstWeekID: String? {
        lessonWeeks.first?.id
    }

    private func configureStoresForCurrentUser() {
        let userID = appSessionStore.user?.id
        generationStore.configure(userID: userID)
        sessionStore.configure(userID: userID) { lessonID in
            generationStore.generatedLesson(for: lessonID)
        }

        guard let userID, userID != syncedUserID else { return }
        syncedUserID = userID
        Task {
            await sessionStore.syncFromBackend(generationStore: generationStore)
        }
    }

    private var activeLesson: LessonPayload? {
        let orderedLessons = curriculumStore.lessons
        return orderedLessons.first { !sessionStore.state(for: $0.id).isCompleted } ?? orderedLessons.first
    }

    private func scrollToActiveLessonIfNeeded(with proxy: ScrollViewProxy) {
        guard !didInitialScroll else { return }
        didInitialScroll = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            guard let activeLesson,
                  let week = lessonWeeks.first(where: { $0.lessons.contains(activeLesson) }) else {
                guard let firstWeekID else { return }
                proxy.scrollTo(firstWeekID, anchor: .top)
                return
            }

            proxy.scrollTo(week.id, anchor: anchor(for: activeLesson, in: week))
        }
    }

    private func scrollToActiveLesson(with proxy: ScrollViewProxy) {
        guard let activeLesson,
              let week = lessonWeeks.first(where: { $0.lessons.contains(activeLesson) }) else {
            guard let firstWeekID else { return }
            withAnimation(.snappy(duration: 0.35)) {
                proxy.scrollTo(firstWeekID, anchor: .top)
            }
            return
        }

        withAnimation(.snappy(duration: 0.35)) {
            proxy.scrollTo(week.id, anchor: anchor(for: activeLesson, in: week))
        }
    }

    private func anchor(for lesson: LessonPayload, in week: LessonPathWeek) -> UnitPoint {
        .center
    }

    private var jumpArrowSystemImage: String {
        switch jumpDirection {
        case .up:
            return "arrow.up"
        case .down:
            return "arrow.down"
        }
    }

    private var jumpArrowAccessibilityLabel: String {
        switch jumpDirection {
        case .up:
            return "Hoppa upp till nästa lektion"
        case .down:
            return "Hoppa ner till nästa lektion"
        }
    }

    private func refreshJumpDirection(viewportHeight: CGFloat) {
        let direction = currentJumpDirection(viewportHeight: viewportHeight)
        if direction != jumpDirection {
            jumpDirection = direction
        }
    }

    private func currentJumpDirection(viewportHeight: CGFloat) -> LessonPathJumpDirection {
        let top = visibleAreaTop
        let bottom = visibleAreaBottom(viewportHeight: viewportHeight)

        if let activeFrame = scrollTracking.activeLessonFrame {
            if activeFrame.maxY < top {
                return .up
            }

            if activeFrame.minY > bottom {
                return .down
            }

            let activeCenter = (activeFrame.minY + activeFrame.maxY) / 2
            let viewportCenter = (top + bottom) / 2
            return activeCenter < viewportCenter ? .up : .down
        }

        guard let activeLesson,
              let activeWeekIndex = lessonWeeks.firstIndex(where: { $0.lessons.contains(activeLesson) }),
              let visibleWeekID = scrollTracking.visibleWeekID,
              let visibleWeekIndex = lessonWeeks.firstIndex(where: { $0.id == visibleWeekID }) else {
            return .down
        }

        return activeWeekIndex > visibleWeekIndex ? .down : .up
    }

    private func updateVisibleWeek(from frames: [LessonVisibleWeekFrame], viewportHeight: CGFloat) {
        let top = visibleAreaTop
        let bottom = visibleAreaBottom(viewportHeight: viewportHeight)

        guard let bestFrame = frames.max(by: { lhs, rhs in
            visibleOverlap(for: lhs, top: top, bottom: bottom) <
                visibleOverlap(for: rhs, top: top, bottom: bottom)
        }) else {
            return
        }

        scrollTracking.visibleWeekID = bestFrame.id
    }

    private func visibleOverlap(for frame: LessonVisibleWeekFrame, top: CGFloat, bottom: CGFloat) -> CGFloat {
        max(0, min(frame.maxY, bottom) - max(frame.minY, top))
    }

    private var visibleAreaTop: CGFloat {
        LessonPathStyle.headerHeight + 16
    }

    private func visibleAreaBottom(viewportHeight: CGFloat) -> CGFloat {
        viewportHeight - 96
    }

}

private enum LessonPathJumpDirection {
    case up
    case down
}

/// Last reported frames of the current lesson's key and the most visible
/// week. A reference type so updating it while scrolling does not
/// invalidate the view.
private final class LessonPathScrollTracking {
    var activeLessonFrame: LessonVisibleLessonFrame?
    var visibleWeekID: String?
}

struct LessonPathWeek: Identifiable, Equatable {
    let level: LessonLevel
    let stage: Int
    let week: Int
    let stageName: String
    let lessons: [LessonPayload]

    var id: String {
        "\(level.rawValue)-stage-\(stage)-week-\(week)"
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
    static let headerHeight: CGFloat = 64
    static let scrollCoordinateSpace = "lesson-path-scroll"
}

private struct LessonPathHeader: View {
    let lessonNumber: Int?

    var body: some View {
        HStack(alignment: .center) {
            SvenskaWordmark(size: 34)

            Spacer()

            CounterWheels(digits: Self.digits(for: lessonNumber), size: 24, prefix: "DAG")
                .accessibilityElement(children: .ignore)
            .accessibilityLabel(lessonNumber.map { "Dag \($0)" } ?? "Dag")
        }
        .frame(height: LessonPathStyle.headerHeight - 10)
    }

    private static func digits(for number: Int?) -> [String] {
        let text = number.map { String(format: "%03d", $0) } ?? "---"
        return text.map(String.init)
    }
}

/// One week as a row of a step sequencer: a near-black module with the level
/// tag and week number, and seven step keys with a lamp above each.
private struct LessonPathWeekSection: View {
    let week: LessonPathWeek
    let weekNumber: Int?
    let activeLessonID: String?
    let lessonNumbers: [String: Int]
    @ObservedObject var sessionStore: LessonSessionStore
    let onLessonTap: (LessonPayload) -> Void
    let onMarkLessonComplete: (LessonPayload) -> Void
    let onMarkWeekComplete: (LessonPathWeek) -> Void

    private static let stepsPerRow = 7

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                LessonLevelTag(level: week.level)
                Text(weekNumber.map { "VECKA \($0)" } ?? "VECKA")
                    .font(RetroFont.label(12))
                    .tracking(1.4)
                    .foregroundStyle(Retro.labelOnDarkSoft)
                Spacer()
            }
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isHeader)

            HStack(spacing: 6) {
                ForEach(week.lessons) { lesson in
                    LessonPathStep(
                        lesson: lesson,
                        number: lessonNumbers[lesson.id],
                        state: sessionStore.state(for: lesson.id),
                        isWeekCompleted: week.lessons.allSatisfy { sessionStore.state(for: $0.id).isCompleted },
                        isActive: lesson.id == activeLessonID,
                        onTap: {
                            onLessonTap(lesson)
                        },
                        onMarkLessonComplete: {
                            onMarkLessonComplete(lesson)
                        },
                        onMarkWeekComplete: {
                            onMarkWeekComplete(week)
                        }
                    )
                    .id(lesson.id)
                }
                ForEach(week.lessons.count..<max(week.lessons.count, Self.stepsPerRow), id: \.self) { _ in
                    Color.clear.frame(maxWidth: .infinity)
                }
            }
        }
        .retroRecess(cornerRadius: 10, padding: 12)
        // The whole module drawn as one layer: its keys, lamps, screws and
        // stacked shadows are too costly to composite piece by piece while
        // the path scrolls. The margin keeps glows and drop shadows inside
        // the layer.
        .padding(6)
        .drawingGroup()
        .padding(-6)
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
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

/// Step key with its lamp: amber when the lesson is done, rust on the current
/// lesson, dark ahead.
private struct LessonPathStep: View {
    let lesson: LessonPayload
    let number: Int?
    let state: LessonState
    let isWeekCompleted: Bool
    let isActive: Bool
    let onTap: () -> Void
    let onMarkLessonComplete: () -> Void
    let onMarkWeekComplete: () -> Void

    private var tint: RetroKeyTint {
        if isActive { return .accent }
        if state.isCompleted { return .bone }
        return .graphite
    }

    var body: some View {
        VStack(spacing: 7) {
            lamp

            Button(action: onTap) {
                VStack(spacing: 1) {
                    Text(number.map(String.init) ?? "–")
                        .font(RetroFont.digits(isActive ? 17 : 15))
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                    if isActive {
                        Text("SPELA")
                            .font(RetroFont.label(7.5))
                            .tracking(0.6)
                    }
                }
                .opacity(state.isCompleted || isActive ? 1 : 0.7)
            }
            .buttonStyle(RetroKeyStyle(tint: tint, cornerRadius: 5, edge: 3))
            .frame(height: 50)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
        .accessibilityAddTraits(.isButton)
        .background {
            // Only the current lesson reports where it is, for the jump key.
            if isActive {
                GeometryReader { proxy in
                    Color.clear.preference(
                        key: LessonVisibleLessonPreferenceKey.self,
                        value: [
                            LessonVisibleLessonFrame(
                                id: lesson.id,
                                minY: proxy.frame(in: .named(LessonPathStyle.scrollCoordinateSpace)).minY,
                                maxY: proxy.frame(in: .named(LessonPathStyle.scrollCoordinateSpace)).maxY
                            )
                        ]
                    )
                }
            }
        }
        .contextMenu {
            Button {
                onMarkLessonComplete()
            } label: {
                Label("Markera lektionen som klar", systemImage: "checkmark.circle")
            }
            .disabled(state.isCompleted)

            Button {
                onMarkWeekComplete()
            } label: {
                Label("Markera veckan som klar", systemImage: "checkmark.circle.fill")
            }
            .disabled(isWeekCompleted)
        }
    }

    private var lamp: some View {
        let color: Color? = isActive ? Retro.accent.mix(with: Retro.amber, by: 0.35) : (state.isCompleted ? Retro.amber : nil)
        return Circle()
            .fill(color ?? Color(white: 0.16))
            .frame(width: 6, height: 6)
            .overlay(Circle().stroke(Color.black.opacity(0.6), lineWidth: 1))
            .shadow(color: (color ?? .clear).opacity(0.8), radius: 3)
    }

    private var accessibilityText: String {
        let base = "Lektion \(number.map(String.init) ?? "")"
        if state.isCompleted { return base + ", klar" }
        if isActive { return base + ", nästa" }
        return base
    }
}

/// Small bone plate with the course level, at the start of each week row.
private struct LessonLevelTag: View {
    let level: LessonLevel

    var body: some View {
        Text(level.rawValue)
            .font(RetroFont.label(10))
            .tracking(0.8)
            .foregroundStyle(Retro.ink)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(Retro.bone.shadow(.inner(color: .white.opacity(0.4), radius: 0.5, y: 0.5)))
            )
            .shadow(color: .black.opacity(0.5), radius: 1, y: 1)
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

private struct LessonVisibleLessonFrame: Equatable {
    let id: String
    let minY: CGFloat
    let maxY: CGFloat
}

private struct LessonVisibleLessonPreferenceKey: PreferenceKey {
    static var defaultValue: [LessonVisibleLessonFrame] = []

    static func reduce(value: inout [LessonVisibleLessonFrame], nextValue: () -> [LessonVisibleLessonFrame]) {
        value.append(contentsOf: nextValue())
    }
}

struct LessonDetailView: View {
    let payload: LessonPayload
    let lessonNumber: Int?
    @ObservedObject var generationStore: LessonGenerationStore
    @ObservedObject var sessionStore: LessonSessionStore
    // Audio progress changes several times per second. The enclosing lesson view
    // does not render that progress itself, so observing it here needlessly
    // invalidates the chat and selectable dialogue text during playback.
    let audioPlayer: AudioPlayerController

    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase

    @State private var isGeneratingLesson = false
    @State private var chatVisibleHeight: CGFloat = 0
    @State private var isSending = false
    @State private var draft = ""
    @State private var errorMessage: String?
    @State private var showRegenerateConfirmation = false
    @State private var expandedPanel: LessonPanel?
    @State private var dialogueScrollOffsetY: CGFloat = 0
    @State private var shouldFlashDialogButton = false
    @State private var isRequestingTranslationQuiz = false
    @State private var isSpeakingPracticePresented = false
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

    private var isLessonAudioReady: Bool {
        audioAvailability.isReady
    }

    private var audioAvailability: LessonAudioAvailability {
        sessionStore.audioAvailability(for: payload.id)
    }

    private var shouldOfferTranslationQuiz: Bool {
        lessonState.translationQuiz == nil &&
            lessonState.phase == .discussion &&
            !isLessonFlowFinished
    }

    /// A lesson marked complete from the path before it was played still
    /// runs its questions; only one that reached the translations is done.
    private var isLessonFlowFinished: Bool {
        lessonState.isCompleted && lessonState.translationQuiz != nil
    }

    private var isComprehensionComplete: Bool {
        switch lessonState.phase {
        case .discussion, .translation, .completed:
            return true
        case .notStarted, .generated, .listening, .comprehension:
            return false
        }
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
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
        .onAppear {
            loadExistingAudio()
            Task {
                await sessionStore.reconcileLessonAudio(lessonID: payload.id)
            }
        }
        .onDisappear {
            sessionStore.cancelLessonAudioReconciliation(lessonID: payload.id)
        }
        .onChange(of: audioAvailability) { _, availability in
            loadExistingAudio()
            if availability.isReady, let generatedLesson {
                appendInitialQuestionMessageIfNeeded(for: generatedLesson)
            }
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active, generatedLesson != nil else { return }
            Task {
                await sessionStore.reconcileLessonAudio(lessonID: payload.id)
            }
        }
        .confirmationDialog(
            "Skapa en ny dialog?",
            isPresented: $showRegenerateConfirmation,
            titleVisibility: .visible
        ) {
            Button("Ny dialog", role: .destructive) {
                Task {
                    await generateLesson(replacingExisting: true)
                }
            }
            Button("Avbryt", role: .cancel) {}
        } message: {
            Text("Dialogen och frågorna byts ut. Chatten och ljudet för den här lektionen nollställs.")
        }
        .fullScreenCover(isPresented: $isSpeakingPracticePresented) {
            if let generatedLesson {
                SpeakingPracticeView(
                    payload: payload,
                    generatedLesson: generatedLesson,
                    sessionStore: sessionStore
                )
            }
        }
    }

    private var preGenerationView: some View {
        VStack(spacing: 22) {
            LessonBackControlRow {
                dismiss()
            }

            Spacer()

            VStack(spacing: 18) {
                CassetteView(isPlaying: isGeneratingLesson, label: cassetteLabel, width: 250)
                    .padding(.vertical, 8)

                AmberReadout(text: isGeneratingLesson ? "SPELAR IN…" : "TOMT BAND", size: 14)
            }

            lessonActionSection
                .padding(.horizontal, 24)

            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(Retro.paper)
                    .padding(12)
                    .background(Retro.accent.opacity(0.85))
                    .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            }

            Spacer()
            Spacer()
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .retroScreenBackground()
    }

    private var cassetteLabel: String {
        lessonNumber.map { "Lektion \($0)" } ?? "Svenska"
    }

    private func generatedLessonExperience(_ generatedLesson: GeneratedLesson) -> some View {
        GeometryReader { _ in
            VStack(spacing: 0) {
                VStack(spacing: 8) {
                    LessonTopControlBar(
                        selection: $expandedPanel,
                        shouldFlashDialogButton: shouldFlashDialogButton,
                        areLessonControlsEnabled: isLessonAudioReady,
                        isMenuEnabled: true
                    ) {
                        dismiss()
                    }
                        .simultaneousGesture(TapGesture().onEnded {
                            dismissKeyboard()
                        })

                    // Transport controls leave the keyboard up so the
                    // learner can replay audio while writing an answer.
                    LessonInlineAudioPlayer(
                        audioPlayer: audioPlayer,
                        availability: audioAvailability,
                        cassetteLabel: cassetteLabel,
                        onGenerateOrRetry: {
                            Task { await generateAudio() }
                        }
                    )

                    if expandedPanel == .menu {
                        lessonExpandedPanel(.menu, generatedLesson: generatedLesson)
                            .simultaneousGesture(TapGesture().onEnded {
                                dismissKeyboard()
                            })
                            .transition(.opacity.combined(with: .move(edge: .top)))
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 10)
                .padding(.bottom, 10)

                // Dialogue and practice sheets sit above the chat paper; the
                // dialogue takes half of the paper area, the chat the other half.
                if let expandedPanel, expandedPanel != .menu {
                    lessonExpandedPanel(expandedPanel, generatedLesson: generatedLesson)
                        .frame(maxHeight: expandedPanel == .dialogue ? .infinity : nil)
                        .padding(.horizontal, 16)
                        .padding(.bottom, 14)
                        .simultaneousGesture(TapGesture().onEnded {
                            dismissKeyboard()
                        })
                        .transition(.opacity)
                }

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 18) {
                            if let errorMessage {
                                Text(errorMessage)
                                    .font(.footnote)
                                    .foregroundStyle(Retro.pencilRed)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }

                            if messages.isEmpty && isLessonAudioReady {
                                LessonStageHeading(stage: .questions)
                                LessonAssistantOpening(
                                    firstQuestion: generatedLesson.comprehensionQuestions.first,
                                    onTranslateSelection: sendTranslationRequest
                                )
                            }

                            ForEach(chatRows, id: \.message.id) { row in
                                if let heading = row.heading {
                                    LessonStageHeading(stage: heading)
                                }
                                LessonChatMessageRow(
                                    message: row.message,
                                    onTranslateSelection: sendTranslationRequest
                                )
                                    .id(row.message.id)
                            }

                            if isSending || isRequestingTranslationQuiz {
                                LessonTypingIndicatorRow()
                            }

                            Color.clear
                                .frame(height: 4)
                                .id("lesson-chat-bottom")
                        }
                        .modifier(PaperChatSurface(visibleHeight: chatVisibleHeight - 2))
                        .padding(.horizontal, 18)
                        .padding(.top, 2)
                    }
                    .onVisibleHeightChange { chatVisibleHeight = $0 }
                    .scrollBounceBehavior(.basedOnSize)
                    .scrollIndicators(.hidden)
                    .paperRoller()
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
                    .onChange(of: isChatFocused) { _, isFocused in
                        guard isFocused else { return }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
                            withAnimation {
                                proxy.scrollTo("lesson-chat-bottom", anchor: .bottom)
                            }
                        }
                    }
                }
                .frame(maxHeight: .infinity)
            }
        }
        .retroScreenBackground()
        .safeAreaInset(edge: .bottom, spacing: 0) {
            LessonChatInputBar(
                draft: $draft,
                isSending: isSending || isRequestingTranslationQuiz,
                isEnabled: isLessonAudioReady,
                canAdvanceLessonStep: canAdvanceLessonStep,
                nextStepAccessibilityLabel: nextStepAccessibilityLabel,
                isFocused: $isChatFocused,
                onNextQuestion: {
                    collapseExpandedPanel()
                    Task {
                        await advanceLessonStep()
                    }
                },
                onSend: {
                    collapseExpandedPanel()
                    Task {
                        await sendTutorMessage(draft)
                    }
                }
            )
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 4)
            // Taps on the bare ledge close an open sheet; the text field
            // handles its own taps, so writing keeps the dialogue open.
            .background {
                Color.clear
                    .contentShape(Rectangle())
                    .onTapGesture {
                        collapseExpandedPanel()
                    }
            }
            .retroBottomBacking()
        }
        .onChange(of: expandedPanel) { _, panel in
            if panel == .dialogue {
                shouldFlashDialogButton = false
            }
        }
        .toolbar(.hidden, for: .tabBar)
    }

    private func lessonExpandedPanel(_ panel: LessonPanel, generatedLesson: GeneratedLesson) -> some View {
        LessonExpandedPanel(
            panel: panel,
            payload: payload,
            generatedLesson: generatedLesson,
            lessonState: lessonState,
            dialogueScrollOffsetY: $dialogueScrollOffsetY,
            isGeneratingLesson: isGeneratingLesson,
            audioAvailability: audioAvailability,
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
            },
            onSpeakingPractice: {
                audioPlayer.stopPlayback()
                collapseExpandedPanel()
                isSpeakingPracticePresented = true
            },
            onTranslateSelection: { selection in
                sendTranslationRequest(selection)
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

    private var lessonActionSection: some View {
        Button {
            Task {
                await generateLesson(replacingExisting: false)
            }
        } label: {
            if isGeneratingLesson {
                ProgressView().tint(Retro.paper)
            } else {
                RetroKeyLabel(title: "Skapa lektion", systemImage: "recordingtape", titleSize: 15)
            }
        }
        .buttonStyle(RetroKeyStyle(tint: .accent))
        .frame(height: 70)
        .disabled(isGeneratingLesson)
    }

    private var currentAudioURL: URL? {
        guard case .ready(let fileURL, _) = audioAvailability else { return nil }
        return fileURL
    }

    private func generateLesson(replacingExisting: Bool) async {
        if !replacingExisting, let generatedLesson, currentAudioURL == nil {
            await generateAudio(for: generatedLesson)
            return
        }

        let model = OpenAIModelDefaults.lessonGenerator.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonGeneratorReasoningEffort

        isGeneratingLesson = true
        errorMessage = nil
        defer { isGeneratingLesson = false }

        do {
            if replacingExisting {
                await sessionStore.uploadDirtySessions()
                let context = try sessionStore.beginRegeneration(lessonID: payload.id)
                let result = try await OpenAITutorService.regenerateLesson(
                    payload: payload,
                    operationKey: context.operationKey,
                    baseServerUpdatedAt: context.baseServerUpdatedAt
                )
                generationStore.save(result.lesson)
                sessionStore.adoptRegeneratedSession(result.session)
                dialogueScrollOffsetY = 0
                await sessionStore.reconcileLessonAudio(
                    lessonID: result.lesson.lessonID,
                    requestIfMissing: false
                )
                if case .ready(let fileURL, _) = sessionStore.audioAvailability(for: result.lesson.lessonID) {
                    appendInitialQuestionMessageIfNeeded(for: result.lesson)
                    audioPlayer.load(url: fileURL)
                }
                return
            }

            let lesson = try await OpenAITutorService.generateLesson(
                payload: payload,
                model: model,
                reasoningEffort: reasoningEffort,
                privateAlternative: false
            )

            generationStore.save(lesson)
            sessionStore.markGenerated(lessonID: payload.id)
            dialogueScrollOffsetY = 0
            await generateAudio(for: lesson)
        } catch BackendError.lessonSessionConflict(let current) {
            if let currentLesson = current.generatedLesson {
                generationStore.save(currentLesson)
            }
            sessionStore.adoptSessionAfterRegenerationConflict(current)
            errorMessage = "The lesson changed on another device. Please try again."
        } catch {
            errorMessage = "Something went wrong. Please try again."
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
        errorMessage = nil
        await sessionStore.uploadDirtySessions()
        await sessionStore.requestLessonAudio(lessonID: lesson.lessonID)
        if case .ready(let fileURL, _) = sessionStore.audioAvailability(for: lesson.lessonID) {
            appendInitialQuestionMessageIfNeeded(for: lesson)
            audioPlayer.load(url: fileURL)
        }
    }

    private func resetChatAndProgress() {
        sessionStore.resetChatAndProgressForGeneratedLesson(lessonID: payload.id)
        if let generatedLesson {
            appendInitialQuestionMessageIfNeeded(for: generatedLesson)
        }
        draft = ""
        errorMessage = nil
    }

    private var canAdvanceLessonStep: Bool {
        guard let generatedLesson else { return false }
        guard isLessonAudioReady else { return false }
        guard !isLessonFlowFinished else { return false }
        if lessonState.translationQuiz != nil {
            return hasResponseForActiveTranslationSentence
        }
        if lessonState.phase == .discussion {
            return true
        }
        return hasResponseForActiveComprehensionQuestion(in: generatedLesson)
    }

    private var nextStepAccessibilityLabel: String {
        if let activeTranslationSentence {
            return activeTranslationSentence.index == activeTranslationSentence.count - 1
                ? "Avsluta lektionen"
                : "Nästa mening"
        }
        guard let generatedLesson else { return "Nästa fråga" }
        if lessonState.phase == .discussion {
            return "Börja översättningen"
        }
        if nextQuestionAfterCurrent(in: generatedLesson) == nil {
            return "Diskutera dialogen"
        }
        return "Nästa fråga"
    }

    private var activeTranslationSentence: (index: Int, count: Int, sentence: String)? {
        guard let quiz = lessonState.translationQuiz, !quiz.sentencesEN.isEmpty else { return nil }
        let index = min(max(lessonState.currentTranslationIndex ?? 0, 0), quiz.sentencesEN.count - 1)
        return (index, quiz.sentencesEN.count, quiz.sentencesEN[index])
    }

    private var hasResponseForActiveTranslationSentence: Bool {
        guard let activeTranslationSentence else { return false }
        let prompt = translationPromptText(
            index: activeTranslationSentence.index,
            count: activeTranslationSentence.count,
            sentence: activeTranslationSentence.sentence
        )
        return hasUserMessageAfterPrompt { message in
            message.content == prompt
        }
    }

    private func hasResponseForActiveComprehensionQuestion(in generatedLesson: GeneratedLesson) -> Bool {
        guard let currentIndex = currentQuestionIndex(in: generatedLesson) else { return false }
        let prompt = questionPromptText(
            for: generatedLesson.comprehensionQuestions[currentIndex],
            in: generatedLesson
        )
        return hasUserMessageAfterPrompt { message in
            message.content.hasSuffix(prompt)
        }
    }

    private func hasUserMessageAfterPrompt(
        matchingPrompt: (LessonChatMessage) -> Bool
    ) -> Bool {
        guard let promptIndex = messages.lastIndex(where: { message in
            message.role == .assistant && matchingPrompt(message)
        }) else {
            return false
        }
        return messages[messages.index(after: promptIndex)...].contains { message in
            message.role == .user &&
                !message.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    private func currentQuestionIndex(in generatedLesson: GeneratedLesson) -> Int? {
        if let currentQuestionID = lessonState.currentQuestionID,
           let index = generatedLesson.comprehensionQuestions.firstIndex(where: { $0.id == currentQuestionID }) {
            return index
        }
        return generatedLesson.comprehensionQuestions.isEmpty ? nil : 0
    }

    private func nextQuestionAfterCurrent(in generatedLesson: GeneratedLesson) -> GeneratedQuestion? {
        guard let currentIndex = currentQuestionIndex(in: generatedLesson) else { return nil }
        let nextIndex = currentIndex + 1
        guard generatedLesson.comprehensionQuestions.indices.contains(nextIndex) else {
            return nil
        }
        return generatedLesson.comprehensionQuestions[nextIndex]
    }

    private func advanceLessonStep() async {
        guard !isSending, !isRequestingTranslationQuiz else { return }
        guard let generatedLesson else {
            errorMessage = "Generate the lesson before chatting."
            return
        }
        guard canAdvanceLessonStep else { return }

        if lessonState.translationQuiz != nil {
            advanceTranslationStep()
            return
        }

        if lessonState.phase == .discussion {
            shouldFlashDialogButton = false
            await requestTranslationQuizIfNeeded()
            return
        }

        appendInitialQuestionMessageIfNeeded(for: generatedLesson)

        if let nextQuestion = nextQuestionAfterCurrent(in: generatedLesson) {
            sessionStore.setCurrentQuestion(nextQuestion.id, lessonID: payload.id)
            sessionStore.appendMessage(
                LessonChatMessage(
                    lessonID: payload.id,
                    role: .assistant,
                    content: questionPromptText(for: nextQuestion, in: generatedLesson)
                )
            )
        } else if lessonState.phase != .discussion {
            sessionStore.startDiscussion(lessonID: payload.id)
            shouldFlashDialogButton = expandedPanel != .dialogue
            sessionStore.appendMessage(
                LessonChatMessage(
                    lessonID: payload.id,
                    role: .assistant,
                    content: dialogueDiscussionPromptText
                )
            )
        }
    }

    private func advanceTranslationStep() {
        guard let activeTranslationSentence else { return }
        let nextIndex = activeTranslationSentence.index + 1

        if nextIndex < activeTranslationSentence.count,
           let quiz = lessonState.translationQuiz {
            sessionStore.setCurrentTranslationIndex(nextIndex, lessonID: payload.id)
            sessionStore.appendMessage(
                LessonChatMessage(
                    lessonID: payload.id,
                    role: .assistant,
                    content: translationPromptText(
                        index: nextIndex,
                        count: activeTranslationSentence.count,
                        sentence: quiz.sentencesEN[nextIndex]
                    )
                )
            )
        } else {
            sessionStore.markCompleted(lessonID: payload.id)
            sessionStore.appendMessage(
                LessonChatMessage(
                    lessonID: payload.id,
                    role: .assistant,
                    content: "Klart. Lektionen är markerad som färdig."
                )
            )
        }
    }

    private func questionPromptText(for question: GeneratedQuestion, in generatedLesson: GeneratedLesson) -> String {
        let index = generatedLesson.comprehensionQuestions.firstIndex { $0.id == question.id } ?? 0
        return "Fråga \(index + 1): **\(question.questionSV)**"
    }

    private func openingQuestionPromptText(for question: GeneratedQuestion, in generatedLesson: GeneratedLesson) -> String {
        "Lyssna på lektionens ljud och svara sedan på förståelsefrågorna här. Du kan också fråga om ord eller grammatik från dialogen.\n\n\(questionPromptText(for: question, in: generatedLesson))"
    }

    private func appendInitialQuestionMessageIfNeeded(for generatedLesson: GeneratedLesson) {
        guard messages.isEmpty,
              let firstQuestion = generatedLesson.comprehensionQuestions.first else {
            return
        }

        sessionStore.appendMessage(
            LessonChatMessage(
                lessonID: payload.id,
                role: .assistant,
                content: openingQuestionPromptText(for: firstQuestion, in: generatedLesson)
            )
        )
    }

    private func translationPromptText(index: Int, count: Int, sentence: String) -> String {
        "Översätt \(index + 1)/\(count): **\(sentence)**"
    }

    private var dialogueDiscussionPromptText: String {
        LessonChatStage.discussionPrompt
    }

    /// Messages paired with the stage heading that starts before them, if any.
    private var chatRows: [(message: LessonChatMessage, heading: LessonChatStage?)] {
        var rows: [(message: LessonChatMessage, heading: LessonChatStage?)] = messages.map { ($0, nil) }
        var currentStage = LessonChatStage.opening
        for index in rows.indices {
            let message = rows[index].message
            guard message.role == .assistant,
                  let stage = LessonChatStage(tutorMessage: message.content),
                  stage > currentStage else {
                continue
            }
            currentStage = stage
            // The first translation prompt is posted right after the tutor's
            // reply that set up the quiz, so that reply opens the stage.
            if stage == .translation, index > 0, rows[index - 1].message.role == .assistant {
                rows[index - 1].heading = stage
            } else {
                rows[index].heading = stage
            }
        }
        return rows
    }

    private func requestStateForTutorMessage(generatedLesson: GeneratedLesson) -> LessonState {
        var state = lessonState
        guard state.translationQuiz == nil, !isLessonFlowFinished else { return state }

        switch state.phase {
        case .notStarted, .generated, .listening, .comprehension:
            let questionID = state.currentQuestionID ?? generatedLesson.comprehensionQuestions.first?.id
            if let questionID {
                sessionStore.setCurrentQuestion(questionID, lessonID: payload.id)
                state = sessionStore.state(for: payload.id)
            }
        case .discussion, .translation, .completed:
            break
        }

        return state
    }

    private func sendTutorMessage(
        _ message: String,
        translationLookup: TranslationLookupMetadata? = nil
    ) async {
        let trimmedMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = OpenAIModelDefaults.lessonInteractor.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonInteractorReasoningEffort

        guard let generatedLesson else {
            errorMessage = "Generate the lesson before chatting."
            return
        }

        guard isLessonAudioReady else { return }

        guard !trimmedMessage.isEmpty else {
            return
        }

        dismissKeyboard()
        let requestState = requestStateForTutorMessage(generatedLesson: generatedLesson)
        let translationAttemptIndex = requestState.phase == .translation ? activeTranslationSentence?.index : nil

        if trimmedMessage == draft.trimmingCharacters(in: .whitespacesAndNewlines) {
            draft = ""
        }
        errorMessage = nil
        isSending = true
        appendInitialQuestionMessageIfNeeded(for: generatedLesson)
        sessionStore.appendMessage(
            LessonChatMessage(lessonID: payload.id, role: .user, content: trimmedMessage)
        )
        let chatHistory = sessionStore.messages(for: payload.id)

        do {
            let response = try await OpenAITutorService.sendLessonMessage(
                payload: payload,
                generatedLesson: generatedLesson,
                state: requestState,
                chatHistory: chatHistory,
                latestUserMessage: trimmedMessage,
                model: model,
                reasoningEffort: reasoningEffort,
                translationLookup: translationLookup
            )
            try sessionStore.apply(response: response, generatedLesson: generatedLesson)
            if let translationAttemptIndex {
                sessionStore.appendTranslationAttempt(
                    sentenceIndex: translationAttemptIndex,
                    answer: trimmedMessage,
                    lessonID: payload.id
                )
            }
            sessionStore.appendMessage(
                LessonChatMessage(lessonID: payload.id, role: .assistant, content: response.assistantText)
            )
        } catch {
            errorMessage = error.localizedDescription
        }
        isSending = false
    }

    private func sendTranslationRequest(_ selection: String) {
        guard isLessonAudioReady, !isSending, !isRequestingTranslationQuiz else { return }
        let lookup = TranslationLookupMetadata(
            selectedText: selection.trimmingCharacters(in: .whitespacesAndNewlines),
            sourceKind: "lesson",
            sourceID: payload.id,
            sourceSurface: expandedPanel?.lookupSurface ?? "lesson_chat",
            surroundingText: nil,
            visibleCourseLevel: payload.courseLevel.rawValue,
            createdAt: Date()
        )
        Task {
            await sendTutorMessage(
                translationRequestMessage(for: selection),
                translationLookup: lookup
            )
        }
    }

    private func requestTranslationQuizIfNeeded() async {
        guard shouldOfferTranslationQuiz, !isRequestingTranslationQuiz, !isSending else { return }
        guard let generatedLesson else { return }

        let model = OpenAIModelDefaults.lessonInteractor.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonInteractorReasoningEffort

        let latestUserMessage = "SYSTEM_UI_ACTION: start_translation_quiz"
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
                model: model,
                reasoningEffort: reasoningEffort
            )
            try sessionStore.apply(response: response, generatedLesson: generatedLesson)
            sessionStore.appendMessage(
                LessonChatMessage(lessonID: payload.id, role: .assistant, content: response.assistantText)
            )
            if let quiz = response.translationQuiz,
               let firstSentence = quiz.sentencesEN.first {
                sessionStore.appendMessage(
                    LessonChatMessage(
                        lessonID: payload.id,
                        role: .assistant,
                        content: translationPromptText(
                            index: 0,
                            count: quiz.sentencesEN.count,
                            sentence: firstSentence
                        )
                    )
                )
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func loadExistingAudio() {
        guard let audioURL = currentAudioURL else { return }
        audioPlayer.load(url: audioURL)
    }
}

private enum LessonPanel: CaseIterable, Identifiable, Hashable {
    case dialogue
    case practice
    case menu

    var id: Self { self }

    var title: String {
        switch self {
        case .dialogue:
            return "Dialog"
        case .practice:
            return "Öva"
        case .menu:
            return "Meny"
        }
    }

    var keyTitle: String? {
        switch self {
        case .dialogue, .practice:
            return title
        case .menu:
            return nil
        }
    }

    var keyImage: String? {
        switch self {
        case .dialogue, .practice:
            return nil
        case .menu:
            return "ellipsis"
        }
    }

    var lookupSurface: String {
        switch self {
        case .dialogue:
            return "generated_dialogue"
        case .practice:
            return "lesson_practice_panel"
        case .menu:
            return "lesson_menu"
        }
    }
}

private struct LessonBackControlRow: View {
    let onBack: () -> Void

    var body: some View {
        HStack {
            LessonTopControlButton(
                systemImage: "arrow.left",
                isSelected: false,
                isFlashing: false,
                accessibilityLabel: "Tillbaka",
                action: onBack
            )
            .frame(width: 58)

            Spacer()
        }
    }
}

private struct LessonTopControlBar: View {
    @Binding var selection: LessonPanel?
    let shouldFlashDialogButton: Bool
    let areLessonControlsEnabled: Bool
    let isMenuEnabled: Bool
    let onBack: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            LessonTopControlButton(
                systemImage: "arrow.left",
                isSelected: false,
                isFlashing: false,
                isEnabled: true,
                accessibilityLabel: "Tillbaka",
                action: onBack
            )
            .frame(width: 52)

            ForEach(LessonPanel.allCases) { panel in
                LessonTopControlButton(
                    title: panel.keyTitle,
                    systemImage: panel.keyImage,
                    isSelected: selection == panel,
                    isFlashing: areLessonControlsEnabled && panel == .dialogue && shouldFlashDialogButton,
                    isEnabled: panel == .menu ? isMenuEnabled : areLessonControlsEnabled,
                    accessibilityLabel: panel.title
                ) {
                    withAnimation(.snappy(duration: 0.22)) {
                        selection = selection == panel ? nil : panel
                    }
                }
                .frame(width: panel == .menu ? 52 : nil)
            }
        }
        .retroRecess(cornerRadius: 8, padding: 6)
    }
}

/// Low typewriter-height key for the lesson/practice top strip. Selected keys
/// latch down in the accent.
struct LessonTopControlButton: View {
    let title: String?
    let systemImage: String?
    let isSelected: Bool
    let isFlashing: Bool
    let isEnabled: Bool
    let accessibilityLabel: String
    let action: () -> Void

    init(
        title: String? = nil,
        systemImage: String? = nil,
        isSelected: Bool,
        isFlashing: Bool,
        isEnabled: Bool = true,
        accessibilityLabel: String,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.systemImage = systemImage
        self.isSelected = isSelected
        self.isFlashing = isFlashing
        self.isEnabled = isEnabled
        self.accessibilityLabel = accessibilityLabel
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            RetroKeyLabel(title: title, systemImage: systemImage, titleSize: 12, imageSize: 15)
        }
        .buttonStyle(RetroKeyStyle(tint: isSelected ? .accent : .graphite, isLatched: isSelected, cornerRadius: 5, edge: 3))
        .frame(maxWidth: .infinity)
        .frame(height: 38)
        .overlay {
            if isFlashing, !isSelected {
                TimelineView(.animation) { context in
                    RoundedRectangle(cornerRadius: 5, style: .continuous)
                        .stroke(Retro.amber.opacity(0.25 + 0.6 * flashIntensity(at: context.date)), lineWidth: 2)
                        .padding(.bottom, 3)
                }
                .allowsHitTesting(false)
            }
        }
        .disabled(!isEnabled)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private func flashIntensity(at date: Date) -> Double {
        let period = 1.3
        let phase = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: period) / period
        return phase < 0.5 ? phase * 2 : (1 - phase) * 2
    }
}

/// Tape-head strip for the lesson audio: a window onto the cassette reels, a
/// 5-second rewind key, the amber time readout over an LED progress strip,
/// and the play key.
private struct LessonInlineAudioPlayer: View {
    @ObservedObject var audioPlayer: AudioPlayerController
    let availability: LessonAudioAvailability
    let cassetteLabel: String
    let onGenerateOrRetry: () -> Void

    private var fileURL: URL? {
        guard case .ready(let url, _) = availability else { return nil }
        return url
    }

    private var hasAudio: Bool {
        fileURL != nil
    }

    private var progress: Double {
        guard audioPlayer.duration > 0 else { return 0 }
        return min(max(audioPlayer.currentTime / audioPlayer.duration, 0), 1)
    }

    var body: some View {
        HStack(spacing: 10) {
            CassetteReelWindow(isPlaying: audioPlayer.isPlaying, width: 104)

            Button {
                audioPlayer.seek(to: max(audioPlayer.currentTime - 5, 0))
            } label: {
                Image(systemName: "gobackward.5")
                    .font(.system(size: 16, weight: .semibold))
            }
            .buttonStyle(RetroKeyStyle(tint: .graphite, cornerRadius: 5, edge: 3))
            .frame(width: 40, height: 48)
            .disabled(!hasAudio)
            .accessibilityLabel("Spola tillbaka 5 sekunder")

            VStack(alignment: .leading, spacing: 7) {
                readout
                if hasAudio {
                    progressStrip
                } else if !availability.isInFlight {
                    Button(action: onGenerateOrRetry) {
                        Text(recoveryActionTitle)
                            .font(RetroFont.label(10))
                            .padding(.horizontal, 6)
                    }
                    .buttonStyle(RetroKeyStyle(tint: .graphite, cornerRadius: 4, edge: 2))
                    .frame(height: 24)
                    .fixedSize()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button {
                audioPlayer.togglePlayback()
            } label: {
                Image(systemName: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 20, weight: .heavy))
            }
            .buttonStyle(RetroKeyStyle(tint: .accent, isLatched: audioPlayer.isPlaying, cornerRadius: 6, edge: 4))
            .frame(width: 50, height: 48)
            .disabled(!hasAudio)
            .accessibilityLabel(audioPlayer.isPlaying ? "Pausa ljudet" : "Spela ljudet")
        }
        .retroRecess(cornerRadius: 10, padding: 10)
    }

    private var readout: some View {
        HStack(spacing: 6) {
            if hasAudio {
                Text("\(audioPlayer.currentTime.lessonClockText) / \(audioPlayer.duration.lessonClockText)")
            } else {
                if availability.isInFlight {
                    ProgressView()
                        .controlSize(.mini)
                        .tint(Retro.amber)
                }
                Text(statusText)
            }
        }
        .font(RetroFont.digits(13))
        .foregroundStyle(Retro.amber)
        .shadow(color: Retro.amber.opacity(0.6), radius: 3)
        .lineLimit(1)
        .minimumScaleFactor(0.8)
    }

    private var progressStrip: some View {
        SegmentProgressBar(progress: progress, segments: 16, height: 8)
            .padding(.vertical, 6)
            .contentShape(Rectangle())
            .overlay {
                GeometryReader { proxy in
                    Color.clear
                        .contentShape(Rectangle())
                        .gesture(
                            DragGesture(minimumDistance: 0)
                                .onChanged { value in
                                    let fraction = min(max(value.location.x / max(proxy.size.width, 1), 0), 1)
                                    audioPlayer.beginScrubbing()
                                    audioPlayer.scrub(to: fraction * audioPlayer.duration)
                                }
                                .onEnded { _ in
                                    audioPlayer.endScrubbing()
                                }
                        )
                }
            }
            .accessibilityElement()
            .accessibilityLabel("Ljudposition")
            .accessibilityValue("\(audioPlayer.currentTime.lessonClockText) av \(audioPlayer.duration.lessonClockText)")
    }

    private var statusText: String {
        switch availability {
        case .queued:
            return "LJUDET KÖAS…"
        case .generating:
            return "SPELAR IN…"
        case .failed:
            return "LJUDFEL"
        case .missing, .ready:
            return "INGET LJUD"
        }
    }

    private var recoveryActionTitle: String {
        if case .failed = availability { return "FÖRSÖK IGEN" }
        return "SKAPA LJUD"
    }
}

private struct LessonExpandedPanel: View {
    let panel: LessonPanel
    let payload: LessonPayload
    let generatedLesson: GeneratedLesson
    let lessonState: LessonState
    @Binding var dialogueScrollOffsetY: CGFloat
    let isGeneratingLesson: Bool
    let audioAvailability: LessonAudioAvailability
    let isSending: Bool
    let isRequestingTranslationQuiz: Bool
    let onRegenerate: () -> Void
    let onRegenerateAudio: () -> Void
    let onResetProgress: () -> Void
    let onMarkComplete: () -> Void
    let onSpeakingPractice: () -> Void
    let onTranslateSelection: (String) -> Void

    var body: some View {
        switch panel {
        case .dialogue:
            PaperSheet {
                TranslatableTextView(
                    attributedText: dialogueAttributedText,
                    isScrollEnabled: true,
                    showsVerticalScrollIndicator: true,
                    contentOffsetY: $dialogueScrollOffsetY,
                    onTranslateSelection: onTranslateSelection
                )
                .frame(maxHeight: .infinity)
            }
        case .practice:
            PaperSheet {
                practiceContent
            }
        case .menu:
            menuContent
        }
    }

    private var practiceContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let quiz = lessonState.translationQuiz {
                VStack(alignment: .leading, spacing: 8) {
                    PaperCaption(text: "Översätt")
                    TranslatableTextView(
                        text: translationText(quiz),
                        textColor: Retro.uiInk,
                        font: RetroFont.readingUIFont(),
                        onTranslateSelection: onTranslateSelection
                    )
                }
            } else if isRequestingTranslationQuiz {
                HStack(spacing: 10) {
                    ProgressView()
                        .tint(Retro.ink)
                    Text("Förbereder översättningen…")
                        .font(RetroFont.reading(.subheadline))
                        .foregroundStyle(Retro.inkSoft)
                }
            }

            if lessonState.translationQuiz == nil {
                VStack(alignment: .leading, spacing: 8) {
                    PaperCaption(text: "Frågor")
                    TranslatableTextView(
                        text: comprehensionText,
                        textColor: Retro.uiInk,
                        font: RetroFont.readingUIFont(),
                        onTranslateSelection: onTranslateSelection
                    )
                }
            }
        }
    }

    private var dialogueAttributedText: NSAttributedString {
        let readingFont = RetroFont.readingUIFont()
        let nameFont = RetroFont.labelUIFont(11)
        let lineStyle = NSMutableParagraphStyle()
        lineStyle.paragraphSpacing = 14
        lineStyle.lineSpacing = 2
        let nameStyle = NSMutableParagraphStyle()
        nameStyle.paragraphSpacing = 2

        let result = NSMutableAttributedString()
        for (index, line) in generatedLesson.dialogue.enumerated() {
            result.append(NSAttributedString(
                string: line.speaker.rawValue.uppercased() + "\n",
                attributes: [.font: nameFont, .foregroundColor: Retro.uiInkAccent, .kern: 1.0, .paragraphStyle: nameStyle]
            ))
            let isLast = index == generatedLesson.dialogue.count - 1
            result.append(NSAttributedString(
                string: line.text + (isLast ? "" : "\n"),
                attributes: [.font: readingFont, .foregroundColor: Retro.uiInk, .paragraphStyle: lineStyle]
            ))
        }
        return result
    }

    private var comprehensionText: String {
        generatedLesson.comprehensionQuestions
            .enumerated()
            .map { index, question in "\(index + 1). \(question.questionSV)" }
            .joined(separator: "\n")
    }

    private func translationText(_ quiz: TranslationQuiz) -> String {
        guard !quiz.sentencesEN.isEmpty else { return "" }
        let index = min(max(lessonState.currentTranslationIndex ?? 0, 0), quiz.sentencesEN.count - 1)
        return "\(index + 1)/\(quiz.sentencesEN.count). \(quiz.sentencesEN[index])"
    }

    private var menuContent: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                Button(action: onSpeakingPractice) {
                    RetroKeyLabel(title: "Tala", systemImage: "phone.fill", subtitle: "Öva uttal", titleSize: 16)
                }
                .buttonStyle(RetroKeyStyle(tint: .accent))
                .disabled(isGeneratingLesson)

                Button(action: onRegenerate) {
                    RetroKeyLabel(title: "Ny dialog", systemImage: "arrow.triangle.2.circlepath", subtitle: "Skapa en ny", titleSize: 14)
                }
                .buttonStyle(RetroKeyStyle(tint: .graphite))
                .disabled(isGeneratingLesson)
            }
            .frame(height: 104)

            HStack(spacing: 10) {
                Button(action: onMarkComplete) {
                    RetroKeyLabel(
                        title: lessonState.isCompleted ? "Klar" : "Klar",
                        systemImage: lessonState.isCompleted ? "checkmark.seal.fill" : "checkmark",
                        subtitle: lessonState.isCompleted ? "Lektionen är klar" : "Markera som klar",
                        titleSize: 14
                    )
                }
                .buttonStyle(RetroKeyStyle(tint: .olive, isLatched: lessonState.isCompleted))
                .disabled(lessonState.isCompleted)

                Button(role: .destructive, action: onResetProgress) {
                    RetroKeyLabel(title: "Nollställ", systemImage: "arrow.counterclockwise", subtitle: "Börja om lektionen", titleSize: 13)
                }
                .buttonStyle(RetroKeyStyle(tint: .dark))
                .disabled(isSending || isGeneratingLesson)
            }
            .frame(height: 96)

            if !audioAvailability.isReady {
                Button(action: onRegenerateAudio) {
                    RetroKeyLabel(title: audioActionTitle, systemImage: "waveform", titleSize: 12)
                }
                .buttonStyle(RetroKeyStyle(tint: .bone))
                .frame(height: 50)
                .disabled(audioAvailability.isInFlight || isGeneratingLesson)
            }
        }
        .retroPanel(cornerRadius: 14, padding: 12)
    }

    private var audioActionTitle: String {
        switch audioAvailability {
        case .failed:
            return "Försök skapa ljud igen"
        case .missing:
            return "Skapa ljud"
        case .queued, .generating:
            return "Skapar ljud…"
        case .ready:
            return "Ljudet är klart"
        }
    }
}

/// Paper background for a chat timeline. Learning text stays undecorated.
/// Chat paper that always reaches the bottom bar: it fills the visible
/// scroll area and runs on under the bar, so no wood shows at the end.
struct PaperChatSurface: ViewModifier {
    var visibleHeight: CGFloat = 0
    private let tail: CGFloat = 40

    func body(content: Content) -> some View {
        PaperSheet(minHeight: visibleHeight + tail) {
            content
                .padding(.bottom, tail)
        }
        .padding(.bottom, -tail)
    }
}

extension ScrollView {
    /// Reports the scroll view's own height. Its frame already stops at the
    /// bottom bar, so the reported bottom inset is not subtracted.
    func onVisibleHeightChange(_ action: @escaping (CGFloat) -> Void) -> some View {
        onScrollGeometryChange(for: CGFloat.self) { geometry in
            geometry.containerSize.height
        } action: { _, height in
            action(height)
        }
    }
}

private struct LessonAssistantOpening: View {
    let firstQuestion: GeneratedQuestion?
    let onTranslateSelection: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            PaperCaption(text: "Läraren")
            TranslatableTextView(
                attributedText: openingText,
                onTranslateSelection: onTranslateSelection
            )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var openingText: NSAttributedString {
        let baseFont = RetroFont.readingUIFont()
        let boldFont = RetroFont.readingUIFont(weight: .bold)
        let result = NSMutableAttributedString(
            string: "Lyssna på lektionens ljud och svara sedan på förståelsefrågorna här. Du kan också fråga om ord eller grammatik från dialogen.",
            attributes: [
                .font: baseFont,
                .foregroundColor: Retro.uiInk
            ]
        )

        if let firstQuestion {
            result.append(NSAttributedString(string: "\n\n"))
            result.append(
                NSAttributedString(
                    string: "Fråga 1:\n",
                    attributes: [
                        .font: boldFont,
                        .foregroundColor: Retro.uiInk
                    ]
                )
            )
            result.append(
                NSAttributedString(
                    string: firstQuestion.questionSV,
                    attributes: [
                        .font: boldFont,
                        .foregroundColor: Retro.uiInk
                    ]
                )
            )
        }

        return result
    }
}

private extension String {
    func lessonChatAttributedString(color: UIColor, alignment: NSTextAlignment) -> NSAttributedString {
        let text = withPromptsOnOwnLine()
        let baseFont = RetroFont.readingUIFont()
        let boldFont = RetroFont.readingUIFont(weight: .bold)
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = alignment
        paragraph.lineSpacing = 2
        let result = NSMutableAttributedString()
        var index = text.startIndex
        var isBold = false

        while index < text.endIndex {
            if text[index...].hasPrefix("**") {
                isBold.toggle()
                index = text.index(index, offsetBy: 2)
                continue
            }

            let nextIndex = text.index(after: index)
            result.append(
                NSAttributedString(
                    string: String(text[index]),
                    attributes: [
                        .font: isBold ? boldFont : baseFont,
                        .foregroundColor: color,
                        .paragraphStyle: paragraph
                    ]
                )
            )
            index = nextIndex
        }

        return result
    }

    /// Starts each "Fråga N:" / "Översätt N/M:" prompt on its own line with a
    /// bold label. Display only: stored messages keep their original text.
    private func withPromptsOnOwnLine() -> String {
        let range = NSRange(startIndex..., in: self)
        let separated = Self.promptLabel.stringByReplacingMatches(in: self, range: range, withTemplate: "\n\n**$1**\n")
        return String(separated.drop { $0.isNewline })
    }

    private static let promptLabel = try! NSRegularExpression(
        pattern: #"\s*(?:\*\*)?((?:Fråga \d+|Översätt \d+/\d+):)(?:\*\*)?[ \t]*"#
    )
}

/// Lesson chat stages, shown as headings on the paper. Detected from the
/// prompts the app itself posts when a stage starts.
enum LessonChatStage: Int, Comparable {
    case opening
    case questions
    case discussion
    case translation

    static let discussionPrompt = "Läs dialogen en gång till. Fråga om ord, uttryck eller något som är oklart."

    init?(tutorMessage content: String) {
        if content.range(of: #"Översätt \d+/\d+:"#, options: .regularExpression) != nil {
            self = .translation
        } else if content == Self.discussionPrompt {
            self = .discussion
        } else if content.range(of: #"Fråga \d+:"#, options: .regularExpression) != nil {
            self = .questions
        } else {
            return nil
        }
    }

    var title: String {
        switch self {
        case .opening: return ""
        case .questions: return "Lyssna och svara"
        case .discussion: return "Samtal om dialogen"
        case .translation: return "Översätt"
        }
    }

    static func < (lhs: LessonChatStage, rhs: LessonChatStage) -> Bool {
        lhs.rawValue < rhs.rawValue
    }
}

/// Bold stage title ruled across the paper.
struct LessonStageHeading: View {
    let stage: LessonChatStage

    var body: some View {
        HStack(spacing: 10) {
            rule
            Text(stage.title.uppercased())
                .font(RetroFont.label(13))
                .tracking(1.6)
                .foregroundStyle(Retro.ink)
                .fixedSize()
            rule
        }
        .padding(.top, 4)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    private var rule: some View {
        Rectangle()
            .fill(Retro.ink.opacity(0.3))
            .frame(height: 1)
    }
}

/// One chat turn printed on the paper: tutor left in brown ink, learner
/// right in orange ink, each with a small caption.
struct LessonChatMessageRow: View {
    let message: LessonChatMessage
    let onTranslateSelection: ((String) -> Void)?

    private var isUser: Bool {
        message.role == .user
    }

    var body: some View {
        HStack(alignment: .bottom) {
            if isUser {
                Spacer(minLength: 40)
            }

            VStack(alignment: isUser ? .trailing : .leading, spacing: 4) {
                PaperCaption(text: isUser ? "Du" : "Läraren", color: isUser ? Retro.inkAccent.opacity(0.8) : Retro.inkSoft)
                TranslatableTextView(
                    attributedText: message.content.lessonChatAttributedString(
                        color: isUser ? Retro.uiInkAccent : Retro.uiInk,
                        alignment: isUser ? .right : .natural
                    ),
                    fillsAvailableWidth: !isUser,
                    onTranslateSelection: onTranslateSelection
                )
            }

            if !isUser {
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}

/// Keyboard strip: paper entry slot, orange send key, olive NÄSTA key.
struct LessonChatInputBar: View {
    @Binding var draft: String
    let isSending: Bool
    let isEnabled: Bool
    let canAdvanceLessonStep: Bool
    let nextStepAccessibilityLabel: String
    var isFocused: FocusState<Bool>.Binding
    let onNextQuestion: () -> Void
    let onSend: () -> Void

    private var canSend: Bool {
        isEnabled && !isSending && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var canTapNextQuestion: Bool {
        isEnabled && !isSending && canAdvanceLessonStep
    }

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("", text: $draft, prompt: Text("Skriv här…").foregroundStyle(Retro.inkSoft), axis: .vertical)
                .font(RetroFont.reading())
                .foregroundStyle(Retro.ink)
                .tint(Retro.inkAccent)
                .lineLimit(1...4)
                .focused(isFocused)
                .disabled(isSending || !isEnabled)
                .padding(.horizontal, 12)
                .padding(.vertical, 12)
                .frame(minHeight: 50)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(Retro.paper))
                .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(Retro.brassDark, lineWidth: 1.5))
                // Keys stand on a 4pt side wall; lift the field so its edges
                // line up with the key caps when they are up.
                .padding(.bottom, 4)

            Button(action: onSend) {
                if isSending {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Retro.paper)
                } else {
                    RetroKeyLabel(systemImage: "paperplane.fill")
                }
            }
            .buttonStyle(RetroKeyStyle(tint: .accent))
            .frame(width: 52, height: 54)
            .disabled(!canSend)
            .accessibilityLabel("Skicka")

            Button(action: onNextQuestion) {
                RetroKeyLabel(title: "Nästa", titleSize: 11)
            }
            .buttonStyle(RetroKeyStyle(tint: .olive))
            .frame(width: 66, height: 54)
            .disabled(!canTapNextQuestion)
            .accessibilityLabel(nextStepAccessibilityLabel)
        }
    }
}

struct LessonTypingIndicatorRow: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            PaperCaption(text: "Läraren")
            TimelineView(.animation(minimumInterval: 0.22, paused: false)) { context in
                let phase = Int(context.date.timeIntervalSinceReferenceDate * 4.5) % 3

                HStack(spacing: 6) {
                    ForEach(0..<3, id: \.self) { index in
                        Circle()
                            .fill(Retro.ink)
                            .frame(width: 7, height: 7)
                            .opacity(index == phase ? 0.9 : 0.25)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityLabel("Läraren skriver")
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

#Preview {
    LessonsHomeView()
}
