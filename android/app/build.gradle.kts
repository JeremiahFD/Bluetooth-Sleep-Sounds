plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "local.sleepsounds.controller"
    compileSdk = 35
    defaultConfig {
        applicationId = "local.sleepsounds.controller"
        minSdk = 26
        targetSdk = 35
        versionCode = 13
        versionName = "0.9.0-alpha.2"
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies { implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0"); testImplementation("junit:junit:4.13.2") }
