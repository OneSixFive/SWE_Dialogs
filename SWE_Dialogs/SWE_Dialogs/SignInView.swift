import AuthenticationServices
import CryptoKit
import SwiftUI

struct SignInView: View {
    @EnvironmentObject private var sessionStore: AppSessionStore
    @State private var currentNonce: String?

    var body: some View {
        VStack(spacing: 26) {
            Spacer()

            VStack(spacing: 6) {
                SvenskaWordmark(size: 54)
                Text("SVENSK KONVERSATION · B1–B2")
                    .font(RetroFont.label(10))
                    .tracking(1.4)
                    .foregroundStyle(Retro.brass)
            }
            .padding(.horizontal, 26)
            .padding(.vertical, 16)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Retro.walnutDeep)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(LinearGradient(colors: [Retro.brass, Retro.brassDark], startPoint: .top, endPoint: .bottom), lineWidth: 3)
            )
            .overlay(alignment: .topLeading) { BrassScrew().padding(7) }
            .overlay(alignment: .topTrailing) { BrassScrew().padding(7) }
            .overlay(alignment: .bottomLeading) { BrassScrew().padding(7) }
            .overlay(alignment: .bottomTrailing) { BrassScrew().padding(7) }

            SchoolComputerView(width: 320)
                .padding(.vertical, 10)

            Spacer()

            SignInWithAppleButton(.signIn) { request in
                let nonce = Self.randomNonceString()
                currentNonce = nonce
                request.requestedScopes = [.email]
                request.nonce = Self.sha256(nonce)
            } onCompletion: { result in
                sessionStore.handleSignInCompletion(result, nonce: currentNonce)
                currentNonce = nil
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 50)
            .retroPanel(cornerRadius: 12, padding: 8)
            .padding(.horizontal, 30)
            .disabled(sessionStore.isSigningIn)

            if sessionStore.isSigningIn {
                ProgressView()
                    .tint(Retro.amber)
            }

            if let errorMessage = sessionStore.errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(Retro.paper)
                    .multilineTextAlignment(.center)
                    .padding(10)
                    .background(Retro.orange.opacity(0.85))
                    .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                    .padding(.horizontal, 32)
            }

            BrassPlateLabel(text: "MODELL 1983 · TILLVERKAD I SVERIGE", size: 9, height: 26)
                .padding(.bottom, 8)
        }
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .retroScreenBackground()
        .preferredColorScheme(.dark)
    }

    private static func sha256(_ input: String) -> String {
        let inputData = Data(input.utf8)
        let hashedData = SHA256.hash(data: inputData)
        return hashedData.compactMap { String(format: "%02x", $0) }.joined()
    }

    private static func randomNonceString(length: Int = 32) -> String {
        precondition(length > 0)
        let charset = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")
        var result = ""
        var remainingLength = length

        while remainingLength > 0 {
            var randoms = [UInt8](repeating: 0, count: 16)
            let status = SecRandomCopyBytes(kSecRandomDefault, randoms.count, &randoms)
            guard status == errSecSuccess else {
                fatalError("Unable to generate nonce.")
            }

            for random in randoms where remainingLength > 0 {
                if random < charset.count {
                    result.append(charset[Int(random)])
                    remainingLength -= 1
                }
            }
        }
        return result
    }
}
