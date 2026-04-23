import Combine
import Foundation

final class Stage4ProgressStore: ObservableObject {
    @Published private(set) var completedDays: Set<Int> = []

    private let completedKey = "stage4_completed_days"
    private let prefillKey = "stage4_prefilled_all_done_v1"
    private let week4PendingMigrationKey = "stage4_week4_pending_migration_v1"
    private let defaults = UserDefaults.standard

    init() {
        let saved = defaults.array(forKey: completedKey) as? [Int] ?? []
        completedDays = Set(saved)

        // Per user request, start with Stage 4 days marked as already done.
        if !defaults.bool(forKey: prefillKey) {
            completedDays = Set(Stage4Content.days.map(\.dayNumber))
            save()
            defaults.set(true, forKey: prefillKey)
        }

        // One-time correction: weeks 1-3 done, week 4 pending.
        if !defaults.bool(forKey: week4PendingMigrationKey) {
            let allDays = Set(Stage4Content.days.map(\.dayNumber))
            if completedDays == allDays {
                completedDays = Set(1...21)
                save()
            }
            defaults.set(true, forKey: week4PendingMigrationKey)
        }
    }

    func isCompleted(_ day: Stage4Day) -> Bool {
        completedDays.contains(day.dayNumber)
    }

    func toggle(_ day: Stage4Day) {
        if completedDays.contains(day.dayNumber) {
            completedDays.remove(day.dayNumber)
        } else {
            completedDays.insert(day.dayNumber)
        }
        save()
    }

    private func save() {
        defaults.set(Array(completedDays).sorted(), forKey: completedKey)
    }
}
