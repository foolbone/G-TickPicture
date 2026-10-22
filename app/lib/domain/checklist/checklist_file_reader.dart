import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart' as arc;
import 'package:csv/csv.dart';
import 'package:excel/excel.dart' as xls;

import 'biff8_reader.dart';

/// 一个工作表的二维数据。
///
/// 解析层只负责把文件变成 `List<List<String?>>`，
/// **所有业务校验都在 [ChecklistImporter] 里做纯逻辑处理**。
/// 这样做的价值：校验规则可以脱离 Excel 包单测，
/// 也不会因为 excel 包升版把业务逻辑搞坏。
class SheetGrid {
  const SheetGrid({required this.name, required this.rows});

  final String name;
  final List<List<String?>> rows;

  int get rowCount => rows.length;

  int get maxColumns =>
      rows.isEmpty ? 0 : rows.map((r) => r.length).reduce((a, b) => a > b ? a : b);
}

/// 清单格式不被支持（附可执行的解决指引）。
class UnsupportedChecklistFormatException implements Exception {
  const UnsupportedChecklistFormatException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// 清单文件读取器。只做格式适配，不做业务判断。
class ChecklistFileReader {
  const ChecklistFileReader._();

  static const List<String> supportedExtensions = <String>['xlsx', 'xls', 'csv'];

  static bool isSupported(String path) {
    final i = path.lastIndexOf('.');
    if (i < 0) return false;
    return supportedExtensions.contains(path.substring(i + 1).toLowerCase());
  }

  /// 读取文件，返回其中所有工作表。
  ///
  /// 微信转发过来的文件常在文件名里带空格与中文，路径一律按原样处理。
  static Future<List<SheetGrid>> read(String path) async {
    final f = File(path);
    if (!await f.exists()) {
      throw FileSystemException('文件不存在', path);
    }
    final ext = path.substring(path.lastIndexOf('.') + 1).toLowerCase();
    final bytes = await f.readAsBytes();

    if (ext == 'csv') {
      return [_readCsv(bytes)];
    }
    if (ext == 'xls') {
      return _readXls(bytes);
    }
    return _readXlsx(bytes);
  }

  // ───────────────────────────────────────────────────────────
  // 测试入口（绕过文件系统直接喂字节；不做业务判断）
  // ───────────────────────────────────────────────────────────

  static List<SheetGrid> readXlsForTest(List<int> bytes) => _readXls(bytes);

  static List<SheetGrid> readXlsxForTest(List<int> bytes) => _readXlsx(bytes);

  static List<int>? renumberLowNumFmtIdsForTest(List<int> bytes) =>
      _renumberLowNumFmtIds(bytes);

  // ───────────────────────────────────────────────────────────
  // .xlsx
  // ───────────────────────────────────────────────────────────

  static List<SheetGrid> _readXlsx(List<int> bytes) {
    try {
      return _decodeExcel(bytes);
    } on Exception catch (e) {
      // WPS / 部分 Excel 生成的文件会把「内置区间」的数字格式（41~163）
      // 显式写进 styles.xml，而 excel 包断言自定义格式必须 >=164，
      // 直接抛 "custom numFmtId starts at 164 but found a value of 41"。
      // 我们只读单元格值、不关心显示格式 —— 把这些 id 重编号到安全
      // 区间后重试；修不动才把原异常抛给上层。
      final fixed =
          e.toString().contains('numFmtId') ? _renumberLowNumFmtIds(bytes) : null;
      if (fixed == null) rethrow;
      return _decodeExcel(fixed);
    }
  }

  static List<SheetGrid> _decodeExcel(List<int> bytes) {
    final book = xls.Excel.decodeBytes(bytes);
    final out = <SheetGrid>[];
    for (final name in book.tables.keys) {
      final table = book.tables[name];
      if (table == null) continue;
      final rows = <List<String?>>[];
      for (final row in table.rows) {
        rows.add(row.map((c) => _cell(c)).toList());
      }
      // 去掉完全空白的行（Excel 尾部常有几百行空行）
      final cleaned = _trimRows(rows);
      if (cleaned.isNotEmpty) out.add(SheetGrid(name: name, rows: cleaned));
    }
    // 富文本修复（见 [_repairRichText]）
    return _repairRichText(bytes, out);
  }

