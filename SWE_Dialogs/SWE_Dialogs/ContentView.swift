import SwiftUI
import UIKit
import Combine

struct ContentView: View {
    @StateObject private var historyStore = HistoryStore()
    @StateObject private var createAudioPlayer = AudioPlayerController()
    @StateObject private var historyAudioPlayer = AudioPlayerController()
    @StateObject private var sessionStore = AppSessionStore()
    @State private var selectedTab: RetroTab = .lessons

    var body: some View {
        Group {
            if sessionStore.isAuthenticated {
                TabView(selection: $selectedTab) {
                    LessonsHomeView()
                        .tag(RetroTab.lessons)

                    VocabularyHomeView()
                        .tag(RetroTab.words)

                    MoreView(historyStore: historyStore, createAudioPlayer: createAudioPlayer, historyAudioPlayer: historyAudioPlayer)
                        .tag(RetroTab.more)
                }
                .environment(\.retroTabSelection, $selectedTab)
            } else {
                SignInView()
            }
        }
        .environmentObject(sessionStore)
        .preferredColorScheme(.dark)
        .tint(Retro.mustard)
    }
}

private struct MoreView: View {
    @EnvironmentObject private var sessionStore: AppSessionStore
    @ObservedObject var historyStore: HistoryStore
    @ObservedObject var createAudioPlayer: AudioPlayerController
    @ObservedObject var historyAudioPlayer: AudioPlayerController
    @State private var showSignOutConfirmation = false
    @State private var isSignOutGuardOpen = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 18) {
                    SvenskaWordmark(size: 40)
                        .padding(.top, 8)

                    accountPlate

                    VStack(spacing: 12) {
                        NavigationLink {
                            GeneratorView(historyStore: historyStore, audioPlayer: createAudioPlayer)
                        } label: {
                            MoreRowLabel(title: "Berätta egen dialog", subtitle: "Klistra in en dialog och lyssna", systemImage: "mic.fill")
                        }

                        NavigationLink {
                            HistoryView(historyStore: historyStore, audioPlayer: historyAudioPlayer)
                        } label: {
                            MoreRowLabel(title: "Mina dialoger", subtitle: "Tidigare inspelningar", systemImage: "doc.text.fill")
                        }
                    }
                    .buttonStyle(RetroKeyStyle(tint: .beige))

                    signOutSwitch
                        .padding(.top, 10)

                    Text("Svenska · Version \(Self.versionText)")
                        .font(RetroFont.label(10, weight: .medium))
                        .foregroundStyle(Retro.labelOnDarkSoft)
                        .padding(.top, 4)
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 24)
            }
            .retroScreenBackground()
            .toolbar(.hidden, for: .navigationBar)
            .retroTabBar()
            .confirmationDialog("Logga ut?", isPresented: $showSignOutConfirmation, titleVisibility: .visible) {
                Button("Logga ut", role: .destructive) {
                    sessionStore.signOut()
                }
                Button("Avbryt", role: .cancel) {
                    isSignOutGuardOpen = false
                }
            }
        }
    }

    private var accountPlate: some View {
        VStack(alignment: .leading, spacing: 8) {
            plateRow("Användare", sessionStore.user?.email ?? "Apple-ID")
            plateRow("Modell", "1983")
            plateRow("Tillverkad", "i Sverige")
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(LinearGradient(colors: [Retro.brass.mix(with: .white, by: 0.15), Retro.brassDark], startPoint: .top, endPoint: .bottom))
        )
        .overlay(alignment: .topLeading) { BrassScrew().padding(6) }
        .overlay(alignment: .topTrailing) { BrassScrew().padding(6) }
        .overlay(alignment: .bottomLeading) { BrassScrew().padding(6) }
        .overlay(alignment: .bottomTrailing) { BrassScrew().padding(6) }
        .shadow(color: .black.opacity(0.4), radius: 4, y: 3)
    }

    private func plateRow(_ title: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title.uppercased())
                .font(RetroFont.label(10))
                .tracking(1)
                .foregroundStyle(Retro.walnutDeep.opacity(0.75))
            Spacer(minLength: 12)
            Text(value)
                .font(RetroFont.digits(13))
                .foregroundStyle(Retro.walnutDeep)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }

    private var signOutSwitch: some View {
        HStack(spacing: 14) {
            Button {
                withAnimation(.snappy(duration: 0.2)) {
                    isSignOutGuardOpen.toggle()
                }
            } label: {
                ZStack {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Retro.orange)
                        .frame(width: 26, height: 34)
                    RoundedRectangle(cornerRadius: 4)
                        .fill(
                            LinearGradient(colors: [Retro.mustard, Retro.ink], startPoint: .leading, endPoint: .trailing)
                        )
                        .opacity(0.85)
                        .frame(width: 34, height: 40)
                        .rotation3DEffect(.degrees(isSignOutGuardOpen ? 70 : 0), axis: (x: 1, y: 0, z: 0), anchor: .top)
                }
                .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isSignOutGuardOpen ? "Stäng skyddet" : "Öppna skyddet för utloggning")

            VStack(alignment: .leading, spacing: 2) {
                Text("LOGGA UT")
                    .font(RetroFont.label(14))
                    .foregroundStyle(Retro.labelOnDark)
                Text(isSignOutGuardOpen ? "Tryck igen för att logga ut" : "Lyft skyddet först")
                    .font(RetroFont.label(10, weight: .medium))
                    .foregroundStyle(Retro.labelOnDarkSoft)
            }

            Spacer()

            Button {
                showSignOutConfirmation = true
            } label: {
                RetroKeyLabel(systemImage: "power")
            }
            .buttonStyle(RetroKeyStyle(tint: .orange))
            .frame(width: 58, height: 52)
            .disabled(!isSignOutGuardOpen)
        }
        .retroPanel(padding: 12)
    }

    private static var versionText: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = info?["CFBundleVersion"] as? String ?? ""
        return build.isEmpty ? version : "\(version) (\(build))"
    }
}

