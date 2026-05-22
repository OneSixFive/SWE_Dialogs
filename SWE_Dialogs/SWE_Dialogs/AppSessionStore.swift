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
        isAuthenticated = KeychainStore.loadSessionToken() != nil
    }

    func handleSignInCompletion(_ result: Result<ASAuthorization, Error>, nonce: String?) {
        Task {
            await signIn(result, nonce: nonce)
        }
    }

    func signOut() {
        KeychainStore.deleteSessionToken()
        user = nil
        errorMessage = nil
        isAuthenticated = false
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
            isAuthenticated = true
        } catch {
            errorMessage = error.localizedDescription
            isAuthenticated = KeychainStore.loadSessionToken() != nil
        }
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
