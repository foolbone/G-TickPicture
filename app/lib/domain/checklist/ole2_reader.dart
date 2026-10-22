import 'dart:typed_data';

/// OLE2 复合文档（CFB）最小只读解析器 —— 只为取出 `Workbook` 流。
///
/// 为什么自研而不是用包：
///   Dart 生态没有能在本工程的 SDK 约束下读取 97-2003 .xls 的库
///   （excel 包不读 xls；excel_plus / excel2003 都要求 Dart >= 3.11 / 3.7.2，
///   本机 Flutter 3.29 带的是 Dart 3.7.0）。为读一个老格式表格而升级整个
///   Flutter SDK，代价与收益倒挂 —— 所以只实现我们真正需要的那一小部分。
///
/// 覆盖范围（只读、够用为止）：
///   · 头部 → 扇区大小 / 目录起点
///   · DIFAT → FAT（含 >109 个 FAT 扇区的扩展 DIFAT 链）
///   · FAT 链 → 目录流、Workbook 流的扇区串联
///   · 目录项 → 查找名为 "Workbook" 或 "Book" 的流
///
/// 刻意不实现：MiniFAT / MiniStream。原因：Workbook 流在真实 .xls 里
/// 必然大于 4096 字节（仅 SST 就可能上千字节），因此永远走普通 FAT。
/// 若遇到小流则返回 null，由上层给出"文件不完整"的提示。
class Ole2Reader {
  Ole2Reader._(this._bytes);

  final Uint8List _bytes;

  static const int _endOfChain = 0xFFFFFFFE;
  static const int _freeSector = 0xFFFFFFFF;

  /// 解析并返回指定名字的流内容；找不到返回 null。
  static Uint8List? extractStream(Uint8List bytes, String name) {
    try {
      return Ole2Reader._(bytes)._extract(name);
    } catch (_) {
      // 结构异常一律视为"读不出"，交给上层兜底提示
      return null;
    }
  }

  /// 文件是否为 OLE2 复合文档（97-2003 二进制格式的判据）。
  static bool looksLikeOle2(Uint8List bytes) {
    if (bytes.length < 8) return false;
    return bytes[0] == 0xD0 &&
        bytes[1] == 0xCF &&
        bytes[2] == 0x11 &&
        bytes[3] == 0xE0 &&
        bytes[4] == 0xA1 &&
        bytes[5] == 0xB1 &&
        bytes[6] == 0x1A &&
        bytes[7] == 0xE1;
  }

  Uint8List? _extract(String name) {
    final u16 = ByteData.sublistView(_bytes);

    final sectorShift = u16.getUint16(30, Endian.little);
    if (sectorShift < 7 || sectorShift > 20) return Uint8List(0);
    final sectorSize = 1 << sectorShift;

    final dirStart = u16.getUint32(48, Endian.little);
    final miniCutoff = u16.getUint32(56, Endian.little);
    final difatStart = u16.getUint32(68, Endian.little);
    final numDifat = u16.getUint32(72, Endian.little);

    final fat = _readFat(u16, sectorSize, difatStart, numDifat);

    // 目录流 → 目录项
    final dirBytes = _readChain(fat, sectorSize, dirStart);
    final entry = _findStreamEntry(dirBytes, name, sectorSize);
    if (entry == null) return null;

    // Workbook 流一定走普通 FAT（见类注释）
    if (entry.size < miniCutoff) return null;
    final stream = _readChain(fat, sectorSize, entry.start);
    if (stream.length < entry.size) return stream;
    return Uint8List.sublistView(stream, 0, entry.size);
  }

  /// 读 FAT：头部自带 109 个表项，再多则沿"扩展 DIFAT 链"继续收集。
  List<int> _readFat(ByteData u16, int sectorSize, int difatStart, int numDifat) {
    final fatSectors = <int>[];

    // 头部偏移 76 起是 109 个 FAT 扇区号
    for (var i = 0; i < 109; i++) {
      final v = u16.getUint32(76 + i * 4, Endian.little);
      if (v == _freeSector) break;
      fatSectors.add(v);
    }

    // 扩展 DIFAT 链：每个扇区末尾 4 字节指向下一个 DIFAT 扇区
    var next = difatStart;
    var guard = 0;
    while (next != _endOfChain && next != _freeSector && guard < numDifat + 8) {
      final off = _offsetOf(next, sectorSize);
      if (off + sectorSize > _bytes.length) break;
      final perSector = sectorSize ~/ 4 - 1;
      for (var i = 0; i < perSector; i++) {
        final v = u16.getUint32(off + i * 4, Endian.little);
        if (v == _freeSector) continue;
        fatSectors.add(v);
      }
      next = u16.getUint32(off + perSector * 4, Endian.little);
      guard++;
    }

    final fat = <int>[];
    for (final s in fatSectors) {
      final off = _offsetOf(s, sectorSize);
      if (off + sectorSize > _bytes.length) break;
      for (var i = 0; i < sectorSize ~/ 4; i++) {
        fat.add(u16.getUint32(off + i * 4, Endian.little));
      }
    }
    return fat;
  }

  /// 沿 FAT 链把所有扇区拼成一个连续 buffer。
  Uint8List _readChain(List<int> fat, int sectorSize, int start) {
    final out = BytesBuilder(copy: false);
    var s = start;
    var guard = 0;
    final maxSectors = _bytes.length ~/ sectorSize + 2;
    while (s != _endOfChain && s != _freeSector && guard < maxSectors) {
      final off = _offsetOf(s, sectorSize);
      if (off + sectorSize > _bytes.length) break;
      out.add(Uint8List.sublistView(_bytes, off, off + sectorSize));
      if (s >= fat.length) break;
      s = fat[s];
      guard++;
    }
    return out.toBytes();
  }

  /// 在目录流里找名字匹配的流（type=2）；找不到时返回 null。
  _DirEntry? _findStreamEntry(Uint8List dir, String name, int sectorSize) {
    // 目录项固定 128 字节
    for (var off = 0; off + 128 <= dir.length; off += 128) {
      final nameLen = dir[off + 64] | (dir[off + 65] << 8);
      if (nameLen < 2 || nameLen > 64) continue;
      final type = dir[off + 66];
      if (type != 2) continue; // 2 = stream

      // 名字是 UTF-16LE，去掉结尾 NUL
      final raw = dir.sublist(off, off + nameLen - 2);
      final entryName = String.fromCharCodes(
        List<int>.generate(raw.length ~/ 2, (i) => raw[i * 2] | (raw[i * 2 + 1] << 8)),
      );
      if (entryName != name) continue;

      final bd = ByteData.sublistView(dir);
      return _DirEntry(
        start: bd.getUint32(off + 116, Endian.little),
        size: bd.getUint32(off + 120, Endian.little),
      );
    }
    return null;
  }

  int _offsetOf(int sector, int sectorSize) => (sector + 1) * sectorSize;
}

class _DirEntry {
  const _DirEntry({required this.start, required this.size});

  final int start;
  final int size;
}
