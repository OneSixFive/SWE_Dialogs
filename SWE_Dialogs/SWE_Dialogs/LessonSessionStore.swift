import Combine
import Foundation

struct LessonSessionRecord: Codable, Hashable {
    var state: LessonState
    var messages: [LessonChatMessage]
    var serverUpdatedAt: Date?
    var isDirty: Bool?

    enum CodingKeys: String, CodingKey {
        case state
        case messages
        case serverUpdatedAt = "server_updated_at"
        case isDirty = "is_dirty"
    }
}

@MainActor
final class LessonSessionStore: ObservableObject {
    @Published private var records: [String: LessonSessionRecord] = [:]

    private var sessionsURL: URL?
    private var configuredUserID: Int?
    private var generatedLessonProvider: ((String) -> GeneratedLesson?)?

    func configure(userID: Int?, generatedLessonProvider: @escaping (String) -> GeneratedLesson?) {
        guard configuredUserID != userID else {
            self.generatedLessonProvider = generatedLessonProvider
            return
        }

        configuredUserID = userID
        self.generatedLessonProvider = generatedLessonProvider

        guard let userID else {
            sessionsURL = nil
            records = [:]
            return
        }

        FileStorage.migrateLegacyFileIfNeeded(fileName: "lesson_sessions.json", toUserID: userID)
        FileStorage.migrateLegacyLessonAudioIfNeeded(toUserID: userID)
        sessionsURL = FileStorage.userDirectory(userID: userID).appendingPathComponent("lesson_sessions.json")
        records = [:]
        load()
    }

    func state(for lessonID: String) -> LessonState {
        records[lessonID]?.state ?? LessonState.fresh(lessonID: lessonID)
    }

    func messages(for lessonID: String) -> [LessonChatMessage] {
        records[lessonID]?.messages ?? []
    }

    func lessonAudioURL(fileName: String) -> URL {
        guard let configuredUserID else {
            return FileStorage.lessonAudioURL(fileName: fileName)
        }
        return FileStorage.lessonAudioURL(fileName: fileName, userID: configuredUserID)
    }

    func saveLessonWavFile(data: Data, lessonID: String) throws -> URL {
        guard let configuredUserID else {
            return try FileStorage.saveLessonWavFile(data: data, lessonID: lessonID)
        }
        return try FileStorage.saveLessonWavFile(data: data, lessonID: lessonID, userID: configuredUserID)
    }

    func syncFromBackend(generationStore: LessonGenerationStore) async {
        guard configuredUserID != nil else { return }

        do {
            let sessions = try await BackendClient.shared.lessonSessions(summaryOnly: false)
            for session in sessions {
                guard let state = session.state else { continue }
                let local = records[session.lessonID]
                if local?.isDirty == true {
                    continue
                }

                if let generatedLesson = session.generatedLesson {
                    generationStore.save(generatedLesson)
                }

                let sanitizedState = state.clearingMissingAudioFile(userID: configuredUserID)
                records[session.lessonID] = LessonSessionRecord(
                    state: sanitizedState,
                    messages: session.messages ?? [],
                    serverUpdatedAt: session.serverUpdatedAt,
                    isDirty: false
                )
            }
            persist()
        } catch {
            // Local progress can still be reconciled if the session download fails.
        }

        await syncCompletedLessonProgress()
        await uploadDirtySessions()
    }

    func uploadDirtySessions() async {
        let dirtyLessonIDs = records
            .filter { $0.value.isDirty == true }
            .map(\.key)

        for lessonID in dirtyLessonIDs {
            await syncLesson(lessonID: lessonID, resetGeneration: false)
        }
    }

    private func syncCompletedLessonProgress() async {
        let completedLessonIDs = records
            .filter { $0.value.state.isCompleted }
            .map(\.key)
            .sorted()

        do {
            _ = try await BackendClient.shared.syncCompletedLessonProgress(lessonIDs: completedLessonIDs)
        } catch {
            // A later app launch will retry this idempotent reconciliation.
        }
    }

    func markGenerated(lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        if record.state.phase == .notStarted {
            record.state.phase = .generated
        }
        record.state.updatedAt = Date()
        save(record, lessonID: lessonID)
    }

    func setAudioFileName(_ fileName: String, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.audioFileName = fileName
        if record.state.phase == .notStarted || record.state.phase == .generated {
            record.state.phase = .listening
        }
        record.state.updatedAt = Date()
        save(record, lessonID: lessonID)
    }

    func appendMessage(_ message: LessonChatMessage) {
        var record = ensuredRecord(for: message.lessonID)
        record.messages.append(message)
        record.state.updatedAt = Date()
        save(record, lessonID: message.lessonID)
    }

    func apply(response: InteractorResponse, generatedLesson: GeneratedLesson) throws {
        var record = ensuredRecord(for: generatedLesson.lessonID)
        var state = record.state
        try state.apply(response: response, generatedLesson: generatedLesson)
        record.state = state
        save(record, lessonID: generatedLesson.lessonID)
    }

    func setCurrentQuestion(_ questionID: String, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.phase = .comprehension
        record.state.currentQuestionID = questionID
        record.state.updatedAt = Date()
        save(record, lessonID: lessonID)
    }

    func startDiscussion(lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.phase = .discussion
        record.state.currentQuestionID = nil
        record.state.updatedAt = Date()
        save(record, lessonID: lessonID)
    }