private struct MoreRowLabel: View {
    let title: String
    let subtitle: String
    let systemImage: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: systemImage)
                .font(.system(size: 20, weight: .semibold))
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 3) {
                Text(title.uppercased())
                    .font(RetroFont.label(13))
                    .tracking(0.6)
                Text(subtitle)
                    .font(RetroFont.label(11, weight: .medium))
                    .opacity(0.7)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 14, weight: .bold))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
    }
}

private struct GeneratorView: View {
    @ObservedObject var historyStore: HistoryStore
    @ObservedObject var audioPlayer: AudioPlayerController

    @State private var dialogText = ""
    @State private var isGenerating = false
    @State private var errorMessage: String?
    @FocusState private var isDialogFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                RetroScreenHeader(title: "Berätta egen dialog")

                PaperSheet {
                    VStack(alignment: .leading, spacing: 8) {
                        PaperCaption(text: "Klistra in dialog")
                        TextEditor(text: $dialogText)
                            .font(RetroFont.reading())
                            .foregroundStyle(Retro.ink)
                            .scrollContentBackground(.hidden)
                            .focused($isDialogFocused)
                            .frame(height: 280)
                    }
                }

                Button {
                    Task {
                        await generate()
                    }
                } label: {
                    if isGenerating {
                        ProgressView().tint(Retro.paper)
                    } else {
                        RetroKeyLabel(title: "Skapa ljud", systemImage: "waveform", titleSize: 14)
                    }
                }
                .buttonStyle(RetroKeyStyle(tint: .orange))
                .frame(height: 64)
                .disabled(isGenerating)

                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(Retro.orange)
                }

                if let currentURL = audioPlayer.currentURL {
                    PlayerSection(audioPlayer: audioPlayer, fileURL: currentURL)
                }
            }
            .padding()
        }
        .scrollDismissesKeyboard(.interactively)
        .retroScreenBackground()
        .toolbar(.hidden, for: .navigationBar)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Klar") {
                    isDialogFocused = false
                }
            }
        }
    }

    private func generate() async {
        let trimmedDialog = dialogText.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !trimmedDialog.isEmpty else {
            errorMessage = "Klistra in en dialog först."
            return
        }

        isGenerating = true
        errorMessage = nil

        do {
            let wavData = try await GeminiTTSService.generateWav(
                dialog: trimmedDialog
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
        VStack(spacing: 10) {
            HStack(spacing: 12) {
                CassetteView(isPlaying: audioPlayer.isPlaying, width: 170)

                Button {
                    audioPlayer.togglePlayback()
                } label: {
                    RetroKeyLabel(systemImage: audioPlayer.isPlaying ? "pause.fill" : "play.fill")
                }
                .buttonStyle(RetroKeyStyle(tint: .orange))
                .frame(width: 64, height: 64)
                .accessibilityLabel(audioPlayer.isPlaying ? "Pausa" : "Spela")

                ShareLink(item: fileURL) {
                    Image(systemName: "square.and.arrow.up")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(Retro.labelOnDark)
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("Dela ljud")
            }

            HStack(spacing: 10) {
                SegmentProgressBar(progress: audioPlayer.duration > 0 ? audioPlayer.currentTime / audioPlayer.duration : 0)
                Text("\(audioPlayer.currentTime.formattedTime) / \(audioPlayer.duration.formattedTime)")
                    .font(RetroFont.digits(12))
                    .foregroundStyle(Retro.amber)
                    .fixedSize()
            }
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 5).fill(Retro.crt))

            Slider(
                value: Binding(
                    get: { audioPlayer.currentTime },
                    set: { audioPlayer.seek(to: $0) }
                ),
                in: 0...max(audioPlayer.duration, 1)
            )
            .tint(Retro.mustard)
        }
        .retroPanel(padding: 12)
    }
}

