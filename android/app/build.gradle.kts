// Trusted Web Activity wrapper: launches the EZTrading site full-screen in Chrome.
// All app behaviour lives in the website; this module only carries identity, icons and colours.
plugins {
    id("com.android.application")
}

val twaHost: String = providers.gradleProperty("twaHost").get()

android {
    namespace = "in.eztrading.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "in.eztrading.app"
        minSdk = 21
        targetSdk = 35
        versionCode = (providers.gradleProperty("versionCode").orNull ?: "1").toInt()
        versionName = providers.gradleProperty("versionName").orNull ?: "1.0.0"

        manifestPlaceholders["hostName"] = twaHost
        resValue("string", "launchUrl", "https://$twaHost/?source=twa")
        resValue("string", "webManifestUrl", "https://$twaHost/manifest.webmanifest")
        resValue("string", "providerAuthority", "in.eztrading.app.fileprovider")
        // Pairs with /.well-known/assetlinks.json on the site (TWA_PACKAGE_NAME / TWA_SHA256_FINGERPRINTS).
        resValue(
            "string", "assetStatements",
            """[{\"relation\": [\"delegate_permission/common.handle_all_urls\"], \"target\": {\"namespace\": \"web\", \"site\": \"https://$twaHost\"}}]""",
        )
    }

    // Release signing comes from environment variables (CI secrets); without them the release build is unsigned.
    val keystorePath: String? = System.getenv("ANDROID_KEYSTORE_PATH")
    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePath != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    buildFeatures {
        resValues = true
        buildConfig = false
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.5.0")
}
