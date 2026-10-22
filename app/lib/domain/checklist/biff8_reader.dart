import 'dart:typed_data';

import 'ole2_reader.dart';

/// BIFF8（Excel 97-2003）记录流解析器 —— 自研，只覆盖我们真正需要的部分。
///
/// ## 为什么自研
/// 见 [Ole2Reader] 的类注释：Dart 生态在 Flutter 3.29 / Dart 3.7 的约束下
/// 没有能读 .xls 的包。实测结论（2026-09-23）：
///   · `excel` 包：只吃 xlsx（zip），对 .xls 直接抛 "Invalid zip archive"
///   · `excel_plus`：所有版本都要求 Dart ^3.11.4（本机 3.7.0）
///   · `excel2003`：要求 Dart >=3.7.2（本机 3.7.0 差一点点）
/// 为读一个 2003 年的老表格去升整个 Flutter SDK，代价与收益严重倒挂。
/// 而清单导入是**离线刚需**——现场拿到的就是老系统导出的 .xls。
///
/// ## 解析三层
/// 1. OLE2 容器 → 取 `Workbook` 流（见 [Ole2Reader]）
/// 2. BIFF8 记录流（本文件）：`rid(2) + len(2) + body(len)` 顺序排列，
///    含多个 substream（全局 0x0005 + 每表 0x0010），用 BOUNDSHEET 索引
/// 3. SST 共享字符串表 + 单元格记录
///
/// ## 刻意不实现（真实清单里用不到，或做了反而增加出错面）
///   · 公式**求值** —— 只读取 FORMULA 里 Excel 已算好的缓存值
///   · 日期序列号 → 真日期 —— 清单里的日期列按原样（数字）透出，
///     业务侧列匹配用的是编码/品名/数量，日期不参与匹配。
///     真要显示时按 1900 日期系统换算即可，但不在这里做，
///     避免"解析层偷偷改变数据语义"。
///   · 加密工作簿 / BIFF5 及更早版本（<BOF 版本号 0x0600）
///
/// ## 与 [SheetGrid] 的契约
/// 输出 `List<List<String?>>`：稀疏单元格填 `null`，行按 index 对齐补空，
/// 尾部空行裁掉。**不做任何业务判断**——列怎么认由 ChecklistImporter 决定。
class Biff8Reader {
  Biff8Reader._(this._bytes);

  final Uint8List _bytes;

  // ── 记录类型 ──────────────────────────────────────────────
  static const int _bof = 0x0809;
  static const int _eof = 0x000A;
  static const int _boundSheet = 0x0085;
  static const int _sst = 0x00FC;
  static const int _continue = 0x003C;
  static const int _labelSst = 0x00FD;
  static const int _label = 0x0204;
  static const int _number = 0x0203;
  static const int _rk = 0x027E;
  static const int _mulRk = 0x00BD;
  static const int _formula = 0x0006;
  static const int _boolErr = 0x0205;

  /// 一个工作表：名字 + 该表 substream 在 Workbook 流里的字节偏移。
  static const int _substreamWorksheet = 0x0010;

  /// 解析整个 .xls（OLE2 复合文档）字节。失败时抛 [FormatException]，
  /// 由调用方 `ChecklistFileReader` 转成对用户友好的提示。
  static List<Biff8Sheet> parse(Uint8List bytes) {
    final stream = Ole2Reader.extractStream(bytes, 'Workbook') ??
        Ole2Reader.extractStream(bytes, 'Book');
    if (stream == null) {
      throw const FormatException('文件里没有找到 Workbook 数据流');
    }
    return Biff8Reader._(stream).parseStream();
  }

  /// 直接解析裸 BIFF8 记录流（测试用；真实文件都走 [parse]）。
  static List<Biff8Sheet> parseStreamBytes(Uint8List stream) =>
      Biff8Reader._(stream).parseStream();

