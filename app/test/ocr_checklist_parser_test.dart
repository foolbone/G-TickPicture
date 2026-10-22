import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/checklist/ocr_checklist_parser.dart';
import 'package:g_tick_picture/domain/model/checklist_row.dart';
import 'package:g_tick_picture/domain/ocr/ocr_text_extractor.dart';

/// [OcrChecklistParser] 的契约测试（老板 09-26 拍板：清单拍照识别）。
///
/// 覆盖两层纯逻辑：
///  1. [OcrChecklistParser.assembleLines] —— token 按坐标重组为行；
///  2. [OcrChecklistParser.parse] —— 行文本提取「编码（必）+ 品名」，
///     表头/无编码行跳过、全角归一、同批合并、与库重复跳过。
void main() {
  OcrTokenResult tok(String text, double cx, double cy) =>
      OcrTokenResult(text: text, ocrConf: 1.0, normCx: cx, normCy: cy);

  group('assembleLines · token 重组为行', () {
    test('同一行（y 相近）按 x 从左到右拼接', () {
      // 故意乱序给入
      final lines = OcrChecklistParser.assembleLines([
        tok('BOX-001', 0.15, 0.200),
        tok('红色', 0.55, 0.205),
        tok('礼盒', 0.35, 0.195),
      ]);
      expect(lines, ['BOX-001 礼盒 红色']);
    });

    test('不同行（y 差超容差）分行，行序从上到下', () {
      final lines = OcrChecklistParser.assembleLines([
        tok('A-001', 0.2, 0.10),
        tok('A-002', 0.2, 0.40),
        tok('甲', 0.6, 0.11),
        tok('乙', 0.6, 0.41),
      ]);
      expect(lines, ['A-001 甲', 'A-002 乙']);
    });

    test('行基准 y 用滑动平均：轻微倾斜不裂行', () {
      // y 从 0.100 缓慢漂到 0.122 —— 每步相对滑动均值都 ≤ 0.014
      final lines = OcrChecklistParser.assembleLines([
        tok('A', 0.1, 0.100),
        tok('B', 0.3, 0.106),
        tok('C', 0.5, 0.112),
        tok('D', 0.7, 0.118),
        tok('E', 0.9, 0.122),
      ]);
      expect(lines, ['A B C D E']);
    });

    test('空输入返回空', () {
      expect(OcrChecklistParser.assembleLines(const []), isEmpty);
    });
  });

  group('parse · 行 → 候选货品', () {
    test('字母数字混合编码（最可信形态）+ 品名提取', () {
      final r = OcrChecklistParser.parse(lines: [
        'BOX-001 青花缠枝莲纹盘 5件',
      ]);
      expect(r.rows, hasLength(1));
      expect(r.rows.single.code, 'BOX-001');
      // "5件" 是数字+字混排，不是纯数字 token → 保留在品名里（预览页可改）
      expect(r.rows.single.name, '青花缠枝莲纹盘 5件');
      expect(r.rows.single.requiredPhotos, 2);
    });

    test('纯数字编码（≥3 位）作备选：无混合 token 时才认', () {
      final r = OcrChecklistParser.parse(lines: ['10023 景德镇白瓷碗']);
      expect(r.rows.single.code, '10023');
      expect(r.rows.single.name, '景德镇白瓷碗');
    });

    test('行首 1~2 位序号不会被当成编码', () {
      final r = OcrChecklistParser.parse(lines: ['1 BOX-777 描金盖碗']);
      expect(r.rows, hasLength(1));
      expect(r.rows.single.code, 'BOX-777');
    });

    test('序号列 001（3 位纯数字）在无混合编码时会被抓为编码 —— 预览页可改', () {
      // 这是已知取舍：纯数字形态天生与货号同形。宁可给候选让人删，
      // 也不悄悄丢行（与"宁多勿错"的分组哲学一致）。
      final r = OcrChecklistParser.parse(lines: ['001 釉下彩茶具']);
      expect(r.rows, hasLength(1));
      expect(r.rows.single.code, '001');
    });

    test('表头行（命中 ≥2 关键词）整行跳过', () {
      final r = OcrChecklistParser.parse(lines: [
        '货品编码 品名 数量 单位',
        'BOX-001 青花盘',
      ]);
      expect(r.rows, hasLength(1));
      expect(r.rows.single.code, 'BOX-001');
      final info = r.issues
          .where((i) => i.level == IssueLevel.info)
          .where((i) => i.message.contains('表头'));
      expect(info, isNotEmpty);
    });

    test('无编码行跳过并留 warning（不静默丢行）', () {
      final r = OcrChecklistParser.parse(lines: ['合计 共 42 件']);
      expect(r.rows, isEmpty);
      expect(r.issues.where((i) => i.level == IssueLevel.warning), isNotEmpty);
    });

    test('全角编码归一化为半角（与 Excel 导入同款规则）', () {
      final r = OcrChecklistParser.parse(lines: ['ＢＯＸ－００１ 青花盘']);
      expect(r.rows.single.code, 'BOX-001');
    });

    test('同批重复编码合并为一件（sourceLineCount 计数）', () {
      final r = OcrChecklistParser.parse(lines: [
        'BOX-001 青花盘 箱A',
        'BOX-001 青花盘 箱B',
      ]);
      expect(r.rows, hasLength(1));
      expect(r.rows.single.sourceLineCount, 2);
      expect(r.issues.where((i) => i.message.contains('合并')), isNotEmpty);
    });

    test('与库里已有编码重复的行跳过', () {
      final r = OcrChecklistParser.parse(
        lines: ['BOX-001 已导入的货', 'BOX-002 新货品'],
        existingCodes: {'BOX-001'},
      );
      expect(r.rows.map((e) => e.code), ['BOX-002']);
    });

    test('编码含文件名不可用字符时 codeSafe 被替换（原始 code 保留）', () {
      final r = OcrChecklistParser.parse(lines: ['AB/CD-01 测试货']);
      expect(r.rows.single.code, 'AB/CD-01');
      expect(r.rows.single.codeSafe, isNot(contains('/')));
    });

    test('多行混合场景：表头、正文、备注行一次过', () {
      final r = OcrChecklistParser.parse(lines: [
        '货品编码 品名 数量',
        'BX-101 青花瓷瓶 2',
        'NOTE.: 客户要求下午发货',
        'BX-102 釉下五彩碗 6',
      ]);
      expect(r.rows.map((e) => e.code), ['BX-101', 'BX-102']);
      // 备注行进 warning（没认出编码），不阻塞其余行
      expect(r.issues.where((i) => i.level == IssueLevel.warning), isNotEmpty);
    });
  });

  group('组合冒烟 · FakeOcrTextExtractor → assembleLines → parse', () {
    test('从 token 到候选货品的完整链路', () async {
      // 模拟一张清单照片：表头 + 两行货品（token 无序）
      final fake = FakeOcrTextExtractor(results: {
        '/tmp/list.jpg': [
          tok('品名', 0.50, 0.05),
          tok('货品编码', 0.15, 0.05),
          tok('数量', 0.80, 0.05),
          tok('BX-201', 0.15, 0.25),
          tok('薄胎瓷灯', 0.45, 0.26),
          tok('3', 0.80, 0.25),
          tok('BX-202', 0.15, 0.55),
          tok('斗彩小盏', 0.45, 0.55),
        ],
      });
      final tokens = await fake.extract('/tmp/list.jpg');
      final lines = OcrChecklistParser.assembleLines(tokens);
      final r = OcrChecklistParser.parse(lines: lines);

      expect(lines.first, contains('货品编码'));
      expect(r.rows.map((e) => e.code), ['BX-201', 'BX-202']);
      expect(r.rows[0].name, '薄胎瓷灯');
      expect(r.rows[1].name, '斗彩小盏');
    });
  });
}
