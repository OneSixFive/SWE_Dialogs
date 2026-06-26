import SwiftUI
import UIKit

struct LessonsHomeView: View {
    @EnvironmentObject private var appSessionStore: AppSessionStore

    @StateObject private var curriculumStore = CurriculumStore()
    @StateObject private var generationStore = LessonGenerationStore()
    @StateObject private var sessionStore = LessonSessionStore()
    @StateObject private var lessonAudioPlayer = AudioPlayerController()

    @State private var path: [String] = []
    @State private var visibleWeekID: String?
    @State private var visibleLessonFrames: [LessonVisibleLessonFrame] = []
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
                            .padding(.top, LessonPathStyle.headerHeight + 22)
                            .padding(.bottom, 104)
                        }
                        .background(LessonPathStyle.background)
                        .coordinateSpace(name: LessonPathStyle.scrollCoordinateSpace)
                        .onPreferenceChange(LessonVisibleWeekPreferenceKey.self) { frames in
                            updateVisibleWeek(from: frames, viewportHeight: geometry.size.height)
                        }
                        .onPreferenceChange(LessonVisibleLessonPreferenceKey.self) { frames in
                            if frames != visibleLessonFrames {
                                visibleLessonFrames = frames
                            }
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
                                    Image(systemName: jumpArrowSystemImage(viewportHeight: geometry.size.height))
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
                                .accessibilityLabel(jumpArrowAccessibilityLabel(viewportHeight: geometry.size.height))

                                Spacer()
                            }
                            .padding(.leading, 16)
                            .padding(.bottom, 16)
                        }
                    }
                    .background(LessonPathStyle.background.ignoresSafeArea())
                    .onAppear {
                        configureStoresForCurrentUser()
                        visibleWeekID = visibleWeekID ?? lessonWeeks.first?.id
                        scrollToActiveLessonIfNeeded(with: proxy)
                    }
                    .onChange(of: appSessionStore.user?.id) { _, _ in
                        configureStoresForCurrentUser()
                    }
                    .onChange(of: firstLessonID) { _, _ in
                        visibleWeekID = visibleWeekID ?? lessonWeeks.first?.id
                        scrollToActiveLessonIfNeeded(with: proxy)
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

    private func configureStoresForCurrentUser() {
        let userID = appSessionStore.user?.id
        generationStore.configure(userID: userID)
        sessionStore.configure(userID: userID) { lessonID in
            generationStore.generatedLesson(for: lessonID)
        }

        guard userID != nil else { return }
        Task {
            await sessionStore.syncFromBackend(generationStore: generationStore)
        }
    }

    private var activeLesson: LessonPayload? {
        let orderedLessons = lessonWeeks.flatMap(\.lessons)
        return orderedLessons.first { !sessionStore.state(for: $0.id).isCompleted } ?? orderedLessons.first
    }

    private func scrollToActiveLessonIfNeeded(with proxy: ScrollViewProxy) {
        guard !didInitialScroll else { return }
        didInitialScroll = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            guard let activeLesson,
                  let week = lessonWeeks.first(where: { $0.lessons.contains(activeLesson) }) else {
                guard let firstWeekID else { return }
                proxy.scrollTo(firstWeekID, anchor: .bottom)
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

    private func jumpArrowSystemImage(viewportHeight: CGFloat) -> String {
        switch jumpDirection(viewportHeight: viewportHeight) {
        case .up:
            return "arrow.up"
        case .down:
            return "arrow.down"
        }
    }

    private func jumpArrowAccessibilityLabel(viewportHeight: CGFloat) -> String {
        switch jumpDirection(viewportHeight: viewportHeight) {
        case .up:
            return "Jump up to first incomplete lesson"
        case .down:
            return "Jump down to first incomplete lesson"
        }
    }

    private func jumpDirection(viewportHeight: CGFloat) -> LessonPathJumpDirection {
        guard let activeLesson else {
            return .down
        }

        let top = visibleAreaTop
        let bottom = visibleAreaBottom(viewportHeight: viewportHeight)

        if let activeFrame = visibleLessonFrames.first(where: { $0.id == activeLesson.id }) {
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

        guard let activeWeekIndex = lessonWeeks.firstIndex(where: { $0.lessons.contains(activeLesson) }),
              let visibleWeekID,
              let visibleWeekIndex = lessonWeeks.firstIndex(where: { $0.id == visibleWeekID }) else {
            return .down
        }

        return activeWeekIndex > visibleWeekIndex ? .up : .down
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

        guard bestFrame.id != visibleWeekID else { return }
        visibleWeekID = bestFrame.id
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

private enum LessonPathJumpDirection {
    case up
    case down
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
    let onMarkLessonComplete: (LessonPayload) -> Void
    let onMarkWeekComplete: (LessonPathWeek) -> Void

    var body: some View {
        VStack(spacing: 0) {
            LessonPathWeekBlock(
                week: week,
                activeLessonID: activeLessonID,
                generationStore: generationStore,
                sessionStore: sessionStore,
                onLessonTap: onLessonTap,
                onMarkLessonComplete: onMarkLessonComplete,
                onMarkWeekComplete: onMarkWeekComplete
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
    let onMarkLessonComplete: (LessonPayload) -> Void
    let onMarkWeekComplete: (LessonPathWeek) -> Void

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
                            isWeekCompleted: week.lessons.allSatisfy { sessionStore.state(for: $0.id).isCompleted },
                            isActive: lesson.id == activeLessonID,
                            horizontalOffset: horizontalOffset(for: lesson.coursePosition.day, width: proxy.size.width),
                            blobWidth: blobWidth,
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
    let isWeekCompleted: Bool
    let isActive: Bool
    let horizontalOffset: CGFloat
    let blobWidth: CGFloat
    let onTap: () -> Void
    let onMarkLessonComplete: () -> Void
    let onMarkWeekComplete: () -> Void

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
        .background {
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
        .contextMenu {
            Button {
                onMarkLessonComplete()
            } label: {
                Label("Mark Lesson Complete", systemImage: "checkmark.circle")
            }
            .disabled(state.isCompleted)

            Button {
                onMarkWeekComplete()
            } label: {
                Label("Mark Week Complete", systemImage: "checkmark.circle.fill")
            }
            .disabled(isWeekCompleted)
        }
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
    @ObservedObject var generationStore: LessonGenerationStore
    @ObservedObject var sessionStore: LessonSessionStore
    @ObservedObject var audioPlayer: AudioPlayerController

    @Environment(\.dismiss) private var dismiss
    @AppStorage("tts_model_raw") private var selectedTTSModelRaw = GeminiTTSService.TTSModel.flash31.rawValue

    @State private var isGeneratingLesson = false
    @State private var isGeneratingAudio = false
    @State private var isSending = false
    @State private var draft = ""
    @State private var errorMessage: String?
    @State private var showRegenerateConfirmation = false
    @State private var expandedPanel: LessonPanel?
    @State private var dialogueScrollOffsetY: CGFloat = 0
    @State private var shouldFlashDialogButton = false
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
        lessonState.translationQuiz == nil &&
            lessonState.phase == .discussion &&
            !lessonState.isCompleted
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
                LessonBackControlRow {
                    dismiss()
                }

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
                    LessonTopControlBar(selection: $expandedPanel, shouldFlashDialogButton: shouldFlashDialogButton) {
                        dismiss()
                    }
                        .simultaneousGesture(TapGesture().onEnded {
                            dismissKeyboard()
                        })

                    LessonInlineAudioPlayer(audioPlayer: audioPlayer, fileURL: currentAudioURL)
                        .simultaneousGesture(TapGesture().onEnded {
                            dismissKeyboard()
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
                                LessonAssistantOpening(
                                    firstQuestion: generatedLesson.comprehensionQuestions.first,
                                    onTranslateSelection: sendTranslationRequest
                                )
                            }

                            ForEach(messages) { message in
                                LessonChatMessageRow(
                                    message: message,
                                    onTranslateSelection: sendTranslationRequest
                                )
                                    .id(message.id)
                            }

                            if isSending || isRequestingTranslationQuiz {
                                LessonTypingIndicatorRow()
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
                    .onChange(of: isChatFocused) { _, isFocused in
                        guard isFocused else { return }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
                            withAnimation {
                                proxy.scrollTo("lesson-chat-bottom", anchor: .bottom)
                            }
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
                canAdvanceLessonStep: canAdvanceLessonStep,
                nextStepAccessibilityLabel: nextStepAccessibilityLabel,
                isFocused: $isChatFocused,
                onNextQuestion: {
                    Task {
                        await advanceLessonStep()
                    }
                },
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
        .onChange(of: expandedPanel) { _, panel in
            if panel == .dialogue {
                shouldFlashDialogButton = false
            }
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
            dialogueScrollOffsetY: $dialogueScrollOffsetY,
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
        return sessionStore.lessonAudioURL(fileName: fileName)
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
        let model = OpenAIModelDefaults.lessonGenerator.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonGeneratorReasoningEffort

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
                model: model,
                reasoningEffort: reasoningEffort
            )
            let fileURL = try await generateAudioFile(for: lesson)

            generationStore.save(lesson)
            if replacingExisting {
                sessionStore.resetForRegeneratedLesson(lessonID: payload.id)
            } else {
                sessionStore.markGenerated(lessonID: payload.id)
            }
            sessionStore.setAudioFileName(fileURL.lastPathComponent, lessonID: lesson.lessonID)
            appendInitialQuestionMessageIfNeeded(for: lesson)
            dialogueScrollOffsetY = 0
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
        isGeneratingAudio = true
        errorMessage = nil
        defer { isGeneratingAudio = false }

        do {
            let fileURL = try await generateAudioFile(for: lesson)
            sessionStore.setAudioFileName(fileURL.lastPathComponent, lessonID: lesson.lessonID)
            audioPlayer.load(url: fileURL)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func generateAudioFile(for lesson: GeneratedLesson) async throws -> URL {
        let wavData = try await GeminiTTSService.generateWav(
            dialog: lesson.ttsText,
            model: selectedTTSModel
        )
        return try sessionStore.saveLessonWavFile(data: wavData, lessonID: lesson.lessonID)
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
        guard !lessonState.isCompleted else { return false }
        if lessonState.translationQuiz != nil {
            return hasAttemptForActiveTranslationSentence
        }
        return !generatedLesson.comprehensionQuestions.isEmpty || lessonState.phase == .discussion
    }

    private var nextStepAccessibilityLabel: String {
        if let activeTranslationSentence {
            return activeTranslationSentence.index == activeTranslationSentence.count - 1
                ? "Finish lesson"
                : "Next translation sentence"
        }
        guard let generatedLesson else { return "Next question" }
        if lessonState.phase == .discussion {
            return "Start translation quiz"
        }
        if nextQuestionAfterCurrent(in: generatedLesson) == nil {
            return "Discuss dialog"
        }
        return "Next question"
    }

    private var activeTranslationSentence: (index: Int, count: Int, sentence: String)? {
        guard let quiz = lessonState.translationQuiz, !quiz.sentencesEN.isEmpty else { return nil }
        let index = min(max(lessonState.currentTranslationIndex ?? 0, 0), quiz.sentencesEN.count - 1)
        return (index, quiz.sentencesEN.count, quiz.sentencesEN[index])
    }

    private var hasAttemptForActiveTranslationSentence: Bool {
        guard let activeTranslationSentence else { return false }
        return lessonState.translationAttempts.contains { attempt in
            attempt.sentenceIndex == activeTranslationSentence.index
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
        "Läs dialogen en gång till. Fråga om ord, uttryck eller något som är oklart."
    }

    private func requestStateForTutorMessage(generatedLesson: GeneratedLesson) -> LessonState {
        var state = lessonState
        guard state.translationQuiz == nil, !state.isCompleted else { return state }

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

    private func sendTutorMessage(_ message: String) async {
        let trimmedMessage = message.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = OpenAIModelDefaults.lessonInteractor.trimmingCharacters(in: .whitespacesAndNewlines)
        let reasoningEffort = OpenAIModelDefaults.lessonInteractorReasoningEffort

        guard let generatedLesson else {
            errorMessage = "Generate the lesson before chatting."
            return
        }

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
                reasoningEffort: reasoningEffort
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
        guard !isSending, !isRequestingTranslationQuiz else { return }
        Task {
            await sendTutorMessage(translationRequestMessage(for: selection))
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

enum LessonChatStyle {
    static let panel = Color(red: 0.06, green: 0.06, blue: 0.06)
    static let panelStroke = Color.white.opacity(0.10)
    static let control = Color.white.opacity(0.10)
    static let controlSelected = Color.white.opacity(0.18)
    static let primaryText = Color.white
    static let secondaryText = Color.white.opacity(0.58)
    static let tertiaryText = Color.white.opacity(0.42)
}

private struct LessonBackControlRow: View {
    let onBack: () -> Void

    var body: some View {
        HStack {
            LessonTopControlButton(
                systemImage: "chevron.left",
                isSelected: false,
                isFlashing: false,
                accessibilityLabel: "Back",
                action: onBack
            )
            .frame(width: 64)

            Spacer()
        }
    }
}

private struct LessonTopControlBar: View {
    @Binding var selection: LessonPanel?
    let shouldFlashDialogButton: Bool
    let onBack: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            LessonTopControlButton(
                systemImage: "chevron.left",
                isSelected: false,
                isFlashing: false,
                accessibilityLabel: "Back",
                action: onBack
            )

            ForEach(LessonPanel.allCases) { panel in
                LessonTopControlButton(
                    systemImage: panel.systemImage,
                    isSelected: selection == panel,
                    isFlashing: panel == .dialogue && shouldFlashDialogButton,
                    accessibilityLabel: panel.title
                ) {
                    withAnimation(.snappy(duration: 0.22)) {
                        selection = selection == panel ? nil : panel
                    }
                }
            }
        }
    }
}

struct LessonTopControlButton: View {
    let systemImage: String
    let isSelected: Bool
    let isFlashing: Bool
    let accessibilityLabel: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(LessonChatStyle.primaryText)
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .background {
                    buttonBackground
                }
                .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
                .overlay {
                    buttonBorder
                }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accessibilityLabel)
    }

    private var backgroundColor: Color {
        if isSelected { return LessonChatStyle.controlSelected }
        return LessonChatStyle.control
    }

    @ViewBuilder
    private var buttonBackground: some View {
        if isFlashing, !isSelected {
            TimelineView(.animation) { context in
                Color.white.opacity(0.10 + 0.24 * flashIntensity(at: context.date))
            }
        } else {
            backgroundColor
        }
    }

    @ViewBuilder
    private var buttonBorder: some View {
        if isFlashing, !isSelected {
            TimelineView(.animation) { context in
                RoundedRectangle(cornerRadius: 26, style: .continuous)
                    .stroke(Color.white.opacity(0.20 + 0.52 * flashIntensity(at: context.date)), lineWidth: 1.5)
            }
        } else {
            RoundedRectangle(cornerRadius: 26, style: .continuous)
                .stroke(LessonChatStyle.panelStroke, lineWidth: 1)
        }
    }

    private func flashIntensity(at date: Date) -> Double {
        let period = 1.3
        let phase = date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: period) / period
        return phase < 0.5 ? phase * 2 : (1 - phase) * 2
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
                        set: { newValue in
                            if audioPlayer.isScrubbing {
                                audioPlayer.scrub(to: newValue)
                            } else {
                                audioPlayer.seek(to: newValue)
                            }
                        }
                    ),
                    in: 0...max(audioPlayer.duration, 1),
                    onEditingChanged: { isEditing in
                        if isEditing {
                            audioPlayer.beginScrubbing()
                        } else {
                            audioPlayer.endScrubbing()
                        }
                    }
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
    @Binding var dialogueScrollOffsetY: CGFloat
    let isGeneratingLesson: Bool
    let isGeneratingAudio: Bool
    let isSending: Bool
    let isRequestingTranslationQuiz: Bool
    let onRegenerate: () -> Void
    let onRegenerateAudio: () -> Void
    let onResetProgress: () -> Void
    let onMarkComplete: () -> Void
    let onTranslateSelection: (String) -> Void

    var body: some View {
        let shouldUseTallScrollArea = panel == .dialogue

        VStack(alignment: .leading, spacing: 18) {
            Label(panel.title, systemImage: panel.systemImage)
                .font(.headline)
                .foregroundStyle(LessonChatStyle.primaryText)

            if shouldUseTallScrollArea {
                dialogueScrollView(height: max(360, maxHeight - 88))
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

    private func dialogueScrollView(height: CGFloat) -> some View {
        TranslatableTextView(
            text: dialogueText,
            isScrollEnabled: true,
            showsVerticalScrollIndicator: true,
            textColor: .white,
            contentOffsetY: $dialogueScrollOffsetY,
            onTranslateSelection: onTranslateSelection
        )
            .frame(height: height)
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
            TranslatableTextView(
                text: "\(payload.courseLevel.rawValue), Stage \(payload.coursePosition.stage), Week \(payload.coursePosition.week), Day \(payload.coursePosition.day)",
                textColor: UIColor(LessonChatStyle.secondaryText),
                font: UIFont.preferredFont(forTextStyle: .title3),
                onTranslateSelection: onTranslateSelection
            )

            TranslatableTextView(
                text: payload.lessonIntent.oneSentenceGoal,
                textColor: UIColor(LessonChatStyle.primaryText),
                font: UIFont.preferredFont(forTextStyle: .title2),
                onTranslateSelection: onTranslateSelection
            )

            TranslatableTextView(
                text: payload.grammarTarget.mainFocus.name,
                textColor: UIColor(LessonChatStyle.primaryText),
                font: UIFont.preferredFont(forTextStyle: .title3),
                onTranslateSelection: onTranslateSelection
            )

            TranslatableTextView(
                text: payload.dialogueTask.scenario,
                textColor: UIColor(LessonChatStyle.secondaryText),
                onTranslateSelection: onTranslateSelection
            )
        }
    }

    private var dialogueContent: some View {
        TranslatableTextView(
            text: dialogueText,
            textColor: .white,
            onTranslateSelection: onTranslateSelection
        )
    }

    private var practiceContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            if let quiz = lessonState.translationQuiz {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Translation")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(LessonChatStyle.secondaryText)

                    TranslatableTextView(
                        text: translationText(quiz),
                        textColor: .white,
                        onTranslateSelection: onTranslateSelection
                    )
                }
            } else if isRequestingTranslationQuiz {
                HStack(spacing: 10) {
                    ProgressView()
                        .tint(.white)
                    Text("Preparing translation quiz")
                        .font(.subheadline)
                        .foregroundStyle(LessonChatStyle.secondaryText)
                }
            }

            if lessonState.translationQuiz == nil {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Comprehension")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(LessonChatStyle.secondaryText)

                    TranslatableTextView(
                        text: comprehensionText,
                        textColor: .white,
                        onTranslateSelection: onTranslateSelection
                    )
                }
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
        guard !quiz.sentencesEN.isEmpty else { return "" }
        let index = min(max(lessonState.currentTranslationIndex ?? 0, 0), quiz.sentencesEN.count - 1)
        return "\(index + 1)/\(quiz.sentencesEN.count). \(quiz.sentencesEN[index])"
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
    let onTranslateSelection: (String) -> Void

    var body: some View {
        TranslatableTextView(
            attributedText: openingText,
            textColor: .white,
            onTranslateSelection: onTranslateSelection
        )
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var openingText: NSAttributedString {
        let baseFont = UIFont.preferredFont(forTextStyle: .body)
        let boldDescriptor = baseFont.fontDescriptor.withSymbolicTraits(.traitBold) ?? baseFont.fontDescriptor
        let boldFont = UIFont(descriptor: boldDescriptor, size: baseFont.pointSize)
        let result = NSMutableAttributedString(
            string: "Lyssna på lektionens ljud och svara sedan på förståelsefrågorna här. Du kan också fråga om ord eller grammatik från dialogen.",
            attributes: [
                .font: baseFont,
                .foregroundColor: UIColor.white
            ]
        )

        if let firstQuestion {
            result.append(NSAttributedString(string: "\n\n"))
            result.append(
                NSAttributedString(
                    string: "Fråga 1: ",
                    attributes: [
                        .font: boldFont,
                        .foregroundColor: UIColor.white
                    ]
                )
            )
            result.append(
                NSAttributedString(
                    string: firstQuestion.questionSV,
                    attributes: [
                        .font: baseFont,
                        .foregroundColor: UIColor.white
                    ]
                )
            )
        }

        return result
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

struct LessonChatMessageRow: View {
    let message: LessonChatMessage
    let onTranslateSelection: ((String) -> Void)?

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
        .frame(maxWidth: .infinity, alignment: message.role == .user ? .trailing : .leading)
    }

    @ViewBuilder
    private var messageContent: some View {
        if message.role == .user {
            TranslatableTextView(
                text: message.content,
                textColor: .white,
                fillsAvailableWidth: false,
                onTranslateSelection: onTranslateSelection
            )
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(Color.white.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        } else {
            TranslatableTextView(
                attributedText: message.content.lessonChatAttributedString(),
                textColor: .white,
                onTranslateSelection: onTranslateSelection
            )
                .padding(.leading, 2)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct LessonChatInputBar: View {
    @Binding var draft: String
    let isSending: Bool
    let canAdvanceLessonStep: Bool
    let nextStepAccessibilityLabel: String
    var isFocused: FocusState<Bool>.Binding
    let onNextQuestion: () -> Void
    let onSend: () -> Void

    private var canSend: Bool {
        !isSending && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var canTapNextQuestion: Bool {
        !isSending && canAdvanceLessonStep
    }

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            TextField("Ask or answer", text: $draft, axis: .vertical)
                .font(.body)
                .foregroundStyle(LessonChatStyle.primaryText)
                .tint(.white)
                .lineLimit(1...4)
                .focused(isFocused)
                .disabled(isSending)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)

            Button(action: onNextQuestion) {
                Image(systemName: "forward.end.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.black)
                    .frame(width: 38, height: 38)
                    .background(canTapNextQuestion ? Color.white : Color.white.opacity(0.35))
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(!canTapNextQuestion)
            .accessibilityLabel(nextStepAccessibilityLabel)

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

struct LessonTypingIndicatorRow: View {
    var body: some View {
        HStack(alignment: .bottom) {
            LessonTypingIndicatorBubble()
            Spacer(minLength: 56)
        }
    }
}

private struct LessonTypingIndicatorBubble: View {
    var body: some View {
        TimelineView(.animation(minimumInterval: 0.22, paused: false)) { context in
            let phase = Int(context.date.timeIntervalSinceReferenceDate * 4.5) % 3

            HStack(spacing: 6) {
                ForEach(0..<3, id: \.self) { index in
                    Circle()
                        .fill(Color.white)
                        .frame(width: 8, height: 8)
                        .opacity(index == phase ? 1 : 0.35)
                        .scaleEffect(index == phase ? 1 : 0.82)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(Color.white.opacity(0.14))
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
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
