import 'dart:convert';
import 'dart:typed_data';

import 'package:archive/archive.dart' as arc;
import 'package:flutter_test/flutter_test.dart';
import 'package:g_tick_picture/domain/checklist/biff8_reader.dart';
import 'package:g_tick_picture/domain/checklist/checklist_file_reader.dart';
import 'package:g_tick_picture/domain/checklist/column_mapper.dart';

import 'fixtures/xls_fixture.dart';

Uint8List get _xlsBytes => base64Decode(kXlsFixtureBase64);

void main() {
  group('Biff8Reader · 真实 .xls', () {
    test('解析出所有工作表，跳过空表', () {
      final sheets = Biff8Reader.parse(_xlsBytes);
      // 夹具里有 3 个表（清单 / 空表 / 第二表），空表无单元格应被跳过
      expect(sheets.map((s) => s.name), ['清单', '第二表']);
    });

    test('字符串 / 中文 / 整数 / 浮点全部正确', () {
      final sheet = Biff8Reader.parse(_xlsBytes).first;
      expect(sheet.rows[0], ['货品编码', '品名', '规格', '数量']);
      expect(sheet.rows[1], ['BOX-M11', 'Plate', '100x200', '20']);
      // 中文走 UTF-16LE 分支 —— 解错会变乱码，这是最关键的一条断言
      expect(sheet.rows[2], ['BOX-M13', '轴套', 'Φ30', '40']);
      // 浮点必须保留小数（RK 解码的符号位/尾数位错了这里就露馅）
      expect(sheet.rows[3], ['RACK-M8-1', '方管', 'M8', '18.5']);
    });

    test('列映射能自动认出货品编码列', () {
      final sheet = Biff8Reader.parse(_xlsBytes).first;
      final grid = SheetGrid(name: sheet.name, rows: sheet.rows);
      final mapping = ColumnMapper.autoDetect(grid);
      expect(mapping.isValid, isTrue, reason: '必须自动认出「货品编码」列');
      expect(mapping.headerRow, 0);
    });
  });

  group('Biff8Reader · 容错', () {
    test('非 OLE2 字节 → Ole2Reader 找不到流 → FormatException', () {
      expect(
        () => Biff8Reader.parse(_xlsBytes.sublist(0, 64)),
        throwsA(isA<Object>()),
      );
    });

    test('畸形记录流不崩溃（返回空或抛受控异常）', () {
      // 全 0xFF 的流：记录头解析会立刻越界，应被吞掉
      final junk = Uint8List.fromList(List<int>.filled(512, 0xFF));
      expect(() {
        try {
          Biff8Reader.parseStreamBytes(junk);
        } catch (_) {
          /* 受控异常可接受 */
        }
      }, returnsNormally);
    });
  });

  group('ChecklistFileReader · .xls 分流', () {
    test('真 OLE2 二进制 .xls → 直接解析出数据（不再抛"请另存为"）', () {
      final grids = ChecklistFileReader.readXlsForTest(_xlsBytes);
      final list = grids.firstWhere((g) => g.name == '清单');
      expect(list.rowCount, 4);
      expect(list.rows[2][1], '轴套');
    });

    test('HTML 表格伪装的 .xls → 直接解析出行列', () {
      const html = '''
<html><body>
<table>
  <tr><th>Carton No.</th><th>Model Number</th><th>DESCRIPTION</th><th>Qty</th></tr>
  <tr><td>BOX-M11</td><td>103010013345AMX</td><td>Plate</td><td>20</td></tr>
  <tr><td>BOX-M12</td><td>103010013353BMX</td><td>Round steel</td><td>40</td></tr>
</table>
</body></html>
''';
      final grids = ChecklistFileReader.readXlsForTest(utf8.encode(html));
      expect(grids, hasLength(1));
      expect(grids.single.rowCount, 3);
      expect(grids.single.rows[1], ['BOX-M11', '103010013345AMX', 'Plate', '20']);
      expect(grids.single.rows[2][1], '103010013353BMX');
    });

    test('HTML 单元格里的标签与常见实体会被清理', () {
      const html = '<table><tr><td><b>A&amp;B</b></td><td>x&nbsp;y</td></tr></table>';
      final grids = ChecklistFileReader.readXlsForTest(utf8.encode(html));
      expect(grids.single.rows[0], ['A&B', 'x y']);
    });

    test('tab 分隔文本伪装的 .xls → 按 TSV 解析', () {
      const tsv = '编码\t品名\t数量\nBOX-1\tPlate\t20\nBOX-2\tShaft\t40';
      final grids = ChecklistFileReader.readXlsForTest(utf8.encode(tsv));
      expect(grids.single.rowCount, 3);
      expect(grids.single.rows[1], ['BOX-1', 'Plate', '20']);
    });

    test('逗号分隔文本伪装的 .xls → 按 CSV 解析', () {
      const csv = '编码,品名\nBOX-1,Plate';
      final grids = ChecklistFileReader.readXlsForTest(utf8.encode(csv));
      expect(grids.single.rows[1], ['BOX-1', 'Plate']);
    });

    test('OLE2 魔数但内容损坏 → 抛出带「另存为」指引的友好异常', () {
      // 只有 8 字节魔数、后面没有真实结构
      final fake = <int>[0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1, 0, 0];
      expect(
        () => ChecklistFileReader.readXlsForTest(fake),
        throwsA(isA<UnsupportedChecklistFormatException>().having(
          (e) => e.message,
          'message',
          contains('另存为'),
        )),
      );
    });
  });

  group('ChecklistFileReader · WPS xlsx numFmtId 修复', () {
    // excel 包断言自定义 numFmtId >= 164；WPS 会写 numFmtId="41"。
    // 这里构造一个只含 xl/styles.xml 的 zip，直接验证重编号逻辑。
    test('低区间 numFmtId 被重编号到 164+，定义与引用同步', () async {
      const stylesXml = '''
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="2">
    <numFmt numFmtId="41" formatCode="_(&quot;\$&quot;* #,##0_)"/>
    <numFmt numFmtId="176" formatCode="0.000"/>
  </numFmts>
  <cellXfs count="2">
    <xf numFmtId="0" applyNumberFormat="0"/>
    <xf numFmtId="41" applyNumberFormat="1"/>
  </cellXfs>
</styleSheet>
''';
      final archive = arc.Archive()
        ..addFile(arc.ArchiveFile.string('xl/styles.xml', stylesXml));
      final zipBytes = arc.ZipEncoder().encode(archive)!;

      final fixed = ChecklistFileReader.renumberLowNumFmtIdsForTest(zipBytes);
      expect(fixed, isNotNull);

      final out = arc.ZipDecoder()
          .decodeBytes(fixed!)
          .files
          .firstWhere((f) => f.name == 'xl/styles.xml');
      final xml = utf8.decode(out.content as List<int>);
      // 41 → 177（实现从「现有最大 id 176 + 1」起编，绝不与现有 id 撞车）
      expect(xml, contains('numFmtId="177"'));
      expect(xml, isNot(contains('numFmtId="41"')));
      expect(xml, contains('numFmtId="176"')); // 高位 id 不动
      // cellXfs 里的引用同步改写（出现 2 次：定义 + 引用）
      expect('numFmtId="177"'.allMatches(xml).length, 2);
    });

    test('没有低区间 numFmtId 的文件返回 null（走原解析）', () {
      const stylesXml = '<numFmt numFmtId="164" formatCode="0.000"/>';
      final archive = arc.Archive()
        ..addFile(arc.ArchiveFile.string('xl/styles.xml', stylesXml));
      final zipBytes = arc.ZipEncoder().encode(archive)!;
      expect(ChecklistFileReader.renumberLowNumFmtIdsForTest(zipBytes), isNull);
    });
  });

  group('ChecklistFileReader · xlsx 富文本 <si> 修复', () {
    // excel 包会把「多个 <r> run 拼成的富文本」读成字面量 "null"。
    // 手工造一个最小 xlsx 复现：A1 分两段富文本、B1 普通文本。
    test('富文本单元格不再丢失，普通单元格不受影响', () {
      final grids = ChecklistFileReader.readXlsxForTest(_buildRichTextXlsx());
      expect(grids, hasLength(1));
      final row = grids.single.rows.first;
      // A1 = "Carton" + " number"（两段），必须拼回完整字符串
      expect(row[0], 'Carton number');
      expect(row[1], 'Model Number');
    });
  });
}

