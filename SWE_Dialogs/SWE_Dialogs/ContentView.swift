import SwiftUI
import UIKit
import Combine

struct ContentView: View {
    @StateObject private var historyStore = HistoryStore()
    @StateObject private var chatStore = ChatStore()
    @StateObject private var createAudioPlayer = AudioPlayerController()
    @StateObject private var historyAudioPlayer = AudioPlayerController()

    var body: some View {
        TabView {
            GeneratorView(historyStore: historyStore, audioPlayer: createAudioPlayer)
                .tabItem {
                    Label("Create", systemImage: "waveform")
                }

            HistoryView(historyStore: historyStore, audioPlayer: historyAudioPlayer)
                .tabItem {
                    Label("History", systemImage: "clock")
                }

            DialogsPlanView()
                .tabItem {
                    Label("Dialogs", systemImage: "checklist")
                }

            ChatsListView(chatStore: chatStore)
                .tabItem {
                    Label("Chats", systemImage: "message")
                }

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
        }
    }
}

private struct GeneratorView: View {
    @ObservedObject var historyStore: HistoryStore
    @ObservedObject var audioPlayer: AudioPlayerController

    @AppStorage("gemini_api_key") private var apiKey = ""
    @AppStorage("tts_model_raw") private var selectedModelRaw = GeminiTTSService.TTSModel.flash31.rawValue
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
        let trimmedKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedDialog = dialogText.trimmingCharacters(in: .whitespacesAndNewlines)
        let selectedModel = GeminiTTSService.TTSModel(rawValue: selectedModelRaw) ?? .flash31

        guard !trimmedKey.isEmpty else {
            errorMessage = "Add your Gemini API key first."
            return
        }

        guard !trimmedDialog.isEmpty else {
            errorMessage = "Paste a dialog first."
            return
        }

        isGenerating = true
        errorMessage = nil

