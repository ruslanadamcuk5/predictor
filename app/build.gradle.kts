plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "by.betcity.predictor"
    compileSdk = 34

    defaultConfig {
        applicationId = "by.betcity.predictor"
        minSdk = 24
        targetSdk = 34
        versionCode = 16
        versionName = "1.15"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    // Релизная подпись задаётся переменными окружения, чтобы ключ не
    // попадал в репозиторий. Без них release собирается debug-ключом —
    // этого достаточно для тестов, но не для публикации в магазине.
    val keyStorePath = System.getenv("PREDICTOR_KEYSTORE")
    val keyStorePassword = System.getenv("PREDICTOR_KEYSTORE_PASSWORD")
    val keyAlias = System.getenv("PREDICTOR_KEY_ALIAS")
    val keyPassword = System.getenv("PREDICTOR_KEY_PASSWORD")
    val hasReleaseKey = !keyStorePath.isNullOrBlank()
        && !keyStorePassword.isNullOrBlank()
        && !keyAlias.isNullOrBlank()
        && !keyPassword.isNullOrBlank()

    signingConfigs {
        if (hasReleaseKey) {
            create("release") {
                storeFile = file(keyStorePath!!)
                storePassword = keyStorePassword
                this.keyAlias = keyAlias
                this.keyPassword = keyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = if (hasReleaseKey) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

// Chaquopy требует Python 3.13. Ищем его в типичных местах и разрешаем
// переопределить путь через CHAQUOPY_BUILD_PYTHON.
val buildPythonPath = System.getenv("CHAQUOPY_BUILD_PYTHON")
    ?: listOf(
        "/usr/bin/python3.13",
        "/usr/local/bin/python3.13",
        "/opt/homebrew/bin/python3.13",
        "C:/Program Files/Python313/python.exe",
    ).firstOrNull { file(it).exists() }

chaquopy {
    defaultConfig {
        version = "3.13"
        if (!buildPythonPath.isNullOrBlank()) {
            buildPython(buildPythonPath)
        }
        // requests / beautifulsoup4 и их чистые Python-зависимости
        // лежат в src/main/python (вендоринг): pip-резолвер на этой машине
        // зависает, а нативные колёса этим пакетам не нужны.
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
}