  /// 修复 excel 包对「富文本 `<si>`」的解析缺陷。
  ///
  /// ## 缺陷表现（实测）
  /// 一个 `.xlsx` 里表头 `Carton number. ` 与 `Order Qty` 是加粗标红的分段
  /// 文本，在 `sharedStrings.xml` 里存成多个 `<r>` run。excel 包会把这格
  /// 读成 `TextCellValue('null')` —— 字面量字符串 "null"，列名因此丢失，
  /// 自动列映射失效，导入报错。用户最初的报错正是这个（叠加 numFmtId 崩溃）。
  ///
  /// ## 修法
  /// 直接读 `sharedStrings.xml`（拼接每个 `<si>` 内所有 `<t>`），
  /// 再读各 `sheetN.xml` 拿到精确的「单元格 → 共享串索引」映射
  /// （`<c r="A1" t="s"><v>3</v></c>`），最后只替换那些**看起来是坏的**
  /// 字符串格（空串或字面量 "null"）。excel 包已正确解析的值不动。
  ///
  /// 任何一步失败都原样返回 —— 修复是尽力而为，不能让它把正常导入搞坏。
  static List<SheetGrid> _repairRichText(List<int> bytes, List<SheetGrid> grids) {
    try {
      final zip = arc.ZipDecoder().decodeBytes(bytes);

      arc.ArchiveFile? sstEntry;
      for (final f in zip.files) {
        if (f.isFile && f.name == 'xl/sharedStrings.xml') {
          sstEntry = f;
          break;
        }
      }
      if (sstEntry == null) return grids;

      final strings = _parseSharedStrings(xmlOf(sstEntry));
      if (strings.isEmpty) return grids;

      // workbook.xml（sheet 名 + r:id） + workbook.xml.rels（r:id → 文件）
      // → 「显示名 → 物理文件」的准确映射，避免靠文件名数字猜顺序。
      final nameToFile = _sheetNameToFile(zip);
      if (nameToFile.isEmpty) return grids;

      final result = <SheetGrid>[];
      for (final grid in grids) {
        final file = nameToFile[grid.name];
        if (file == null) {
          result.add(grid);
          continue;
        }
        final patch = _cellTextMap(xmlOf(file), strings);
        result.add(SheetGrid(
          name: grid.name,
          rows: _applyPatch(grid.rows, patch),
        ));
      }
      return result;
    } catch (_) {
      return grids;
    }
  }

  static String xmlOf(arc.ArchiveFile f) =>
      utf8.decode(f.content as List<int>, allowMalformed: true);

  /// 只覆盖「空串 / 字面量 null」的文本格 —— excel 包已正确解析的值不碰。
  ///
  /// grid 的行已被 [_trimRows] 压掉空行，而 patch 用 xlsx 原始行号。
  /// 被压掉的行必然是空行（不含富文本），所以两者在真实文件里是对齐的；
  /// 万一不对齐，最坏结果也只是某个空格多填了一个值，不会破坏已有数据。
  static List<List<String?>> _applyPatch(
      List<List<String?>> rows, Map<int, Map<int, String>> patch) {
    final out = <List<String?>>[];
    for (var r = 0; r < rows.length; r++) {
      final src = patch[r];
      final row = List<String?>.from(rows[r]);
      if (src != null) {
        src.forEach((c, v) {
          if (c < row.length) {
            final cur = row[c];
            if (cur == null || cur.isEmpty || cur == 'null') row[c] = v;
          }
        });
      }
      out.add(row);
    }
    return out;
  }

  static List<String> _parseSharedStrings(String xml) {
    final out = <String>[];
    final siRe = RegExp(r'<si>([\s\S]*?)</si>|<si\s*/>');
    final tRe = RegExp(r'<t[^>]*>([\s\S]*?)</t>');
    for (final m in siRe.allMatches(xml)) {
      final body = m.group(1);
      if (body == null) {
        out.add('');
        continue;
      }
      final sb = StringBuffer();
      for (final tm in tRe.allMatches(body)) {
        sb.write(_unescapeXml(tm.group(1) ?? ''));
      }
      out.add(sb.toString());
    }
    return out;
  }