  List<Biff8Sheet> parseStream() {
    final records = _readRecords();
    if (records.isEmpty) throw const FormatException('BIFF 记录流为空');

    final strings = _readSst(records);
    final sheets = <Biff8Sheet>[];
    for (final bs in records) {
      if (bs.id != _boundSheet) continue;
      final sheet = _readSheet(records, bs, strings);
      if (sheet != null) sheets.add(sheet);
    }
    if (sheets.isEmpty) {
      // 没有 BOUNDSHEET 的极端情况：按第一个 worksheet substream 兜底
      final firstWs = records.firstWhere(
        (r) => r.id == _bof && r.substreamType == _substreamWorksheet,
        orElse: () => throw const FormatException('文件里没有工作表'),
      );
      final grid = _collectCells(records, firstWs.bodyStart, strings);
      if (grid != null) sheets.add(Biff8Sheet(name: 'Sheet1', rows: grid));
    }
    return sheets;
  }

  // ───────────────────────────────────────────────────────────
  // 记录层
  // ───────────────────────────────────────────────────────────

  /// 顺序扫描记录流，产出轻量索引（id / body 在流里的起点）。
  ///
  /// 只记录「带 substream 类型」的 BOF 的 body 起点用于定位，
  /// 不复制 body —— .xls 动辄几百 KB，复制会有明显的内存代价。
  List<_Rec> _readRecords() {
    final bd = ByteData.sublistView(_bytes);
    final out = <_Rec>[];
    var i = 0;
    // 上限防呆：每 4 字节至少一条记录，留 4 倍余量足够
    final maxRecords = _bytes.length ~/ 4 + 16;
    while (i + 4 <= _bytes.length && out.length < maxRecords) {
      final id = bd.getUint16(i, Endian.little);
      final len = bd.getUint16(i + 2, Endian.little);
      if (id == 0 && len == 0) break; // 流结束哨兵
      if (i + 4 + len > _bytes.length) break; // 截断文件，停在最后一条完整记录
      var subType = -1;
      if (id == _bof && len >= 4) {
        subType = bd.getUint16(i + 4 + 2, Endian.little);
      }
      out.add(_Rec(id: id, bodyStart: i + 4, len: len, substreamType: subType));
      i += 4 + len;
    }
    return out;
  }

  /// 定位每个 BOUNDSHEET 对应的工作表，并收集其单元格。
  Biff8Sheet? _readSheet(List<_Rec> records, _Rec bs, List<String> sst) {
    final name = _readShortString(_bytes, bs.bodyStart + 6);
    final offset = _uint32(bs.bodyStart);
    final grid = _collectCells(records, offset, sst);
    if (grid == null) return null;
    return Biff8Sheet(name: name.isEmpty ? 'Sheet' : name, rows: grid);
  }

