# Jaha Android sign-in

The Android app currently provides sign-in, session restoration, and sign-out.
Open this directory in Android Studio or build it with JDK 21 and the Android 36 SDK.

```sh
cd android
export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
export ANDROID_HOME="$HOME/Library/Android/sdk"
./gradlew signingReport
./gradlew assembleDebug
"$ANDROID_HOME/platform-tools/adb" install -r build/outputs/apk/debug/Jaha-debug.apk
```

`jahaBackendUrl` defaults to the shared HTTPS backend. The Android app and
backend default to Jaha's public Web OAuth client ID. For a different Google
Cloud project, set `jahaGoogleClientId` when building the app and set the
matching `GOOGLE_CLIENT_ID` in the backend.
In Google Auth Platform, register an Android OAuth client for `se.jaha.android`
with the debug SHA-1 from `signingReport`. Register the release signing SHA-1
when distributing a release build.

For Apple, associate a Services ID with the primary iOS App ID
`dima.SWE-Dialogs` and register an HTTPS return URL ending in
`/auth/android/apple/callback`. Set `APPLE_SERVICES_ID` and
`APPLE_ANDROID_REDIRECT_URI` in the backend. Confirm the host and port work
with the Apple developer portal. The Android app opens the system browser
for Apple sign-in. The browser returns the learner to Jaha after the server
verifies the Apple identity token. A one-time exchange tied to that app
instance issues the usual app session token.

Verify continuity using an existing iPhone Apple account and compare the
account ID returned by `/me` on both devices. Google accounts use their
Google subject as a separate identity. The backend ignores email when
choosing the account.
