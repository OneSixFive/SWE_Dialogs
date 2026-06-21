import Combine
import Foundation

@MainActor
final class VocabularyPracticeStore: ObservableObject {
    @Published private(set) var practices: [VocabularyPracticeSummary] = []
    @Published private(set) var sessions: [String: VocabularyPractice] = [:]
    @Published private(set) var isLoading = false
    @Published private(set) var isGenerating = false
    @Published var errorMessage: String?

    private var configuredUserID: Int?

    func configure(userID: Int?) {
        guard configuredUserID != userID else { return }
        configuredUserID = userID
        practices = []
        sessions = [:]
        errorMessage = nil
        guard userID != nil else { return }
        Task { await refresh() }
    }

    func refresh() async {
        guard configuredUserID != nil, !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            practices = try await BackendClient.shared.vocabularyPractices()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func generate() async -> VocabularyPractice? {
        guard configuredUserID != nil, !isGenerating else { return nil }
        isGenerating = true
        errorMessage = nil
        defer { isGenerating = false }
        do {
            let practice = try await BackendClient.shared.createVocabularyPractice()
            update(practice)
            return practice
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func load(id: String) async -> VocabularyPractice? {
        if let session = sessions[id] { return session }
        do {
            let practice = try await BackendClient.shared.vocabularyPractice(id: id)
            update(practice)
            return practice
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func send(id: String, message: String) async -> VocabularyPractice? {
        do {
            let practice = try await BackendClient.shared.sendVocabularyPracticeMessage(id: id, message: message)
            update(practice)
            errorMessage = nil
            return practice
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func advance(id: String) async -> VocabularyPractice? {
        do {
            let practice = try await BackendClient.shared.advanceVocabularyPractice(id: id)
            update(practice)
            errorMessage = nil
            return practice
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func abandon(id: String) async -> VocabularyPractice? {
        do {
            let practice = try await BackendClient.shared.abandonVocabularyPractice(id: id)
            update(practice)
            errorMessage = nil
            return practice
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func session(id: String) -> VocabularyPractice? {
        sessions[id]
    }

    private func update(_ practice: VocabularyPractice) {
        sessions[practice.id] = practice
        if let index = practices.firstIndex(where: { $0.id == practice.id }) {
            practices[index] = practice.summary
        } else {
            practices.insert(practice.summary, at: 0)
        }
        practices.sort { $0.createdAt > $1.createdAt }
    }
}
