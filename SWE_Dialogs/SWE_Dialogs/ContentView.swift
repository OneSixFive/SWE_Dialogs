import SwiftUI
import UIKit
import Combine

struct ContentView: View {
    @StateObject private var historyStore = HistoryStore()
    @StateObject private var createAudioPlayer = AudioPlayerController()
    @StateObject private var historyAudioPlayer = AudioPlayerController()
    @StateObject private var sessionStore = AppSessionStore()

    var body: some View {
        Group {
            if sessionStore.isAuthenticated {
                TabView {
                    LessonsHomeView()
                        .tabItem {
                            Label("Lessons", systemImage: "graduationcap")
                        }

                    VocabularyHomeView()
                        .tabItem {
                            Label("Vocabulary", systemImage: "character.book.closed")
                        }

                    SettingsView()
                        .tabItem {
                            Label("Settings", systemImage: "gearshape")
                        }

                    MoreView(historyStore: historyStore, createAudioPlayer: createAudioPlayer, historyAudioPlayer: historyAudioPlayer)
                        .tabItem {
                            Label("More", systemImage: "ellipsis.circle")
                        }
                }
            } else {
                SignInView()
            }
        }
        .environmentObject(sessionStore)
    }
}

private struct MoreView: View {
    @ObservedObject var historyStore: HistoryStore
    @ObservedObject var createAudioPlayer: AudioPlayerController
    @ObservedObject var historyAudioPlayer: AudioPlayerController

    var body: some View {
        NavigationStack {
            List {
                NavigationLink {
                    GeneratorView(historyStore: historyStore, audioPlayer: createAudioPlayer)
                } label: {
                    Label("Narrate custom dialog", systemImage: "waveform")
                }

                NavigationLink {
                    HistoryView(historyStore: historyStore, audioPlayer: historyAudioPlayer)
                } label: {
                    Label("Custom dialogs history", systemImage: "clock")
                }
            }
            .navigationTitle("More")
        }
    }
}

private struct GeneratorView: View {
    @ObservedObject var historyStore: HistoryStore
    @ObservedObject var audioPlayer: AudioPlayerController

    @AppStorage("tts_model_raw") private var selectedModelRaw = GeminiTTSService.TTSModel.pro25.rawValue
    @State private var dialogText = ""
    @State private var isGenerating = false
    @State private var errorMessage: String?
    @FocusState private var isDialogFocused: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Paste dialog")
                        .font(.headline)

                    TextEditor(text: $dialogText)
                        .font(.body)
                        .focused($isDialogFocused)
                        .frame(height: 280)
                        .padding(8)
                        .overlay {
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.secondary.opacity(0.3), lineWidth: 1)
                        }

                    Picker("Model", selection: $selectedModelRaw) {
                        ForEach(GeminiTTSService.TTSModel.allCases) { model in
                            Text(model.title).tag(model.rawValue)
                        }
                    }
                    .pickerStyle(.menu)

                    Button {
                        Task {
                            await generate()
                        }
                    } label: {
                        if isGenerating {
                            ProgressView()
                                .frame(maxWidth: .infinity)
                        } else {
                            Text("Generate Audio")
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isGenerating)

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }

                    if let currentURL = audioPlayer.currentURL {
                        PlayerSection(audioPlayer: audioPlayer, fileURL: currentURL)
                    }
                }
            }
            .padding()
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") {
                        isDialogFocused = false
                    }
                }
            }
            .navigationTitle("Dialog TTS")
        }
    }

    private func generate() async {
        let trimmedDialog = dialogText.trimmingCharacters(in: .whitespacesAndNewlines)
        let selectedModel = GeminiTTSService.TTSModel(rawValue: selectedModelRaw) ?? .pro25

        guard !trimmedDialog.isEmpty else {
            errorMessage = "Paste a dialog first."
            return
        }

        isGenerating = true
        errorMessage = nil

        do {
            let wavData = try await GeminiTTSService.generateWav(
                dialog: trimmedDialog,
                model: selectedModel
            )
            let fileURL = try FileStorage.saveWavFile(data: wavData)
            let item = HistoryItem(transcript: trimmedDialog, fileName: fileURL.lastPathComponent, createdAt: .now)
            historyStore.add(item)
            audioPlayer.load(url: fileURL)
        } catch {
            errorMessage = error.localizedDescription
        }

        isGenerating = false
    }
}

