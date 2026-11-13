package se.jaha.android

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.credentials.ClearCredentialStateRequest
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.lifecycle.lifecycleScope
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom

class MainActivity : ComponentActivity() {
    private val credentials by lazy { CredentialManager.create(this) }
    private val session by lazy { SessionStorage(this) }
    private var appleState: String? = null
    private var appleVerifier: String? = null
    private var signedInAs: String? = null
    private var busy = false
    private var message = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        appleState = savedInstanceState?.getString("appleState")
        appleVerifier = savedInstanceState?.getString("appleVerifier")
        if (!finishAppleSignIn(intent)) {
            val token = session.load()
            if (token != null) runAuth {
                showUser(AuthApi.request("/me", token = token))
            }
        }
        render()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("appleState", appleState)
        outState.putString("appleVerifier", appleVerifier)
        super.onSaveInstanceState(outState)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        finishAppleSignIn(intent)
    }

    private fun render() {
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
        }
        ViewCompat.setOnApplyWindowInsetsListener(layout) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val margin = (24 * resources.displayMetrics.density).toInt()
            view.setPadding(bars.left + margin, bars.top + margin, bars.right + margin, bars.bottom + margin)
            insets
        }
        layout.addView(TextView(this).apply {
            text = "Jaha"
            textSize = 40f
            gravity = Gravity.CENTER
        })

        if (signedInAs == null) {
            layout.addView(button("Logga in med Google", BuildConfig.GOOGLE_CLIENT_ID.isNotEmpty()) {
                signInWithGoogle()
            })
            layout.addView(button("Logga in med Apple") { startAppleSignIn() })
        } else {
            layout.addView(TextView(this).apply {
                text = signedInAs
                gravity = Gravity.CENTER
            })
            layout.addView(button("Logga ut") {
                session.clear()
                signedInAs = null
                runAuth { credentials.clearCredentialState(ClearCredentialStateRequest()) }
            })
        }
        layout.addView(TextView(this).apply {
            text = if (busy) "Vänta …" else message
            gravity = Gravity.CENTER
            accessibilityLiveRegion = TextView.ACCESSIBILITY_LIVE_REGION_POLITE
        })
        setContentView(layout)
    }

    private fun button(label: String, available: Boolean = true, action: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        isEnabled = available && !busy
        setOnClickListener { action() }
    }

    private fun signInWithGoogle() = runAuth {
        val verifier = newVerifier()
        val state = startRequest("google", verifier).getString("state")
        val option = GetSignInWithGoogleOption.Builder(BuildConfig.GOOGLE_CLIENT_ID)
            .setNonce(state)
            .build()
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
        val credential = credentials.getCredential(context = this, request = request).credential
        check(credential is CustomCredential && credential.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL)
        val idToken = GoogleIdTokenCredential.createFrom(credential.data).idToken
        finishSession(AuthApi.request("/auth/google", exchangeBody(state, verifier).put("id_token", idToken)))
    }

    private fun startAppleSignIn() = runAuth {
        val verifier = newVerifier()
        val response = startRequest("apple", verifier)
        val url = Uri.parse(response.getString("authorization_url"))
        check(url.scheme == "https" && url.host == "appleid.apple.com" && url.path == "/auth/authorize")
        appleState = response.getString("state")
        appleVerifier = verifier
        startActivity(Intent(Intent.ACTION_VIEW, url))
    }

    private fun finishAppleSignIn(intent: Intent): Boolean {
        val url = intent.data ?: return false
        if (intent.action != Intent.ACTION_VIEW || url.scheme != "jaha-auth" || url.host != "apple") return false
        val state = appleState ?: return false
        val verifier = appleVerifier ?: return false
        if (url.getQueryParameter("state") != state || busy) return false
        runAuth {
            val result = AuthApi.request("/auth/android/apple/exchange", exchangeBody(state, verifier))
            finishSession(result)
            appleState = null
            appleVerifier = null
        }
        return true
    }

    private suspend fun startRequest(provider: String, verifier: String): JSONObject {
        val hash = MessageDigest.getInstance("SHA-256")
            .digest(verifier.toByteArray(Charsets.US_ASCII))
            .joinToString("") { "%02x".format(it) }
        return AuthApi.request(
            "/auth/android/start",
            JSONObject().put("provider", provider).put("verifier_hash", hash),
        )
    }

    private fun exchangeBody(state: String, verifier: String) = JSONObject()
        .put("state", state)
        .put("verifier", verifier)

    private fun newVerifier(): String {
        val bytes = ByteArray(32).also(SecureRandom()::nextBytes)
        return Base64.encodeToString(bytes, Base64.NO_WRAP or Base64.URL_SAFE or Base64.NO_PADDING)
    }

    private fun finishSession(result: JSONObject) {
        session.save(result.getString("session_token"))
        showUser(result.getJSONObject("user"))
    }

    private fun showUser(user: JSONObject) {
        signedInAs = if (user.isNull("email")) "Inloggad" else user.getString("email")
    }

    private fun runAuth(action: suspend () -> Unit) {
        if (busy) return
        busy = true
        message = ""
        render()
        lifecycleScope.launch {
            try {
                action()
            } catch (error: CancellationException) {
                throw error
            } catch (_: GetCredentialCancellationException) {
                message = ""
            } catch (error: AuthHttpException) {
                if (error.status == 401 && signedInAs == null) session.clear()
                message = when (error.status) {
                    404, 503 -> "Inloggningen är inte tillgänglig just nu."
                    401 -> "Inloggningen kunde inte verifieras. Försök igen."
                    else -> "Inloggningen misslyckades. Försök igen."
                }
            } catch (_: Exception) {
                message = "Inloggningen misslyckades. Försök igen."
            } finally {
                busy = false
                render()
            }
        }
    }
}