private struct HistoryView: View {
    @ObservedObject var historyStore: HistoryStore
    @ObservedObject var audioPlayer: AudioPlayerController

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                RetroScreenHeader(title: "Mina dialoger")
                    .padding(.bottom, 4)

                if historyStore.items.isEmpty {
                    Text("Inga dialoger ännu.")
                        .font(RetroFont.label(13, weight: .medium))
                        .foregroundStyle(Retro.labelOnDarkSoft)
                        .padding(.top, 40)
                }

                ForEach(historyStore.items) { item in
                    NavigationLink {
                        HistoryDetailView(item: item, audioPlayer: audioPlayer)
                    } label: {
                        PaperSheet {
                            VStack(alignment: .leading, spacing: 8) {
                                PaperCaption(text: item.createdAt.formatted(date: .abbreviated, time: .shortened))
                                Text(item.transcript)
                                    .font(RetroFont.reading(.subheadline))
                                    .foregroundStyle(Retro.ink)
                                    .lineLimit(3)
                                    .multilineTextAlignment(.leading)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .contextMenu {
                        Button(role: .destructive) {
                            guard let index = historyStore.items.firstIndex(where: { $0.id == item.id }) else {
                                return
                            }
                            historyStore.remove(at: IndexSet(integer: index))
                        } label: {
                            Label("Radera", systemImage: "trash")
                        }
                    }
                }
            }
            .padding()
        }
        .retroScreenBackground()
        .toolbar(.hidden, for: .navigationBar)
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
            VStack(alignment: .leading, spacing: 16) {
                RetroScreenHeader(title: item.createdAt.formatted(date: .abbreviated, time: .shortened))

                PlayerSection(audioPlayer: audioPlayer, fileURL: fileURL)

                PaperSheet {
                    SelectableTextView(text: item.transcript)
                        .frame(height: 320)
                }
            }
            .padding()
        }
        .retroScreenBackground()
        .toolbar(.hidden, for: .navigationBar)
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
        textView.font = RetroFont.readingUIFont()
        textView.textColor = Retro.uiInk
        return textView
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        uiView.text = text
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