  /// 从 sheet XML 里取 `<c r="A1" t="s"><v>idx</v></c>` 的精确行列与文本。
  static Map<int, Map<int, String>> _cellTextMap(
      String xml, List<String> strings) {
    final out = <int, Map<int, String>>{};
    final cRe = RegExp(r'<c\s+r="([A-Z]+)(\d+)"([^>]*)>([\s\S]*?)</c>');
    for (final m in cRe.allMatches(xml)) {
      final attrs = m.group(3) ?? '';
      if (!attrs.contains('t="s"')) continue; // 只看共享字符串格
      final vRe = RegExp(r'<v>(\d+)</v>');
      final vm = vRe.firstMatch(m.group(4) ?? '');
      if (vm == null) continue;
      final idx = int.tryParse(vm.group(1)!) ?? -1;
      if (idx < 0 || idx >= strings.length) continue;
      final col = _columnIndex(m.group(1)!);
      final row = (int.tryParse(m.group(2)!) ?? 1) - 1; // 0-based
      (out[row] ??= <int, String>{})[col] = strings[idx];
    }
    return out;
  }

  /// "A"→0, "B"→1, ... "AA"→26
  static int _columnIndex(String letters) {
    var n = 0;
    for (final code in letters.toUpperCase().codeUnits) {
      n = n * 26 + (code - 0x40);
    }
    return n - 1;
  }

  /// 由 `xl/workbook.xml` 与 `xl/_rels/workbook.xml.rels` 还原
  /// 「工作表显示名 → 物理 sheetN.xml」的映射。
  ///
  /// 不能靠「sheet1.xml 就是第一个表」来猜 —— 表顺序与文件名无关
  /// （用户可以拖动排序，也可以删表后再增表）。读不出时返回空表，
  /// 由调用方跳过修复。
  static Map<String, arc.ArchiveFile> _sheetNameToFile(arc.Archive zip) {
    final out = <String, arc.ArchiveFile>{};

    arc.ArchiveFile? wb;
    arc.ArchiveFile? rels;
    final files = <String, arc.ArchiveFile>{};
    for (final f in zip.files) {
      if (!f.isFile) continue;
      files[f.name] = f;
      if (f.name == 'xl/workbook.xml') wb = f;
      if (f.name == 'xl/_rels/workbook.xml.rels') rels = f;
    }
    if (wb == null || rels == null) return out;

    // rels: <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
    final ridToTarget = <String, String>{};
    for (final m in RegExp(r'<Relationship\b[^>]*>')
        .allMatches(xmlOf(rels))) {
      final tag = m.group(0)!;
      final id = _attr(tag, 'Id');
      final target = _attr(tag, 'Target');
      if (id == null || target == null) continue;
      ridToTarget[id] = target.startsWith('/')
          ? target.substring(1)
          : (target.startsWith('xl/') ? target : 'xl/$target');
    }

    // workbook: <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
    for (final m in RegExp(r'<sheet\b[^>]*>').allMatches(xmlOf(wb))) {
      final tag = m.group(0)!;
      final name = _attr(tag, 'name');
      final rid = _attr(tag, 'r:id') ?? _attr(tag, 'id');
      if (name == null || rid == null) continue;
      final target = ridToTarget[rid];
      if (target == null) continue;
      final norm = target.replaceAll('\\', '/');
      final f = files[norm] ?? files[norm.replaceFirst('./', '')];
      if (f != null) out[_unescapeXml(name)] = f;
    }
    return out;
  }

  /// 从标签文本里取属性值（兼容单/双引号）。
  static String? _attr(String tag, String name) {
    final m = RegExp('$name\\s*=\\s*"([^"]*)"').firstMatch(tag) ??
        RegExp("$name\\s*=\\s*'([^']*)'").firstMatch(tag);
    return m?.group(1);
  }

  static String _unescapeXml(String s) {
    var t = s;
    t = t.replaceAll('&lt;', '<');
    t = t.replaceAll('&gt;', '>');
    t = t.replaceAll('&quot;', '"');
    t = t.replaceAll('&apos;', "'");
    t = t.replaceAll('&amp;', '&'); // & 最后处理，避免二次解码
    return t;
  }