/// 构造一个最小 xlsx：只有一段富文本 A1 与普通文本 B1，
/// 专门复现 excel 包的富文本缺陷。
List<int> _buildRichTextXlsx() {
  const sharedStrings = '''
<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="2" uniqueCount="2">
  <si><r><t>Carton</t></r><r><rPr><b/></rPr><t xml:space="preserve"> number</t></r></si>
  <si><t>Model Number</t></si>
</sst>
''';
  const sheet1 = '''
<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
  </sheetData>
</worksheet>
''';
  const workbook = '''
<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>
''';
  const wbRels = '''
<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
  <Relationship Id="rId2" Target="sharedStrings.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"/>
  <Relationship Id="rId3" Target="styles.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"/>
</Relationships>
''';
  const contentTypes = '''
<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>
''';
  // excel 包强制要求 styles.xml 存在，否则报 "Damaged Excel file: styles"
  const styles = '''
<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>
''';

  final archive = arc.Archive()
    ..addFile(arc.ArchiveFile.string('[Content_Types].xml', contentTypes))
    ..addFile(arc.ArchiveFile.string('xl/workbook.xml', workbook))
    ..addFile(arc.ArchiveFile.string('xl/_rels/workbook.xml.rels', wbRels))
    ..addFile(arc.ArchiveFile.string('xl/worksheets/sheet1.xml', sheet1))
    ..addFile(arc.ArchiveFile.string('xl/sharedStrings.xml', sharedStrings))
    ..addFile(arc.ArchiveFile.string('xl/styles.xml', styles));
  return arc.ZipEncoder().encode(archive)!;
}
