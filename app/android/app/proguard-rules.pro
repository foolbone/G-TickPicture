# ProGuard / R8 rules for 集刻-采集 release build.
#
# google_mlkit_text_recognition references optional-language recognizer
# classes (Devanagari / Japanese / Korean) that are NOT shipped in our
# dependency graph - we only use Chinese + Latin recognition (M4).
# Those code branches never execute at runtime, so R8 just needs to be
# told not to fail on the missing classes.

-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**
-dontwarn com.google.mlkit.vision.text.korean.**

# Official ML Kit recommendation: keep ML Kit classes from being stripped
# (the plugin initializes recognizers reflectively via the Pigeon layer).
-keep class com.google.mlkit.** { *; }

# ── PP-OCRv6（P4 诉求 4）ONNX Runtime ─────────────────────────
# ONNX Runtime 通过 JNI 从 native 回调 Java 类，R8 看不到这些引用。
# 不 keep 的话 release 包会在 createSession 时崩：
#   java.lang.ClassNotFoundException: ai.onnxruntime.OrtSession
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**

# 本工程的 PP-OCR 桥接层也靠反射式的 MethodChannel 调用，
# 且 native 侧不参与 R8 分析，统一保留。
-keep class com.gtick.g_tick_picture.ppocr.** { *; }
