# -*- coding: utf-8 -*-
"""Web 层的共享依赖（路径常量、DB 连接、治理后台任务、照片输出结构）。

抽出来的原因：这些是 routes/ 下多个模块共用的东西，留在 server.py 里
会让路由包反向依赖入口文件，形成环。

⚠️ 本模块必须能在没有 FastAPI 路由的情况下单独 import（cli / selftest 也用）。
"""
import os
import sys
import threading
from datetime import datetime

# ⚠️ 导入顺序有讲究：paths 是包内模块，导入它需要包能被找到，而包能不能找到
# 又取决于 ROOT 是否已在 sys.path。所以先用 os 原地算一次 ROOT（bootstrap），
# 再导入 paths 用它的正式结果覆盖。顺序反了会 ImportError。
_BOOTSTRAP_ROOT = getattr(sys, 'frozen', False) and None or \
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BOOTSTRAP_ROOT and _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

# 路径一律走 paths.py（唯一真源）。此前 ROOT 在这里/server.py/cli.py 各算一遍，
# 打包成 exe 后三处全失效 —— 2026-10-06 抽出 paths 统一。
from tools.productlib import paths  # noqa: E402

ROOT = paths.app_root()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.productlib import pipeline, schema, store  # noqa: E402

DATA_DIR = paths.data_dir()
UPLOAD_DIR = paths.upload_dir()
THUMB_DIR = paths.thumb_dir()
VIEW_DIR = paths.view_dir()
STANDARD_DIR = paths.standard_dir()
REPORT_DIR = paths.reports_dir()
WEB_DIR = paths.web_dir()
STATIC_DIR = paths.static_dir()

paths.ensure_dirs()


def con():
    """每个请求开一条自己的 sqlite 连接（sqlite 连接不能跨线程复用）。"""
    return store.connect()


# ═══════════════════════════════════════════════════════════════════
# 治理任务（后台线程）—— 2026-10-18 起支持多任务并行（老板需求 4）
# ═══════════════════════════════════════════════════════════════════
# 任务模型：key = batch_id（批次任务）或 '__all__'（全量）。
#   · 同 key 互斥（同一批次不能同时两轮治理）
#   · '__all__' 任务独占（全量 reset 会重置所有照片，与任何任务冲突）
#   · 不同批次可并行（各自独立连接、WAL busy_timeout 兜底写竞争）
# _GOVERN 保留为「兼容视图」：镜像最新任务的状态，旧消费者不炸。

_LOCK = threading.Lock()
_GTASKS = {}                    # key -> task dict（含 threading.Event stop）
_GSEQ = [0]                     # 启动序号（status 排序：先启动的在前）
_GOV_FLD = ('running', 'done', 'total', 'linked', 'file', 'result',
            'started', 'error')


def _govern_compat_view():
    """旧单任务字段视图：取最新启动的任务镜像（没有任务时全空态）。"""
    if not _GTASKS:
        t = {k: (False if k == 'running' else None) for k in _GOV_FLD}
        t.update(done=0, total=0, linked=0, file='')
        return t
    latest = max(_GTASKS.values(), key=lambda t: t.get('seq', 0))
    return {k: latest.get(k) for k in _GOV_FLD}


# 兼容导出：旧 import 处可用；govern.py 已改走 govern_status()
_GOVERN = {}
for _k in _GOV_FLD:
    _GOVERN[_k] = None
_GOVERN.update(done=0, total=0, linked=0, file='')
# 兼容导出的停止事件：指向全量任务（stop 端点已支持按 key 停）
_GOVERN_STOP = threading.Event()


def govern_tasks():
    """全部任务的快照列表（先启动的在前）。"""
    with _LOCK:
        ts = sorted(_GTASKS.values(), key=lambda t: t.get('seq', 0))
        out = []
        for t in ts:
            d = {k: t.get(k) for k in _GOV_FLD}
            d['key'] = t['key']
            d['batch_id'] = t.get('batch_id')
            d['name'] = t.get('name')
            out.append(d)
        return out


def govern_status():
    """治理状态：兼容单任务字段 + tasks 列表。"""
    tasks = govern_tasks()
    compat = _govern_compat_view()
    compat['tasks'] = tasks
    return compat


def _refresh_compat():
    """把最新任务镜像进兼容导出 _GOVERN（进程内旧引用仍可用）。"""
    v = _govern_compat_view()
    _GOVERN.update(v)


