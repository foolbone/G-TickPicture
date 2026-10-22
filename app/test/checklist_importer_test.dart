import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/checklist/checklist_file_reader.dart';
import 'package:g_tick_picture/domain/checklist/checklist_importer.dart';
import 'package:g_tick_picture/domain/checklist/column_mapper.dart';
import 'package:g_tick_picture/domain/model/checklist_row.dart';
import 'package:g_tick_picture/domain/model/enums.dart';

/// 清单解析与校验的测试 —— 设计方案 §5.1「导入校验规则（硬性）」的逐条规格。
void main() {
  SheetGrid g(List<List<String?>> rows) => SheetGrid(name: 'S1', rows: rows);

  const header = ['货品编码', '货品名称', '数量', '单位', '要求张数'];

  const mapping = ColumnMapping(
    headerRow: 0,
    columns: {
      ChecklistField.itemCode: 0,
      ChecklistField.name: 1,
      ChecklistField.qty: 2,
      ChecklistField.unit: 3,
      ChecklistField.requiredPhotos: 4,
    },
  );

  group('正常解析', () {
    test('三行数据全部解析成功', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '牛皮纸箱', '100', '箱', '2'],
          ['DEF-2001', '钢制法兰', '50', '件', '2'],
          ['GHI-3300', '塑料件', '20', '袋', '3'],
        ]),
        mapping: mapping,
      );

      expect(r.rows.length, 3);
      expect(r.rows.first.code, 'ABC-1024');
      expect(r.rows.first.name, '牛皮纸箱');
      expect(r.rows.first.qty, 100);
      expect(r.rows.first.unit, '箱');
      expect(r.rows.first.requiredPhotos, 2);
      expect(r.rows.last.requiredPhotos, 3);
      expect(r.errorCount, 0);
      expect(r.canProceed, isTrue);
    });

    test('要求张数缺失时用默认值', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '', '', ''],
        ]),
        mapping: mapping,
        defaultRequiredPhotos: 2,
      );
      expect(r.rows.single.requiredPhotos, 2);
    });

    test('previewRows 只给前 5 行', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ...List.generate(10, (i) => ['C-$i', 'X', '1', '件', '2']),
        ]),
        mapping: mapping,
      );
      expect(r.previewRows.length, 5);
      expect(r.rows.length, 10);
    });

    test('表头行不是第 1 行时，行号仍指向原表真实行', () {
      final r = ChecklistImporter.parse(
        grid: g([
          ['某某公司 预检清单'],       // 第 1 行：标题
          ['制表日期 2026-09-22'],     // 第 2 行
          header,                      // 第 3 行：真表头
          ['ABC-1024', '纸箱', '1', '箱', '2'],   // 第 4 行
        ]),
        mapping: const ColumnMapping(
          headerRow: 2,
          columns: {
            ChecklistField.itemCode: 0,
            ChecklistField.name: 1,
            ChecklistField.qty: 2,
            ChecklistField.unit: 3,
            ChecklistField.requiredPhotos: 4,
          },
        ),
      );
      expect(r.rows.single.sourceRow, 4);
      expect(r.headerRow, 2);
      expect(r.totalSourceRows, 1);
    });
  });

  group('规则 1：编码为空 → 丢弃该行', () {
    test('有数据的空编码行报错并跳过（如"合计"行）', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '100', '箱', '2'],
          ['', '合计', '150', '', ''],
        ]),
        mapping: mapping,
      );
      expect(r.rows.length, 1);
      expect(r.errorCount, 1);
      expect(r.issues.first.row, 3, reason: '要指回 Excel 的第 3 行');
      expect(r.issues.first.message, contains('编码为空'));
    });

    test('完全空白的行静默跳过，不报错', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '1', '箱', '2'],
          ['', '', '', '', ''],
        ]),
        mapping: mapping,
      );
      expect(r.rows.length, 1);
      expect(r.errorCount, 0);
    });
  });

  // ─────────────────────────────────────────────────────────────
  // 规则 2：编码重复（P4 诉求 1，语义甲）
  //
  // 语义甲：同一件货可能分散在多个箱子里，被清单列成多行。
  // 业务上这是**一件货** → 合并为一条、数量累加、箱号收集。
  // 「保留首次、其余跳过」是旧行为，会让数量少算，已废弃（可显式关回去）。
  // ─────────────────────────────────────────────────────────────
  group('规则 2：编码重复 → 合并（语义甲）', () {
    test('同编码多行合并成一条，数量累加', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '3', '箱', '2'],
          ['DEF-2001', '法兰', '1', '件', '2'],
          ['ABC-1024', '纸箱', '5', '箱', '2'],
        ]),
        mapping: mapping,
      );
      expect(r.rows.length, 2, reason: '重复的那一行被合并掉，不是新增一条');
      expect(r.rows.first.code, 'ABC-1024');
      expect(r.rows.first.qty, 8, reason: '3 + 5 = 8（旧行为只会留 3，数量是错的）');
      expect(r.rows.first.sourceRow, 2, reason: '合并记录沿用首次出现的原表行号');
    });

    test('合并是提示（info）不是警告 —— 数据没丢，只是被汇总了', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱A', '1', '箱', '2'],
          ['DEF-2001', '法兰', '1', '件', '2'],
          ['ABC-1024', '纸箱B', '1', '箱', '2'],
        ]),
        mapping: mapping,
      );
      expect(r.warningCount, 0);
      expect(r.errorCount, 0);
      final mergeIssue = r.issues.firstWhere((i) => i.message.contains('重复'));
      expect(mergeIssue.level, IssueLevel.info);
      expect(mergeIssue.row, 4, reason: '提示应指向被合并的那一行（原表第 4 行）');
      expect(mergeIssue.message, contains('已合并为一件货'));
    });

    test('同编码出现在多个箱子 → 箱号收集成「箱A、箱B」', () {
      final r = ChecklistImporter.parse(
        grid: g([
          const ['货品编码', '货品名称', '数量', '单位', '要求张数', '包装箱号'],
          ['BOX-0012', '轴承', '3', '件', '2', '箱A'],
          ['BOX-0012', '轴承', '5', '件', '2', '箱B'],
        ]),
        mapping: const ColumnMapping(
          headerRow: 0,
          columns: {
            ChecklistField.itemCode: 0,
            ChecklistField.name: 1,
            ChecklistField.qty: 2,
            ChecklistField.unit: 3,
            ChecklistField.requiredPhotos: 4,
            ChecklistField.container: 5,
          },
        ),
      );
      final row = r.rows.single;
      expect(row.qty, 8);
      expect(row.container, '箱A、箱B');
    });

    test('箱号去重：同一箱被列了两次不重复显示', () {
      final r = ChecklistImporter.parse(
        grid: g([
          const ['货品编码', '货品名称', '数量', '单位', '要求张数', '包装箱号'],
          ['BOX-0012', '轴承', '3', '件', '2', '箱A'],
          ['BOX-0012', '轴承', '5', '件', '2', '箱A'],
        ]),
        mapping: const ColumnMapping(
          headerRow: 0,
          columns: {
            ChecklistField.itemCode: 0,
            ChecklistField.name: 1,
            ChecklistField.qty: 2,
            ChecklistField.unit: 3,
            ChecklistField.requiredPhotos: 4,
            ChecklistField.container: 5,
          },
        ),
      );
      expect(r.rows.single.container, '箱A');
      expect(r.rows.single.qty, 8, reason: '箱号去重不影响数量累加');
    });

    test('只有首行有箱号时也保留下来', () {
      final r = ChecklistImporter.parse(
        grid: g([
          const ['货品编码', '货品名称', '数量', '单位', '要求张数', '包装箱号'],
          ['BOX-0012', '轴承', '3', '件', '2', '箱A'],
          ['BOX-0012', '轴承', '5', '件', '2', ''],
        ]),
        mapping: const ColumnMapping(
          headerRow: 0,
          columns: {
            ChecklistField.itemCode: 0,
            ChecklistField.name: 1,
            ChecklistField.qty: 2,
            ChecklistField.unit: 3,
            ChecklistField.requiredPhotos: 4,
            ChecklistField.container: 5,
          },
        ),
      );
      expect(r.rows.single.container, '箱A');
    });

    test('任一行缺数量 → 整件货数量留空（不给少算的数）', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '3', '箱', '2'],
          ['ABC-1024', '纸箱', '待定', '箱', '2'],
        ]),
        mapping: mapping,
      );
      expect(
        r.rows.single.qty,
        isNull,
        reason: '总数已不可信，宁可留空让人回原表查，也不要给一个少算的数',
      );
    });

    test('首行就缺数量 → 后续行也不该给出总数', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '', '箱', '2'],
          ['ABC-1024', '纸箱', '5', '箱', '2'],
        ]),
        mapping: mapping,
      );
      expect(r.rows.single.qty, isNull);
    });

    test('三行以上合并同样正确，且提示逐行指出与首行冲突', () {
      final r = ChecklistImporter.parse(
        grid: g([
          const ['货品编码', '货品名称', '数量', '单位', '要求张数', '包装箱号'],
          ['M-001', '螺母', '10', '件', '2', '箱A'],
          ['M-001', '螺母', '20', '件', '2', '箱B'],
          ['M-001', '螺母', '30', '件', '2', '箱C'],
        ]),
        mapping: const ColumnMapping(
          headerRow: 0,
          columns: {
            ChecklistField.itemCode: 0,
            ChecklistField.name: 1,
            ChecklistField.qty: 2,
            ChecklistField.unit: 3,
            ChecklistField.requiredPhotos: 4,
            ChecklistField.container: 5,
          },
        ),
      );
      expect(r.rows.single.qty, 60);
      expect(r.rows.single.container, '箱A、箱B、箱C');
      expect(r.issues.where((i) => i.message.contains('重复')).length, 2);
      expect(r.skippedRows, 2, reason: '清单 3 行 → 货品 1 件，少掉的 2 行就是被合并的');
    });

    test('关掉 sameCodeMultiRow → 退回「保留首次、其余跳过」的旧行为', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱A', '3', '箱', '2'],
          ['ABC-1024', '纸箱B', '5', '箱', '2'],
        ]),
        mapping: mapping,
        sameCodeMultiRow: false,
      );
      expect(r.rows.length, 1);
      expect(r.rows.single.name, '纸箱A');
      expect(r.rows.single.qty, 3, reason: '旧行为：数量不累加');
      expect(r.warningCount, 1);
    });

    test('与项目里已存在的编码冲突 → 跳过（保护它已有的照片归属）', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '1', '箱', '2'],
          ['NEW-0001', '新货', '1', '件', '2'],
        ]),
        mapping: mapping,
        existingCodes: {'ABC-1024'},
      );
      expect(r.rows.length, 1);
      expect(r.rows.single.code, 'NEW-0001');
      expect(r.issues.first.message, contains('已存在'));
    });

    test('合并后的编码不会与库里已有编码互相干扰（合并优先）', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['A-1', '甲', '1', '件', '2'],
          ['A-1', '甲', '2', '件', '2'],
          ['B-1', '乙', '1', '件', '2'],
        ]),
        mapping: mapping,
        existingCodes: {'B-1'},
      );
      expect(r.rows.length, 1);
      expect(r.rows.single.code, 'A-1');
      expect(r.rows.single.qty, 3);
    });

    test('sourceLineCount 记录合并了几行（单行货品 = 1）', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['S-1', '单行货', '1', '件', '2'],
          ['M-1', '多行货', '1', '件', '2'],
          ['M-1', '多行货', '2', '件', '2'],
          ['M-1', '多行货', '3', '件', '2'],
        ]),
        mapping: mapping,
      );
      final single = r.rows.firstWhere((x) => x.code == 'S-1');
      final multi = r.rows.firstWhere((x) => x.code == 'M-1');
      expect(single.sourceLineCount, 1);
      expect(multi.sourceLineCount, 3);
      expect(multi.qty, 6);
    });
  });

  group('规则 3：文件名不安全字符 → 自动替换', () {
    test('斜杠等字符被替换，且原始编码仍保留', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['AB/CD:12', '纸箱', '1', '箱', '2'],
        ]),
        mapping: mapping,
      );
      final row = r.rows.single;
      expect(row.code, 'AB/CD:12', reason: '原始编码必须原样保留');
      expect(row.codeSafe, 'AB_CD_12', reason: '文件名版本做替换');
      expect(r.warningCount, 1);
    });

    test('编码尾部不能以点或空格结尾（Windows 限制）', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024. ', '纸箱', '1', '箱', '2'],
        ]),
        mapping: mapping,
      );
      expect(r.rows.single.codeSafe.endsWith('.'), isFalse);
    });
  });

  group('规则 4：全角与空格 → 归一化', () {
    test('全角编码被规范为半角，并给提示', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ＡＢＣ－１０２４', '纸箱', '１００', '箱', '２'],
        ]),
        mapping: mapping,
      );
      expect(r.rows.single.code, 'ABC-1024');
      expect(r.rows.single.qty, 100);
      expect(r.rows.single.requiredPhotos, 2);
      expect(
        r.issues.any((i) => i.level == IssueLevel.info && i.message.contains('全角')),
        isTrue,
      );
    });

    test('前后空格被去掉', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['  ABC-1024  ', '纸箱', '1', '箱', '2'],
        ]),
        mapping: mapping,
      );
      expect(r.rows.single.code, 'ABC-1024');
    });
  });

  group('其他', () {
    test('数量无法解析时留空并给提示，不阻塞导入', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '一百箱', '箱', '2'],
        ]),
        mapping: mapping,
      );
      expect(r.rows.single.qty, isNull);
      expect(r.canProceed, isTrue);
    });

    test('未指定编码列 → 报错，且不产出任何行', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', '纸箱', '1', '箱', '2'],
        ]),
        mapping: const ColumnMapping.empty(),
      );
      expect(r.canProceed, isFalse);
      expect(r.issues.first.message, contains('货品编码'));
    });

    test('全部行都无效 → 不能继续', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['', '', '', '', ''],
        ]),
        mapping: mapping,
      );
      expect(r.rows, isEmpty);
      expect(r.canProceed, isFalse);
    });

    test('skippedRows 统计正确', () {
      final r = ChecklistImporter.parse(
        grid: g([
          header,
          ['ABC-1024', 'A', '1', '箱', '2'],
          ['', '合计', '1', '', ''],
          ['ABC-1024', '重复', '2', '箱', '2'],
          ['DEF-2001', 'B', '1', '件', '2'],
        ]),
        mapping: mapping,
      );
      expect(r.totalSourceRows, 4);
      expect(r.rows.length, 2, reason: '重复行被合并进第一行，不是新增一条');
      expect(r.rows.first.qty, 3, reason: '1 + 2，合并后累加');
      // 少掉的 2 行：空编码的「合计」行 + 被合并的重复行
      expect(r.skippedRows, 2);
    });
  });

  group('列映射自动推断', () {
    test('中文表头能全部命中', () {
      final m = ColumnMapper.autoDetect(g([header]));
      expect(m[ChecklistField.itemCode], 0);
      expect(m[ChecklistField.name], 1);
      expect(m[ChecklistField.qty], 2);
      expect(m[ChecklistField.unit], 3);
      expect(m[ChecklistField.requiredPhotos], 4);
      expect(m.isValid, isTrue);
    });

    test('英文/混合表头也能命中', () {
      final m = ColumnMapper.autoDetect(g([
        ['Item Code', 'Description', 'QTY', 'Unit', 'Remark'],
      ]));
      expect(m[ChecklistField.itemCode], 0);
      expect(m[ChecklistField.name], 1);
      expect(m[ChecklistField.qty], 2);
      expect(m[ChecklistField.unit], 3);
      expect(m[ChecklistField.remark], 4);
    });

    test('表头不在第一行时能自动找到它', () {
      final m = ColumnMapper.autoDetect(g([
        ['XX 公司预检清单'],
        ['制表：小王'],
        header,
        ['ABC-1024', '纸箱', '1', '箱', '2'],
      ]));
      expect(m.headerRow, 2);
      expect(m.isValid, isTrue);
    });

    test('「规格型号」不会被误判成「型号」和别的字段', () {
      final m = ColumnMapper.autoDetect(g([
        ['货品编码', '品名', '规格型号', '数量'],
      ]));
      expect(m[ChecklistField.spec], 2);
      // 一个列只能映射到一个字段
      final cols = m.columns.values.toList();
      expect(cols.toSet().length, cols.length);
    });

    test('识别不出编码列时 isValid 为 false', () {
      final m = ColumnMapper.autoDetect(g([
        ['甲', '乙', '丙'],
        ['1', '2', '3'],
      ]));
      expect(m.isValid, isFalse);
    });
  });

  // ─────────────────────────────────────────────────────────────
  // 包装箱列识别（P4 诉求 1）
  // ─────────────────────────────────────────────────────────────
  group('列映射自动推断 · 包装箱', () {
    test('「包装箱号」被识别为包装箱列', () {
      final m = ColumnMapper.autoDetect(g([
        ['货品编码', '货品名称', '数量', '包装箱号'],
      ]));
      expect(m[ChecklistField.container], 3);
    });

    test('单独一个「箱号」也能命中', () {
      final m = ColumnMapper.autoDetect(g([
        ['货品编码', '品名', '箱号'],
      ]));
      expect(m[ChecklistField.container], 2);
    });

    test('英文表头 carton no. / box 能命中', () {
      final m = ColumnMapper.autoDetect(g([
        ['Item Code', 'Description', 'Qty', 'Carton No.'],
      ]));
      expect(m[ChecklistField.container], 3);
    });

    test('全角空格（U+3000）包裹的表头也能命中', () {
      final m = ColumnMapper.autoDetect(g([
        ['货品编码', '品名', '\u3000包装箱号\u3000'],
      ]));
      expect(m[ChecklistField.container], 2);
    });

    test('没有箱号列时不误报 —— container 不出现在映射里', () {
      final m = ColumnMapper.autoDetect(g([header]));
      expect(m[ChecklistField.container], isNull);
      expect(m[ChecklistField.itemCode], 0);
      expect(m.isValid, isTrue, reason: '箱号列缺失不该让整个导入不可用');
    });

    test('「要求张数」不会被「箱」字抢走', () {
      final m = ColumnMapper.autoDetect(g([
        ['货品编码', '要求张数', '包装箱'],
      ]));
      expect(m[ChecklistField.requiredPhotos], 1);
      expect(m[ChecklistField.container], 2);
    });
  });

  // ─────────────────────────────────────────────────────────────
  // 真实清单结构（2026-09-24 客户清单 PIDU9352234 实证）
  //
  // 该清单的三个结构特征，每一条都逼出了代码改进：
  //   1. 英文表头：Carton number. / Model Number / DESCRIPTION / Order Qty
  //      —— Model Number 不含 'no'/'code' 子串，通用词命中不了，
  //      需要给 itemCode 加具体词。
  //   2. 箱号稀疏填写（Excel 合并单元格的视觉习惯）：BOX-M10 只写在
  //      同箱首行，其余行留空 —— 需要向下填充。
  //   3. 末尾备注行：整行只有 "NOTE.:1、..."，编码为空 —— 应跳过且
  //      不能污染箱号 carry。
  // ─────────────────────────────────────────────────────────────
  group('真实清单结构（PIDU9352234 实证）', () {
    const piduHeader = [
      'Carton number. ',
      'Model Number',
      'DESCRIPTION',
      'Order Qty',
      'Loading Qty',
      'Quantity Check result',
    ];

    const piduMapping = ColumnMapping(
      headerRow: 0,
      columns: {
        ChecklistField.container: 0,
        ChecklistField.itemCode: 1,
        ChecklistField.name: 2,
        ChecklistField.qty: 3,
      },
    );

    test('英文表头自动映射：Model Number 必须命中编码列', () {
      final m = ColumnMapper.autoDetect(g([piduHeader]));
      expect(m[ChecklistField.container], 0);
      expect(m[ChecklistField.itemCode], 1, reason: '编码列就叫 Model Number');
      expect(m[ChecklistField.name], 2);
      expect(m[ChecklistField.qty], 3);
      expect(m.isValid, isTrue);
    });

    test('箱号稀疏填写 → 向下填充（合并单元格的视觉语义）', () {
      final r = ChecklistImporter.parse(
        grid: g([
          piduHeader,
          ['BOX-M10', '103006010017BM', 'Plate, connecting', '108', '108', 'PASS'],
          ['', '103006010026BMX', 'Sleeve, shaft', '72', '72', 'PASS'],
          ['', '103006010027CM', 'Plate, connecting', '36', '36', 'PASS'],
          ['BOX-M12', '103003010019AMX', 'Ear plate', '36', '36', 'PASS'],
          ['', '103003010026AMX', 'Shaft sleeve', '18', '18', 'PASS'],
        ]),
        mapping: piduMapping,
      );
      expect(r.rows.length, 5);
      expect(r.rows[0].container, 'BOX-M10');
      expect(r.rows[1].container, 'BOX-M10', reason: '首行箱号向下填充');
      expect(r.rows[2].container, 'BOX-M10');
      expect(r.rows[3].container, 'BOX-M12', reason: '新箱号覆盖 carry');
      expect(r.rows[4].container, 'BOX-M12');
    });

    test('备注行（编码为空）被跳过，且不污染后续行的箱号', () {
      final r = ChecklistImporter.parse(
        grid: g([
          piduHeader,
          ['BOX-M10', '103006010017BM', 'Plate', '108', '108', 'PASS'],
          ['NOTE.:1、103006010021CMX loaded into RACK M17;', '', '', '', '', ''],
          ['PALLET-M1', '1000000119', '焊丝ER50-6', '1', '1', 'PASS'],
        ]),
        mapping: piduMapping,
      );
      expect(r.rows.length, 2);
      expect(r.rows[0].container, 'BOX-M10');
      expect(r.rows[1].container, 'PALLET-M1',
          reason: 'NOTE 行不能把自己的文字灌进下一行的箱号');
      expect(r.rows[1].code, '1000000119');
    });

    test('同一编码分散多箱（真实清单 6 组重复）→ 合并且箱号收集', () {
      final r = ChecklistImporter.parse(
        grid: g([
          piduHeader,
          ['BOX-M10', '103006010026BMX', 'Sleeve, shaft', '72', '72', 'PASS'],
          ['BOX-M12', '103006010026BMX', 'Sleeve, shaft', '18', '18', 'PASS'],
          ['PALLET-M1', '1000000119', '焊丝', '1', '1', 'PASS'],
          ['PALLET-M2', '1000000119', '焊丝', '1', '1', 'PASS'],
        ]),
        mapping: piduMapping,
      );
      expect(r.rows.length, 2);
      final bmx = r.rows.firstWhere((x) => x.code == '103006010026BMX');
      expect(bmx.qty, 90, reason: '72 + 18');
      expect(bmx.container, 'BOX-M10、BOX-M12');
      final wire = r.rows.firstWhere((x) => x.code == '1000000119');
      expect(wire.container, 'PALLET-M1、PALLET-M2');
    });
  });
}
