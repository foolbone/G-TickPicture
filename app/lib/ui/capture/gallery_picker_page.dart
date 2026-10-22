import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../app/providers.dart';
import '../../app/theme.dart';
import '../../core/async_limiter.dart';
import '../../core/device_tier.dart';
import '../../domain/capture/native_gallery_service.dart';
import '../../domain/model/native_gallery_photo.dart';
import '../widgets/zoomable_image.dart';
import 'import_actions.dart';

/// 「从相册选择照片」页面（2026-09-29 重写，替代 file_picker 系统对话框）。
///
/// 现场取证挑图的高频动作：挑一批、快速连选、按时间跳、上次看到哪接着看。
/// 系统选择器一个都做不了，这里用「原生 MediaStore 直读 + 自建网格」补上。
///
/// 关键交互：
///   · 点选 = 切换选中（格子右上角勾选）。
///   · 长按 = 打开大图预览（确认这张是不是要的，避免误选）。
///   · 「连选」开关 = 进入连选模式：点第一张设起点，再点一张即把两者之间的
///     整段一次性选中（含端点）；再次点起点取消。
///   · 底部时间轴 = 拖动定位到某天，或从相册里「按时间」直接跳。
///   · 记忆位置：退出时记下顶部照片的 MediaStore id（时间兜底），下次进
///     来按 id 精确滚回去，成功/失败都有 SnackBar 反馈。
///   · 顶部「只看某相册」= 按 bucket 过滤。
///
/// ⚠️ 架构纪律：本页只 import `domain/model/` 与 `domain/capture/` 的服务，
/// 绝不 import `data/`（规则 2）；它拿不到 itemId，无从写归属。
class GalleryPickerPage extends ConsumerStatefulWidget {
  const GalleryPickerPage({super.key, required this.projectId});

  /// 仅用于上下文/日志，选图本身不依赖项目。
  final String projectId;

  @override
  ConsumerState<GalleryPickerPage> createState() => _GalleryPickerPageState();
}

class _GalleryPickerPageState extends ConsumerState<GalleryPickerPage> {
  final List<NativeGalleryPhoto> _photos = [];
  final Set<int> _selected = {};
  int? _anchorId;
  var _rangeMode = false;
  var _loading = false;
  var _loadingMore = false;
  var _hasMore = true;
  var _crossAxisCount = 3;
  String? _bucket;
  List<NativeGalleryBucket> _buckets = const [];

  // ── 日期过滤（2026-10-12 v0.20.0）────────────────────────
  // 非空 = 只看这一天（真过滤，不是旧版的滚动定位）。旧版语义是
  // 「定位到那天的位置」，目标日期没照片时画面纹丝不动且无提示 ——
  // 老板真机反馈「永远只能看到 9月24」的直接根因。
  DateTime? _day;

  /// 有照片的日期清单（原生归日，本地时区）。空 = 原生查询失败 →
  /// 选择器谓词关闭（全部可选）。
  List<DateTime> _days = const [];
  final _scroll = ScrollController();

  /// 每页张数**按设备档次**（2026-09-29 性能排查）：低配机一次少建几十个
  /// 格子，首屏更快、内存更稳；高配机维持 120 减少翻页次数。
  int get _pageSize => DeviceTier.current.galleryPageSize;
  static const _restorePageCap = 30;

  /// 读取原图的进度（选很多张时那是最慢的一步，必须看得见）。
  var _reading = false;
  var _readDone = 0;
  var _readTotal = 0;

  /// 时间轴 min/max 缓存 —— 见 [_syncScrubberRange]。
  var _minMs = 0;
  var _maxMs = 0;

  /// 时间轴当前值的**局部广播**（2026-09-29 性能排查）。
  ///
  /// 原来滚动时先 `setState` 改 `_scrubberMs` 再重建 —— 那会把整个
  /// Scaffold 连同 GridView 一起重建，滚动中每跨一行就来一次，是这页
  /// 掉帧的主因之一。改成只让它驱动底部时间轴那一小块 rebuild，
  /// 网格本身完全不动。
  final ValueNotifier<int> _scrubberTick = ValueNotifier<int>(0);

  // 位置记忆（09-29 第二版）：保存「顶部可见照片的 MediaStore id」为主键，
  // 拍摄时间做兜底（照片可能被删 / 列表变化，id 找不到时按时间近似）。
  // 旧版只存时间戳，日期检索 + 行高换算任何一环有偏差就「看起来没恢复」，
  // 且全程无反馈 —— 用户无法区分「没存上」和「没恢复」。这一版恢复后
  // SnackBar 明说结果。
  int? _pendingRestoreId;
  int? _pendingRestoreMs;
  // 首次 _init 才做位置恢复；切相册 / 重试不再触发（恢复到别的相册会错位）。
  var _restoreArmed = false;
  // 滚动过程中实时记下的「顶部那张」—— 退出时 ScrollController 常常已经
  // detach，offset 读不到了，靠它兜底（详见 [_captureTop]）。
  int? _topId;
  int? _topMs;
  var _scrubberMs = 0;
  final _fmtDay = DateFormat('yyyy/MM/dd');

  // 行高估算缓存：didChangeDependencies 时算好，dispose 里也能安全用
  // （MediaQuery.of 在 unmount 后访问会抛异常 —— 09-29 位置记忆失效的根因之一）。
  double _rowH = 140;

