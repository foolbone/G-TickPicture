import java.util.Properties
import java.io.FileInputStream

// 正式签名（upload key）。密钥材料都在版本控制之外：
//   · keystore：D:/G-TickPicture/keys/upload-keystore.jks（工作区根 keys/，不在 git 内）
//   · key.properties：android/key.properties（已被 app/.gitignore 忽略）
// ⚠️ keystore 丢失 = 同包名应用永远无法再覆盖安装（签名不匹配），务必备份。
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.gtick.g_tick_picture"
    compileSdk = flutter.compileSdkVersion

    // NDK 版本必须**显式钉死**，不能用 flutter.ndkVersion。
    // 原因：Flutter 默认给 26.3.11579264，而 camera / file_picker /
    // permission_handler / sqlite3_flutter_libs 等一批插件都要求
    // 27.0.12077973，构建时 Flutter 会先警告、插件再各自按需下载 → 又慢又不确定。
    // NDK 是向后兼容的，所以统一取所需的最高版本即可。
    // 本机 D:\dev\Android\SDK\ndk\ 下 27.0.12077973 已安装，不需要额外下载。
    ndkVersion = "27.0.12077973"

    signingConfigs {
        create("release") {
            keyAlias = keystoreProperties["keyAlias"] as String?
            keyPassword = keystoreProperties["keyPassword"] as String?
            storeFile = keystoreProperties["storeFile"]?.let { file(it) }
            storePassword = keystoreProperties["storePassword"] as String?
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.gtick.g_tick_picture"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        // 拍板决策：仅支持 Android 8.0+（minSdk 26，adaptive icon 前提）。
        // 不能用 flutter.minSdkVersion —— Flutter 默认给 21，会放宽到 5.0。
        minSdk = 26
        targetSdk = flutter.targetSdkVersion

        // 只打 arm64：现场手机全部 arm64-v8a；x86/x86_64 是模拟器架构、
        // armeabi-v7a 是老 32 位机，各带一份 ML Kit OCR 模型 so(~7-12MB/份)
        // 会把 APK 撑到 100MB+。若临时要在 x86_64 模拟器跑 debug，
        // 再把 "x86_64" 加回列表即可。
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // PP-OCRv6 模型（assets/ppocr/*.onnx，共 31MB）**不压缩**进 APK。
    // 原因：AAPT2 默认会 deflate 不认识的扩展名，压缩资产只能流式解压
    // 读取（慢），且各 ROM 对 AssetInputStream 的实现有差异；noCompress
    // 之后资产原样存储，materialize() 拷贝既快又能用 openFd 拿准确长度。
    // 注：build.gradle 里不能再放 .onnx 的排除规则 —— 2026-09-24 真机
    // 反馈"增强识别不可用"后加的保险之一。
    androidResources {
        noCompress += "onnx"
    }

    buildTypes {
        release {
            // 正式签名：keys/upload-keystore.jks / alias gt-upload。
            // key.properties 缺失时上面的 signingConfigs 留空，构建会在
            // 签名一步失败——这是有意的（宁可不产出，不发 debug 签名包）。
            signingConfig = signingConfigs.getByName("release")

            // ML Kit text-recognition references optional-language recognizer
            // classes (Devanagari/Japanese/Korean) that are not in our
            // dependencies - R8 fails on them without -dontwarn rules.
            // NOTE: proguardFile() (singular) APPENDS; do not switch to
            // proguardFiles() which would replace the Flutter-injected rules.
            proguardFile(getDefaultProguardFile("proguard-android-optimize.txt"))
            proguardFile("proguard-rules.pro")
        }
    }
}

// ML Kit 中文文字识别模型。google_mlkit_text_recognition 0.13.1 对各语言包
// 只做 compileOnly（编译得过但不进 APK），只自带拉丁基座。M4 OCR 用中文
// 识别，必须由 app 侧引入 chinese artifact：不加则 debug 运行时中文识别
// NoClassDefFoundError、release 构建 R8 Missing class。版本须与插件一致。
dependencies {
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")

    // ── P4 诉求 4：PP-OCRv6 推理运行时 ─────────────────────────
    // ONNX Runtime Android AAR。选它而不是 Paddle-Lite 的理由见
    // domain/ocr/ocr_engine.dart 与 ppocr/PpOcrEngine.kt 的类注释。
    //
    // ⚠️ 1.21.1 的 minSdk 是 26，与本工程一致 —— 不要降到 1.19 以下，
    //    那些版本的 minSdk 是 21，会带上不需要的兼容代码。
    // ⚠️ 模型文件（det.onnx / rec.onnx / keys.txt）**不在这里**，
    //    它们在 android/app/src/main/assets/ppocr/，由
    //    tools/fetch_ppocr_model.ps1 下载。缺文件不会编译失败，
    //    但运行时会自动回退 ML Kit（PpOcrEngine.create 返回 null）。
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.21.1")
}

flutter {
    source = "../.."
}
