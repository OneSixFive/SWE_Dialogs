import Combine
import CryptoKit
import Foundation

enum LessonAudioAvailability: Equatable {
    case missing
    case queued
    case generating
    case ready(URL, contentHash: String)
    case failed(retryable: Bool, errorCode: String?)

    var isReady: Bool {
        if case .ready = self { return true }
        return false
    }

    var isInFlight: Bool {
        self == .queued || self == .generating
    }
}

struct LessonSessionRecord: Codable, Hashable {
    var state: LessonState
    var messages: [LessonChatMessage]
    var serverUpdatedAt: String?
    var isDirty: Bool?
    var audioContentHash: String?

    enum CodingKeys: String, CodingKey {
        case state
        case messages
        case serverUpdatedAt = "server_updated_at"
        case isDirty = "is_dirty"
        case audioContentHash = "audio_content_hash"
    }
}

struct LessonGenerationIdentity: Equatable {
    let lessonID: String
    let generatedAtSecond: Int64
    let model: String
    let schemaVersion: Int
    let contentHash: String

    init(_ lesson: GeneratedLesson) {
        lessonID = lesson.lessonID
        generatedAtSecond = Int64(lesson.generatedAt.timeIntervalSince1970.rounded(.down))
        model = lesson.model
        schemaVersion = lesson.schemaVersion
        let dialogue = lesson.dialogue
            .map { "\($0.speaker.rawValue):\($0.text)" }
            .joined(separator: "\n")
        let questions = lesson.comprehensionQuestions
            .map { "\($0.id):\($0.questionSV)" }
            .joined(separator: "\n")
        let source = "\(lesson.lessonID)\n\(lesson.model)\n\(lesson.schemaVersion)\n\(dialogue)\n\(questions)"
        contentHash = SHA256.hash(data: Data(source.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

enum LessonSessionSyncError: LocalizedError {
    case notSignedIn
    case generationChanged
    case uploadFailed
    case serverDidNotConfirmGeneration

    var errorDescription: String? {
        switch self {
        case .notSignedIn:
            return "Sign in before starting Speaking practice."
        case .generationChanged:
            return "The lesson changed while Speaking practice was preparing. Please try again."
        case .uploadFailed:
            return "The lesson could not be synchronized. Check your connection and try again."
        case .serverDidNotConfirmGeneration:
            return "The server has not confirmed the current lesson generation. Please try again."
        }
    }
}

@MainActor
protocol LessonSynchronizing: AnyObject {
    func ensureLessonSynced(
        lessonID: String,
        expectedGenerationIdentity: LessonGenerationIdentity
    ) async throws
}

@MainActor
final class LessonSessionStore: ObservableObject {
    @Published private var records: [String: LessonSessionRecord] = [:]
    @Published private var audioAvailabilityByLessonID: [String: LessonAudioAvailability] = [:]

    private var sessionsURL: URL?
    private var configuredUserID: Int?
    private var generatedLessonProvider: ((String) -> GeneratedLesson?)?
    private let lessonSessionUploader: any LessonSessionUploading
    private var lessonSyncTasks: [String: Task<Void, Never>] = [:]
    private var queuedLessonSyncs: Set<String> = []
    private var resetGenerationLessonIDs: Set<String> = []
    private var serverAudioLessonIDs: Set<String> = []
    private var audioReconciliationTasks: [String: Task<Void, Never>] = [:]
    private var audioReconciliationIDs: [String: UUID] = [:]

    init() {
        self.lessonSessionUploader = BackendClient.shared
    }

    init(lessonSessionUploader: any LessonSessionUploading) {
        self.lessonSessionUploader = lessonSessionUploader
    }

    func configure(userID: Int?, generatedLessonProvider: @escaping (String) -> GeneratedLesson?) {
        guard configuredUserID != userID else {
            self.generatedLessonProvider = generatedLessonProvider
            return
        }

        configuredUserID = userID
        self.generatedLessonProvider = generatedLessonProvider
        lessonSyncTasks.values.forEach { $0.cancel() }
        audioReconciliationTasks.values.forEach { $0.cancel() }
        lessonSyncTasks = [:]
        queuedLessonSyncs = []
        resetGenerationLessonIDs = []
        serverAudioLessonIDs = []
        audioReconciliationTasks = [:]
        audioReconciliationIDs = [:]
        audioAvailabilityByLessonID = [:]

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

    func audioAvailability(for lessonID: String) -> LessonAudioAvailability {
        if let availability = audioAvailabilityByLessonID[lessonID] {
            return availability
        }
        guard let record = records[lessonID],
              let fileName = record.state.audioFileName,
              let contentHash = record.audioContentHash else {
            return .missing
        }
        let url = lessonAudioURL(fileName: fileName)
        guard FileManager.default.fileExists(atPath: url.path) else { return .missing }
        return .ready(url, contentHash: contentHash)
    }

    func reconcileLessonAudio(lessonID: String, requestIfMissing: Bool = true) async {
        if let existing = audioReconciliationTasks[lessonID] {
            await existing.value
            return
        }
        let reconciliationID = UUID()
        let task = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.performAudioReconciliation(lessonID: lessonID, requestIfMissing: requestIfMissing)
        }
        audioReconciliationTasks[lessonID] = task
        audioReconciliationIDs[lessonID] = reconciliationID
        await task.value
        if audioReconciliationIDs[lessonID] == reconciliationID {
            audioReconciliationTasks[lessonID] = nil
            audioReconciliationIDs[lessonID] = nil
        }
    }

    func requestLessonAudio(lessonID: String) async {
        cancelLessonAudioReconciliation(lessonID: lessonID)
        audioAvailabilityByLessonID[lessonID] = .queued
        do {
            let status = try await BackendClient.shared.requestLessonAudio(lessonID: lessonID)
            applyAudioStatus(status, lessonID: lessonID)
            await reconcileLessonAudio(lessonID: lessonID, requestIfMissing: false)
        } catch {
            audioAvailabilityByLessonID[lessonID] = .failed(retryable: true, errorCode: nil)
        }
    }

    func cancelLessonAudioReconciliation(lessonID: String) {
        audioReconciliationTasks[lessonID]?.cancel()
        audioReconciliationTasks[lessonID] = nil
        audioReconciliationIDs[lessonID] = nil
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

        var audioRestoreCandidates: [BackendLessonSession] = []
        do {
            let sessions = try await BackendClient.shared.lessonSessions(summaryOnly: false)
            for session in sessions {
                guard session.state != nil else { continue }
                updateServerAudioTracking(from: session)
                if var local = records[session.lessonID], local.isDirty == true {
                    if shouldAdoptRemote(session, over: local) {
                        if let generatedLesson = session.generatedLesson {
                            generationStore.save(generatedLesson)
                        }
                        records[session.lessonID] = record(from: session, preservingAudioFrom: local)
                        if session.hasAudio == true {
                            audioRestoreCandidates.append(session)
                        }
                    } else {
                        // Keep newer local content, but refresh the exact server token before retrying.
                        local.serverUpdatedAt = session.serverUpdatedAt
                        records[session.lessonID] = local
                    }
                    continue
                }

                if let generatedLesson = session.generatedLesson {
                    generationStore.save(generatedLesson)
                }

                let localRecord = records[session.lessonID]
                records[session.lessonID] = record(from: session, preservingAudioFrom: localRecord)
                if session.hasAudio == true {
                    audioRestoreCandidates.append(session)
                }
            }
            persist()
        } catch {
            // Local progress can still be reconciled if the session download fails.
        }

        for session in audioRestoreCandidates {
            await reconcileLessonAudio(lessonID: session.lessonID, requestIfMissing: false)
        }
        await syncCompletedLessonProgress()
        await uploadDirtySessions()
        await uploadRecentGeneratedLessonAudioIfNeeded()
    }

    func uploadDirtySessions() async {
        let dirtyLessonIDs = records
            .filter { $0.value.isDirty == true }
            .map(\.key)

        for lessonID in dirtyLessonIDs {
            scheduleSync(lessonID: lessonID, resetGeneration: false)
        }
        let tasks = dirtyLessonIDs.compactMap { lessonSyncTasks[$0] }
        for task in tasks {
            await task.value
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
        if let contentHash = record.audioContentHash {
            audioAvailabilityByLessonID[lessonID] = .ready(lessonAudioURL(fileName: fileName), contentHash: contentHash)
        }
    }

    func uploadLessonAudioIfNeeded(lessonID: String) async {
        await uploadDirtySessions()
        guard let record = records[lessonID] else { return }
        await uploadLessonAudioIfPresent(lessonID: lessonID, state: record.state)
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
        cancelLessonAudioReconciliation(lessonID: lessonID)
        audioAvailabilityByLessonID[lessonID] = .missing
        var state = LessonState.fresh(lessonID: lessonID)
        state.phase = .generated
        save(
            LessonSessionRecord(state: state, messages: [], serverUpdatedAt: records[lessonID]?.serverUpdatedAt, isDirty: true, audioContentHash: nil),
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
            LessonSessionRecord(state: state, messages: [], serverUpdatedAt: records[lessonID]?.serverUpdatedAt, isDirty: true, audioContentHash: records[lessonID]?.audioContentHash),
            lessonID: lessonID,
            resetGeneration: false
        )
    }

    private func ensuredRecord(for lessonID: String) -> LessonSessionRecord {
        records[lessonID] ?? LessonSessionRecord(
            state: LessonState.fresh(lessonID: lessonID),
            messages: [],
            serverUpdatedAt: nil,
            isDirty: false,
            audioContentHash: nil
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
        queuedLessonSyncs.insert(lessonID)
        if resetGeneration {
            resetGenerationLessonIDs.insert(lessonID)
        }
        guard lessonSyncTasks[lessonID] == nil else { return }
        let userID = configuredUserID

        lessonSyncTasks[lessonID] = Task { [weak self] in
            await self?.drainSyncQueue(lessonID: lessonID, userID: userID)
        }
    }

    private func drainSyncQueue(lessonID: String, userID: Int?) async {
        var conflictAttempts = 0
        var shouldReschedule = false

        while !Task.isCancelled,
              configuredUserID == userID,
              let uploadRecord = records[lessonID],
              uploadRecord.isDirty == true {
            queuedLessonSyncs.remove(lessonID)
            let resetGeneration = resetGenerationLessonIDs.contains(lessonID)

            do {
                let response = try await lessonSessionUploader.upsertLessonSession(
                    lessonID: lessonID,
                    state: uploadRecord.state.clearingAudioFileName(),
                    generatedLesson: generatedLessonProvider?(lessonID),
                    messages: uploadRecord.messages,
                    baseServerUpdatedAt: uploadRecord.serverUpdatedAt,
                    resetGeneration: resetGeneration
                )
                conflictAttempts = 0

                if response.hasAudio == true {
                    serverAudioLessonIDs.insert(lessonID)
                }
                if var currentRecord = records[lessonID] {
                    let hasNewerLocalContent = !sameLocalContent(currentRecord, uploadRecord)
                    currentRecord.serverUpdatedAt = response.serverUpdatedAt
                    currentRecord.isDirty = hasNewerLocalContent
                    records[lessonID] = currentRecord
                    if resetGeneration && !hasNewerLocalContent {
                        resetGenerationLessonIDs.remove(lessonID)
                    }
                }
                persist()
                if response.isCompleted {
                    await uploadLessonAudioIfPresent(lessonID: lessonID, state: uploadRecord.state)
                }
            } catch BackendError.lessonSessionConflict(let current) {
                updateServerAudioTracking(from: current)
                conflictAttempts += 1
                if let local = records[lessonID], shouldAdoptRemote(current, over: local) {
                    records[lessonID] = record(from: current)
                    resetGenerationLessonIDs.remove(lessonID)
                    persist()
                    if current.hasAudio == true {
                        await reconcileLessonAudio(lessonID: current.lessonID, requestIfMissing: false)
                    }
                    break
                }

                if var local = records[lessonID] {
                    local.serverUpdatedAt = current.serverUpdatedAt
                    local.isDirty = true
                    records[lessonID] = local
                    persist()
                }
                if conflictAttempts >= 3 {
                    break
                }
            } catch {
                shouldReschedule = queuedLessonSyncs.contains(lessonID)
                break
            }
        }

        guard configuredUserID == userID else { return }
        let hadQueuedSync = queuedLessonSyncs.remove(lessonID) != nil
        let hasDirtyRecord = records[lessonID]?.isDirty == true
        lessonSyncTasks[lessonID] = nil
        if hasDirtyRecord && (shouldReschedule || hadQueuedSync) {
            scheduleSync(
                lessonID: lessonID,
                resetGeneration: resetGenerationLessonIDs.contains(lessonID)
            )
        }
    }

    private func updateServerAudioTracking(from session: BackendLessonSession) {
        if session.hasAudio == true {
            serverAudioLessonIDs.insert(session.lessonID)
        } else {
            serverAudioLessonIDs.remove(session.lessonID)
        }
    }

    private func performAudioReconciliation(lessonID: String, requestIfMissing: Bool) async {
        guard configuredUserID != nil,
              generatedLessonProvider?(lessonID) != nil else {
            audioAvailabilityByLessonID[lessonID] = .missing
            return
        }

        do {
            var status = try await BackendClient.shared.lessonAudioStatus(lessonID: lessonID)
            if status.status == "missing" && requestIfMissing {
                status = try await BackendClient.shared.requestLessonAudio(lessonID: lessonID)
            }

            var pollDelay: UInt64 = 1_000_000_000
            while true {
                try Task.checkCancellation()
                applyAudioStatus(status, lessonID: lessonID)
                if let serverHash = status.contentHash {
                    adoptServerAudioHash(serverHash, lessonID: lessonID)
                }
                guard status.status == "pending" || status.status == "running" else { break }
                try await Task.sleep(nanoseconds: pollDelay)
                pollDelay = min(pollDelay * 2, 8_000_000_000)
                status = try await BackendClient.shared.lessonAudioStatus(lessonID: lessonID)
            }

            guard status.status == "ready" else { return }
            guard let expectedHash = status.contentHash else {
                audioAvailabilityByLessonID[lessonID] = .missing
                return
            }
            if let local = matchingLocalAudio(lessonID: lessonID, expectedHash: expectedHash) {
                audioAvailabilityByLessonID[lessonID] = .ready(local, contentHash: expectedHash)
                return
            }
            let download = try await BackendClient.shared.lessonAudio(
                lessonID: lessonID,
                expectedContentHash: expectedHash
            )
            let fileURL = try saveLessonWavFile(data: download.data, lessonID: lessonID)
            installLocalAudio(fileURL: fileURL, contentHash: download.contentHash, lessonID: lessonID)
        } catch is CancellationError {
            return
        } catch {
            if !audioAvailability(for: lessonID).isReady {
                audioAvailabilityByLessonID[lessonID] = .failed(retryable: true, errorCode: nil)
            }
        }
    }

    func ensureLessonSynced(
        lessonID: String,
        expectedGenerationIdentity: LessonGenerationIdentity
    ) async throws {
        guard configuredUserID != nil else {
            throw LessonSessionSyncError.notSignedIn
        }
        guard let currentGeneration = generatedLessonProvider?(lessonID),
              LessonGenerationIdentity(currentGeneration) == expectedGenerationIdentity else {
            throw LessonSessionSyncError.generationChanged
        }

        for _ in 0..<3 where records[lessonID]?.isDirty == true {
            scheduleSync(
                lessonID: lessonID,
                resetGeneration: resetGenerationLessonIDs.contains(lessonID)
            )
            if let syncTask = lessonSyncTasks[lessonID] {
                await syncTask.value
            }
        }
        guard records[lessonID]?.isDirty != true else {
            throw LessonSessionSyncError.uploadFailed
        }

        let serverSession = try await lessonSessionUploader.lessonSession(lessonID: lessonID)
        guard let confirmedGeneration = serverSession.generatedLesson,
              LessonGenerationIdentity(confirmedGeneration) == expectedGenerationIdentity else {
            throw LessonSessionSyncError.serverDidNotConfirmGeneration
        }
        guard let latestGeneration = generatedLessonProvider?(lessonID),
              LessonGenerationIdentity(latestGeneration) == expectedGenerationIdentity else {
            throw LessonSessionSyncError.generationChanged
        }
        if var record = records[lessonID] {
            record.serverUpdatedAt = serverSession.serverUpdatedAt
            records[lessonID] = record
            persist()
        }
    }

    private func applyAudioStatus(_ status: BackendLessonAudioStatus, lessonID: String) {
        switch status.status {
        case "pending":
            audioAvailabilityByLessonID[lessonID] = .queued
        case "running":
            audioAvailabilityByLessonID[lessonID] = .generating
        case "failed":
            audioAvailabilityByLessonID[lessonID] = .failed(
                retryable: status.retryable,
                errorCode: status.errorCode
            )
        case "missing":
            audioAvailabilityByLessonID[lessonID] = .missing
        default:
            break
        }
    }

    private func installLocalAudio(fileURL: URL, contentHash: String, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.audioFileName = fileURL.lastPathComponent
        record.audioContentHash = contentHash
        if record.state.phase == .notStarted || record.state.phase == .generated {
            record.state.phase = .listening
        }
        records[lessonID] = record
        persist()
        serverAudioLessonIDs.insert(lessonID)
        audioAvailabilityByLessonID[lessonID] = .ready(fileURL, contentHash: contentHash)
    }

    private func matchingLocalAudio(lessonID: String, expectedHash: String) -> URL? {
        guard let record = records[lessonID],
              record.audioContentHash == expectedHash,
              let fileName = record.state.audioFileName else { return nil }
        let fileURL = lessonAudioURL(fileName: fileName)
        return FileManager.default.fileExists(atPath: fileURL.path) ? fileURL : nil
    }

    private func adoptServerAudioHash(_ contentHash: String, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        guard record.audioContentHash != contentHash else { return }
        record.audioContentHash = contentHash
        record.state.audioFileName = nil
        records[lessonID] = record
        persist()
    }

    private func uploadRecentGeneratedLessonAudioIfNeeded() async {
        let candidates = records
            .filter { entry in
                generatedLessonProvider?(entry.key) != nil
                    && generatedLessonProvider?(entry.key)?.artifactID == nil
                    && !serverAudioLessonIDs.contains(entry.key)
                    && entry.value.audioContentHash != nil
                    && localAudioExists(for: entry.value.state)
            }
            .sorted { lhs, rhs in
                let lhsGeneratedAt = generatedLessonProvider?(lhs.key)?.generatedAt ?? lhs.value.state.updatedAt
                let rhsGeneratedAt = generatedLessonProvider?(rhs.key)?.generatedAt ?? rhs.value.state.updatedAt
                return lhsGeneratedAt > rhsGeneratedAt
            }
            .prefix(5)

        for (lessonID, record) in candidates {
            await uploadLessonAudioIfPresent(lessonID: lessonID, state: record.state)
        }
    }

    private func uploadLessonAudioIfPresent(lessonID: String, state: LessonState) async {
        guard generatedLessonProvider?(lessonID)?.artifactID == nil,
              records[lessonID]?.audioContentHash != nil else { return }
        guard let fileName = state.audioFileName else { return }
        let fileURL = lessonAudioURL(fileName: fileName)
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }

        do {
            let audioData = try Data(contentsOf: fileURL)
            try await lessonSessionUploader.uploadLessonAudio(lessonID: lessonID, data: audioData)
            serverAudioLessonIDs.insert(lessonID)
        } catch {
            // Audio upload is best-effort; the session itself remains synced and future sync can retry.
        }
    }

    private func localAudioExists(for state: LessonState) -> Bool {
        guard let fileName = state.audioFileName else { return false }
        return FileManager.default.fileExists(atPath: lessonAudioURL(fileName: fileName).path)
    }

    private func record(
        from session: BackendLessonSession,
        preservingAudioFrom local: LessonSessionRecord? = nil
    ) -> LessonSessionRecord {
        var state = session.state?.clearingMissingAudioFile(userID: configuredUserID)
            ?? LessonState.fresh(lessonID: session.lessonID)
        var localFileName: String?
        var localContentHash: String?
        if let localState = local?.state,
           let fileName = localState.audioFileName,
           let contentHash = local?.audioContentHash,
           localAudioExists(for: localState) {
            localFileName = fileName
            localContentHash = contentHash
        }
        if let fileName = localFileName {
            state.audioFileName = fileName
            if state.phase == .notStarted || state.phase == .generated {
                state.phase = .listening
            }
        }

        return LessonSessionRecord(
            state: state,
            messages: session.messages ?? [],
            serverUpdatedAt: session.serverUpdatedAt,
            isDirty: false,
            audioContentHash: localContentHash
        )
    }

    private func shouldAdoptRemote(_ remote: BackendLessonSession, over local: LessonSessionRecord) -> Bool {
        if remote.isCompleted && !local.state.isCompleted {
            return true
        }
        if remote.state == local.state.clearingAudioFileName(),
           (remote.messages ?? []) == local.messages {
            return true
        }
        return remote.clientUpdatedAt > local.state.updatedAt
            && (remote.messages?.count ?? 0) >= local.messages.count
    }

    private func sameLocalContent(_ lhs: LessonSessionRecord, _ rhs: LessonSessionRecord) -> Bool {
        lhs.state == rhs.state && lhs.messages == rhs.messages
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

extension LessonSessionStore: LessonSynchronizing {}

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