  /// 从某个 substream 起点开始，扫到它的 EOF，收集单元格。
  ///
  /// 返回 null 表示该表没有任何单元格（真实文件里的空表，跳过）。
  List<List<String?>>? _collectCells(
      List<_Rec> records, int substreamStart, List<String> sst) {
    final bd = ByteData.sublistView(_bytes);
    // 稀疏存放：行号 → 列号 → 值
    final byRow = <int, Map<int, String?>>{};
    var started = false;

    for (var k = 0; k < records.length; k++) {
      final r = records[k];
      if (!started) {
        if (r.bodyStart - 4 != substreamStart) continue;
        started = true;
        continue;
      }
      if (r.id == _eof) break;

      switch (r.id) {
        case _labelSst:
          // r(2) c(2) xf(2) isst(4)
          final row = bd.getUint16(r.bodyStart, Endian.little);
          final col = bd.getUint16(r.bodyStart + 2, Endian.little);
          final isst = bd.getUint32(r.bodyStart + 6, Endian.little);
          _put(byRow, row, col,
              isst >= 0 && isst < sst.length ? sst[isst] : '');
        case _label:
          // BIFF8 的 LABEL 记录（少见，多为第三方工具生成）
          final row = bd.getUint16(r.bodyStart, Endian.little);
          final col = bd.getUint16(r.bodyStart + 2, Endian.little);
          _put(byRow, row, col, _readShortString(_bytes, r.bodyStart + 6));
        case _rk:
          // r(2) c(2) xf(2) rk(4)
          final row = bd.getUint16(r.bodyStart, Endian.little);
          final col = bd.getUint16(r.bodyStart + 2, Endian.little);
          final rk = bd.getUint32(r.bodyStart + 6, Endian.little);
          _put(byRow, row, col, _formatNumber(_decodeRk(rk)));
        case _mulRk:
          // r(2) c1(2) [xf(2) rk(4)]* c2(2)
          final row = bd.getUint16(r.bodyStart, Endian.little);
          final c1 = bd.getUint16(r.bodyStart + 2, Endian.little);
          final count = (r.len - 6) ~/ 6;
          for (var n = 0; n < count; n++) {
            final rk = bd.getUint32(r.bodyStart + 8 + n * 6 + 2, Endian.little);
            _put(byRow, row, c1 + n, _formatNumber(_decodeRk(rk)));
          }
        case _number:
          // r(2) c(2) xf(2) double(8)
          final row = bd.getUint16(r.bodyStart, Endian.little);
          final col = bd.getUint16(r.bodyStart + 2, Endian.little);
          final v = bd.getFloat64(r.bodyStart + 6, Endian.little);
          _put(byRow, row, col, _formatNumber(v));
        case _formula:
          // r(2) c(2) xf(2) result(8) ... —— 只取 Excel 已算好的缓存值
          final row = bd.getUint16(r.bodyStart, Endian.little);
          final col = bd.getUint16(r.bodyStart + 2, Endian.little);
          final v = _decodeFormulaResult(bd, r.bodyStart + 6);
          if (v != null) _put(byRow, row, col, v);
        case _boolErr:
          // r(2) c(2) xf(2) bBoolErr(1) fError(1)
          final row = bd.getUint16(r.bodyStart, Endian.little);
          final col = bd.getUint16(r.bodyStart + 2, Endian.little);
          final isErr = _bytes[r.bodyStart + 7];
          if (isErr == 0) {
            _put(byRow, row, col, _bytes[r.bodyStart + 6] == 0 ? 'FALSE' : 'TRUE');
          }
      }
    }

    if (byRow.isEmpty) return null;
    return _materialize(byRow);
  }

  /// 稀疏结构 → 规整的二维表（补 null、裁尾部空行）。
  List<List<String?>> _materialize(Map<int, Map<int, String?>> byRow) {
    final maxRow = byRow.keys.reduce((a, b) => a > b ? a : b);
    final maxCol = byRow.values
        .expand((m) => m.keys)
        .fold<int>(0, (a, b) => a > b ? a : b);
    final rows = <List<String?>>[];
    for (var r = 0; r <= maxRow; r++) {
      final src = byRow[r];
      final row = List<String?>.filled(maxCol + 1, null);
      if (src != null) src.forEach((c, v) => row[c] = v);
      rows.add(row);
    }
    // 裁掉尾部完全空白的行（Excel 常带格式残留的空行）
    while (rows.isNotEmpty && rows.last.every((c) => c == null || c.trim().isEmpty)) {
      rows.removeLast();
    }
    return rows;
  }

  static void _put(
      Map<int, Map<int, String?>> m, int row, int col, String? v) {
    if (v == null) return;
    (m[row] ??= <int, String?>{})[col] = v;
  }

  // ───────────────────────────────────────────────────────────
  // SST 共享字符串表
  // ───────────────────────────────────────────────────────────

  /// 读 SST（0x00FC）。SST 极易超过单条记录上限（8224 字节），
  /// 超出的部分拆到紧随的 CONTINUE（0x003C）记录里 —— 而且
  /// **续接点可能落在一个字符串中间或字符中间**，此时 CONTINUE
  /// 的开头会有 1 字节的编码标志重述剩余部分的编码。
  /// 因此必须用「跨片段游标」逐字符读，不能简单拼接字节。
  List<String> _readSst(List<_Rec> records) {
    final idx = records.indexWhere((r) => r.id == _sst);
    if (idx < 0) return const [];

    // 收集 SST body 及其后连续的 CONTINUE body
    final fragments = <Uint8List>[
      Uint8List.sublistView(_bytes, records[idx].bodyStart, records[idx].bodyStart + records[idx].len),
    ];
    for (var k = idx + 1; k < records.length && records[k].id == _continue; k++) {
      final r = records[k];
      fragments.add(Uint8List.sublistView(_bytes, r.bodyStart, r.bodyStart + r.len));
    }

    final bd0 = ByteData.sublistView(fragments.first);
    final unique = bd0.getUint32(4, Endian.little);
    final cur = _FragmentCursor(fragments, startOffset: 8); // 跳过 total(4)+unique(4)
    final out = <String>[];
    for (var n = 0; n < unique; n++) {
      out.add(_readUnicodeString(cur));
    }
    return out;
  }

