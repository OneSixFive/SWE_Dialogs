import AuthenticationServices
import Combine
import Foundation

@MainActor
final class AppSessionStore: ObservableObject {
    @Published private(set) var isAuthenticated: Bool
    @Published private(set) var user: BackendUser?
    @Published var errorMessage: String?
    @Published var isSigningIn = false

    init() {
        user = Self.loadCachedUser()
        isAuthenticated = KeychainStore.loadSessionToken() != nil
        if isAuthenticated {
            Task {
                await refreshCurrentUser()
            }
        }
    }

    func handleSignInCompletion(_ result: Result<ASAuthorization, Error>, nonce: String?) {
        Task {
            await signIn(result, nonce: nonce)
        }
    }

    func signOut() {
        KeychainStore.deleteSessionToken()
        Self.clearCachedUser()
        user = nil
        errorMessage = nil
        isAuthenticated = false
    }

    func refreshCurrentUser() async {
        guard KeychainStore.loadSessionToken() != nil else {
            signOut()
            return
        }

        do {
            let currentUser = try await BackendClient.shared.currentUser()
            user = currentUser
            Self.cacheUser(currentUser)
            isAuthenticated = true
        } catch {
            if case BackendError.apiError(let status, _) = error, status == 401 {
                signOut()
            } else if user == nil {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func signIn(_ result: Result<ASAuthorization, Error>, nonce: String?) async {
        isSigningIn = true
        errorMessage = nil
        defer { isSigningIn = false }

        do {
            let authorization = try result.get()
            guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential else {
                throw AppSessionError.invalidCredential
            }
            guard let tokenData = credential.identityToken,
                  let idToken = String(data: tokenData, encoding: .utf8)
            else {
                throw AppSessionError.missingIdentityToken
            }

            let response = try await BackendClient.shared.exchangeAppleToken(idToken: idToken, nonce: nonce)
            try KeychainStore.saveSessionToken(response.sessionToken)
            user = response.user
            Self.cacheUser(response.user)
            isAuthenticated = true
        } catch {
            errorMessage = error.localizedDescription
            isAuthenticated = KeychainStore.loadSessionToken() != nil
        }
    }

    private static let cachedUserKey = "svenska_backend_user"

    private static func cacheUser(_ user: BackendUser) {
        guard let data = try? JSONEncoder().encode(user) else { return }
        UserDefaults.standard.set(data, forKey: cachedUserKey)
    }

    private static func loadCachedUser() -> BackendUser? {
        guard let data = UserDefaults.standard.data(forKey: cachedUserKey) else { return nil }
        return try? JSONDecoder().decode(BackendUser.self, from: data)
    }

    private static func clearCachedUser() {
        UserDefaults.standard.removeObject(forKey: cachedUserKey)
    }
}

enum AppSessionError: LocalizedError {
    case invalidCredential
    case missingIdentityToken

    var errorDescription: String? {
        switch self {
        case .invalidCredential:
            return "Apple did not return a usable credential."
        case .missingIdentityToken:
            return "Apple did not return an identity token."
        }
    }
}
