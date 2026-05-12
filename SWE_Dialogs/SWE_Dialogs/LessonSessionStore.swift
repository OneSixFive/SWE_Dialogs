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
        try LessonValidator.validate(response: response, generatedLesson: generatedLesson)

        var record = ensuredRecord(for: generatedLesson.lessonID)
        var state = record.state
        let validQuestionIDs = Set(generatedLesson.comprehensionQuestions.map(\.id))

        if let phase = response.statePatch.phase {
            state.phase = phase
        }

        state.currentQuestionID = response.statePatch.currentQuestionID

        for id in response.statePatch.acceptedQuestionIDsAdd where validQuestionIDs.contains(id) {
            state.acceptedQuestionIDs.insert(id)
        }

        if !response.statePatch.mistakeNotesAdd.isEmpty {
            state.mistakeNotes.append(contentsOf: response.statePatch.mistakeNotesAdd)
            if state.mistakeNotes.count > 30 {
                state.mistakeNotes = Array(state.mistakeNotes.suffix(30))
            }
        }

        if let translationQuiz = response.translationQuiz {
            state.translationQuiz = translationQuiz
            state.phase = .translation
        } else if state.acceptedQuestionIDs.count == generatedLesson.comprehensionQuestions.count,
                  state.phase == .comprehension {
            state.phase = .discussion
        }

        state.updatedAt = Date()
        record.state = state
        records[generatedLesson.lessonID] = record
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