    func setCurrentTranslationIndex(_ index: Int, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        guard let quiz = record.state.translationQuiz,
              quiz.sentencesEN.indices.contains(index) else {
            return
        }

        record.state.phase = .translation
        record.state.currentTranslationIndex = index
        record.state.updatedAt = Date()
        save(record, lessonID: lessonID)
    }

    func appendTranslationAttempt(sentenceIndex: Int, answer: String, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        guard let quiz = record.state.translationQuiz,
              quiz.sentencesEN.indices.contains(sentenceIndex) else {
            return
        }

        record.state.translationAttempts.append(
            TranslationAttempt(sentenceIndex: sentenceIndex, answer: answer)
        )
        if record.state.translationAttempts.count > 50 {
            record.state.translationAttempts = Array(record.state.translationAttempts.suffix(50))
        }
        record.state.updatedAt = Date()
        save(record, lessonID: lessonID)
    }

    func markCompleted(lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.phase = .completed
        record.state.isCompleted = true
        record.state.updatedAt = Date()
        save(record, lessonID: lessonID)
    }

    func resetForRegeneratedLesson(lessonID: String) {
        var state = LessonState.fresh(lessonID: lessonID)
        state.phase = .generated
        save(
            LessonSessionRecord(state: state, messages: [], serverUpdatedAt: records[lessonID]?.serverUpdatedAt, isDirty: true),
            lessonID: lessonID,
            resetGeneration: true
        )
    }

    func resetChatAndProgressForGeneratedLesson(lessonID: String) {
        let existingAudioFileName = records[lessonID]?.state.audioFileName
        var state = LessonState.fresh(lessonID: lessonID)
        state.phase = existingAudioFileName == nil ? .generated : .listening
        state.audioFileName = existingAudioFileName
        save(
            LessonSessionRecord(state: state, messages: [], serverUpdatedAt: records[lessonID]?.serverUpdatedAt, isDirty: true),
            lessonID: lessonID,
            resetGeneration: true
        )
    }

    private func ensuredRecord(for lessonID: String) -> LessonSessionRecord {
        records[lessonID] ?? LessonSessionRecord(
            state: LessonState.fresh(lessonID: lessonID),
            messages: [],
            serverUpdatedAt: nil,
            isDirty: false
        )
    }

    private func save(_ record: LessonSessionRecord, lessonID: String, resetGeneration: Bool = false) {
        var dirtyRecord = record
        dirtyRecord.isDirty = true
        records[lessonID] = dirtyRecord
        persist()
        scheduleSync(lessonID: lessonID, resetGeneration: resetGeneration)
    }

    private func scheduleSync(lessonID: String, resetGeneration: Bool) {
        guard configuredUserID != nil else { return }
        Task {
            await syncLesson(lessonID: lessonID, resetGeneration: resetGeneration)
        }
    }

    private func syncLesson(lessonID: String, resetGeneration: Bool) async {
        guard configuredUserID != nil,
              var record = records[lessonID] else {
            return
        }

        let generatedLesson = generatedLessonProvider?(lessonID)
        let uploadState = record.state.clearingAudioFileName()
        let uploadedUpdatedAt = record.state.updatedAt
        let uploadedMessageCount = record.messages.count

        do {
            let response = try await BackendClient.shared.upsertLessonSession(
                lessonID: lessonID,
                state: uploadState,
                generatedLesson: generatedLesson,
                messages: record.messages,
                baseServerUpdatedAt: record.serverUpdatedAt,
                resetGeneration: resetGeneration
            )
            var needsFollowUpSync = false
            if var currentRecord = records[lessonID] {
                currentRecord.serverUpdatedAt = response.serverUpdatedAt
                currentRecord.isDirty = !(currentRecord.state.updatedAt == uploadedUpdatedAt && currentRecord.messages.count == uploadedMessageCount)
                needsFollowUpSync = currentRecord.isDirty == true
                records[lessonID] = currentRecord
            }
            persist()
            if needsFollowUpSync {
                scheduleSync(lessonID: lessonID, resetGeneration: false)
            }
        } catch {
            if var currentRecord = records[lessonID] {
                currentRecord.isDirty = true
                records[lessonID] = currentRecord
            }
            persist()
        }
    }

    private func load() {
        guard let sessionsURL else {
            records = [:]
            return
        }
        guard let data = try? Data(contentsOf: sessionsURL) else { return }

        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            records = try decoder.decode([String: LessonSessionRecord].self, from: data)
        } catch {
            records = [:]
        }
    }

    private func persist() {
        guard let sessionsURL else { return }
        do {
            try FileManager.default.createDirectory(
                at: sessionsURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            encoder.dateEncodingStrategy = .iso8601
            let data = try encoder.encode(records)
            try data.write(to: sessionsURL, options: [.atomic])
        } catch {
            // Keep UI responsive if session persistence fails.
        }
    }
}

private extension LessonState {
    func clearingAudioFileName() -> LessonState {
        var copy = self
        copy.audioFileName = nil
        return copy
    }

    func clearingMissingAudioFile(userID: Int?) -> LessonState {
        guard let fileName = audioFileName else { return self }

        let url: URL
        if let userID {
            url = FileStorage.lessonAudioURL(fileName: fileName, userID: userID)
        } else {
            url = FileStorage.lessonAudioURL(fileName: fileName)
        }

        guard FileManager.default.fileExists(atPath: url.path) else {
            return clearingAudioFileName()
        }
        return self
    }
}