  /// XLUnicodeRichExtendedString：
  ///   cch(2) + flags(1)
  ///   [+ cRun(2) if flags&0x08] [+ cbExtRst(4) if flags&0x04]
  ///   + 字符数据（flags&0x01 → UTF-16LE 双字节；否则 1 字节/字符）
  ///   + [rich runs] + [ext data]
  String _readUnicodeString(_FragmentCursor cur) {
    final cch = cur.u16();
    final flags = cur.u8();
    final rich = (flags & 0x08) != 0;
    final ext = (flags & 0x04) != 0;
    var wide = (flags & 0x01) != 0;

    var cRun = 0;
    if (rich) cRun = cur.u16();
    var cbExt = 0;
    if (ext) cbExt = cur.u32();

    final codeUnits = <int>[];
    var remaining = cch;
    while (remaining > 0) {
      if (cur.atFragmentBoundary) {
        // 跨 CONTINUE：头部一字节重述后续编码
        cur.jumpToNextFragment();
        final f = cur.u8();
        wide = (f & 0x01) != 0;
      }
      final avail = cur.available;
      if (avail <= 0) {
        cur.jumpToNextFragment();
        continue;
      }
      if (wide) {
        final take = avail ~/ 2 > remaining ? remaining : avail ~/ 2;
        if (take == 0) {
          cur.jumpToNextFragment();
          continue;
        }
        for (var i = 0; i < take; i++) {
          final lo = cur.u8();
          final hi = cur.u8();
          codeUnits.add(lo | (hi << 8));
        }
        remaining -= take;
      } else {
        final take = avail > remaining ? remaining : avail;
        for (var i = 0; i < take; i++) {
          codeUnits.add(cur.u8());
        }
        remaining -= take;
      }
    }
    // rich runs 每条 4 字节；ext 数据逐字节跳过
    for (var i = 0; i < cRun * 4; i++) {
      cur.u8();
    }
    for (var i = 0; i < cbExt; i++) {
      cur.u8();
    }
    return String.fromCharCodes(codeUnits);
  }

  // ───────────────────────────────────────────────────────────
  // 数值解码
  // ───────────────────────────────────────────────────────────

  /// RK 紧凑数字编码（4 字节存浮点/整数，省空间）：
  ///   bit0 = 1 → 值需 ÷100
  ///   bit1 = 1 → 30 位有符号整数（高 30 位，左移 2 的空位）
  ///   bit1 = 0 → 浮点：高 30 位是 IEEE754 double 的高 30 位，低 34 位补 0
  static double _decodeRk(int rk) {
    final div100 = (rk & 0x01) != 0;
    final isInt = (rk & 0x02) != 0;
    double v;
    if (isInt) {
      var n = rk >> 2;
      if ((n & 0x20000000) != 0) n -= 0x40000000; // 30 位符号扩展
      v = n.toDouble();
    } else {
      // 浮点模式：RK 的高 30 位就是 IEEE754 double 的**高 32 位**
      // （低 2 位被 RK 标志占用，故先清掉），低 32 位补 0。
      // 注意要写在小端序 buffer 的「高地址字」（偏移 4）上。
      final bd = ByteData(8);
      bd.setUint32(4, (rk & 0xFFFFFFFC) & 0xFFFFFFFF, Endian.little);
      bd.setUint32(0, 0, Endian.little);
      v = bd.getFloat64(0, Endian.little);
    }
    return div100 ? v / 100 : v;
  }