def govern_stop(batch_id=None):
    """请求停止：指定批次任务或全部。返回 {stopped: n, ...}。"""
    n = 0
    with _LOCK:
        for key, t in _GTASKS.items():
            if t.get('running') and (batch_id is None or key == batch_id):
                t['stop'].set()
                n += 1
    if batch_id is None:
        _GOVERN_STOP.set()      # 兼容旧引用
    return {'stopped': n}


def govern_start(limit=None, use_vision=True, use_ocr=True, reset=False,
                 batch_id=None, retry_failed=False, skip_linked=False):
    """启动一个治理任务（多任务规则见 _GTASKS 注释）。

    返回 {'started': True/False, 'reason': ...}。
    """
    key = batch_id or '__all__'
    with _LOCK:
        if '__all__' in _GTASKS and _GTASKS['__all__'].get('running'):
            return {'started': False, 'reason': '已有全量治理在跑（它覆盖所有照片，不能与其它任务并行）'}
        if key == '__all__' and _GTASKS:
            running = [k for k, t in _GTASKS.items() if t.get('running')]
            if running:
                return {'started': False,
                        'reason': '全量治理要求没有其它治理任务在跑（当前：%s）'
                                  % '、'.join(running)}
        if key in _GTASKS and _GTASKS[key].get('running'):
            return {'started': False, 'reason': '该批次的治理已在跑'}
        _GSEQ[0] += 1
        task = {'key': key, 'batch_id': batch_id, 'name': batch_id or '全部照片',
                'running': True, 'done': 0, 'total': 0, 'linked': 0, 'file': '',
                'result': None, 'error': None, 'seq': _GSEQ[0],
                'started': datetime.now().isoformat(timespec='seconds'),
                'stop': threading.Event()}
        _GTASKS[key] = task
        _refresh_compat()
    t = threading.Thread(target=_run_govern_task, args=(task, limit, use_vision,
                                                        use_ocr, reset, batch_id,
                                                        retry_failed, skip_linked),
                         daemon=True)
    try:
        t.start()
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            task['running'] = False
            task['error'] = '启动失败：%s' % str(e)[:200]
            _refresh_compat()
        return {'started': False, 'reason': task['error']}
    return {'started': True}


def _run_govern_task(task, limit, use_vision, use_ocr, reset=False,
                     batch_id=None, retry_failed=False, skip_linked=False):
    stop_ev = task['stop']
    stop_ev.clear()
    c = None
    try:
        c = store.connect()

        def prog(done, total, fname, linked):
            with _LOCK:
                task.update(done=done, total=total, file=fname, linked=linked)
                _refresh_compat()

        res = pipeline.govern_all(c, limit=limit, use_vision=use_vision,
                                  use_ocr=use_ocr, progress=prog, reset=reset,
                                  batch_id=batch_id, retry_failed=retry_failed,
                                  stop_event=stop_ev,
                                  skip_linked=skip_linked)
        with _LOCK:
            task.update(running=False, result=res)
            _refresh_compat()
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            task.update(running=False, error=str(e)[:500])
            _refresh_compat()
    finally:
        stop_ev.set()           # 兜底：线程退出后残留信号不留给下一轮复用
        if c:
            try:
                c.close()
            except Exception:
                pass
        with _LOCK:
            # 已结束的任务保留状态（前端能看到结果），只清过旧的：
            done_keys = [k for k, t in _GTASKS.items()
                         if not t.get('running')]
            while len(done_keys) > 6:          # 最多留 6 个已结束任务
                oldest = min(done_keys, key=lambda k: _GTASKS[k].get('seq', 0))
                del _GTASKS[oldest]
                done_keys.remove(oldest)


# 旧名字（routes 里还有 import）—— 指向新实现
_run_govern = _run_govern_task


# ═══════════════════════════════════════════════════════════════════
# 照片输出结构（products / photos / review 三处共用）
# ═══════════════════════════════════════════════════════════════════

def _photo_out(c, r):
    """统一照片输出结构。加 thumb/view/full 的 URL，前端不必自己拼。

    [view] 长边受限的预览图 —— 抽屉/详情**显示**用这个，不要直接上原图：
    真实库单张 3.8~21MB，原图冷加载实测 4.47s，左右切换会一张卡一次。
    [full] 原图 —— 只在「点击看细节」时用。
    """
    d = dict(r)
    d['thumb'] = '/thumb/%s' % r['id']
    d['view'] = '/img/%s?w=%d' % (r['id'], schema.VIEW_LONG_EDGE)
    d['full'] = '/img/%s' % r['id']
    d['size_mb'] = round((r['bytes'] or 0) / 1048576, 2)
    return d
