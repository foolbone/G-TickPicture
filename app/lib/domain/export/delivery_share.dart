import 'export_service.dart';

/// 分享动作的类型：把一串文件路径交给系统（≈ share_plus 的 shareXFiles）。
///
/// 抽成函数参数是为了**能测**：这条调用策略的正确性全落在
/// "一次传几个文件" 上（见 [DeliverySharer.shareVolume]），
/// 而 share_plus 在被测进程里是个静态 MethodChannel，没法就地把 behavior
/// 弄清楚 —— 换成注入的函数，断言就落在数据上而不是平台.mockito 上。
typedef ShareFiles = Future<void> Function(
  List<String> paths, {
  required String subject,
  required String text,
});

/// 交付包的分享策略（2026-10-01）。
///
/// ═══════════════════════════════════════════════════════════════
/// 这个文件存在的唯一原因：**微信不出现在多文件分享面板里**。
/// ═══════════════════════════════════════════════════════════════
/// share_plus 的 Android 实现按文件个数分流：
///   1 个  → `Intent.ACTION_SEND`
///   ≥2 个 → `Intent.ACTION_SEND_MULTIPLE`
/// （源码：share_plus-10.1.4 `Share.kt` → `shareFiles`）
/// 而微信只注册了 ACTION_SEND，于是"一次分享 N 卷"的面板里没有微信，
/// 现场就表现为「分卷后没法发给客户」。
///
/// 结论不是"别分卷"，而是：**分了卷就一卷一卷发**。本类把这层判断收口，
/// UI 只管调哪个方法，不用记得这条平台差异。
class DeliverySharer {
  const DeliverySharer(this._share);

  final ShareFiles _share;

  static const _subject = '预检照片交付包';

  /// 逐卷发送 —— **每次只传一个文件**，保证走 ACTION_SEND、微信在面板里。
  Future<void> shareVolume(DeliveryResult result, DeliveryVolume volume) {
    return _share(
      [volume.path],
      subject: _subject,
      text: _summary(result, suffix: result.isSplit ? '（${volume.fileName}）' : null),
    );
  }

  /// 一次发送全部卷 —— 走 ACTION_SEND_MULTIPLE，**不含微信**。
  ///
  /// 适合网盘 / 邮件 / 蓝牙这类能一次收多个文件的目标；卷数多时（十几卷）
  /// 逐个点确实烦，所以留着这条。
  Future<void> shareAll(DeliveryResult result) {
    // volumes 为空 = v0.11 及以前的单 zip 记录，那时 result 里只有 zipPath。
    final paths = result.volumes.isEmpty
        ? <String>[result.zipPath]
        : <String>[for (final v in result.volumes) v.path];
    return _share(
      paths,
      subject: _subject,
      text: _summary(result,
          suffix: result.isSplit ? '（分 ${result.volumes.length} 卷）' : null),
    );
  }

  String _summary(DeliveryResult r, {String? suffix}) =>
      '预检照片交付包：${r.itemCount} 件货品 / ${r.photoCount} 张照片'
      '${suffix ?? ''}';
}
