plugins {
    id("com.android.application") version "8.13.2"
    id("org.jetbrains.kotlin.android") version "2.2.21"
}

android {
    namespace = "se.jaha.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "se.jaha.android"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"

        val backendUrl = providers.gradleProperty("jahaBackendUrl")
            .orElse("https://svenska-api.dima-ib.xyz:8443").get()
        val googleClientId = providers.gradleProperty("jahaGoogleClientId").orElse("").get()
        require(Regex("https://[A-Za-z0-9.-]+(:[0-9]+)?").matches(backendUrl))
        require(googleClientId.isEmpty() || Regex("[A-Za-z0-9._-]+\\.apps\\.googleusercontent\\.com").matches(googleClientId))
        buildConfigField("String", "BACKEND_URL", "\"$backendUrl\"")
        buildConfigField("String", "GOOGLE_CLIENT_ID", "\"$googleClientId\"")
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    jvmToolchain(21)
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.4")
    implementation("androidx.credentials:credentials:1.5.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.5.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.1.1")
}