        do {
            let wavData = try await GeminiTTSService.generateWav(
                dialog: trimmedDialog,
                apiKey: trimmedKey,
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

private struct PlayerSection: View {
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
    @AppStorage("gemini_api_key") private var apiKey = ""
    @AppStorage("openai_api_key") private var openAIAPIKey = ""
    @AppStorage("openai_chat_model") private var openAIChatModel = "gpt-5.4-nano"

    var body: some View {
        NavigationStack {
            Form {
                Section("Gemini") {
                    SecureField("Gemini API key", text: $apiKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section("OpenAI") {
                    SecureField("OpenAI API key", text: $openAIAPIKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()

                    TextField("Chat model", text: $openAIChatModel)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    Text("The key is saved on this device for future app launches.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
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

private struct ChatsListView: View {
    @ObservedObject var chatStore: ChatStore
    @AppStorage("openai_api_key") private var openAIAPIKey = ""
    @State private var path: [UUID] = []
    @State private var errorMessage: String?
    @State private var isCreating = false

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if chatStore.sessions.isEmpty {
                    Text("No chats yet.")
                        .foregroundStyle(.secondary)
                }

                ForEach(chatStore.sessions) { session in
                    Button {
                        path.append(session.id)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(session.title)
                                .font(.headline)
                                .lineLimit(1)
                            Text(session.updatedAt.formatted(date: .abbreviated, time: .shortened))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)
                    }
                }
                .onDelete(perform: chatStore.deleteSessions)
            }
            .navigationTitle("Chats")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await createChat() }
                    } label: {
                        if isCreating {
                            ProgressView()
                        } else {
                            Image(systemName: "plus")
                        }
                    }
                    .disabled(isCreating)
                }
            }
            .safeAreaInset(edge: .bottom) {
                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                        .padding(.vertical, 8)
                }
            }
            .navigationDestination(for: UUID.self) { sessionID in
                ChatDetailView(chatStore: chatStore, sessionID: sessionID)
            }
        }
    }

    private func createChat() async {
        let trimmedKey = openAIAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedKey.isEmpty else {
            errorMessage = "Add your OpenAI API key in Settings."
            return
        }

        isCreating = true
        errorMessage = nil
        defer { isCreating = false }

        do {
            let session = try await chatStore.createSession(apiKey: trimmedKey)
            path.append(session.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct ChatDetailView: View {
    @ObservedObject var chatStore: ChatStore
    let sessionID: UUID

    @AppStorage("openai_api_key") private var openAIAPIKey = ""
    @AppStorage("openai_chat_model") private var openAIChatModel = "gpt-5.4-nano"

    @State private var draft = ""
    @State private var isSending = false
    @State private var errorMessage: String?

    private var session: ChatSession? {
        chatStore.session(id: sessionID)
    }

    private var messages: [ChatMessage] {
        chatStore.messages(for: sessionID)
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if messages.isEmpty {
                            Text("Start the conversation.")
                                .foregroundStyle(.secondary)
                        }

                        ForEach(messages) { message in
                            HStack {
                                if message.role == .assistant { Spacer(minLength: 40) }

                                Text(message.content)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 10)
                                    .background(message.role == .user ? Color.accentColor : Color.secondary.opacity(0.2))
                                    .foregroundStyle(message.role == .user ? Color.white : Color.primary)
                                    .clipShape(RoundedRectangle(cornerRadius: 12))

                                if message.role == .user { Spacer(minLength: 40) }
                            }
                            .id(message.id)
                        }
                    }
                    .padding()
                }
                .onChange(of: messages.count) { _, _ in
                    guard let lastID = messages.last?.id else { return }
                    withAnimation {
                        proxy.scrollTo(lastID, anchor: .bottom)
                    }
                }
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
                    .padding(.top, 8)
            }

            HStack(spacing: 8) {
                TextField("Type a message", text: $draft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...6)
                    .disabled(isSending)

                Button("Send") {
                    Task { await sendMessage() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isSending || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding()
        }
        .navigationTitle(session?.title ?? "Chat")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func sendMessage() async {
        let trimmedKey = openAIAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = openAIChatModel.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !trimmedKey.isEmpty else {
            errorMessage = "Add your OpenAI API key in Settings."
            return
        }

        guard !model.isEmpty else {
            errorMessage = "Set a chat model in Settings."
            return
        }

        guard !text.isEmpty else {
            return
        }

        draft = ""
        errorMessage = nil
        isSending = true
        defer { isSending = false }

        do {
            try await chatStore.sendMessage(sessionID: sessionID, text: text, apiKey: trimmedKey, model: model)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

struct ChatSession: Identifiable, Codable {
    let id: UUID
    let conversationID: String
    var title: String
    let createdAt: Date
    var updatedAt: Date
}

struct ChatMessage: Identifiable, Codable {
    enum Role: String, Codable {
        case user
        case assistant
    }

    let id: UUID
    let sessionID: UUID
    let role: Role
    let content: String
    let createdAt: Date
}

@MainActor
final class ChatStore: ObservableObject {
    @Published private(set) var sessions: [ChatSession] = []
    @Published private var messageMap: [UUID: [ChatMessage]] = [:]

    private let sessionsURL = FileStorage.documentsDirectory.appendingPathComponent("chat_sessions.json")
    private let messagesURL = FileStorage.documentsDirectory.appendingPathComponent("chat_messages.json")

    init() {
        load()
    }

    func session(id: UUID) -> ChatSession? {
        sessions.first(where: { $0.id == id })
    }

    func messages(for sessionID: UUID) -> [ChatMessage] {
        messageMap[sessionID, default: []]
    }

    func createSession(apiKey: String) async throws -> ChatSession {
        let conversationID = try await OpenAIChatService.createConversation(apiKey: apiKey)
        let now = Date()
        let session = ChatSession(
            id: UUID(),
            conversationID: conversationID,
            title: "New chat",
            createdAt: now,
            updatedAt: now
        )
        sessions.insert(session, at: 0)
        messageMap[session.id] = []
        save()
        return session
    }

    func sendMessage(sessionID: UUID, text: String, apiKey: String, model: String) async throws {
        guard let session = session(id: sessionID) else {
            throw ChatStoreError.sessionNotFound
        }

        appendMessage(
            ChatMessage(id: UUID(), sessionID: sessionID, role: .user, content: text, createdAt: .now),
            updateTitleFromUserText: true
        )

        let assistantText = try await OpenAIChatService.sendMessage(
            apiKey: apiKey,
            model: model,
            conversationID: session.conversationID,
            text: text
        )

        appendMessage(
            ChatMessage(id: UUID(), sessionID: sessionID, role: .assistant, content: assistantText, createdAt: .now),
            updateTitleFromUserText: false
        )
    }

    func deleteSessions(at offsets: IndexSet) {
        let removedIDs = offsets.map { sessions[$0].id }
        for index in offsets.sorted(by: >) {
            sessions.remove(at: index)
        }
        for id in removedIDs {
            messageMap[id] = nil
        }
        save()
    }

    private func appendMessage(_ message: ChatMessage, updateTitleFromUserText: Bool) {
        var messages = messageMap[message.sessionID, default: []]
        messages.append(message)
        messageMap[message.sessionID] = messages

        if let index = sessions.firstIndex(where: { $0.id == message.sessionID }) {
            sessions[index].updatedAt = Date()
            if updateTitleFromUserText && sessions[index].title == "New chat" {
                sessions[index].title = String(message.content.prefix(40))
            }
            let session = sessions.remove(at: index)
            sessions.insert(session, at: 0)
        }

        save()
    }

    private func load() {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601

        if let sessionsData = try? Data(contentsOf: sessionsURL),
           let decodedSessions = try? decoder.decode([ChatSession].self, from: sessionsData) {
            sessions = decodedSessions
        }

        if let messagesData = try? Data(contentsOf: messagesURL),
           let decodedMessages = try? decoder.decode([UUID: [ChatMessage]].self, from: messagesData) {
            messageMap = decodedMessages
        }
    }

    private func save() {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted]
        encoder.dateEncodingStrategy = .iso8601

        do {
            let sessionsData = try encoder.encode(sessions)
            try sessionsData.write(to: sessionsURL, options: [.atomic])

            let messagesData = try encoder.encode(messageMap)
            try messagesData.write(to: messagesURL, options: [.atomic])
        } catch {
            // Ignore persistence errors in this prototype path.
        }
    }
}

enum ChatStoreError: LocalizedError {
    case sessionNotFound

    var errorDescription: String? {
        switch self {
        case .sessionNotFound:
            return "Chat session not found."
        }
    }
}

enum OpenAIChatService {
    static func createConversation(apiKey: String) async throws -> String {
        guard let url = URL(string: "https://api.openai.com/v1/conversations") else {
            throw OpenAIChatError.invalidRequest
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.httpBody = Data("{}".utf8)

        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        let payload = try JSONDecoder().decode(CreateConversationResponse.self, from: data)
        return payload.id
    }

    static func sendMessage(apiKey: String, model: String, conversationID: String, text: String) async throws -> String {
        guard let url = URL(string: "https://api.openai.com/v1/responses") else {
            throw OpenAIChatError.invalidRequest
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")

        let body = SendMessageRequest(
            model: model,
            conversation: conversationID,
            input: [InputMessage(role: "user", content: text)]
        )
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response: response, data: data)
        do {
            let payload = try JSONDecoder().decode(ResponsePayload.self, from: data)
            if let outputText = payload.outputText?.trimmingCharacters(in: .whitespacesAndNewlines),
               !outputText.isEmpty {
                return outputText
            }

            let flattened = payload.flattenedOutputText.trimmingCharacters(in: .whitespacesAndNewlines)
            if !flattened.isEmpty {
                return flattened
            }

            throw OpenAIChatError.parseError(
                "No assistant text in response. Raw: \(rawSnippet(from: data))"
            )
        } catch let error as OpenAIChatError {
            throw error
        } catch {
            throw OpenAIChatError.parseError(
                "Failed to parse response: \(error.localizedDescription). Raw: \(rawSnippet(from: data))"
            )
        }
    }

    private static func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw OpenAIChatError.invalidResponse
        }

        guard (200...299).contains(http.statusCode) else {
            if let apiError = try? JSONDecoder().decode(OpenAIErrorEnvelope.self, from: data) {
                throw OpenAIChatError.apiError(apiError.error.message)
            }
            let raw = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw OpenAIChatError.apiError(raw)
        }
    }

    private static func rawSnippet(from data: Data) -> String {
        let raw = String(data: data, encoding: .utf8) ?? "<non-utf8 response>"
        if raw.count > 500 {
            return String(raw.prefix(500)) + "..."
        }
        return raw
    }
}

private struct CreateConversationResponse: Decodable {
    let id: String
}

private struct SendMessageRequest: Encodable {
    let model: String
    let conversation: String
    let input: [InputMessage]
}

private struct InputMessage: Encodable {
    let role: String
    let content: String
}

private struct ResponsePayload: Decodable {
    let outputText: String?
    let output: [OutputItem]?

    enum CodingKeys: String, CodingKey {
        case outputText = "output_text"
        case output
    }

    var flattenedOutputText: String {
        guard let output else { return "" }
        let chunks = output.flatMap { item in
            item.content?.compactMap { $0.text } ?? []
        }
        return chunks.joined(separator: "\n")
    }
}

private struct OutputItem: Decodable {
    let content: [OutputContent]?
}

private struct OutputContent: Decodable {
    let text: String?
    let type: String?

    enum CodingKeys: String, CodingKey {
        case text
        case type
    }
}

private struct OpenAIErrorEnvelope: Decodable {
    struct APIError: Decodable {
        let message: String
    }

    let error: APIError
}

enum OpenAIChatError: LocalizedError {
    case invalidRequest
    case invalidResponse
    case apiError(String)
    case parseError(String)

    var errorDescription: String? {
        switch self {
        case .invalidRequest:
            return "Failed to build OpenAI request."
        case .invalidResponse:
            return "Invalid response from OpenAI."
        case .apiError(let message):
            return "OpenAI API error: \(message)"
        case .parseError(let details):
            return "OpenAI response parse error: \(details)"
        }
    }
}

#Preview {
    ContentView()
}
