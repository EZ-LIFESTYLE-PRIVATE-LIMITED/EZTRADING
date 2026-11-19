# EZTrading Android app (Trusted Web Activity)

This module is a thin wrapper that opens the EZTrading website full-screen in Chrome using a
[Trusted Web Activity](https://developer.chrome.com/docs/android/trusted-web-activity). The app
itself contains no product code. Every UI change ships with a normal web deploy, so there is no
Play Store update for UI work.

Why a TWA rather than a WebView: Google sign-in and web-push notifications both keep working. Google
blocks OAuth inside WebViews, and WebViews have no Push API. Push notifications show up as this
app's notifications through notification delegation.

## 1. Point the app at your site

Set the host in `gradle.properties` (`twaHost=trade.example.com`), or pass `-PtwaHost=...` on each
build. In CI, set the `TWA_HOST` repository variable.

## 2. Create a signing key (once — keep it safe; losing it means a new app listing)

```bash
keytool -genkeypair -v -keystore eztrading-release.jks -alias eztrading -keyalg RSA -keysize 2048 -validity 10000
keytool -list -v -keystore eztrading-release.jks -alias eztrading   # copy the SHA256 fingerprint
```

## 3. Prove you own the site (removes the URL bar)

On the server, set the following in `.env` and redeploy:

```
TWA_PACKAGE_NAME=in.eztrading.app
TWA_SHA256_FINGERPRINTS=<your SHA256>[,<Play App Signing SHA256>]
```

Then check `https://<host>/.well-known/assetlinks.json`. If you publish through Google Play with
Play App Signing, also add the fingerprint shown under Play Console → Setup → App signing.

## 4. Build

You need JDK 17 or newer and the Android SDK (Android Studio's bundled JBR works):

```bash
cd android
./gradlew assembleDebug                      # app/build/outputs/apk/debug/app-debug.apk (sideload for testing)
ANDROID_KEYSTORE_PATH=/path/eztrading-release.jks ANDROID_KEYSTORE_PASSWORD=... \
ANDROID_KEY_ALIAS=eztrading ANDROID_KEY_PASSWORD=... \
./gradlew bundleRelease -PtwaHost=trade.example.com -PversionCode=2 -PversionName=1.0.1
```

`bundleRelease` produces `app/build/outputs/bundle/release/app-release.aab`, which is the file you
upload to Play.

The **Android app** GitHub workflow builds the same artifacts. Add these repository secrets to have
it sign them:

- `ANDROID_KEYSTORE_B64` (output of `base64 -w0 eztrading-release.jks`)
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

## 5. Test on a phone

1. Install the debug APK with `adb install app/build/outputs/apk/debug/app-debug.apk`.
2. Open the app. Until `assetlinks.json` matches the APK's signing key, Chrome shows a small URL
   bar. The debug build uses your local debug key, so add its SHA256 too while testing:
   `keytool -list -v -keystore ~/.android/debug.keystore -storepass android`.
3. Check each of these: Google sign-in, Connect Kite (it opens kite.zerodha.com and returns), and
   Settings → Notifications → Browser push → Send test notification.

## Testing against a local dev server (emulator)

Use a Google APIs or Play Store emulator image, since those include Chrome. Chrome treats
`http://localhost` as a secure origin, so the service worker and push work here too:

```bash
adb reverse tcp:8000 tcp:8000          # emulator 127.0.0.1:8000 -> your PC's port 8000
./gradlew installDebug -PtwaHost=127.0.0.1:8000 -PtwaScheme=http
```

In PowerShell, quote the arguments (`'-PtwaHost=127.0.0.1:8000'`). Otherwise PowerShell splits them.

**The app's host must match the server's `PUBLIC_BASE_URL`**, which defaults to `http://127.0.0.1:8000`.
The Google and Kite callbacks return to `PUBLIC_BASE_URL`. If the app runs on a different
origin, such as `localhost` or `127.0.0.1`, the session cookie is missing and the callback fails.

What to expect locally:

- **URL bar:** shown, because a local origin can't pass asset-link verification. To hide it on an
  emulator, have Chrome skip verification for that origin. This affects that emulator only:
  ```bash
  adb shell am set-debug-app --persistent com.android.chrome
  adb shell "echo '_ --disable-digital-asset-link-verification-for-url=\"http://127.0.0.1:8000\"' > /data/local/tmp/chrome-command-line"
  adb shell am force-stop com.android.chrome
  ```
- **Push:** set `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` (from `python scripts/gen_keys.py`). Notifications show as
  coming from *Chrome*. With a verified production domain they show as *EZTrading* instead.
- **Google sign-in:** the button appears only when `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set. Also
  add `<PUBLIC_BASE_URL>/auth/google/callback` to the OAuth client's authorized redirect URIs. `LOGIN_METHODS`
  chooses what the login page offers: `google` for the real app, or `dev` for a sandbox (email sign-in
  where the code is always `FIXED_OTP`, 7891).
- **Kite:** the Kite developer app's redirect URL must be `<PUBLIC_BASE_URL>/auth/kite/callback`. Settings in
  the app shows the exact value.

If `adb devices` shows `authorizing` or `offline`, cold-boot the emulator (Device Manager → ⋮ →
Cold Boot Now).

## How sign-in and Kite work in the app

The app *is* the website, running in Chrome, so it shares Chrome's cookies, and every redirect
flow is the same as on the web:

- **Google sign-in:** the app goes to accounts.google.com inside the same Chrome tab, which shows a
  small toolbar while off-site, then returns to `/auth/google/callback`. Google allows this
  because it's Chrome, not a WebView.
- **Kite:** **one Kite redirect URL serves both web and Android**:
  `https://<your domain>/auth/kite/callback`. The app opens kite.zerodha.com, Kite redirects back
  to that URL, and the app lands on `/?kite=connected`. If Android hands that link to the app
  through the App Links filter, `LauncherActivity` reopens it in the same Chrome session, so the
  login still completes.

## Icons

`python scripts/make_icons.py` (needs Pillow) regenerates the launcher, splash and notification
icons here, along with the web app icons in `static/icons/`.
