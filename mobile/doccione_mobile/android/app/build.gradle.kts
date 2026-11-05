import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Opt-in build identity for the isolated USB pilot. Ordinary debug/release
// builds retain the production applicationId and Google Services setup.
val usbIntegrationBuild =
    providers.gradleProperty("doccioneUsbIntegration").orNull == "true"
if (!usbIntegrationBuild) {
    apply(plugin = "com.google.gms.google-services")
}

val releaseProperties = Properties()
val releasePropertiesFile = rootProject.file("key.properties")
if (releasePropertiesFile.exists()) {
    releasePropertiesFile.inputStream().use(releaseProperties::load)
}

android {
    namespace = "com.doccione.mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
        isCoreLibraryDesugaringEnabled = true
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = if (usbIntegrationBuild) {
            "com.doccione.mobile.usbpilot"
        } else {
            "com.doccione.mobile"
        }
        manifestPlaceholders["doccioneAppLabel"] = if (usbIntegrationBuild) {
            "Doccione USB Pilot"
        } else {
            "Doccione Mobile"
        }
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    if (releasePropertiesFile.exists()) {
        signingConfigs {
            create("release") {
                storeFile = file(releaseProperties["storeFile"] as String)
                storePassword = releaseProperties["storePassword"] as String
                keyAlias = releaseProperties["keyAlias"] as String
                keyPassword = releaseProperties["keyPassword"] as String
            }
        }
    }

    buildTypes {
        release {
            // Nunca usar la clave debug para publicar.
            signingConfig = signingConfigs.findByName("release")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_1_8
        freeCompilerArgs.add("-Xjvm-default=all-compatibility")
    }
}

flutter {
    source = "../.."
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.0.4")
    implementation(platform("com.google.firebase:firebase-bom:32.7.0"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("com.google.ar:core:1.54.0")
}
