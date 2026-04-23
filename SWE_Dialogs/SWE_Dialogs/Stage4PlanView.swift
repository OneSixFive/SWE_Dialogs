import SwiftUI
import UIKit

struct Stage4PlanView: View {
    @StateObject private var progress = Stage4ProgressStore()
    @AppStorage("stage4_show_completed") private var showCompleted = false

    private var visibleDays: [Stage4Day] {
        if showCompleted {
            return Stage4Content.days
        }
        return Stage4Content.days.filter { !progress.isCompleted($0) }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Toggle("Show completed", isOn: $showCompleted)

                    Text("Done: \(progress.completedDays.count)/\(Stage4Content.days.count)")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if visibleDays.isEmpty {
                    Section {
                        Text("No visible days right now.")
                            .foregroundStyle(.secondary)
                        Button("Show completed days") {
                            showCompleted = true
                        }
                    }
                } else {
                    ForEach([1, 2, 3, 4], id: \.self) { week in
                        let weekDays = visibleDays.filter { $0.weekNumber == week }

                        if !weekDays.isEmpty {
                            Section("Week \(week)") {
                                ForEach(weekDays) { day in
                                    Stage4DayRow(day: day, completed: progress.isCompleted(day)) {
                                        progress.toggle(day)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Dialogs")
        }
    }
}

private struct Stage4DayRow: View {
    let day: Stage4Day
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
                    UIPasteboard.general.string = "Stage 4, Week \(day.weekNumber), Day \(day.dayNumber)\n\n\(day.prompt)"
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

#Preview {
    Stage4PlanView()
}
