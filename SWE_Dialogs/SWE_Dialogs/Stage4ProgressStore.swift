import Combine
import Foundation

final class DialogProgressStore: ObservableObject {
    @Published private(set) var completedDays: Set<Int> = []

    private let defaults = UserDefaults.standard
    private var currentLevel: DialogLevel = .b1
    private var currentStage: Int = 4

    private var completedKey: String {
        "dialogs_completed_\(currentLevel.rawValue.lowercased())_stage_\(currentStage)"
    }

    init() {
        migrateLegacyStage4StateIfNeeded()
        loadContext(level: .b1, stage: 4)
    }

    func loadContext(level: DialogLevel, stage: Int) {
        currentLevel = level
        currentStage = stage

        if let saved = defaults.array(forKey: completedKey) as? [Int] {
            completedDays = Set(saved)
            return
        }

        if level == .b1, stage == 4 {
            completedDays = Set(1...21)
            save()
            return
        }

        completedDays = []
    }

    func isCompleted(_ day: DialogDay) -> Bool {
        completedDays.contains(day.progressIndex)
    }

    func toggle(_ day: DialogDay) {
        if completedDays.contains(day.progressIndex) {
            completedDays.remove(day.progressIndex)
        } else {
            completedDays.insert(day.progressIndex)
        }
        save()
    }

    private func save() {
        defaults.set(Array(completedDays).sorted(), forKey: completedKey)
    }

    private func migrateLegacyStage4StateIfNeeded() {
        let legacyCompletedKey = "stage4_completed_days"
        let legacyPrefillKey = "stage4_prefilled_all_done_v1"
        let legacyWeek4MigrationKey = "stage4_week4_pending_migration_v1"
        let modernKey = "dialogs_completed_b1_stage_4"

        guard defaults.object(forKey: legacyCompletedKey) != nil else {
            return
        }

        if defaults.object(forKey: modernKey) == nil {
            let legacyCompleted = defaults.array(forKey: legacyCompletedKey) as? [Int] ?? []
            defaults.set(legacyCompleted, forKey: modernKey)
        }

        defaults.removeObject(forKey: legacyCompletedKey)
        defaults.removeObject(forKey: legacyPrefillKey)
        defaults.removeObject(forKey: legacyWeek4MigrationKey)
    }
}

typealias Stage4ProgressStore = DialogProgressStore