struct PlayerSection: View {
    @ObservedObject var audioPlayer: AudioPlayerController
    let fileURL: URL

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Player")
                .font(.headline)

            HStack(spacing: 12) {
                Button(audioPlayer.isPlaying ? "Pause" : "Play") {
                    audioPlayer.togglePlayback()
                }
                .buttonStyle(.bordered)

                ShareLink(item: fileURL) {
                    Label("Download", systemImage: "square.and.arrow.down")
                }
            }

            Slider(
                value: Binding(
                    get: { audioPlayer.currentTime },
                    set: { audioPlayer.seek(to: $0) }
                ),
                in: 0...max(audioPlayer.duration, 1)
            )

            Text("\(audioPlayer.currentTime.formattedTime) / \(audioPlayer.duration.formattedTime)")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 8)
    }
}

private struct HistoryView: View {
    @ObservedObject var historyStore: HistoryStore
    @ObservedObject var audioPlayer: AudioPlayerController

    var body: some View {
        NavigationStack {
            List {
                if historyStore.items.isEmpty {
                    Text("No history yet.")
                        .foregroundStyle(.secondary)
                }

                ForEach(historyStore.items) { item in
                    NavigationLink {
                        HistoryDetailView(item: item, audioPlayer: audioPlayer)
                    } label: {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(item.createdAt.formatted(date: .abbreviated, time: .shortened))
                                .font(.subheadline)
                                .foregroundStyle(.secondary)

                            Text(item.transcript)
                                .lineLimit(3)
                                .font(.body)
                        }
                        .padding(.vertical, 4)
                    }
                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                        Button(role: .destructive) {
                            guard let index = historyStore.items.firstIndex(where: { $0.id == item.id }) else {
                                return
                            }
                            historyStore.remove(at: IndexSet(integer: index))
                        } label: {
                            Label("Delete", systemImage: "trash")
                        }
                    }
                }
                .onDelete(perform: historyStore.remove)
            }
            .navigationTitle("History")
        }
    }
}

private struct HistoryDetailView: View {
    let item: HistoryItem
    @ObservedObject var audioPlayer: AudioPlayerController

    private var fileURL: URL {
        FileStorage.documentsDirectory.appendingPathComponent(item.fileName)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("Dialog")
                    .font(.headline)

                SelectableTextView(text: item.transcript)
                .frame(height: 280)
                .padding(8)
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.secondary.opacity(0.3), lineWidth: 1)
                }

                PlayerSection(audioPlayer: audioPlayer, fileURL: fileURL)

                Spacer(minLength: 0)
            }
            .padding()
        }
        .navigationTitle(item.createdAt.formatted(date: .abbreviated, time: .shortened))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            audioPlayer.load(url: fileURL)
        }
    }
}

private struct SelectableTextView: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.isEditable = false
        textView.isSelectable = true
        textView.isScrollEnabled = true
        textView.backgroundColor = .clear
        textView.textContainerInset = .zero
        textView.textContainer.lineFragmentPadding = 0
        textView.font = UIFont.preferredFont(forTextStyle: .body)
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        uiView.text = text
    }
}

private struct SettingsView: View {
    @EnvironmentObject private var sessionStore: AppSessionStore

    var body: some View {
        NavigationStack {
            Form {
                Section("Account") {
                    if let email = sessionStore.user?.email {
                        Text(email)
                    } else {
                        Text("Signed in with Apple")
                    }
                }

                Section {
                    Button("Sign Out", role: .destructive) {
                        sessionStore.signOut()
                    }
                }
            }
            .navigationTitle("Settings")
        }
    }
}

private extension TimeInterval {
    var formattedTime: String {
        let seconds = Int(self)
        let minutesPart = seconds / 60
        let secondsPart = seconds % 60
        return String(format: "%02d:%02d", minutesPart, secondsPart)
    }
}

#Preview {
    ContentView()
}
