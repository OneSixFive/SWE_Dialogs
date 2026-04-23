import Combine
import Foundation

struct HistoryItem: Identifiable, Codable {
    let id: UUID
    let transcript: String
    let fileName: String
    let createdAt: Date

    init(id: UUID = UUID(), transcript: String, fileName: String, createdAt: Date) {
        self.id = id
        self.transcript = transcript
        self.fileName = fileName
        self.createdAt = createdAt
    }
}

final class HistoryStore: ObservableObject {
    @Published private(set) var items: [HistoryItem] = []

    private let historyURL = FileStorage.documentsDirectory.appendingPathComponent("history.json")

    init() {
        load()
    }

    func add(_ item: HistoryItem) {
        items.insert(item, at: 0)
        save()
    }

    func remove(at offsets: IndexSet) {
        let removed = offsets.map { items[$0] }

        for item in removed {
            let url = FileStorage.documentsDirectory.appendingPathComponent(item.fileName)
            try? FileManager.default.removeItem(at: url)
        }

        for index in offsets.sorted(by: >) {
            items.remove(at: index)
        }
        save()
    }

    private func load() {
        guard let data = try? Data(contentsOf: historyURL) else { return }

        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            items = try decoder.decode([HistoryItem].self, from: data)
        } catch {
            items = []
        }
    }

    private func save() {
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted]
            encoder.dateEncodingStrategy = .iso8601
            let data = try encoder.encode(items)
            try data.write(to: historyURL, options: [.atomic])
        } catch {
            // Keep UI responsive: ignore persistence failures for this simple app.
        }
    }
}