  // 2026-09-29 空态排查：失败原因必须说清楚，不能把「权限被拒」「查询
  // 报错」「真没照片」三种情况渲染成同一句废话。
  var _noPermission = false;
  var _partialAccess = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    _init();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _rowH = _calcRowHeight();
  }

  @override
  void dispose() {
    _scrubberTick.dispose();
    _scroll.removeListener(_onScroll);
    // resample=false：此刻 controller 常常已经 detach，再按 offset 反算
    // 只会得到 0，把滚动时记下的真实位置覆盖成「第一张」。
    _savePosition(resample: false);
    _scroll.dispose();
    super.dispose();
  }

  // ─────────────────────────────────────────────────────────
  // 数据加载
  // ─────────────────────────────────────────────────────────

  Future<void> _init() async {
    setState(() {
      _loading = true;
      _error = null;
      _noPermission = false;
    });
    try {
      final prefs = await SharedPreferences.getInstance();
      // 只在首次进入时装填恢复目标；切相册 / 失败重试不再恢复
      // （那是另一个列表，恢复旧位置只会错位）。
      if (!_restoreArmed) {
        _pendingRestoreId = prefs.getInt('gallery.last_viewed_id');
        _pendingRestoreMs = prefs.getInt('gallery.last_viewed_ms');
        // ⚠️ 上次相册也只在这里装一次 —— 原来每次 _init 都重载，
        // 顶部「只看某相册」点了会被旧值盖回去，等于切不动相册。
        final b = prefs.getString('gallery.last_bucket') ?? '';
        _bucket = b.isEmpty ? null : b;
        _restoreArmed = true;
      }

      final svc = ref.read(nativeGalleryServiceProvider);

      // 先问授权再查询 —— 部分授权（Android 14「仅选中的照片」）下查询
      // 不报错但只回用户勾选过的行，不提示用户会以为相册真空了。
      final st = await svc.galleryStatus();
      if (!st.granted) {
        if (mounted) setState(() => _noPermission = true);
        return;
      }
      _partialAccess = st.partial;

      _buckets = await svc.queryBuckets();
      // 日期清单（2026-10-12 v0.20.0；2026-10-13 v0.21.2 修正口径）：
      // 日期选择器置灰无照片的日子。失败静默返回空 → 谓词关闭
      // （全部可选，选了没图就空态）。
      // ⚠️ **必须带上当前相册**：v0.21.1 的清单按「全部相册」算、照片列表
      // 按「当前相册」查 —— 两个数据集不一致，于是日历说某天有照片、
      // 选进去却是空态（老板真机「实际有照片却提示没有」的真实根因）。
      // 相册是会被记住的（gallery.last_bucket），换台手机表现就不同。
      final days = await svc.queryDays(bucket: _bucket);
      _days = days;
      // 换列表（切相册 / 重试）时旧位置已无意义 —— 不清掉的话退出时
      // 会把上一张照片的 id 存进新相册的记录里，下次进来按 id 找不到。
      _photos.clear();
      _topId = null;
      _topMs = null;
      final first = await svc.queryImages(
          limit: _pageSize, bucket: _bucket, day: _day);
      _photos.addAll(first);
      _hasMore = first.length == _pageSize;
      _syncScrubberRange();
      // 一次都没滚过就退出时也得有位置可存 —— 默认列表最前面那张。
      if (_topId == null && _photos.isNotEmpty) _rememberIndex(0);
    } catch (e) {
      // 原生查询异常（ROM 差异 / 列缺失）必须原样露出 —— 否则又变成
      // 「没有可选择的照片」这种把 BUG 化妆成正常态的空提示。
      _error = e.toString();
    } finally {
      if (mounted) setState(() => _loading = false);
    }
    if (mounted && (_pendingRestoreId != null || _pendingRestoreMs != null)) {
      await _restore();
    }
  }

  /// 空态页上的「去授权」：重走运行时申请，成功则重载。
  Future<void> _requestAndReload() async {
    final ok = await requestGalleryPermission(ref);
    if (!mounted) return;
    if (!ok) {
      _announce('仍未授权 —— 请点「去系统设置」手动打开照片权限');
      return;
    }
    await _init();
  }

  Future<bool> _loadMorePage() async {
    if (_loadingMore || !_hasMore) return false;
    _loadingMore = true;
    try {
      final svc = ref.read(nativeGalleryServiceProvider);
      final more = await svc.queryImages(
          limit: _pageSize,
          offset: _photos.length,
          bucket: _bucket,
          day: _day);
      _photos.addAll(more);
      _hasMore = more.length == _pageSize;
      _syncScrubberRange();
      return more.isNotEmpty;
    } finally {
      _loadingMore = false;
    }
  }

  /// 记忆位置（09-29 第二版）：三阶段定位。
  ///
  /// ① 当前已加载列表里找上次那**张照片的 id** —— 精确，不受新拍照片插入、
  ///    行高换算偏差影响。
  /// ② 找不到就继续翻页找 id（照片在很靠后的位置时）。
  /// ③ 仍找不到（照片被删 / 换了相册过滤）→ 退化为按拍摄时间近似。
  ///
  /// 时机是关键（09-29「没实现」的根因之一）：GridView 在 `_loading` 结束的
  /// 下一帧才进树，ScrollController attach 之前 `jumpTo` 是 no-op
  /// （release）/ 抛异常（debug）—— 先等帧且确认 hasClients，每加载一页再等一帧。
  ///
  /// ⚠️ 第三击教训（真机「提示成功但位置不对」）：**数据加载 ≠ UI 认账**。
  /// 翻页只改 `_photos`，GridView 的 itemCount / maxScrollExtent 必须
  /// setState 重建才增长；否则目标 offset 超出可滚范围，jumpTo 被 clamp
  /// 截断在半路 —— SnackBar 弹「已回到上次浏览位置」，人却停在几十行之前。
  /// 所以：每翻一页 setState；跳转交给 [_scrollToTarget] 逐段逼近并核对落点。
  Future<void> _restore() async {
    final targetId = _pendingRestoreId;
    final ms = _pendingRestoreMs;
    _pendingRestoreId = null;
    _pendingRestoreMs = null;
    if (targetId == null && ms == null) return;

    await _waitFrame();
    // 双保险：个别机型帧回调时序不同，controller 还没 attach 就再等几帧。
    for (var i = 0; i < 5 && !_scroll.hasClients; i++) {
      await _waitFrame();
    }

    // ①② 按 id 精确查找：先看已加载的，没有就翻页找。
    var idx =
        targetId == null ? -1 : _photos.indexWhere((p) => p.id == targetId);
    var pages = 0;
    while (idx < 0 && targetId != null && _hasMore && pages < _restorePageCap) {
      final got = await _loadMorePage();
      if (!got) break;
      pages++;
      // ⚠️ 必须 setState：_loadMorePage 只改 _photos 数据，GridView 的
      // itemCount / maxScrollExtent 要重建才认账 —— 否则下面 jumpTo
      // 被 clamp 到首帧规模的可滚范围，停在半路却提示成功（真机 BUG）。
      if (mounted) setState(() {});
      await _waitFrame(); // 新页渲染、maxScrollExtent 更新后再滚
      idx = _photos.indexWhere((p) => p.id == targetId);
    }

    // ③ id 失效（被删 / 被相册过滤挡住）→ 按时间近似：翻到出现
    //    「不晚于上次位置」的照片为止。
    if (idx < 0 && ms != null) {
      while (pages < _restorePageCap) {
        final reached = _photos.any((p) =>
            p.dateTaken != null && p.dateTaken!.millisecondsSinceEpoch <= ms);
        if (reached || !_hasMore) break;
        final got = await _loadMorePage();
        if (!got) break;
        pages++;
        if (mounted) setState(() {});
        await _waitFrame();
      }
      // fallbackToEnd:false —— 目标太深没加载到时返回 -1 走诚实提示，
      // 绝不能像时间轴定位那样兜底到最旧（那是假成功）。
      idx = _indexOfDateNotLaterThan(ms, fallbackToEnd: false);
    }

    if (!mounted) return;
    if (idx < 0) {
      // 有记录但一张都对不上：不假装恢复成功。
      _announce('上次浏览的照片已不在，从最新开始');
      return;
    }
    // 目标行 = idx 所在行的行首。落在最后几屏时物理上无法让行顶对齐视口
    // 顶（滚到底也够不着）—— 那时 [_scrollToTarget] 会停在能到的最深处，
    // 提示「附近」而不是假装精准。
    final target = idx ~/ _crossAxisCount * _rowH;
    final arrived = await _scrollToTarget(target);
    if (!mounted) return;
    _updateScrubber();
    setState(() {});
    _announce(arrived ? '已回到上次浏览位置' : '已回到上次浏览位置附近');
  }

  /// 等当前（或下一个）帧渲染完 —— 保证 GridView 已布局、controller 已 attach。
  Future<void> _waitFrame() => WidgetsBinding.instance.endOfFrame;

  /// 把网格滚到 [target] 像素位置，返回是否真的落到了那儿。
  ///
  /// ⚠️ 不能 `jumpTo(target)` 一次了事（2026-09-29 位置记忆失效的最后一环）：
  /// GridView 是**懒构建**的 Sliver —— `maxScrollExtent` 不等于全部数据的
  /// 高度，没构建到的行还没进估算。实测 240 张（80 行）时 max 只有 10332px，
  /// 真实内容 20552px：`if (target <= max)` 那一判看着合理，可 jumpTo 一旦
  /// 越过真实可滚范围就被静默 clamp，停在半路还提示「已回到上次浏览位置」。
  ///
  /// 所以改成「逼近」：跳一次 → 等一帧让新一屏 child 构建出来（可滚范围
  /// 随之变长）→ 没到就补一页数据再跳，直到落点命中或到底。
  Future<bool> _scrollToTarget(double target) async {
    for (var i = 0; i < 40 && mounted; i++) {
      if (!_scroll.hasClients) {
        await _waitFrame();
        continue;
      }
      _scroll.jumpTo(target); // 超出可滚范围时会被 clamp —— 这正是逼近的一步
      await _waitFrame();
      if (!mounted || !_scroll.hasClients) break;
      if ((_scroll.offset - target).abs() < 1.0) return true;
      if (!_hasMore) break; // 到底了仍够不着：能到的最深就是这个位置
      await _loadMorePage();
      if (mounted) setState(() {});
    }
    return mounted && _scroll.hasClients && (_scroll.offset - target).abs() < 1.0;
  }

  void _onScroll() {
    if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 600) {
      if (_hasMore && !_loadingMore) {
        _loadMorePage().then((_) {
          if (mounted) setState(() {});
        });
      }
    }
    _updateScrubber();
  }

  // ─────────────────────────────────────────────────────────
  // 滚动 / 时间定位
  // ─────────────────────────────────────────────────────────

  /// 行高估算（didChangeDependencies / 列数切换时刷新到 [_rowH]）。
  ///
  /// ⚠️ 公式必须与 GridView 一致：childAspectRatio:1 → 行高 = 格宽 +
  /// 纵向间距（mainAxisSpacing=2）。旧版多加了 20px「日期条」—— 日期条
  /// 是 overlay 不占布局高度，多加的量随行数放大，定位越往后越偏。
  double _calcRowHeight() {
    final w = MediaQuery.of(context).size.width;
    const pad = 8.0; // GridView.padding 左右各 8（两边合计 16）
    const gap = 2.0; // mainAxisSpacing
    final tileW = (w - pad * 2 - gap * (_crossAxisCount - 1)) / _crossAxisCount;
    return tileW + gap; // childAspectRatio=1 → 格高等于格宽
  }

  /// 找第一张「拍摄时间不晚于 [ms]」的照片下标。
  ///
  /// [fallbackToEnd]：列表里没有任何「不晚于 [ms]」的照片（目标比已加载
  /// 范围还老）时——
  ///  · 时间轴定位（默认 true）：兜底跳到最旧 —— 目标已在范围外，最旧处
  ///    就是合理落点；
  ///  · 位置恢复（false）：返回 -1 —— 装作恢复成功比诚实失败更糟
  ///    （「已回到上次浏览位置」弹出来、人却在别处，比不提示更伤信任）。
  int _indexOfDateNotLaterThan(int ms, {bool fallbackToEnd = true}) {
    var idx = -1;
    for (var i = 0; i < _photos.length; i++) {
      final d = _photos[i].dateTaken;
      if (d == null) continue;
      idx = i;
      if (d.millisecondsSinceEpoch <= ms) return i;
    }
    return fallbackToEnd && idx >= 0 ? idx : -1;
  }

  /// 按索引跳转：index → 行号 → 行高换算像素。
  ///
  /// 走 [_scrollToTarget] 的逼近逻辑 —— 时间轴定位同样会被懒构建的
  /// maxScrollExtent 截断（拖到某个日期却停在半路）。
  Future<void> _jumpToIndex(int idx) async {
    if (_photos.isEmpty) return;
    await _scrollToTarget(idx ~/ _crossAxisCount * _rowH);
    _updateScrubber();
  }

  Future<void> _scrollToDate(int ms) =>
      _jumpToIndex(_indexOfDateNotLaterThan(ms));

  // ── 日期过滤（2026-10-12 v0.20.0）────────────────────────

  /// 选日期 = **过滤**到那天（系统相册语义，替代旧版的滚动定位 ——
  /// 目标日期没照片时定位会原地不动且无提示，老板真机反馈的根因）。
  Future<void> _setDayFilter(DateTime day) async {
    setState(() {
      _day = day;
      _photos.clear();
      _topId = null;
      _topMs = null;
      _hasMore = true;
      _loading = true;
    });
    final svc = ref.read(nativeGalleryServiceProvider);
    try {
      final first = await svc.queryImages(
          limit: _pageSize, bucket: _bucket, day: day);
      _photos.addAll(first);
      _hasMore = first.length == _pageSize;
      _syncScrubberRange();
    } catch (e) {
      // 查询异常原样露出（纪律：不把 BUG 化妆成空态）
      _error = e.toString();
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// 清除日期过滤，回全量列表（重走 _init；_restoreArmed 已 true，
  /// 不会触发旧位置恢复 —— 用户主动清除，回到顶部是合理落点）。
  Future<void> _clearDayFilter() async {
    if (_day == null) return;
    setState(() => _day = null);
    await _init();
  }

  /// 清除相册过滤（2026-10-13 v0.21.2）：空态里「这一天在当前相册没照片」
  /// 的一键退路 —— 换到全部相册再看同一天。日期过滤保留。
  Future<void> _clearBucketFilter() async {
    if (_bucket == null) return;
    setState(() {
      _bucket = null;
      _photos.clear();
      _hasMore = true;
    });
    await _init();
  }

  /// 日历选择：有照片的日期才可选（原生清单置灰无图日，从源头消除
  /// 「选了没反应」）；清单查询失败时谓词关闭（全部可选，选空态兜底）。
  Future<void> _pickAndFilterDay(int currentMs) async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _day ??
          DateTime.fromMillisecondsSinceEpoch(currentMs),
      firstDate: DateTime(now.year - 5),
      lastDate: now,
      selectableDayPredicate: _days.isEmpty
          ? null
          : (d) => _days.any((x) =>
              x.year == d.year && x.month == d.month && x.day == d.day),
    );
    if (picked != null) await _setDayFilter(picked);
  }

  /// 滚动时更新时间轴。**不 setState** —— 只推 [_scrubberTick]，让底部
  /// 时间轴那一小块自己重建，网格与其余 UI 完全不动（09-29 性能排查）。
  void _updateScrubber() {
    if (_photos.isEmpty || !_scroll.hasClients) return;
    final idx = _captureTop();
    if (idx < 0) return;
    final d = _photos[idx].dateTaken;
    if (d != null) {
      final ms = d.millisecondsSinceEpoch;
      if (ms != _scrubberMs) {
        _scrubberMs = ms;
        _scrubberTick.value = ms;
      }
    }
  }

  /// 写时间轴当前值（程序跳转 / 拖动都走这里），自动广播给时间轴 UI。
  void _setScrubber(int ms) {
    _scrubberMs = ms;
    _scrubberTick.value = ms;
  }

  /// 记住「当前视口顶部那张照片」，返回它的下标（-1 = 取不到）。
  ///
  /// ⚠️ 这才是位置记忆的主记录点（2026-09-29 真机「退出再进回不到原位」
  /// 的根因）：原来只在退出（dispose / 导入前）那一刻按
  /// `ScrollController.offset` 反算，而那时路由已经在拆 —— controller 多半
  /// 已经 detach（`hasClients=false`），offset 取到 0，于是把「第一张」写进
  /// 记录，下次进入自然回到顶部。**滚动过程中就把顶部照片记下来**，退出时
  /// 不论 controller 还在不在，都有最后一次有效位置可用。
  int _captureTop() {
    if (_photos.isEmpty || !_scroll.hasClients) return -1;
    final row = (_scroll.offset / _rowH).floor();
    var idx = row < 0 ? 0 : row * _crossAxisCount;
    // 滚到底部换算出的 idx 可能超出列表 —— clamp 到最后一张，绝不能丢保存。
    if (idx >= _photos.length) idx = _photos.length - 1;
    _rememberIndex(idx);
    return idx;
  }

  void _rememberIndex(int idx) {
    final p = _photos[idx];
    _topId = p.id;
    _topMs = p.dateTaken?.millisecondsSinceEpoch ?? _topMs;
  }

  void _syncScrubberRange() {
    var min = 0, max = 0;
    for (final p in _photos) {
      final d = p.dateTaken;
      if (d == null) continue;
      final ms = d.millisecondsSinceEpoch;
      if (min == 0 || ms < min) min = ms;
      if (max == 0 || ms > max) max = ms;
    }
    // ⚠️ 性能（09-29 排查）：min/max 原来在 build() 里现算 —— 每帧遍历
    // 整份列表（滚到深处上千条）。改成这里算一次存字段，build 直接读。
    _minMs = min;
    _maxMs = max;
    // 网格倒序（最新在前），顶部可见 = 最新；初始把时间轴指到最新。
    _setScrubber(_scrubberMs == 0 ? max : _scrubberMs.clamp(min, max));
  }

  // ─────────────────────────────────────────────────────────
  // 选中
  // ─────────────────────────────────────────────────────────

  void _toggle(int id) {
    setState(() {
      if (_selected.contains(id)) {
        _selected.remove(id);
      } else {
        _selected.add(id);
      }
    });
  }

  void _onTileTap(int id) {
    if (_rangeMode && _anchorId != null) {
      final a = _photos.indexWhere((p) => p.id == _anchorId);
      final b = _photos.indexWhere((p) => p.id == id);
      if (a < 0 || b < 0) {
        _toggle(id);
        return;
      }
      final lo = a < b ? a : b;
      final hi = a < b ? b : a;
      setState(() {
        for (var i = lo; i <= hi; i++) {
          _selected.add(_photos[i].id);
        }
        _anchorId = null;
      });
      _announce('已连选 ${hi - lo + 1} 张');
      return;
    }
    _toggle(id);
  }

  void _onTileLongPress(int id) async {
    final svc = ref.read(nativeGalleryServiceProvider);
    final res = await svc.readImages([id]);
    if (!mounted || res.isEmpty) return;
    final picked = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => _PreviewPage(
          result: res.first,
          initialSelected: _selected.contains(id),
        ),
      ),
    );
    if (!mounted || picked == null) return;
    setState(() {
      if (picked) {
        _selected.add(id);
      } else {
        _selected.remove(id);
      }
    });
  }

  void _toggleRangeMode() {
    setState(() {
      _rangeMode = !_rangeMode;
      _anchorId = null;
    });
    if (_rangeMode) {
      _announce('连选模式：点第一张设起点，再点一张即选整段');
    }
  }

  void _selectAll() {
    setState(() {
      for (final p in _photos) {
        _selected.add(p.id);
      }
    });
  }

  void _selectDay() {
    DateTime? refDay;
    if (_anchorId != null) {
      refDay = _photos
          .firstWhere((p) => p.id == _anchorId, orElse: () => _photos.first)
          .dayStart;
    } else if (_selected.isNotEmpty) {
      refDay = _photos
          .firstWhere((p) => _selected.contains(p.id),
              orElse: () => _photos.first)
          .dayStart;
    } else if (_scrubberMs > 0) {
      final d = DateTime.fromMillisecondsSinceEpoch(_scrubberMs);
      refDay = DateTime(d.year, d.month, d.day);
    }
    if (refDay == null) return;
    setState(() {
      for (final p in _photos) {
        if (p.dayStart == refDay) _selected.add(p.id);
      }
    });
    _announce('已选 ${refDay.month}/${refDay.day} 当日全部');
  }

  void _announce(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), duration: const Duration(seconds: 2)),
    );
  }

  // ─────────────────────────────────────────────────────────
  // 位置记忆
  // ─────────────────────────────────────────────────────────

  /// 位置记忆落盘。⚠️ 会从 dispose() 调用 —— 此时 element 已 unmount，
  /// 不能碰 MediaQuery/context，行高用 [_rowH] 缓存值（09-29 根因：
  /// dispose 里 MediaQuery.of 抛异常，位置根本没存上）。
  ///
  /// 存的是顶部可见照片的 **MediaStore id**（精确恢复主键）+ 拍摄时间
  /// （兜底）。
  ///
  /// [resample]：退出前（导入确认 / 左上角关闭）页面还活着，可以按当前
  /// offset 重算一次；dispose 尾声 controller 多已 detach，重算只会得到 0
  /// 并把真实位置覆盖掉 —— 那种场景必须传 false，只落盘滚动时记下的值。
  Future<void> _savePosition({bool resample = true}) async {
    if (_photos.isEmpty) return;
    if (resample) _captureTop();
    final id = _topId;
    if (id == null) return;
    final ms = _topMs;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('gallery.last_viewed_id', id);
      if (ms != null) await prefs.setInt('gallery.last_viewed_ms', ms);
      await prefs.setString('gallery.last_bucket', _bucket ?? '');
    } catch (_) {
      // 存不上位置不该影响退出
    }
  }

  // ─────────────────────────────────────────────────────────
  // 确认导入
  // ─────────────────────────────────────────────────────────

  /// 退出前先把位置落盘（页面还活着，能按当前 offset 重算一次）。
  /// dispose 兜底用的是「滚动时记下的位置」，这里先存一遍更准。
  Future<void> _exit() async {
    await _savePosition();
    if (mounted) Navigator.of(context).pop();
  }

  Future<void> _confirm() async {
    if (_selected.isEmpty || _reading) return;
    final ids = _selected.toList();
    final svc = ref.read(nativeGalleryServiceProvider);
    // await 前先把导航器取好 —— 跨 async gap 再摸 context 会踩
    // use_build_context_synchronously。
    final nav = Navigator.of(context);

    // ⚠️ 性能（2026-09-29 排查）：一次把 N 张原图全交给原生复制，中途
    // 一点反馈都没有 —— 选 100 张就是几十秒的黑屏，主观上等于"卡死"。
    // 改成分批提交：每批之间 UI 有机会刷一次进度（耗时几乎不变，
    // 因为瓶颈是磁盘 IO 而不是批次数）。
    final chunk = DeviceTier.current.importChunkSize;
    final results = <NativeGalleryReadResult>[];
    setState(() {
      _reading = true;
      _readDone = 0;
      _readTotal = ids.length;
    });
    for (var i = 0; i < ids.length; i += chunk) {
      final end = (i + chunk) < ids.length ? (i + chunk) : ids.length;
      final part = await svc.readImages(ids.sublist(i, end));
      results.addAll(part);
      if (!mounted) return;
      setState(() => _readDone = end);
    }
    if (!mounted) return;
    setState(() => _reading = false);

    if (!mounted) return;
    // 用 await：导入完立刻退出，位置必须已经写进 prefs 再 pop。
    await _savePosition();
    if (results.isEmpty) {
      _announce('没有可读取的照片');
      return;
    }
    // 返回给 runGalleryImport：它据此 importFromGallery（**不写相册**）。
    nav.pop(results);
  }

  // ─────────────────────────────────────────────────────────
  // 构建
  // ─────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final svc = ref.watch(nativeGalleryServiceProvider);
    final min = _oldestMs();
    final max = _newestMs();
    final hasRange = min > 0 && max > min;

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: _exit,
          tooltip: '取消',
        ),
        title: Text(_selected.isEmpty ? '选择照片' : '已选 ${_selected.length} 张'),
        actions: [
          // AppBar 只留 3 个入口 —— 6 个图标会把标题挤成「选...」
          // （2026-09-29 真机截图），低频操作全部收进「更多」菜单。
          IconButton(
            icon: Icon(
                _rangeMode ? Icons.linear_scale : Icons.linear_scale_outlined),
            onPressed: _toggleRangeMode,
            tooltip: '连选模式',
          ),
          PopupMenuButton<String?>(
            // 激活态换实心图标 + 主题色（2026-10-14 v0.21.3）：相册过滤
            // **会被记住**（gallery.last_bucket），光靠轮廓图标用户根本
            // 看不出自己还在过滤 —— 真机事故「系统相册有照片，app 里却
            // 没有」就是用户忘了在只看某个相册。
            icon: Icon(
              _bucket != null ? Icons.photo_album : Icons.photo_album_outlined,
              color: _bucket != null ? AppTheme.accent : null,
            ),
            tooltip: _bucket != null ? '只看「$_bucket」相册' : '只看某相册',
            onSelected: (b) {
              setState(() {
                _bucket = b;
                _photos.clear();
                _hasMore = true;
              });
              _init();
            },
            itemBuilder: (_) => [
              PopupMenuItem<String?>(
                value: null,
                child: Row(
                  children: [
                    const Expanded(child: Text('全部相册')),
                    if (_bucket == null)
                      const Icon(Icons.check, size: 16, color: AppTheme.accent),
                  ],
                ),
              ),
              for (final b in _buckets)
                PopupMenuItem<String?>(
                  value: b.name,
                  child: Row(
                    children: [
                      Expanded(child: Text('${b.name}（${b.count}）')),
                      if (_bucket == b.name)
                        const Icon(Icons.check,
                            size: 16, color: AppTheme.accent),
                    ],
                  ),
                ),
            ],
          ),
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert),
            tooltip: '更多',
            onSelected: (v) {
              switch (v) {
                case 'day':
                  _selectDay();
                case 'all':
                  _selectAll();
                case 'c3':
                  setState(() {
                    _crossAxisCount = 3;
                    _rowH = _calcRowHeight();
                  });
                case 'c4':
                  setState(() {
                    _crossAxisCount = 4;
                    _rowH = _calcRowHeight();
                  });
                case 'c5':
                  setState(() {
                    _crossAxisCount = 5;
                    _rowH = _calcRowHeight();
                  });
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'day', child: Text('全选当日')),
              PopupMenuItem(value: 'all', child: Text('全选已加载')),
              PopupMenuDivider(),
              PopupMenuItem(value: 'c3', child: Text('3 列（大图）')),
              PopupMenuItem(value: 'c4', child: Text('4 列')),
              PopupMenuItem(value: 'c5', child: Text('5 列（多）')),
            ],
          ),
        ],
      ),
      // SafeArea(top:false)（真机反馈：三键导航下「导入」按钮被系统导航栏
      // 盖住点不到）。edge-to-edge 下（capture_page 离开时全局设为
      // edgeToEdge；Android 15 + targetSdk 35 也是强制）内容延伸到导航栏
      // 后面，底部时间轴与确认栏必须消费 bottom inset。AppBar 的状态栏
      // inset 由 Scaffold 自己处理，这里只消费 bottom。
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            if (_rangeMode && _anchorId != null)
              Container(
                width: double.infinity,
                color: AppTheme.accent.withValues(alpha: 0.12),
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: const Text(
                  '连选起点已选：点选终点完成整段选择；再次点起点取消。',
                  style: TextStyle(fontSize: 12, color: AppTheme.navy),
                ),
              ),
            // Android 14「仅允许选中的照片」部分授权：查询不报错，但只回
            // 用户勾选过的行 —— 必须明说，否则用户以为相册真空了。
            if (_partialAccess && !_noPermission && _error == null)
              Container(
                width: double.infinity,
                color: Colors.orange.withValues(alpha: 0.15),
                padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
                child: const Row(
                  children: [
                    Expanded(
                      child: Text(
                        '系统授权为「仅允许选中的照片」，这里只显示你勾选过的图。',
                        style: TextStyle(fontSize: 12, color: AppTheme.navy),
                      ),
                    ),
                    TextButton(
                      onPressed: openAppSettings,
                      child: Text('去改授权', style: TextStyle(fontSize: 12)),
                    ),
                  ],
                ),
              ),
            // 相册过滤横幅（2026-10-14 v0.21.3）：与日期 chip 同款原则
            // ——「过滤态必须一眼可见、一键可退，不然人忘了在过滤」。
            // 相册选择会被记住，而顶部只有一个看不出状态的图标；
            // 用户忘了在只看某相册，看到别的相册的日子缺照片，就报
            // 「系统相册有照片，app 里却没有」。横幅常驻说明白 + 一键回全部。
            if (_bucket != null && !_noPermission && _error == null)
              Container(
                width: double.infinity,
                color: AppTheme.accent.withValues(alpha: 0.10),
                padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
                child: Row(
                  children: [
                    const Icon(Icons.photo_album,
                        size: 15, color: AppTheme.accent),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        '当前只看「$_bucket」相册 —— 其他相册的照片不在这里',
                        style:
                            const TextStyle(fontSize: 12, color: AppTheme.navy),
                      ),
                    ),
                    TextButton(
                      onPressed: _clearBucketFilter,
                      child: const Text('看全部',
                          style: TextStyle(fontSize: 12)),
                    ),
                  ],
                ),
              ),
            Expanded(
              child: _loading && _photos.isEmpty
                  ? const Center(child: CircularProgressIndicator())
                  : _noPermission
                      ? _BrokenStateBox(
                          icon: Icons.lock_outline,
                          message: '没有相册读取权限，无法展示照片。',
                          actions: {
                            '去授权': _requestAndReload,
                            '去系统设置': () => openAppSettings(),
                          },
                        )
                      : _error != null
                          ? _BrokenStateBox(
                              icon: Icons.error_outline,
                              message: '读取相册失败：$_error',
                              actions: {'重试': _init},
                            )
                          : _photos.isEmpty
                              ? Center(
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Text(
                                        // 2026-10-13 v0.21.2：日期 + 相册双层
                                        // 过滤时必须说清是**哪个相册的哪一天**
                                        // —— 只写「这一天没有照片」会让人以为
                                        // 手机里真没有，其实是当前相册没有。
                                        _day != null
                                            ? (_bucket != null
                                                ? '「$_bucket」相册在 ${_fmtDay.format(_day!)} 这一天没有照片'
                                                : '${_fmtDay.format(_day!)} 这一天没有照片')
                                            : _bucket != null
                                                ? '「$_bucket」相册里没有照片，试试顶部切换「全部相册」'
                                                : '相册里没有照片',
                                        textAlign: TextAlign.center,
                                        style: const TextStyle(
                                            color: AppTheme.textMuted),
                                      ),
                                      if (_day != null) ...[
                                        const SizedBox(height: 12),
                                        TextButton(
                                          onPressed: _clearDayFilter,
                                          child: const Text('查看全部日期'),
                                        ),
                                        if (_bucket != null)
                                          TextButton(
                                            onPressed: _clearBucketFilter,
                                            child: const Text('查看全部相册'),
                                          ),
                                      ],
                                    ],
                                  ),
                                )
                              : GridView.builder(
                                  controller: _scroll,
                                  padding: const EdgeInsets.all(8),
                                  // 预构建区域按设备档次收紧：低配机少建屏外
                                  // 格子，换来更稳的帧率（多滚一下才会露白）。
                                  cacheExtent:
                                      DeviceTier.current.gridCacheExtentPx,
                                  gridDelegate:
                                      SliverGridDelegateWithFixedCrossAxisCount(
                                    crossAxisCount: _crossAxisCount,
                                    crossAxisSpacing: 2,
                                    mainAxisSpacing: 2,
                                    childAspectRatio: 1,
                                  ),
                                  itemCount:
                                      _photos.length + (_hasMore ? 1 : 0),
                                  itemBuilder: (_, i) {
                                    if (i >= _photos.length) {
                                      return const Center(
                                          child: SizedBox(
                                              width: 20,
                                              height: 20,
                                              child: CircularProgressIndicator(
                                                  strokeWidth: 2)));
                                    }
                                    final p = _photos[i];
                                    final selected = _selected.contains(p.id);
                                    final isAnchor = _anchorId == p.id;
                                    return _Tile(
                                      svc: svc,
                                      photo: p,
                                      selected: selected,
                                      isAnchor: isAnchor,
                                      onTap: () => _onTileTap(p.id),
                                      onLongPress: () => _onTileLongPress(p.id),
                                    );
                                  },
                                ),
            ),
            // 时间轴（按时间定位）
            //
            // 只让这一小块跟着 [_scrubberTick] 重建 —— 滚动时它每跨一行就
            // 变一次，若整页 setState，GridView 会被连带重建（09-29 性能排查）。
            if (hasRange)
              Container(
                padding: const EdgeInsets.fromLTRB(12, 6, 12, 2),
                color: Colors.white,
                child: ValueListenableBuilder<int>(
                  valueListenable: _scrubberTick,
                  builder: (_, ms, __) => Row(
                    children: [
                      // 日期过滤 chip（2026-10-12 v0.20.0）：过滤中显示
                      // 「当前日期 ✕」，点 ✕ 回全量 —— 过滤态必须一眼可见、
                      // 一键可退，不然人忘了在过滤，以为相册就这几张。
                      if (_day != null)
                        InkWell(
                          onTap: _clearDayFilter,
                          borderRadius: BorderRadius.circular(12),
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: AppTheme.accent.withValues(alpha: 0.12),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(
                                  _fmtDay.format(_day!),
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: AppTheme.accent,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(width: 3),
                                const Icon(Icons.close,
                                    size: 13, color: AppTheme.accent),
                              ],
                            ),
                          ),
                        )
                      else
                        Text(
                            _fmtDay.format(
                                DateTime.fromMillisecondsSinceEpoch(ms)),
                            style: const TextStyle(
                                fontSize: 12, color: AppTheme.textMuted)),
                      Expanded(
                        child: Slider(
                          min: min.toDouble(),
                          max: max.toDouble(),
                          value: ms.clamp(min, max).toDouble(),
                          onChanged: (v) => _setScrubber(v.toInt()),
                          onChangeEnd: (v) => _scrollToDate(v.toInt()),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.search, size: 18),
                        tooltip: _day == null ? '按日期筛选' : '换个日期',
                        onPressed: () async =>
                            await _pickAndFilterDay(ms),
                      ),
                    ],
                  ),
                ),
              ),
            // 底部精简确认栏（缩小确认区域，最大化预览）
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.white,
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.08),
                    blurRadius: 6,
                    offset: const Offset(0, -2),
                  ),
                ],
              ),
              child: Row(
                children: [
                  Expanded(
                    child: _reading
                        ? Row(
                            children: [
                              const SizedBox(
                                width: 14,
                                height: 14,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2),
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  '正在读取 $_readDone / $_readTotal 张',
                                  style: const TextStyle(
                                      fontSize: 13,
                                      color: AppTheme.textMuted),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            ],
                          )
                        : Text(
                            _selected.isEmpty
                                ? '未选择照片'
                                : '已选 ${_selected.length} 张',
                            style: const TextStyle(
                                fontSize: 13, color: AppTheme.textMuted),
                          ),
                  ),
                  ElevatedButton(
                    onPressed: (_selected.isEmpty || _reading) ? null : _confirm,
                    child: Text(
                        _selected.isEmpty ? '导入' : '导入 ${_selected.length} 张'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 时间轴最早时刻（缓存值，随列表变化在 [_syncScrubberRange] 里重算）。
  int _oldestMs() => _minMs;

  /// 时间轴最晚时刻（同上）。
  int _newestMs() => _maxMs;
}

/// 无权限 / 查询报错的兜底态：把原因说清楚 + 给可点的出路。
/// 「查不到 ≠ 相册空」——把失败渲染成正常空态是 09-29 空态事故的根源。
class _BrokenStateBox extends StatelessWidget {
  const _BrokenStateBox({
    required this.icon,
    required this.message,
    required this.actions,
  });

  final IconData icon;
  final String message;
  final Map<String, VoidCallback> actions;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 40, color: Colors.grey),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            Wrap(
              spacing: 12,
              children: [
                for (final entry in actions.entries)
                  ElevatedButton(
                    onPressed: entry.value,
                    child: Text(entry.key),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 相册网格缩略图的**有界缓存 + 并发闸门**（2026-09-29 性能排查）。
///
/// 旧实现两个坑：
///   · `static Map` 只增不减 —— 滚过一千张就把一千份 JPEG 字节常驻在堆里
///     （每份 20~60KB，合起来几十 MB），低配机滚久了就卡。
///   · 每个格子各自发起一次通道调用 —— 快速滑动时几十个请求同时排队，
///     原生侧串行出图，Dart 侧却已经把整屏格子都标成"等待中"。
///
/// 现在：容量固定（超出淘汰最早的），并发固定（超出的排队）。
class _GalleryThumbStore {
  _GalleryThumbStore._();

  /// 缓存条数上限。约等于三屏格子 —— 再大就是"滚过的历史"占着内存不放。
  static const _maxEntries = 240;

  final Map<int, Uint8List?> _bytes = {};
  final Map<int, Future<Uint8List?>> _futures = {};
  final List<int> _lru = <int>[];
  final AsyncLimiter _limiter = AsyncLimiter(DeviceTier.current.thumbConcurrency);

  Uint8List? cached(int id) => _bytes[id];

  /// 取缩略图：命中缓存立即返回；否则**同一 id 共用同一个 future**
  /// （滚出再滚回来的格子不会重复请求，也不会因为"别人正在取"就永远空白），
  /// 且过一次并发闸门 —— 快滑时不会一次性压给原生几百个请求。
  Future<Uint8List?> get(int id, Future<Uint8List?> Function() loader) {
    final hit = _bytes[id];
    if (hit != null) return Future<Uint8List?>.value(hit);
    final pending = _futures[id];
    if (pending != null) return pending;
    final f = _limiter.run(loader).then((v) {
      _futures.remove(id);
      _remember(id, v);
      return v;
    });
    _futures[id] = f;
    return f;
  }

  void _remember(int id, Uint8List? v) {
    if (v == null) return;
    _bytes[id] = v;
    _lru.remove(id);
    _lru.add(id);
    while (_lru.length > _maxEntries) {
      final dead = _lru.removeAt(0);
      _bytes.remove(dead);
    }
  }

  static final _GalleryThumbStore instance = _GalleryThumbStore._();
}

/// 单格缩略图。缩略图走原生系统缓存（绝不解码原图），按 id 缓存。
class _Tile extends StatefulWidget {
  const _Tile({
    required this.svc,
    required this.photo,
    required this.selected,
    required this.isAnchor,
    required this.onTap,
    required this.onLongPress,
  });

  final NativeGalleryService svc;
  final NativeGalleryPhoto photo;
  final bool selected;
  final bool isAnchor;
  final VoidCallback onTap;
  final VoidCallback onLongPress;

  @override
  State<_Tile> createState() => _TileState();
}

class _TileState extends State<_Tile> {
  Uint8List? _bytes;

  @override
  void initState() {
    super.initState();
    _bytes = _GalleryThumbStore.instance.cached(widget.photo.id);
    if (_bytes == null) _load();
  }

  @override
  void didUpdateWidget(_Tile old) {
    super.didUpdateWidget(old);
    if (old.photo.id != widget.photo.id) {
      _bytes = _GalleryThumbStore.instance.cached(widget.photo.id);
      if (_bytes == null) _load();
    }
  }

  Future<void> _load() async {
    final id = widget.photo.id;
    final px = DeviceTier.current.galleryThumbPx;
    final v = await _GalleryThumbStore.instance
        .get(id, () => widget.svc.thumbnail(id, sizePx: px));
    if (!mounted || v == null) return;
    if (_bytes == null || !identical(_bytes, v)) setState(() => _bytes = v);
  }

  @override
  Widget build(BuildContext context) {
    final photo = widget.photo;
    final future = _bytes;
    final label = photo.dateTaken == null
        ? '—'
        : DateFormat('MM/dd HH:mm').format(photo.dateTaken!);
    return GestureDetector(
      onTap: widget.onTap,
      onLongPress: widget.onLongPress,
      child: Stack(
        fit: StackFit.expand,
        children: [
          Container(
            color: Colors.black12,
            child: future != null
                ? Image.memory(future,
                    fit: BoxFit.cover,
                    // 按显示尺寸解码：格子只有 1/3 屏宽，没必要把 256px
                    // 的图整个展开到纹理内存里（低配机省一大截）。
                    cacheWidth: DeviceTier.current.galleryThumbPx,
                    gaplessPlayback: true,
                    filterQuality: FilterQuality.low)
                : const Center(
                    child: Icon(Icons.image, color: Colors.grey)),
          ),
          // 日期条
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              color: Colors.black54,
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
              child: Text(
                label,
                style: const TextStyle(fontSize: 10, color: Colors.white),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
          // 选中勾选
          if (widget.selected)
            const Positioned(
              top: 4,
              right: 4,
              child: Icon(Icons.check_circle, color: AppTheme.accent, size: 22),
            ),
          // 连选起点高亮
          if (widget.isAnchor)
            Positioned(
              top: 4,
              left: 4,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                decoration: BoxDecoration(
                  color: AppTheme.accent,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: const Text('起点',
                    style: TextStyle(fontSize: 10, color: Colors.white)),
              ),
            ),
          if (widget.selected)
            Positioned.fill(
              child: Container(
                decoration: BoxDecoration(
                  border: Border.all(color: AppTheme.accent, width: 2),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// 大图预览（长按格子进入）。可在此直接切换选中，确认这张是不是要的。
///
/// 2026-09-30 拍板：预览必须支持双指缩放看细节 —— 现场要核对标签
/// 小字 / 封条号，一张 fit 屏宽的静态图看不清。手势用公用组件
/// [ZoomableImage]（与整理页全屏查看同一套：双指缩放 / 平移 / 双击复位）。
class _PreviewPage extends StatefulWidget {
  const _PreviewPage({required this.result, required this.initialSelected});

  final NativeGalleryReadResult result;
  final bool initialSelected;

  @override
  State<_PreviewPage> createState() => _PreviewPageState();
}

class _PreviewPageState extends State<_PreviewPage> {
  late bool _selected;

  @override
  void initState() {
    super.initState();
    _selected = widget.initialSelected;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.result.displayName,
            style: const TextStyle(fontSize: 14)),
        actions: [
          IconButton(
            icon: Icon(
                _selected ? Icons.check_circle : Icons.radio_button_unchecked),
            tooltip: _selected ? '取消选择' : '选择',
            onPressed: () {
              setState(() => _selected = !_selected);
              Navigator.of(context).pop(_selected);
            },
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: ZoomableImage(
              path: widget.result.tempPath,
              // ⚠️ 预览的是**原图**（可能 12MP）。不限制解码尺寸的话，一张就
              // 要开出 ~48MB 的像素缓冲，低配机连翻几张就会被系统杀进程。
              // 解码宽度 = **2 倍**屏幕物理宽度（09-30 起支持缩放看细节）：
              // 1 倍屏宽的图放大 2 倍就糊（像素不够）；2 倍 = 放大 2 倍依然
              // 清晰，而内存只多花约 14MB（2160x1620x4B），单张页可接受。
              // 真要看更细就长按前的原图，这里已经覆盖"核对标签小字"。
              cacheWidth: (MediaQuery.of(context).size.width *
                      MediaQuery.devicePixelRatioOf(context) *
                      2)
                  .round(),
              filterQuality: FilterQuality.medium,
              errorBuilder: (context) => const Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.broken_image_outlined,
                        size: 40, color: AppTheme.textMuted),
                    SizedBox(height: 8),
                    Text(
                      '这张照片读不出来',
                      style: TextStyle(color: AppTheme.textMuted, fontSize: 13),
                    ),
                  ],
                ),
              ),
            ),
          ),
          // 底部操作提示（与全屏查看页同款文案习惯，现场人员不用学）
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Text(
                '双指放大看细节 · 双击复位',
                style: TextStyle(
                  fontSize: 11.5,
                  color: AppTheme.textMuted.withValues(alpha: 0.9),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
