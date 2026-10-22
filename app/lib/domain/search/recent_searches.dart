import 'package:shared_preferences/shared_preferences.dart';

/// 最近搜过的编码（本地最多 10 条）。
///
/// 为什么要有这个：现场一天里会反复查同一批编码（"上午那批 XX 拍了没"、
/// "下午补拍时再看一眼"）。重新敲一遍长编码是纯浪费，而编码又不是
/// 能从列表里一眼挑出来的东西 —— 所以存最近 10 条，点一下就搜。
///
/// 只存**人的原始输入**（`ABC-123` 而不是规范化后的串）：最近记录是
/// 给人认的，不是给机器比的，显示成 `ABC123` 反而和唛头对不上。
class RecentSearches {
  /// 构造；[prefs] 仅供测试注入。
  RecentSearches({SharedPreferences? prefs}) : _prefsOverride = prefs;

  final SharedPreferences? _prefsOverride;
  SharedPreferences? _cache;

  Future<SharedPreferences> get _prefs async =>
      _cache ??= _prefsOverride ?? await SharedPreferences.getInstance();

  /// 存储键。
  static const String _kKey = 'search.recent_codes';

  /// 最多保留多少条。
  static const int maxEntries = 10;

  /// 读最近搜索（新的在前）。
  ///
  /// ⚠️ 返回值**必须可修改**：`push` 要在上面 removeWhere/insert。
  ///    曾经空历史时返回 `const []`（不可变）→ 现场第一次搜索就抛
  ///    UnsupportedError，最近搜索功能其实一次都没存成功过
  ///    （2026-10-15 v0.24.2 由 widget 测试抓出）。
  Future<List<String>> load() async {
    final v = (await _prefs).getStringList(_kKey);
    if (v == null || v.isEmpty) return <String>[];
    return v.where((e) => e.trim().isNotEmpty).toList();
  }

  /// 记一条（已存在则提到最前，超过上限丢最旧的）。
  Future<void> push(String code) async {
    final raw = code.trim();
    if (raw.isEmpty) return;
    final list = await load();
    list.removeWhere((e) => e == raw);
    list.insert(0, raw);
    final trimmed = list.length <= maxEntries
        ? list
        : list.sublist(0, maxEntries);
    await (await _prefs).setStringList(_kKey, trimmed);
  }

  /// 清空历史。
  Future<void> clear() async {
    await (await _prefs).remove(_kKey);
  }
}