  static String? _cell(xls.Data? d) {
    if (d == null) return null;
    final v = d.value;
    if (v == null) return null;
    if (v is xls.TextCellValue) return v.value.text;
    if (v is xls.IntCellValue) return v.value.toString();
    if (v is xls.DoubleCellValue) {
      final n = v.value;
      return n == n.roundToDouble() ? n.toInt().toString() : n.toString();
    }
    return v.toString();
  }

  /// 去掉完全空白的行（Excel / WPS 尾部常有几百行格式残留的空行）。
  static List<List<String?>> _trimRows(List<List<String?>> rows) =>
      rows.where((r) => r.any((c) => c != null && c.trim().isNotEmpty)).toList();

  /// 把 xlsx（zip）里 styles.xml 中 <164 的自定义 numFmtId 重编号到
  /// 「现有最大 id + 1」起的连续区间。定义处（<numFmt>）与引用处
  /// （cellXfs 里的 xf）都会被同一条 `numFmtId="N"` 替换覆盖。
  /// 修不动（非 zip / 没有 styles.xml / 意外结构）时返回 null。
  static List<int>? _renumberLowNumFmtIds(List<int> bytes) {
    try {
      final zip = arc.ZipDecoder().decodeBytes(bytes);
      arc.ArchiveFile? entry;
      for (final file in zip.files) {
        if (file.isFile && file.name == 'xl/styles.xml') {
          entry = file;
          break;
        }
      }
      if (entry == null) return null;

      var xmlText = utf8.decode(entry.content as List<int>, allowMalformed: true);
      final defRe = RegExp(r'<numFmt[^>]*numFmtId="(\d+)"');
      final ids =
          defRe.allMatches(xmlText).map((m) => int.parse(m.group(1)!)).toSet();
      if (ids.isEmpty) return null;
      final low = ids.where((n) => n < 164).toList()..sort();
      if (low.isEmpty) return null;

      var next = ids.fold<int>(163, (a, b) => a > b ? a : b) + 1;
      for (final old in low) {
        xmlText = xmlText.replaceAll('numFmtId="$old"', 'numFmtId="$next"');
        next++;
      }
      // ArchiveFile.content 只读 —— 用改好的 styles.xml 重建该条目
      final outZip = arc.Archive();
      for (final f in zip.files) {
        if (f.isFile && f.name == entry.name) {
          outZip.addFile(arc.ArchiveFile.string(entry.name, xmlText));
        } else {
          outZip.addFile(f);
        }
      }
      return arc.ZipEncoder().encode(outZip);
    } catch (_) {
      return null;
    }
  }

  // ───────────────────────────────────────────────────────────
  // .xls（97-2003 与「伪装 .xls」）
  // ───────────────────────────────────────────────────────────

  /// .xls 的三条分流。真正的 97-2003 二进制格式（OLE2 复合文档）
  /// 走自研的 [Biff8Reader]；另外两类「伪 .xls」在老 ERP / 物流系统里
  /// 同样常见，一并支持：
  ///   · OLE2 魔数 → BIFF8 记录流解析（[Biff8Reader]）
  ///   · HTML 表格伪装 → 直接提取 <table>
  ///   · 纯文本（tab / 逗号分隔）→ 按 CSV 解析
  static List<SheetGrid> _readXls(List<int> bytes) {
    // OLE2 复合文档魔数：D0 CF 11 E0 A1 B1 1A E1
    final isOle2 = bytes.length >= 8 &&
        bytes[0] == 0xD0 &&
        bytes[1] == 0xCF &&
        bytes[2] == 0x11 &&
        bytes[3] == 0xE0 &&
        bytes[4] == 0xA1 &&
        bytes[5] == 0xB1 &&
        bytes[6] == 0x1A &&
        bytes[7] == 0xE1;
    if (isOle2) {
      try {
        final sheets = Biff8Reader.parse(Uint8List.fromList(bytes));
        final out = sheets
            .map((s) => SheetGrid(name: s.name, rows: _trimRows(s.rows)))
            .where((g) => g.rows.isNotEmpty)
            .toList();
        if (out.isNotEmpty) return out;
        throw const UnsupportedChecklistFormatException(
            '这个 .xls 文件里没有可用的表格数据。'
            '请确认文件内容，或用 Excel / WPS 另存为 .xlsx 后再导入。');
      } on UnsupportedChecklistFormatException {
        rethrow;
      } catch (_) {
        // 加密工作簿、BIFF5 及更早版本、文件损坏等 —— 给出可执行的出路
        throw const UnsupportedChecklistFormatException(
            '这个 .xls 文件读不出来（可能是加密、损坏，或是 Excel 5.0 之前的老格式）。'
            '请用 Excel 或 WPS 打开后「另存为」.xlsx 再导入。');
      }
    }

    final text = utf8.decode(bytes, allowMalformed: true).trimLeft();
    if (text.startsWith('<')) {
      // HTML / XML 伪装的 .xls
      final grid = _readHtmlTable(text);
      if (grid != null) return [grid];
      throw const UnsupportedChecklistFormatException(
          '这个 .xls 文件的内容无法识别。'
          '请用 Excel 或 WPS 打开后另存为 .xlsx 再导入。');
    }

    // 文本伪装：按首个数据行里 tab 与逗号的数量选分隔符
    final delimiter = _sniffDelimiter(text);
    return [_readDelimited(text, delimiter, name: 'XLS')];
  }

