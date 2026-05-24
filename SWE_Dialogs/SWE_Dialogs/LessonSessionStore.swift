import Combine
import Foundation

struct LessonSessionRecord: Codable, Hashable {
    var state: LessonState
    var messages: [LessonChatMessage]
}

@MainActor
final class LessonSessionStore: ObservableObject {
    @Published private var records: [String: LessonSessionRecord] = [:]

    private let sessionsURL = FileStorage.documentsDirectory.appendingPathComponent("lesson_sessions.json")

    init() {
        load()
    }

    func state(for lessonID: String) -> LessonState {
        records[lessonID]?.state ?? LessonState.fresh(lessonID: lessonID)
    }

    func messages(for lessonID: String) -> [LessonChatMessage] {
        records[lessonID]?.messages ?? []
    }

    func markGenerated(lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        if record.state.phase == .notStarted {
            record.state.phase = .generated
        }
        record.state.updatedAt = Date()
        records[lessonID] = record
        persist()
    }

    func setAudioFileName(_ fileName: String, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.audioFileName = fileName
        if record.state.phase == .notStarted || record.state.phase == .generated {
            record.state.phase = .listening
        }
        record.state.updatedAt = Date()
        records[lessonID] = record
        persist()
    }

    func appendMessage(_ message: LessonChatMessage) {
        var record = ensuredRecord(for: message.lessonID)
        record.messages.append(message)
        record.state.updatedAt = Date()
        records[message.lessonID] = record
        persist()
    }

    func apply(response: InteractorResponse, generatedLesson: GeneratedLesson) throws {
        var record = ensuredRecord(for: generatedLesson.lessonID)
        var state = record.state
        try state.apply(response: response, generatedLesson: generatedLesson)
        record.state = state
        records[generatedLesson.lessonID] = record
        persist()
    }

    func setCurrentQuestion(_ questionID: String, lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.phase = .comprehension
        record.state.currentQuestionID = questionID
        record.state.updatedAt = Date()
        records[lessonID] = record
        persist()
    }

    func startDiscussion(lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.phase = .discussion
        record.state.currentQuestionID = nil
        record.state.updatedAt = Date()
        records[lessonID] = record
        persist()
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
        records[lessonID] = record
        persist()
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
        records[lessonID] = record
        persist()
    }

    func markCompleted(lessonID: String) {
        var record = ensuredRecord(for: lessonID)
        record.state.phase = .completed
        record.state.isCompleted = true
        record.state.updatedAt = Date()
        records[lessonID] = record
        persist()
    }

    func resetForRegeneratedLesson(lessonID: String) {
        var state = LessonState.fresh(lessonID: lessonID)
        state.phase = .generated
        records[lessonID] = LessonSessionRecord(state: state, messages: [])
        persist()
    }

    func resetChatAndProgressForGeneratedLesson(lessonID: String) {
        let existingAudioFileName = records[lessonID]?.state.audioFileName
        var state = LessonState.fresh(lessonID: lessonID)
        state.phase = existingAudioFileName == nil ? .generated : .listening
        state.audioFileName = existingAudioFileName
        records[lessonID] = LessonSessionRecord(state: state, messages: [])
        persist()
    }

    private func ensuredRecord(for lessonID: String) -> LessonSessionRecord {
        records[lessonID] ?? LessonSessionRecord(state: LessonState.fresh(lessonID: lessonID), messages: [])
    }

    private func load() {
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
        do {
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
