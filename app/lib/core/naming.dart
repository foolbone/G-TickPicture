import 'constants.dart';

/// 文件名安全化：把不可用于文件名的字符替换为 `_`。
///
/// 设计方案 §5.1 的硬性要求：
/// **数据库保留原始编码（code），文件名用安全版本（codeSafe）**，两者都要留。
String safeFileName(String raw) {
  var s = raw.trim();
  for (final c in AppConst.unsafeFilenameChars) {
    s = s.replaceAll(c, '_');
  }
  // Windows 文件名不允许以点或空格结尾
  s = s.replaceAll(RegExp(r'[ .]+$'), '');
  return s.isEmpty ? '_' : s;
}

/// 品名简称：截断到 [AppConst.dirNameShortMax] 字，并做安全化。
String shortName(String raw, {int max = AppConst.dirNameShortMax}) {
  final t = raw.trim().replaceAll(RegExp(r'\s+'), '');
  final cut = t.length <= max ? t : t.substring(0, max);
  return safeFileName(cut);
}

/// 交付目录名：`{3位序号}_{编码}_{品名简称}`
String deliveryDirName({required int seq, required String codeSafe, required String name}) {
  final n = seq.toString().padLeft(3, '0');
  final s = shortName(name);
  return s.isEmpty ? '${n}_$codeSafe' : '${n}_${codeSafe}_$s';
}

/// 交付文件名：`{编码}_{2位序号}.jpg`
String deliveryFileName({required String codeSafe, required int index}) =>
    '${codeSafe}_${index.toString().padLeft(2, '0')}.jpg';

// ─────────────────────────────────────────────────────────────
// 平铺交付命名（M5 · 老板 2026-09-23 拍板的交付结构）
//
// 交付结构是「照片按身份命名」，而不是设计方案 §5.5 原定的
// 「按货品分目录」。
//
// 硬约束：**文件名必须自带全部身份信息**。
// 一旦退化成 `001.jpg`，报告员就无法从文件名看出它属于哪件货，
// 包内就再也没有任何线索 —— 那是单点，不该赌。
//
// 因此平铺名同时编码了「货品序号」与「该货品的第几张」：
//   {3位货品序号}_{编码}_{2位张序}.jpg
// 例：007_103010013345AMX_02.jpg
//
// 为什么还要 3 位货品序号：编码本身在清单里可能重复（同一型号多件），
// 光靠编码无法唯一标识"第几件货"。
// ─────────────────────────────────────────────────────────────

/// 平铺交付文件名：`{3位货品序号}_{编码}_{2位张序}.jpg`
///
/// [itemSeq]    货品在清单中的序号（1 起）
/// [codeSafe]   安全化后的货品编码
/// [index]      该货品的第几张照片（1 起）
String flatDeliveryName({
  required int itemSeq,
  required String codeSafe,
  required int index,
}) =>
    '${itemSeq.toString().padLeft(3, '0')}_$codeSafe'
    '_${index.toString().padLeft(2, '0')}.jpg';

// ─────────────────────────────────────────────────────────────
// 箱号目录（M5.1 · 老板 2026-09-26 拍板：打包时按箱号分文件夹）
// ─────────────────────────────────────────────────────────────

/// 从箱号汇总里取**主箱**（第一个箱号）。
///
/// containerSummary 语义（P4 诉求 1）：同一件货分散多箱时是
/// 「箱A、箱B」顿号连接的文本。交付目录只取主箱 —— 照片在包内
/// 只出现一次（绝不复制多份占体积），完整箱号信息由 manifest 留全。
/// null / 空 = 清单没提供箱号。
String? primaryCartonOf(String? containerSummary) {
  final s = (containerSummary ?? '').trim();
  if (s.isEmpty) return null;
  final first = s.split('、').first.trim();
  return first.isEmpty ? null : first;
}

/// 箱号 → 交付包内的目录名。无箱号 → `_未分箱/`
/// （与 `_未使用/` 同款下划线约定：特殊目录排最前、一眼可辨）。
///
/// 目录名走 [shortName]：清掉文件系统非法字符（Windows 解压方
/// 多半是它）、截 40 字。空箱号汇总（如「、、」）按无箱号处理。
///
/// ⚠️ 2026-09-27 起它只服务于**清单信息**的展示，不再决定交付目录。
/// 交付目录看 [userCartonDir]。
String cartonDirName(String? containerSummary) {
  final c = primaryCartonOf(containerSummary);
  if (c == null) return '_未分箱';
  return shortName(c, max: 40);
}

// ─────────────────────────────────────────────────────────────
// 用户指定箱号（M6 · 老板 2026-09-27 拍板）
//
// 「分组时，由用户输入或指定箱号，不依赖货品清单」——
// 交付分文件夹的依据从清单的 containerSummary 换成**整理时人手输的那个**。
//
// 与 [cartonDirName] 的分工：
//   cartonDirName(清单写的汇总) → 需要按顿号拆主箱，且多数清单根本没有
//   userCartonDir(人输入的箱号) → 本身就是一个箱号，不需要拆
// ─────────────────────────────────────────────────────────────

/// 用户指定箱号 → 目录名。null / 空 = 没指定。
///
/// 返回 null（而不是 `_未分箱`）是刻意的：让调用方自己决定
/// 「一个箱号都没有 → 保持平铺」还是「放进 _未分箱」——
/// 这两个决策依赖"整份交付里有没有别的箱号"，构建器才知道。
String? userCartonDir(String? carton) {
  final c = (carton ?? '').trim();
  if (c.isEmpty) return null;
  return shortName(c, max: 40);
}

/// 交付包内「预检」部分的根目录名。
const String deliveryPrecheckDir = '预检';

/// 交付包内「监装」部分的根目录名。
///
/// 监装照片与货品清单无关，全部平铺在这里、用原始文件名
/// （老板 2026-09-27 拍板：「放一个文件夹即可」）。
const String deliverySupervisionDir = '监装';
