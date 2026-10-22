// P4 诉求 4：OCR 引擎切换与回退的契约测试。
//
// 这一组测试只覆盖**可以在纯 Dart 环境验证**的部分：
//   · OcrEngine 枚举的 code ↔ 枚举 映射（存库稳定性）
//   · PpOcrV6Extractor 对原生返回值的**防御性解析**
//   · OcrEngineFactory 的三档回退
//   · SuggestPipeline 的引擎偏好读写
//
// 验证不了的部分（明确列出，避免误以为已覆盖）：
//   · 原生侧 ONNX 推理是否正确 —— 需要真机 + 模型文件，见 tools/fetch_ppocr_model.ps1
//   · MlKitTextExtractor 的实际识别 —— flutter test 环境无插件
//   · MethodChannel 的真实往返 —— 这里用 setMockMethodCallHandler 模拟
import 'package:drift/native.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/data/db/database.dart';
import 'package:g_tick_picture/domain/ocr/mlkit_text_extractor.dart';
import 'package:g_tick_picture/domain/ocr/ocr_engine.dart';
import 'package:g_tick_picture/domain/ocr/ocr_engine_factory.dart';
import 'package:g_tick_picture/domain/ocr/ocr_text_extractor.dart';
import 'package:g_tick_picture/domain/ocr/pp_ocr_v6_extractor.dart';
import 'package:g_tick_picture/domain/suggest/suggest_pipeline.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // ── 通道桩：模拟原生侧 ────────────────────────────────────
  //
  // 用真的 MethodChannel 而不是往 PpOcrV6Extractor 里塞假对象，
  // 是为了把「Dart 侧怎么调、原生侧怎么答」这层协议也钉住 ——
  // 方法名写错、参数名写错都会在这里失败，而不是等到真机上。
  const channel = MethodChannel('gtick/ppocr');

  void stubChannel(Future<Object?>? Function(MethodCall call) handler) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, handler);
  }

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  // ═══════════════════════════════════════════════════════════
  group('OcrEngine 枚举', () {
    test('code 是稳定值，改它等于让老用户的设置静默失效', () {
      expect(OcrEngine.mlkit.code, 'mlkit');
      expect(OcrEngine.ppOcrV6.code, 'ppocr_v6');
    });

    test('fromCode 认已知值', () {
      expect(OcrEngine.fromCode('mlkit'), OcrEngine.mlkit);
      expect(OcrEngine.fromCode('ppocr_v6'), OcrEngine.ppOcrV6);
    });

    test('fromCode 对 null / 未知值 / 空串一律回 ML Kit', () {
      // 回 ML Kit 而不是抛异常：设置读坏了不该让整理页打不开。
      // ML Kit 是"随 APK 分发、不可能不可用"的那个，是唯一安全兜底。
      expect(OcrEngine.fromCode(null), OcrEngine.mlkit);
      expect(OcrEngine.fromCode(''), OcrEngine.mlkit);
      expect(OcrEngine.fromCode('ppocr_v7'), OcrEngine.mlkit);
      expect(OcrEngine.fromCode('PPOCR_V6'), OcrEngine.mlkit); // 大小写敏感，不做猜测
    });

    test('每个引擎都有面向现场人员的 label 与 hint', () {
      for (final e in OcrEngine.values) {
        expect(e.label, isNotEmpty, reason: '${e.code} 缺 label');
        expect(e.hint, isNotEmpty, reason: '${e.code} 缺 hint');
        // 措辞纪律：面向预检员，不出现引擎技术名词。
        expect(e.label.contains('ONNX'), isFalse);
        expect(e.label.contains('Paddle'), isFalse);
      }
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('PpOcrV6Extractor · 原生返回值解析', () {
    test('正常返回：text/confidence/cx/cy 全部映射', () async {
      stubChannel((call) async {
        expect(call.method, 'recognize');
        expect(call.arguments, {'path': '/tmp/a.jpg'});
        return <Map<String, Object?>>[
          {'text': 'BOX-001', 'confidence': 0.93, 'cx': 0.2, 'cy': 0.3},
          {'text': 'BOX-002', 'confidence': 0.81, 'cx': 0.7, 'cy': 0.8},
        ];
      });

      final tokens = await PpOcrV6Extractor(channel: channel).extract('/tmp/a.jpg');

      expect(tokens.length, 2);
      expect(tokens[0].text, 'BOX-001');
      expect(tokens[0].ocrConf, closeTo(0.93, 1e-9));
      expect(tokens[0].normCx, closeTo(0.2, 1e-9));
      expect(tokens[0].normCy, closeTo(0.3, 1e-9));
      expect(tokens[1].text, 'BOX-002');
    });

    test('空列表 vs null 都当"图里没文字"，不抛异常', () async {
      stubChannel((call) async => <Object?>[]);
      expect(await PpOcrV6Extractor(channel: channel).extract('/tmp/a.jpg'),
          isEmpty);

      stubChannel((call) async => null);
      expect(await PpOcrV6Extractor(channel: channel).extract('/tmp/a.jpg'),
          isEmpty);
    });

    test('缺 confidence / 坐标 → 用"未知不打折"的默认值', () async {
      // 不打折原则：拿不到就按中性值处理，不要因为"没信息"就压低分数，
      // 那会让本来正确的建议被误标成低置信。
      stubChannel((call) async => <Map<String, Object?>>[
            {'text': 'BOX-001'}, // 什么都没有
            {'text': 'BOX-002', 'confidence': null, 'cx': null, 'cy': null},
          ]);

      final tokens = await PpOcrV6Extractor(channel: channel).extract('/tmp/a.jpg');

      for (final t in tokens) {
        expect(t.ocrConf, 1.0);
        expect(t.normCx, 0.5);
        expect(t.normCy, 0.5);
      }
    });

    test('畸形条目被跳过而非整张失败', () async {
      // 原生侧返回结构不符（非 Map / text 缺失 / text 为空）时，
      // 跳过坏条目保住好条目 —— 比整张标 failed 更符合"尽量给建议"。
      stubChannel((call) async => <Object?>[
            'not a map',
            42,
            <String, Object?>{'text': ''},
            <String, Object?>{'text': null},
            <String, Object?>{'confidence': 0.9}, // 无 text
            <String, Object?>{'text': 'BOX-001', 'confidence': 0.9},
          ]);

      final tokens = await PpOcrV6Extractor(channel: channel).extract('/tmp/a.jpg');

      expect(tokens.length, 1);
      expect(tokens.single.text, 'BOX-001');
    });

    test('原生侧抛错 → 异常往上抛（失败 ≠ 识别为空）', () async {
      // 契约核心：返回空列表 = "图里没有文字"，抛异常 = "这张识别失败了"。
      // 管道靠这个区分把照片标 done 还是 failed。两者混同会让
      // 「识别不出来」和「没有文字」在数据上不可区分。
      stubChannel((call) async => throw PlatformException(code: 'E_OCR'));

      await expectLater(
        PpOcrV6Extractor(channel: channel).extract('/tmp/a.jpg'),
        throwsA(isA<PlatformException>()),
      );
    });

    test('isAvailable：true / false / 抛错 三态', () async {
      stubChannel((call) async {
        expect(call.method, 'isReady');
        return true;
      });
      expect(await PpOcrV6Extractor(channel: channel).isAvailable(), isTrue);

      stubChannel((call) async => false);
      expect(await PpOcrV6Extractor(channel: channel).isAvailable(), isFalse);

      stubChannel((call) async => throw PlatformException(code: 'E_INIT'));
      expect(await PpOcrV6Extractor(channel: channel).isAvailable(), isFalse);
    });

    test('isAvailable 结果被缓存：不每张照片都问一次原生侧', () async {
      var calls = 0;
      stubChannel((call) async {
        if (call.method == 'isReady') calls++;
        return true;
      });

      final p = PpOcrV6Extractor(channel: channel);
      await p.isAvailable();
      await p.isAvailable();
      await p.isAvailable();

      expect(calls, 1, reason: '第二次之后应直接读缓存，否则白搭几百次通道往返');
    });

    test('close 重置缓存并通知原生释放；释放失败不抛', () async {
      var disposed = 0;
      var ready = true;
      stubChannel((call) async {
        if (call.method == 'dispose') {
          disposed++;
          throw PlatformException(code: 'E_DISPOSE');
        }
        if (call.method == 'isReady') return ready;
        return null;
      });

      final p = PpOcrV6Extractor(channel: channel);
      expect(await p.isAvailable(), isTrue);

      await p.close(); // 内部 dispose 会抛，但 close 吞掉
      expect(disposed, 1);

      // 缓存已重置 → 重新问原生侧。
      ready = false;
      expect(await p.isAvailable(), isFalse);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('NoopOcrTextExtractor · 降级实现', () {
    test('永远返回空列表，且绝不抛异常', () async {
      const n = NoopOcrTextExtractor();
      expect(await n.extract('/whatever.jpg'), isEmpty);
      expect(await n.extract(''), isEmpty);
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('OcrEngineFactory · 三档回退', () {
    test('① 选增强 + 原生就绪 → 用增强', () async {
      stubChannel((call) async => true);
      final built = await OcrEngineFactory.build(
        preferred: OcrEngine.ppOcrV6,
        mlkit: MlKitTextExtractor(),
        ppocr: PpOcrV6Extractor(channel: channel),
      );
      expect(built.effective, OcrEngine.ppOcrV6);
      expect(built.extractor, isA<PpOcrV6Extractor>());
    });

    test('② 选增强但原生没准备 → 静默回退 ML Kit，并如实报告 effective', () async {
      stubChannel((call) async => false);
      final built = await OcrEngineFactory.build(
        preferred: OcrEngine.ppOcrV6,
        mlkit: MlKitTextExtractor(),
        ppocr: PpOcrV6Extractor(channel: channel),
      );
      // effective 必须是**真正在用的**那个 —— UI 拿它显示状态，
      // 显示用户选的那个就是在撒谎。
      expect(built.effective, OcrEngine.mlkit);
      expect(built.extractor, isA<MlKitTextExtractor>());
    });

    test('② 原生探测抛异常也回退，不把异常漏给调用方', () async {
      stubChannel((call) async => throw PlatformException(code: 'E_INIT'));
      final built = await OcrEngineFactory.build(
        preferred: OcrEngine.ppOcrV6,
        mlkit: MlKitTextExtractor(),
        ppocr: PpOcrV6Extractor(channel: channel),
      );
      expect(built.effective, OcrEngine.mlkit);
    });

    test('① 选标准 → 直接用 ML Kit，**不探测原生侧**', () async {
      var probed = false;
      stubChannel((call) async {
        probed = true;
        return true;
      });
      final built = await OcrEngineFactory.build(
        preferred: OcrEngine.mlkit,
        mlkit: MlKitTextExtractor(),
        ppocr: PpOcrV6Extractor(channel: channel),
      );
      expect(built.effective, OcrEngine.mlkit);
      expect(probed, isFalse, reason: '没选增强就不该白跑一次原生探测');
    });
  });

  // ═══════════════════════════════════════════════════════════
  group('SuggestPipeline · 引擎偏好读写', () {
    late AppDatabase db;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      db = AppDatabase.forTesting(NativeDatabase.memory());
    });

    tearDown(() => db.close());

    test('默认引擎是 ML Kit（零额外体积、不可能不可用）', () async {
      final p = SuggestPipeline(db: db, extractor: const NoopOcrTextExtractor());
      expect(await p.preferredEngine, OcrEngine.mlkit);
    });

    test('写入后能读回（跨实例 —— 真的落到 SharedPreferences）', () async {
      final p1 = SuggestPipeline(db: db, extractor: const NoopOcrTextExtractor());
      await p1.setPreferredEngine(OcrEngine.ppOcrV6);

      final p2 = SuggestPipeline(db: db, extractor: const NoopOcrTextExtractor());
      expect(await p2.preferredEngine, OcrEngine.ppOcrV6);

      await p1.setPreferredEngine(OcrEngine.mlkit);
      expect(await p2.preferredEngine, OcrEngine.mlkit);
    });

    test('setPreferredEngine 只写偏好，不动提取器', () async {
      // 分开是刻意的：写偏好必须成功，装配是 async 且可能失败。
      // 装配失败不能让"设置没保存"成为一个可能结果。
      const before = NoopOcrTextExtractor();
      final p = SuggestPipeline(db: db, extractor: before);

      await p.setPreferredEngine(OcrEngine.ppOcrV6);

      expect(identical(p.extractor, before), isTrue);
    });

    test('swapExtractor 立即改变实际使用的提取器', () async {
      final p = SuggestPipeline(db: db, extractor: const NoopOcrTextExtractor());
      final next = FakeOcrTextExtractor(results: {
        '/x.jpg': const [OcrTokenResult(text: 'X', ocrConf: 1, normCx: .5, normCy: .5)],
      });

      p.swapExtractor(next);

      expect(identical(p.extractor, next), isTrue);
      expect((await p.extractor.extract('/x.jpg')).single.text, 'X');
      // 旧的 Noop 已不再被使用。
      expect(await const NoopOcrTextExtractor().extract('/x.jpg'), isEmpty);
    });
  });
}
