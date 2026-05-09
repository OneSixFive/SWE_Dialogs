import SwiftUI
import UIKit

struct DialogsPlanView: View {
    @StateObject private var progress = DialogProgressStore()
    @AppStorage("dialogs_selected_level") private var selectedLevelRaw = DialogLevel.b1.rawValue
    @AppStorage("dialogs_selected_stage") private var selectedStage = 4
    @AppStorage("dialogs_selected_week") private var selectedWeek = 4
    @AppStorage("stage4_show_completed") private var showCompleted = false

    private var selectedLevel: DialogLevel {
        DialogLevel(rawValue: selectedLevelRaw) ?? .b1
    }

    private var stageDays: [DialogDay] {
        DialogContent.days(for: selectedLevel, stage: selectedStage)
    }

    private var selectedWeekDays: [DialogDay] {
        stageDays.filter { $0.weekNumber == selectedWeek }
    }

    private var visibleDays: [DialogDay] {
        if showCompleted {
            return selectedWeekDays
        }
        return selectedWeekDays.filter { !progress.isCompleted($0) }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Picker("Level", selection: $selectedLevelRaw) {
                        ForEach(DialogLevel.allCases) { level in
                            Text(level.rawValue).tag(level.rawValue)
                        }
                    }
                    .pickerStyle(.menu)

                    Picker("Stage", selection: $selectedStage) {
                        ForEach(1...4, id: \.self) { stage in
                            Text("Stage \(stage)").tag(stage)
                        }
                    }
                    .pickerStyle(.menu)

                    Picker("Week", selection: $selectedWeek) {
                        ForEach(1...4, id: \.self) { week in
                            Text("Week \(week)").tag(week)
                        }
                    }
                    .pickerStyle(.menu)

                    Toggle("Show completed", isOn: $showCompleted)

                    Text("Done: \(progress.completedDays.count)/\(stageDays.count)")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if visibleDays.isEmpty {
                    Section {
                        if stageDays.isEmpty {
                            Text("No dialogs have been added for this selection yet.")
                                .foregroundStyle(.secondary)
                        } else {
                            Text("No visible days right now.")
                                .foregroundStyle(.secondary)
                            Button("Show completed days") {
                                showCompleted = true
                            }
                        }
                    }
                } else {
                    Section("Week \(selectedWeek)") {
                        ForEach(visibleDays) { day in
                            DialogDayRow(day: day, completed: progress.isCompleted(day)) {
                                progress.toggle(day)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Dialogs")
            .onAppear {
                progress.loadContext(level: selectedLevel, stage: selectedStage)
            }
            .onChange(of: selectedLevelRaw) { _, _ in
                progress.loadContext(level: selectedLevel, stage: selectedStage)
            }
            .onChange(of: selectedStage) { _, _ in
                progress.loadContext(level: selectedLevel, stage: selectedStage)
            }
        }
    }
}

private struct DialogDayRow: View {
    let day: DialogDay
    let completed: Bool
    let onToggleDone: () -> Void

    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Day \(day.dayNumber)")
                    .font(.headline)

                Spacer()

                Button {
                    UIPasteboard.general.string = day.copyText
                    copied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                        copied = false
                    }
                } label: {
                    Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                        .labelStyle(.titleAndIcon)
                }
                .buttonStyle(.bordered)

                Button {
                    onToggleDone()
                } label: {
                    Image(systemName: completed ? "checkmark.circle.fill" : "circle")
                        .font(.title3)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(completed ? "Mark as not done" : "Mark as done")
            }

            Text(day.prompt)
                .font(.body)
                .textSelection(.enabled)
                .foregroundStyle(completed ? .secondary : .primary)
        }
        .padding(.vertical, 4)
    }
}

typealias Stage4PlanView = DialogsPlanView

#Preview {
    DialogsPlanView()
}