  /// FORMULA 的 8 字节结果：末两字节为 0xFFFF 表示非数字（字符串/布尔/错误）。
  String? _decodeFormulaResult(ByteData bd, int off) {
    final hi = bd.getUint16(off + 6, Endian.little);
    if (hi == 0xFFFF) {
      final kind = _bytes[off];
      if (kind == 1) return _bytes[off + 2] == 0 ? 'FALSE' : 'TRUE';
      if (kind == 2) return null; // 错误值 #DIV/0! 等 —— 当作空
      if (kind == 3) return null; // 空串
      return null; // 字符串结果需要额外的 STRING 记录，清单场景不用
    }
    return _formatNumber(bd.getFloat64(off, Endian.little));
  }

  /// 数字 → 字符串。整数不带小数点（清单里数量列是整数，
  /// 显示成 "20.0" 会让人以为支持小数）。
  static String _formatNumber(double v) {
    if (v.isNaN || v.isInfinite) return '';
    if (v == v.roundToDouble() && v.abs() < 1e15) {
      return v.toInt().toString();
    }
    return v.toString();
  }

  // ───────────────────────────────────────────────────────────
  // 小工具
  // ───────────────────────────────────────────────────────────

  int _uint32(int off) =>
      ByteData.sublistView(_bytes).getUint32(off, Endian.little);

  /// BOUNDSHEET 上的短字符串（sheet 名）：
  ///   cch(1) + flags(1) + 字符（flags&0x01 → UTF-16LE）
  String _readShortString(Uint8List b, int off) {
    if (off + 2 > b.length) return '';
    final cch = b[off];
    final flags = b[off + 1];
    final wide = (flags & 0x01) != 0;
    final start = off + 2;
    if (wide) {
      if (start + cch * 2 > b.length) return '';
      return String.fromCharCodes(
        List<int>.generate(cch, (i) => b[start + i * 2] | (b[start + i * 2 + 1] << 8)),
      );
    }
    if (start + cch > b.length) return '';
    return String.fromCharCodes(b.sublist(start, start + cch));
  }
}

/// 一个工作表（名字 + 规整二维数据）。
class Biff8Sheet {
  const Biff8Sheet({required this.name, required this.rows});

  final String name;
  final List<List<String?>> rows;
}

class _Rec {
  const _Rec({
    required this.id,
    required this.bodyStart,
    required this.len,
    required this.substreamType,
  });

  final int id;
  final int bodyStart;
  final int len;

  /// 仅 BOF 记录有意义：0x0005 全局 / 0x0010 工作表；其余为 -1。
  final int substreamType;
}

/// 跨 SST / CONTINUE 片段的逐字节游标。
///
/// 「atFragmentBoundary」在读到当前片段末尾时为 true —— SST 解析据此
/// 判断是否要按 BIFF 规则读取续接处的编码标志字节。
class _FragmentCursor {
  _FragmentCursor(this._fragments, {int startOffset = 0})
      : _fi = 0,
        _p = startOffset;

  final List<Uint8List> _fragments;
  int _fi;
  int _p;

  int get available => _fragments[_fi].length - _p;

  bool get atFragmentBoundary => available <= 0;

  void jumpToNextFragment() {
    if (_fi + 1 < _fragments.length) {
      _fi++;
      _p = 0;
    }
  }

  int u8() {
    while (available <= 0) {
      if (_fi + 1 >= _fragments.length) return 0;
      jumpToNextFragment();
    }
    return _fragments[_fi][_p++];
  }

  int u16() {
    // 记录头/长度字段不会跨 CONTINUE 断开（BIFF 规则保证）
    while (available < 2) {
      if (_fi + 1 >= _fragments.length) return 0;
      jumpToNextFragment();
    }
    final v = _fragments[_fi][_p] | (_fragments[_fi][_p + 1] << 8);
    _p += 2;
    return v;
  }

  int u32() {
    while (available < 4) {
      if (_fi + 1 >= _fragments.length) return 0;
      jumpToNextFragment();
    }
    final f = _fragments[_fi];
    final v = f[_p] | (f[_p + 1] << 8) | (f[_p + 2] << 16) | (f[_p + 3] << 24);
    _p += 4;
    return v;
  }
}
