// Copyright 2013 The Flutter Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

package io.flutter.plugins.camerax;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.resolutionselector.ResolutionSelector;
import java.io.File;
import java.io.IOException;
import java.util.concurrent.Executors;
import kotlin.Result;
import kotlin.Unit;
import kotlin.jvm.functions.Function1;

/**
 * ProxyApi implementation for {@link ImageCapture}. This class may handle instantiating native
 * object instances that are attached to a Dart instance or handle method calls on the associated
 * native class or an instance of that class.
 */
class ImageCaptureProxyApi extends PigeonApiImageCapture {
  static final String TEMPORARY_FILE_NAME = "CAP";
  static final String JPG_FILE_TYPE = ".jpg";

  ImageCaptureProxyApi(@NonNull ProxyApiRegistrar pigeonRegistrar) {
    super(pigeonRegistrar);
  }

  @NonNull
  @Override
  public ProxyApiRegistrar getPigeonRegistrar() {
    return (ProxyApiRegistrar) super.getPigeonRegistrar();
  }

  @NonNull
  @Override
  public ImageCapture pigeon_defaultConstructor(
      @Nullable ResolutionSelector resolutionSelector,
      @Nullable Long targetRotation,
      @Nullable CameraXFlashMode flashMode) {
    final ImageCapture.Builder builder = new ImageCapture.Builder();
    // ── GTick fork（2026-10-12 v0.21.0）─────────────────────────
    // 上游 pigeon API 未暴露这两项，且 camera 包升级路线已断
    // （0.12+ 要 Dart 3.9+，本项目 Flutter 3.29 锁死）。两处改动
    // 对标原生相机：
    //   ① ZSL（零快门延迟）：默认 MAXIMIZE_QUALITY 每张都等 AE/AF
    //      收敛，暗光 300-800ms；ZSL 从环形缓冲取最近帧，快门 <150ms。
    //      ⚠️ 已知限制：ZSL 与部分闪光/HDR 扩展互斥（本项目闪光默认
    //      off，可接受）；**成片分辨率必须真机验证 ≥ 传感器 max**
    //      （方案 v3 第一验收项），受限则回退本行即可。
    //   ② JPEG 质量 100（默认 95）：取证照片画质优先，体积 +5% 可接受。
    builder.setCaptureMode(ImageCapture.CAPTURE_MODE_ZERO_SHUTTER_LAG);
    builder.setJpegQuality(100);
    // ── GTick fork end ──────────────────────────────────────────
    if (targetRotation != null) {
      builder.setTargetRotation(targetRotation.intValue());
    }
    if (flashMode != null) {
      // This sets the requested flash mode, but may fail silently.
      switch (flashMode) {
        case AUTO:
          builder.setFlashMode(ImageCapture.FLASH_MODE_AUTO);
          break;
        case OFF:
          builder.setFlashMode(ImageCapture.FLASH_MODE_OFF);
          break;
        case ON:
          builder.setFlashMode(ImageCapture.FLASH_MODE_ON);
          break;
      }
    }
    if (resolutionSelector != null) {
      builder.setResolutionSelector(resolutionSelector);
    }
    return builder.build();
  }

  @Override
  public void setFlashMode(
      @NonNull ImageCapture pigeonInstance, @NonNull CameraXFlashMode flashMode) {
    int nativeFlashMode = -1;
    switch (flashMode) {
      case AUTO:
        nativeFlashMode = ImageCapture.FLASH_MODE_AUTO;
        break;
      case OFF:
        nativeFlashMode = ImageCapture.FLASH_MODE_OFF;
        break;
      case ON:
        nativeFlashMode = ImageCapture.FLASH_MODE_ON;
    }
    pigeonInstance.setFlashMode(nativeFlashMode);
  }

  @Override
  public void takePicture(
      @NonNull ImageCapture pigeonInstance,
      @NonNull Function1<? super Result<String>, Unit> callback) {
    final File outputDir = getPigeonRegistrar().getContext().getCacheDir();
    File temporaryCaptureFile;
    try {
      temporaryCaptureFile = File.createTempFile(TEMPORARY_FILE_NAME, JPG_FILE_TYPE, outputDir);
    } catch (IOException | SecurityException e) {
      ResultCompat.failure(e, callback);
      return;
    }

    final ImageCapture.OutputFileOptions outputFileOptions =
        createImageCaptureOutputFileOptions(temporaryCaptureFile);
    final ImageCapture.OnImageSavedCallback onImageSavedCallback =
        createOnImageSavedCallback(temporaryCaptureFile, callback);

    pigeonInstance.takePicture(
        outputFileOptions, Executors.newSingleThreadExecutor(), onImageSavedCallback);
  }

  @Override
  public void setTargetRotation(ImageCapture pigeonInstance, long rotation) {
    pigeonInstance.setTargetRotation((int) rotation);
  }

  @Nullable
  @Override
  public ResolutionSelector resolutionSelector(@NonNull ImageCapture pigeonInstance) {
    return pigeonInstance.getResolutionSelector();
  }

  ImageCapture.OutputFileOptions createImageCaptureOutputFileOptions(@NonNull File file) {
    return new ImageCapture.OutputFileOptions.Builder(file).build();
  }

  @NonNull
  ImageCapture.OnImageSavedCallback createOnImageSavedCallback(
      @NonNull File file, @NonNull Function1<? super Result<String>, Unit> callback) {
    return new ImageCapture.OnImageSavedCallback() {
      @Override
      public void onImageSaved(@NonNull ImageCapture.OutputFileResults outputFileResults) {
        ResultCompat.success(file.getAbsolutePath(), callback);
      }

      @Override
      public void onError(@NonNull ImageCaptureException exception) {
        ResultCompat.failure(exception, callback);
      }
    };
  }
}
