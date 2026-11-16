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

## Icons

`python scripts/make_icons.py` (needs Pillow) regenerates the launcher, splash and notification
icons here, along with the web app icons in `static/icons/`.