  static String _sniffDelimiter(String text) {
    final firstLine = text.split('\n').first;
    final tabs = '\t'.allMatches(firstLine).length;
    final commas = ','.allMatches(firstLine).length;
    return tabs > commas ? '\t' : ',';
  }

  /// 极简 HTML 表格提取（老系统导出的 .xls 多为规整的 <table> 文本）。
  /// 不做 colspan 展开 —— 货品清单场景列合并极少见，出现时宁可错位
  /// 也不静默吞行；解析不出任何行返回 null。
  static SheetGrid? _readHtmlTable(String text) {
    final tableRe =
        RegExp(r'<table[^>]*>([\s\S]*?)</table>', caseSensitive: false);
    final table = tableRe.firstMatch(text);
    if (table == null) return null;

    final trRe = RegExp(r'<tr[^>]*>([\s\S]*?)</tr>', caseSensitive: false);
    final cellRe = RegExp(r'<t[dh][^>]*>([\s\S]*?)</t[dh]>', caseSensitive: false);

    final rows = <List<String?>>[];
    for (final tr in trRe.allMatches(table.group(1)!)) {
      rows.add(
          cellRe.allMatches(tr.group(1)!).map((m) => _stripHtml(m.group(1) ?? '')).toList());
    }
    final cleaned =
        rows.where((r) => r.any((c) => c != null && c.trim().isNotEmpty)).toList();
    if (cleaned.isEmpty) return null;
    return SheetGrid(name: 'XLS', rows: cleaned);
  }

  static String _stripHtml(String s) {
    var t = s.replaceAll(RegExp(r'<[^>]*>'), ' ');
    const entities = <String, String>{
      '&nbsp;': ' ',
      '&amp;': '&',
      '&lt;': '<',
      '&gt;': '>',
      '&quot;': '"',
      '&#39;': "'",
    };
    entities.forEach((k, v) => t = t.replaceAll(k, v));
    return t.replaceAll(RegExp(r'\s+'), ' ').trim();
  }

  // ───────────────────────────────────────────────────────────
  // CSV / 分隔文本
  // ───────────────────────────────────────────────────────────

  static SheetGrid _readCsv(List<int> bytes) {
    var text = utf8.decode(bytes, allowMalformed: true);
    if (text.startsWith('\uFEFF')) text = text.substring(1); // 去 BOM
    return _readDelimited(text, ',', name: 'CSV');
  }

  static SheetGrid _readDelimited(String text, String delimiter,
      {required String name}) {
    // csv 包默认只按 \r\n 分行 —— Unix/微信传输的文件常是 \n，
    // 不统一行尾的话整份文件会被解析成一行（2026-09-23 实测踩中）。
    final normalized = text.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
    final raw = CsvToListConverter(
      shouldParseNumbers: false,
      fieldDelimiter: delimiter,
      eol: '\n',
    ).convert(normalized);
    final rows = raw
        .map<List<String?>>((r) => r.map<String?>((c) => c?.toString()).toList())
        .where((r) => r.any((c) => c != null && c.trim().isNotEmpty))
        .toList();
    return SheetGrid(name: name, rows: rows);
  }
}
