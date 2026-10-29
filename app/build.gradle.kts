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
        versionCode = 15
        versionName = "1.14"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
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

chaquopy {
    defaultConfig {
        version = "3.13"
        buildPython("C:/Program Files/Python313/python.exe")
        // requests / beautifulsoup4 и их чистые Python-зависимости
        // лежат в src/main/python (вендоринг): pip-резолвер на этой машине
        // зависает, а нативные колёса этим пакетам не нужны.
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
}
