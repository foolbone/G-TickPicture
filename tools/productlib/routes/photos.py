# -*- coding: utf-8 -*-
"""照片：导入文件夹/上传/列表/批次/原图与缩略图

由 server.py 按业务域切出，逻辑未改。
"""
import json
import os
import shutil
import sqlite3
import time
import uuid
import functools
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

# deps 放最前：它负责 sys.path 引导
from tools.productlib.deps import (  # noqa: F401
    DATA_DIR, ROOT, THUMB_DIR, UPLOAD_DIR, VIEW_DIR, WEB_DIR,
    _GOVERN, _LOCK, _photo_out, _run_govern, con,
)
from tools.productlib import pipeline, schema, store, vision

router = APIRouter()


def _parse_dt(s):
    """taken_at 字符串 → datetime；解析不了返回 None（调用方不过滤）。
    容忍 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DDTHH:MM:SS' / 带小数秒。"""
    if not s:
        return None
    t = str(s).strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(t[:26], fmt)
        except ValueError:
            continue
    return None

# ═══════════════════════════════════════════════════════════════════
# 第 2 条：照片批量上传
# ═══════════════════════════════════════════════════════════════════

@router.post('/api/photos/import-folder')
def api_import_folder(payload: dict):
    """从本机目录导入（900MB 的照片走这条路，不要走网页上传）。

    body: {folder: 'D:/...', name: '批次名', container_id: '柜 id（必填）'}

    ⚠️ 2026-10-05 v3：container_id 必填（无柜不导）。闸门在后端 ——
    前端拦得住误操作，拦不住脚本。
    """
    # 先柜后目录：柜是流程第一步，别让用户去折腾路径（与 import-auto 同口径）
    cid = (payload.get('container_id') or '').strip()
    if not cid:
        raise HTTPException(400, '请先选择柜（先到「柜」页新建或选一个柜）')
    folder = (payload.get('folder') or '').strip()
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, '目录不存在：%s' % folder)
    c = con()
    try:
        return store.add_photos(c, folder, batch_name=payload.get('name'),
                                container_id=cid)
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post('/api/photos/import-standard')
def api_import_standard(payload: dict):
    """按标准采集格式导入：.../预检/{箱号}/照片.jpg + .../监装/

    🔴 **柜号一律取 body 里的 container_id（界面上选的柜）**；目录名只当
    "来源目录"用于批次命名与追溯，**绝不用于建柜或挂批次**（2026-10-06
    老板定口径）。原来这个端点按目录名自动建柜，网页入口已改走
    /import-auto，这里同步口径，避免脚本调用时又造出残缺柜。

    body: {folder: 'D:/预检图片', container_id: '柜 id（必填）'}
    """
    cid = (payload.get('container_id') or '').strip()
    if not cid:
        raise HTTPException(400, '请先选择柜 —— 照片要挂在柜下面'
                                '（先到「柜」页新建或选一个柜）')
    folder = (payload.get('folder') or '').strip()
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, '目录不存在：%s' % folder)
    c = con()
    try:
        return store.import_standard_folder(c, folder, container_id=cid)
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post('/api/photos/import-auto')
def api_import_auto(payload: dict):
    """自动识别格式导入 —— 老板只要选一个目录，不用判断该点哪个按钮。

    先按标准采集格式 `.../预检/{箱号}/照片.jpg` 探测：
      命中 → 走标准导入
      未命中 → 走普通目录导入（整目录一个批次）

    ⚠️ 探测用 scan_standard_folder 而不是自己再写一份目录判断 ——
       格式规则只能有一个真源，写两份必然漂移。

    🔴 **柜号一律取 container_id（界面上选的柜）**；目录名只当"来源目录"，
    绝不用于建柜或挂批次（2026-10-06 老板定口径）。两种格式都必须先选柜。

    body: {folder: 'D:/...', container_id: '柜 id（必填）'}
    返回统一结构：{mode: 'standard'|'plain', ...各模式自己的字段}
    """
    # ⚠️ 顺序：**先查柜、再查目录**。柜是流程第一步（闸门），
    #    目录不存在是次要问题。反过来的话用户看到"目录不存在"，
    #    会去折腾路径，而真正该做的是先建柜。
    cid = (payload.get('container_id') or '').strip()
    if not cid:
        raise HTTPException(400, '请先选择柜 —— 照片要挂在柜下面'
                                '（先到「柜」页新建或选一个柜）')
    folder = (payload.get('folder') or '').strip()
    if not folder or not os.path.isdir(folder):
        raise HTTPException(400, '目录不存在：%s' % folder)
    c = con()
    try:
        # 探测：能扫到标准格式照片就走标准路径
        try:
            probe = store.scan_standard_folder(folder)
        except Exception:  # noqa: BLE001
            probe = []
        if probe:
            r = store.import_standard_folder(c, folder, container_id=cid)
            r['mode'] = 'standard'
            return r
        r = store.add_photos(c, folder, container_id=cid)
        r['mode'] = 'plain'
        return r
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


def retry_write(fn):
    """SQLite 瞬时写错误自动重试（2026-10-14 打包版实测踩坑）。

    现象：v0.10.0 打包验收时，新库高频写入偶发 500 —— add_photos /
    set_photo_usage 等写路径随机撞
    `sqlite3.OperationalError: attempt to write a readonly database`
    （~30% 概率；换目录、单进程、WAL+30s busy_timeout 都排除过，
    高度疑似杀软对**新建 DB 文件**的瞬时拦截，等一下就好）。

    🔴 重试必须**整个函数重跑**而不是重放 SQL：readonly 一旦出现，坏掉
    的是那个连接，路由函数里 `c = con()` 会拿到新连接。只兜瞬时类错误，
    真问题照抛。
    """
    @functools.wraps(fn)
    def wrapper(*a, **k):
        for attempt in range(3):
            try:
                return fn(*a, **k)
            except sqlite3.OperationalError as e:
                s = str(e)
                transient = ('readonly' in s or 'locked' in s
                             or 'I/O error' in s)
                if not transient or attempt == 2:
                    raise
                time.sleep(0.4 * (attempt + 1))
    return wrapper


@router.post('/api/photos/upload')
@retry_write
def api_upload(files: list[UploadFile] = File(...), name: str = Form(''),
               container_id: str = Form('')):
    """网页批量上传。文件先落盘到 uploads/，再走与目录导入同一条扫描逻辑 ——
    MD5 去重、EXIF 时间、分组全部复用，不存在两套口径。"""
    if not (container_id or '').strip():
        raise HTTPException(400, '请先选择柜（先到「柜」页新建或选一个柜）')
    bid = uuid.uuid4().hex[:8]
    dst_dir = os.path.join(UPLOAD_DIR, bid)
    os.makedirs(dst_dir, exist_ok=True)
    saved = 0
    for f in files:
        fn = os.path.basename(f.filename or '')
        if not fn:
            continue
        dst = os.path.join(dst_dir, fn)
        i = 1
        while os.path.exists(dst):
            stem, ext = os.path.splitext(fn)
            dst = os.path.join(dst_dir, '%s_%d%s' % (stem, i, ext))
            i += 1
        with open(dst, 'wb') as o:
            shutil.copyfileobj(f.file, o)
        saved += 1
    if saved == 0:
        raise HTTPException(400, '没有收到任何文件')
    c = con()
    try:
        r = store.add_photos(c, dst_dir, batch_name=name or '网页上传 %s' % bid,
                             container_id=container_id.strip())
        r['saved'] = saved
        return r
    except store.ContainerError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get('/api/photos')
def api_photos(state: str = '', kind: str = '', unlinked: int = 0,
               linked: int = 0,
               batch: str = '', q: str = '', usage: str = '',
               container_id: str = '', limit: int = 60, offset: int = 0,
               flag: str = '', mark: int = 0, invalid: str = 'hide',
               ignored: str = 'hide',
               pending: int = 0, todo: str = '', sort: str = 'time'):
    """[linked] 1 = 只要已关联的（10-07 老板：照片要能按「已关联/未关联」分组看）。

    ⚠️ 与 `unlinked` 是**两把独立的筛子**，不是同一个开关的两态 —— 前端分组视图
    要各发一次请求拿各自的总数，一把开关给不出「两组各多少张」。
    同时传两个（linked=1&unlinked=1）逻辑上为空集，不做特殊处理。

    ⚠️ 口径**故意不对称**：`unlinked` 沿用既有写法（未关联 **且** 非重复照片），
    `linked` 只看「在 links 表里」，不排重复 —— 一张重复照片若被关联过，
    它就是一条有效关联，藏起来反而不该。副作用：两组之和 ≤ 该范围总数
    （差值就是被 unlinked 排除掉的重复照片），前端文案因此写
    「共 a+b 张（已关联 a · 未关联 b）」，不声称等于全部。

    [flag]  分组档位（10-07 第二轮）：'' 全部 / linked / unlinked /
            cand（待确认关联） / newprod（新产品确认）。前两档等价于
            linked/unlinked 参数（保留参数是为了不破坏老调用方）。
    [mark]  1 = 每张带上 in_cand / in_newprod 角标（列表页要画「待确认」
            「新产品」小标签时用；默认关，因为要多算一次映射）。
    [pending] 1 = 只要「监装细分待确认」集合（2026-10-14：③的待办从独立
            列表合并进左侧树形筛选，走的就是这个参数）。与③的待办清单
            **同一个函数**（supervision_pending_of），按 container_id
            收窄；没给柜号就没有范围，返回空（不撒谎成全库的数）。
    """
    c = con()
    try:
        extra_ids = []
        # 🔴 flag 的前两档必须翻译成 linked/unlinked 筛子（docstring 声称
        #    「等价于 linked/unlinked 参数」，但此前代码只处理 cand/newprod，
        #    前端选项卡只传 flag、不传 linked/unlinked → 两档都返回全部照片，
        #    「已关联/未关联」选项卡看到的是同一批 = 筛选失效）。
        if flag == 'linked':
            linked = 1
        elif flag == 'unlinked':
            unlinked = 1
        elif flag == 'invalid':
            # 无效图片档（2026-10-15 需求5）：翻成「只看无效」。
            # 与徽章 photo_flag_counts 的 invalid 档同一口径（photo_where_sql）。
            invalid = 'only'
        elif flag == 'ignored':
            # 已忽略档（2026-10-18 老板需求）：本次忽略的照片（新产品确认时
            # 标记的），退出一切关联队列后的查看/恢复入口。
            ignored = 'only'
        if pending:
            if not container_id:
                return {'total': 0, 'items': [], 'pending': 1}
            # 🔴 supervision_pending_of 返回 {items, total, labels}，取 .items
            extra_ids = [r['photo_id'] for r in
                         store.supervision_pending_of(c, container_id)['items']]
            if not extra_ids:
                return {'total': 0, 'items': [], 'pending': 1}
        elif flag == 'cand':
            extra_ids = sorted(store.cand_photo_ids(c))
            if not extra_ids:
                return {'total': 0, 'items': [], 'flag': flag}
        elif flag == 'newprod':
            extra_ids = sorted(store.newprod_photo_map(c))
            if not extra_ids:
                return {'total': 0, 'items': [], 'flag': flag}
        # 关联待办进查询条件（2026-10-15 需求3）：与树/状态/分类自由组合。
        # 与 flag 的 extra_ids 取交集 —— 两个筛子同时给时不许互相覆盖。
        if todo in ('cand', 'newprod'):
            ids = set(store.cand_photo_ids(c)) if todo == 'cand' \
                else set(store.newprod_photo_map(c))
            if container_id:
                scope = {r[0] for r in c.execute(
                    'SELECT p.id FROM photos p JOIN batches b ON b.id=p.batch_id'
                    ' WHERE b.container_id=?', [container_id])}
                ids &= scope
            extra = sorted(ids)
            if not extra:
                return {'total': 0, 'items': [], 'todo': todo}
            extra_ids = sorted(set(extra_ids) & set(extra)) if extra_ids else extra
            if not extra_ids:
                return {'total': 0, 'items': [], 'todo': todo}
        join, frag, args = store.photo_where_sql(
            state=state, kind=kind, batch=batch, usage=usage,
            unlinked=unlinked, linked=linked, q=q, container_id=container_id,
            invalid=invalid, ignored=ignored)
        if extra_ids:
            # id 集合可能上千，IN 参数分批（SQLite 变量上限 999）——
            # 用 OR 串起来而不是分批查询，避免「总数与列表条数不一致」。
            parts = []
            for i in range(0, len(extra_ids), 400):
                chunk = extra_ids[i:i + 400]
                parts.append('p.id IN (%s)' % ','.join('?' * len(chunk)))
                args.extend(chunk)
            # ⚠️ frag 为空时要补 WHERE —— 直接接 ' AND (...)' 会语法错。
            frag += (' WHERE ' if not frag.strip() else ' AND ') + '(%s)' % ' OR '.join(parts)
        sql = ('SELECT p.*, (SELECT COUNT(*) FROM links l WHERE l.photo_id=p.id) AS nlink'
               ' FROM photos p' + join + frag)
        total = c.execute(
            'SELECT COUNT(*) FROM (%s)' % sql.replace('SELECT p.*,', 'SELECT p.id,', 1),
            list(args)).fetchone()[0]
        # 排序（2026-10-19 老板需求「显示当前排序规则，增加更多排序方式」）：
        #   time（默认，拍摄时间升序 —— 连拍判断的基线）/ code（按读出的编码，
        #   同编码聚在一起方便核对）/ state（按治理状态：待治理→已治理，
        #   干活时先看到没处理的）。全部带 id 兜底保证稳定分页。
        _SORTS = {
            'time': 'p.taken_at, p.id',
            'code': 'p.vision_codes, p.taken_at, p.id',
            'state': "CASE p.govern_state WHEN 'pending' THEN 0 WHEN 'failed' THEN 1"
                     " WHEN 'done' THEN 2 ELSE 3 END, p.taken_at, p.id",
        }
        sql += ' ORDER BY %s LIMIT ? OFFSET ?' % _SORTS.get(sort or 'time',
                                                            _SORTS['time'])
        args2 = list(args) + [limit, offset]
        rows = c.execute(sql, args2).fetchall()
        items = [_photo_out(c, r) for r in rows]
        if mark:
            fm = store.photo_flag_map(c, [r['id'] for r in rows])
            for it in items:
                t = fm.get(it['id']) or []
                it['in_cand'] = 'cand' in t
                it['in_newprod'] = 'newprod' in t
        return {'total': total, 'items': items, 'flag': flag}
    finally:
        c.close()


@router.get('/api/photo-flags')
def api_photo_flags(ids: str = ''):
    """给一批照片打「待确认关联 / 新产品确认」角标（ids 逗号分隔）。

    🔴 **独立端点，不做成 /api/photos 的 mark 参数** —— 这两个集合要全库
    模糊匹配 + OCR 聚合，冷缓存实测 6.6 秒（2738 张照片），缓存命中 0.3 秒。
    挂在列表主查询上会把照片页首屏从 0.3s 拖成 6.6s，而且用户是「先看到照片
    再看到角标」更自然。所以：列表照常返回，前端渲染完再异步来补角标。
    （角标没到之前就是不显示 —— 不显示 ≠ 「没有」，别画成 0。）

    返回 {photo_id: ['cand'|'newprod', ...]}。
    """
    ids = [i for i in (ids or '').split(',') if i]
    if not ids or len(ids) > 500:
        return {}
    c = con()
    try:
        return store.photo_flag_map(c, ids)
    finally:
        c.close()


@router.get('/api/photos/linkstate')
def api_photo_linkstate(container_id: str = '', batch: str = '',
                        state: str = '', kind: str = '', usage: str = '',
                        q: str = '', unlinked: int = 0, invalid: str = 'hide',
                        pending: int = 0, todo: str = ''):
    """五档分组计数（全部 / 已关联 / 未关联 / 待确认关联 / 新产品确认）。

    选项卡徽章的数据源 —— 与 /api/photos 列表**共用 `_photo_where_sql`**，
    徽章数字与列表条数不会漂（各写一份 WHERE 必然漂一位）。
    ⚠️ 2026-10-14 起接收**完整筛选上下文**（state/kind/usage/q/unlinked/
    invalid/pending）：左侧树选了用途/分类后，徽章与「共 N 张」必须跟着
    收窄 —— 否则「树选了监装 3 张、统计还写全柜 1072」= 数字撒谎
    （老板实测反馈）。
    """
    c = con()
    try:
        return store.photo_flag_counts(c, container_id=container_id,
                                       batch_id=batch, state=state, kind=kind,
                                       usage=usage, q=q, unlinked=unlinked,
                                       invalid=invalid, pending=pending,
                                       todo=todo)
    finally:
        c.close()


@router.get('/api/photos/facets')
def api_photo_facets(state: str = '', kind: str = '', batch: str = '',
                     q: str = '', usage: str = '', container_id: str = '',
                     unlinked: int = 0, invalid: str = 'hide', todo: str = ''):
    """用途 / 分类分布计数（左侧树形筛选，2026-10-14 老板需求）。

    与 /api/photos 列表共用 photo_where_sql —— 树上的数字和点进去的条数
    同源，不会漂。交叉筛选：传 kind 时用途计数反映该分类，反之亦然。
    """
    c = con()
    try:
        return store.photo_facet_counts(c, state=state, kind=kind, batch=batch,
                                        q=q, usage=usage,
                                        container_id=container_id,
                                        unlinked=unlinked, invalid=invalid,
                                        todo=todo)
    finally:
        c.close()


@router.get('/api/photos/carton-groups')
def api_photos_carton_groups(container_id: str = '', state: str = '',
                             kind: str = '', usage: str = '', q: str = '',
                             unlinked: int = 0, invalid: str = 'hide',
                             pending: int = 0, limit: int = 30, offset: int = 0):
    """按箱号（carton_no）聚合的照片组（2026-10-14 老板需求：③按箱号分组看）。

    筛选口径与 /api/photos 完全一致（photo_where_sql 同源）；pending=1 时
    只聚合「监装细分待确认」集合 —— 树上选了待确认，箱号分组也只出待办。
    🔴 字面量端点，必须排在 /api/photos/{pid} 之前（路由顺序陷阱）。
    """
    c = con()
    try:
        extra = None
        if pending:
            if not container_id:
                return {'total': 0, 'items': []}
            extra = [r['photo_id'] for r in
                     store.supervision_pending_of(c, container_id)['items']]
        return store.photos_by_carton(
            c, container_id=container_id, state=state, kind=kind, usage=usage,
            q=q, unlinked=unlinked, invalid=invalid, extra_ids=extra,
            limit=limit, offset=offset)
    finally:
        c.close()


@router.get('/api/batches')
def api_batches(kind: str = 'photos', container_id: str = ''):
    """批次列表 + 每批次的照片/治理/关联进度。预检批次页的数据源。"""
    c = con()
    try:
        items = store.batches_stats(c, kind=kind or None)
        cid = (container_id or '').strip()
        if cid:
            items = [b for b in items if (b.get('container_id') or '') == cid]
        return {'items': items}
    finally:
        c.close()


@router.get('/api/photos/groups')
def api_photo_groups(state: str = '', kind: str = '', unlinked: int = 0,
                     batch: str = '', q: str = '', usage: str = '',
                     limit: int = 30, offset: int = 0, invalid: str = 'hide',
                     todo: str = ''):
    """按 (batch_id, group_idx) 聚合的照片组视图。

    筛选条件匹配到的照片 → 返回其所属组的全部照片。
    每组带分类分布、读到的编码、已关联产品等语义摘要。
    用于"分组聚类"视图：同货品连拍聚成一组，点开看整组。
    """
    c = con()
    try:
        return store.photo_groups(c, state=state, kind=kind, batch=batch,
                                  unlinked=unlinked, q=q, usage=usage,
                                  limit=limit, offset=offset, invalid=invalid,
                                  todo=todo)
    finally:
        c.close()


@router.post('/api/photos/regroup')
def api_regroup(batch_id: str = '', dry_run: bool = False, gap_sec: int = 0,
                max_per_group: int = 0):
    """按拍照时间重算照片分组（去掉旧口径的「满 12 张就切一组」）。

    一次连拍十几张是常态，旧口径（满 12 张就切）把一段连拍切得太碎。
    新口径：间隔 > gap_sec（默认 45 秒）才切；张数上限 30 只作安全阀
    （这批照片常是 0~2 秒一张的连续流，没上限会切出 400+ 张的巨型组）。

    只改 photos.group_idx：不动关联、不动文件、不重跑识别。
    dry_run=1 只统计不写库 —— 前端/CLI 都应该先试算再真跑。
    """
    c = con()
    try:
        return store.regroup_photos_by_time(
            c, batch_id=(batch_id or '').strip() or None,
            dry_run=dry_run, gap_sec=gap_sec or None,
            max_per_group=max_per_group or None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '重算分组失败：%s' % e)
    finally:
        c.close()


@router.post('/api/photos/kind')
@retry_write
def api_set_photo_kind(payload: dict):
    """人工改照片分类（2026-10-15 老板需求：模型识别不一定准，要能手改）。

    body: {photo_ids: [...], kind: 'label'|'packing_list'|'product'|
           'packaging'|'scene'|'unknown'}

    单张也走这里（photo_ids=[id]）—— 抽屉里的分类下拉与照片库的批量
    下拉共用同一个入口，改一处生效。
    人工选完之后 kind_conf 清空（那是模型的置信度，人拍的板不挂模型分数）。
    """
    ids = payload.get('photo_ids') or []
    if not ids:
        raise HTTPException(400, 'photo_ids 不能为空')
    kind = (payload.get('kind') or '').strip()
    try:
        n = store.set_photo_kinds(con(), ids, kind,
                                  by=payload.get('by') or 'web')
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True, 'updated': n, 'kind': kind or 'unknown'}


@router.post('/api/photos/{pid}/regovern')
def api_photo_regovern(pid: str, payload: dict = None):
    """改判即重治（2026-10-15 需求1：分类准确性保障）。

    人工在抽屉里改了分类 → 前端紧接着调这里：按**人工的 kind** 重跑
    读码链路（OCR token 匹配 + 视觉读码 + 精确命中自动关联），把「分类
    判错导致编码没识别」的图救回来。不重新分类 —— 人拍板的值是权威。
    同步执行（单张本地 OCR 1~3s / 视觉 API 2~5s），前端 toast 等结果。

    body: {mode: 'full'|'ocr'}（2026-10-19 老板要求：抽屉里拆成两个按钮）
      · full（缺省，兼容老调用）—— 完整链路，含视觉读码，花多模态额度
      · ocr  —— 只跑本地 OCR（**强制重跑**，先清旧 token），不花一分钱；
                视觉字段（codes/desc/model）原值保留
    """
    c = con()
    try:
        regen = ((payload or {}).get('mode') or 'full').strip().lower()
        if regen not in ('full', 'ocr'):
            raise HTTPException(400, 'mode 只支持 full / ocr')
        row = c.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
        if not row:
            raise HTTPException(404, '照片不存在')
        index = pipeline._build_index(c)
        out = pipeline.regovern_one(c, row, row['photo_kind'] or 'unknown',
                                    index, regen=regen)
        c.commit()
        return {'ok': True, 'kind': out['kind'], 'tokens_n': out['tokens_n'],
                'hits_n': len(out['hits']), 'links_added': out['links_added'],
                'codes': out['vision_codes'], 'ocr_ok': out['ocr_ok'],
                'mode': regen}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '重新识别失败：%s' % str(e)[:200])
    finally:
        c.close()


@router.post('/api/photos/invalid')
@retry_write
def api_set_photos_invalid(payload: dict):
    """批量标记/撤销「无效照片」（2026-10-12 老板需求）。

    body: {photo_ids: [...], invalid: true|false, by: 'web'}

    无效 = 拍糊/误拍/与作业无关。标记后默认从照片列表、待确认关联、
    监装选图等工作队列排除（「仅看无效」筛选可查看与撤销）。
    只写标记，永不删文件 —— 原始照片是取证证据。
    """
    ids = payload.get('photo_ids') or []
    if not ids:
        raise HTTPException(400, 'photo_ids 不能为空')
    if len(ids) > 500:
        raise HTTPException(400, '一次最多 500 张（先分批）')
    c = con()
    try:
        n = store.set_photos_invalid(c, ids, bool(payload.get('invalid')),
                                     by=payload.get('by', 'web'))
        return {'ok': True, 'updated': n,
                'invalid': bool(payload.get('invalid'))}
    finally:
        c.close()


@router.post('/api/photos/ignore')
@retry_write
def api_set_photos_ignored(payload: dict):
    """批量标记/恢复「本次忽略」（2026-10-18 老板需求）。

    body: {photo_ids: [...], ignored: true|false, by: 'web'}

    忽略 = 这张照片本次不关联（新产品先不入库）—— 退出待关联/候选/
    新产品确认等一切关联队列；「已忽略」选项卡可查看与恢复。
    与无效的区别：照片本身没问题，只是本次不处理；数据保留，
    后续柜清单导入同一编码时 relink 仍可能自动关联上。
    """
    ids = payload.get('photo_ids') or []
    if not ids:
        raise HTTPException(400, 'photo_ids 不能为空')
    if len(ids) > 500:
        raise HTTPException(400, '一次最多 500 张（先分批）')
    c = con()
    try:
        n = store.set_photo_ignored(c, ids, bool(payload.get('ignored')),
                                    by=payload.get('by', 'web'))
        return {'ok': True, 'updated': n,
                'ignored': bool(payload.get('ignored'))}
    finally:
        c.close()


@router.patch('/api/photos/{pid}/usage')
@retry_write
def api_set_photo_usage(pid: str, payload: dict):
    """设置单张照片的用途分类（监装/预检/空=清除）。"""
    c = con()
    try:
        n = store.set_photo_usage(c, pid, payload.get('usage', ''), by=payload.get('by', 'user'))
        if n == 0:
            raise HTTPException(404, '照片不存在')
        return {'ok': True, 'usage': payload.get('usage', '') or None}
    finally:
        c.close()


@router.post('/api/photos/supervision-tag')
@retry_write
def api_set_supervision_tag(payload: dict):
    """给监装照片打语义标签（空柜/柜侧/封条/锁门/卡车头/装柜过程/其他）。

    body: {photo_ids: [...], tag: 'container_seal'}（空 tag = 清除标注）

    ⚠️ 只写元数据，不碰像素 —— 方向矫正/缩放/裁剪是**报告生成**的事。
    人工真要修图走标准图（standard_images），报告优先用标准图。
    """
    ids = payload.get('photo_ids') or ([payload['photo_id']] if payload.get('photo_id') else [])
    c = con()
    try:
        n = store.set_supervision_tag(c, ids, payload.get('tag', ''),
                                      by=payload.get('by', 'user'))
        return {'ok': True, 'updated': n,
                'tag': (payload.get('tag') or '').strip() or None}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post('/api/photos/supervision-tag/accept-ai')
def api_accept_sup_tag(payload: dict):
    """采用大模型给的监装细分建议（等价于人工点了那个下拉框）。

    body: {photo_id} 或 {photo_ids:[...]}（批量「全部采用」用同一个端点）

    ⚠️ 建议值在 store 层校验枚举 —— 模型自造的值/历史脏数据会报 400，
    绝不静默写进报告用的 supervision_tag。
    """
    ids = payload.get('photo_ids') or ([payload['photo_id']] if payload.get('photo_id') else [])
    c = con()
    try:
        done, skipped, why = [], [], ''
        for pid in ids:
            try:
                if store.accept_sup_tag_suggestion(c, pid):
                    done.append(pid)
                else:
                    skipped.append(pid)
            except ValueError as e:
                skipped.append(pid)
                why = why or str(e)      # 记第一条原因，别把「为什么不行」吞掉
        if not done and skipped:
            # 全部都没采用成 → 要说清「为什么不行」，不能回 ok=0 了事
            raise HTTPException(400, why or '选中的照片都没有可用的细分建议')
        return {'ok': True, 'accepted': len(done), 'skipped': len(skipped),
                'accepted_ids': done, 'skipped_ids': skipped}
    finally:
        c.close()


@router.get('/api/photos/supervision-tags')
def api_supervision_tags(batch: str = ''):
    """监装标签字典 + 各标签计数 + 待确认建议数（照片页/柜详情页提示）。"""
    c = con()
    try:
        return {'tags': schema.SUPERVISION_TAGS,
                'counts': store.batch_supervision_tags(c, batch_id=batch or ''),
                'pending_ai': store.sup_tag_pending_count(c, batch_id=batch or '')}
    finally:
        c.close()


@router.get('/api/photos/auto-invalid')
def api_auto_invalid(container_id: str = ''):
    """清单/包装照清理名单（2026-10-15 需求2）：系统识别、用户确认。

    未关联的 packing_list / packaging 照片 —— 老板口径「用户都当无效图」。
    只出名单不动数据，确认走既有的 POST /api/photos/invalid。
    🔴 字面量端点，必须排在 /api/photos/{pid} 之前（路由顺序陷阱）。
    """
    if not container_id:
        return {'total': 0, 'linked_n': 0, 'ids': [], 'preview': []}
    c = con()
    try:
        d = store.auto_invalid_candidates(c, container_id)
        rows = []
        if d['ids']:
            qs = ','.join('?' * len(d['ids'][:60]))
            rows = [ _photo_out(c, r) for r in c.execute(
                'SELECT p.* FROM photos p WHERE p.id IN (%s)' % qs,
                d['ids'][:60])]
        d['preview'] = rows
        return d
    finally:
        c.close()


@router.get('/api/photos/dups')
def api_photo_dups(container_id: str = '', backfill: int = 1):
    """相似重复照片分组（2026-10-15 需求3）：dHash 指纹近邻。

    缺指纹的先补算一批（backfill=1 时最多 600 张，防止单请求卡死）；
    remaining>0 表示还没算完，前端提示稍后再开一次。
    🔴 分组行是裸 SQL —— thumb/view 必须在这里补上，否则模态
       src='undefined' 全裂图（2026-10-15 老板实测）。
    🔴 字面量端点，必须排在 /api/photos/{pid} 之前（路由顺序陷阱）。
    """
    if not container_id:
        return {'groups': [], 'total_groups': 0, 'remaining': 0}
    c = con()
    try:
        remaining = 0
        if backfill:
            remaining = store.backfill_phash(c, container_id, limit=600)
        groups = store.dup_groups(c, container_id)
        for g in groups:
            g['keep'] = _photo_out(c, g['keep'])
            g['others'] = [_photo_out(c, o) for o in g['others']]
        return {'groups': groups[:60], 'total_groups': len(groups),
                'remaining': remaining}
    finally:
        c.close()


# 🔴 这条**必须**排在上面那三个字面量路由之后 —— FastAPI 按注册顺序匹配，
#    '/api/photos/{pid}' 会把 'supervision-tags' 当成 pid 吞掉
#    （表现为：端点写对了、路由检查也绿，但 GET 返回的是照片详情的形状）。
#    checks/routes.py 只校验「有没有这个端点」，抓不到这种顺序错位。
@router.get('/api/photos/{pid}')
def api_photo(pid: str):
    c = con()
    try:
        r = c.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
        if not r:
            raise HTTPException(404, '照片不存在')
        out = _photo_out(c, r)
        out['tokens'] = [dict(t) for t in c.execute(
            'SELECT raw_text,confidence FROM ocr_tokens WHERE photo_id=?'
            ' ORDER BY confidence DESC LIMIT 60', (pid,))]
        out['links'] = [dict(l) for l in c.execute(
            'SELECT l.*, p.name FROM links l LEFT JOIN products p ON p.code_norm=l.code_norm'
            ' WHERE l.photo_id=?', (pid,))]
        # 同组其他照片：同一批次(batch_id)内 group_idx 相同 = 同一次连拍
        # ⚠️ 必须同时限定 batch_id：group_idx 是每次导入从 0 开始的局部索引，
        #    不限定批次会导致不同日期/批次的照片被误判为同组。
        gid = r['group_idx']
        bid = r['batch_id']
        if gid is not None and str(gid) != '' and bid:
            gr = c.execute(
                'SELECT * FROM photos WHERE batch_id=? AND group_idx=? AND id!=? AND is_dup=0'
                ' ORDER BY taken_at', (bid, gid, pid)).fetchall()
            out['group_photos'] = [_photo_out(c, x) for x in gr]
        else:
            out['group_photos'] = []
        return out
    finally:
        c.close()


@router.get('/api/photos/{pid}/panoramas')
def api_photo_panoramas(pid: str):
    """「同组连拍 + 可能的全景图」**合并候选**（2026-10-18 老板要求）。

    老板原话：「同组连拍照片可以合并至上方的『可能的全景图』，保留一个就可以，
    规则进行融合。」—— 两块本来回答同一个问题（这几张是不是同一件货），
    分两块等于让老板对同一件事判断两次。

    合并口径（一块列表，按来源打标签，**同组排前**）：
      · group —— 同 batch_id + 同 group_idx 的同一次连拍（强语义，导入时聚类得出）
      · pano  —— product_panorama_candidates：已关联标签近景的**顺序邻居**
                 （微信图无 EXIF，只能靠 import_seq 邻近，故叫「可能」）
    去重按 photo_id；group 来源优先保留（它更确定），pano 补进来的带 gap_txt/used_by。
    **绝不自动关联**，一律人工确认。

    另附 `siblings`：**同产品编码的其他照片**，作为辅助判断参考 —— 老板看到
    同编码的其它图，才能判断"这件货长什么样"。
    """
    c = con()
    try:
        row = c.execute(
            'SELECT id, batch_id, group_idx FROM photos WHERE id=?', (pid,)).fetchone()
        if not row:
            return {'items': [], 'siblings': []}
        codes = [r['code_norm'] for r in c.execute(
            'SELECT code_norm FROM links WHERE photo_id=?', (pid,))]
        rej = store.rejected_pairs(c)
        items, seen = [], set()

        def _add(it, source):
            p = it.get('photo_id')
            if not p or p == pid or p in seen:
                return
            it = dict(it)
            it['source'] = source
            seen.add(p)
            items.append(it)

        # ① 同组连拍：同批次同 group_idx = 同一次连拍（强语义，先入池）
        gid, bid = row['group_idx'], row['batch_id']
        if gid is not None and str(gid) != '' and bid:
            gr = c.execute(
                'SELECT p.* FROM photos p WHERE p.batch_id=? AND p.group_idx=? '
                'AND p.id!=? AND IFNULL(p.is_dup,0)=0 AND IFNULL(p.is_invalid,0)=0 '
                'ORDER BY p.taken_at, p.import_seq', (bid, gid, pid)).fetchall()
            for i, x in enumerate(gr):
                _why = store.burst_reason(row, x, store.burst_gap_sec(row, x))
                _add({'photo_id': x['id'], 'file': x['file'],
                      'path': x['path'],
                      'taken_at': x['taken_at'], 'photo_kind': x['photo_kind'],
                      # carton_no 必须带上：前端/测试要靠它确认「推荐的还是这个箱」
                      # —— 同组条目原先没有这个字段，一校验就被当成跨箱。
                      'carton_no': x['carton_no'],
                      'reason': _why or '同一次连拍',
                      'thumb': '/thumb/%s' % x['id'], 'full': '/img/%s' % x['id'],
                      'same_group': True, 'group_idx': gid,
                      'used_by': c.execute(
                          'SELECT COUNT(DISTINCT code_norm) FROM links '
                          'WHERE photo_id=?', (x['id'],)).fetchone()[0],
                      'seq': i}, 'group')

        # ② 可能的全景图：同文件夹 + 同一时间段内的邻居（多个编码合并去重）
        #
        # ⏱ 口径全部委托给 store.within_burst（**唯一真源**），这里不再自己
        #    算时间窗 —— 2026-10-19 事故：这里原来写
        #    `win = 300 if time_src=='exif' else 1800`，把 App 采集命名
        #    （`20260927_151257_00896.jpg`，时间戳就是快门时刻）当成"微信那种
        #    不可信时间"放宽到 30 分钟。实测候选里 61% 相隔 5 分钟以上、
        #    36% 推荐到了别的箱号 —— 老板反馈「推荐不是很准」就是这么来的。
        #
        #    现在两道闸：① 同一个文件夹（箱号目录）② 时间窗按文件名形态分档。
        #    store 侧已按「已关联的那张照」筛过一次，这里再按**当前这张**筛一次
        #    （同一编码可能在两个箱里都有，两个方向都要卡）。
        base_row = c.execute('SELECT * FROM photos WHERE id=?', (pid,)).fetchone()
        for cn in codes:
            # anchor=当前这张：store 内部**先按它筛再截断**，否则 k 条名额会被
            # 别的箱号的候选占满（同一编码常常在多个箱里都有已关联照）。
            for s in store.product_panorama_candidates(c, cn, k=4,
                                                       anchor=base_row):
                if (cn, s['photo_id']) in rej:
                    continue
                s = dict(s)
                s['code'] = cn            # 前端「确认为同一产品」直接用
                _add(s, 'pano')

        # 同组在前；组内按拍摄序，邻域按原打分。⚠️ 微信来源一组实测平均 22.9 张
        # —— 整组甩出来不是建议是负担（与 pano 引擎同一条教训），同组最多 8 张。
        GROUP_MAX = 8
        g_n = 0
        items.sort(key=lambda x: (0 if x['source'] == 'group' else 1,
                                  x.get('seq') if x['source'] == 'group' else 0,
                                  -int(x.get('score') or 0), str(x.get('taken_at') or '')))
        kept = []
        for it in items:
            if it['source'] == 'group':
                if g_n >= GROUP_MAX:
                    continue
                g_n += 1
            kept.append(it)
        for it in kept:
            it.pop('seq', None)

        # ③ 同产品编码的其他照片（辅助判断参考）
        siblings = []
        if codes:
            qs = ','.join('?' * len(codes))
            rows = c.execute(
                'SELECT DISTINCT p.id, p.file, p.taken_at, p.photo_kind, p.time_src '
                'FROM links l JOIN photos p ON p.id=l.photo_id '
                'WHERE l.code_norm IN (%s) AND p.id!=? AND IFNULL(p.is_dup,0)=0 '
                'AND IFNULL(p.is_invalid,0)=0 '
                'ORDER BY p.taken_at LIMIT 36' % qs,
                tuple(codes) + (pid,)).fetchall()
            siblings = [{'photo_id': x['id'], 'file': x['file'],
                         'taken_at': x['taken_at'], 'photo_kind': x['photo_kind'],
                         'time_src': x['time_src'],
                         'thumb': '/thumb/%s' % x['id'],
                         'full': '/img/%s' % x['id']} for x in rows]
        return {'items': kept, 'siblings': siblings}
    finally:
        c.close()


@router.post('/api/batches/{bid}/usage')
def api_set_batch_usage(bid: str, payload: dict):
    """批量设置一个照片批次下所有照片的用途分类。"""
    c = con()
    try:
        n = store.set_batch_usage(c, bid, payload.get('usage', ''), by=payload.get('by', 'user'))
        return {'ok': True, 'updated': n, 'usage': payload.get('usage', '') or None}
    finally:
        c.close()

# 缩略图可被浏览器长期缓存：30 天（理由与失效场景见 thumb() 的注释）
_THUMB_HEADERS = {'Cache-Control': 'public, max-age=2592000'}
# 预览图同理：key 是 (photo id, 长边)，内容由原图唯一确定
_VIEW_HEADERS = {'Cache-Control': 'public, max-age=2592000'}


def _placeholder_svg(text='源文件缺失'):
    """源文件不在磁盘时的占位图（移动硬盘没挂载/路径迁移的现场常态）。

    返回 500/404 的话页面上全是裂图图标，用户不知道发生了什么；
    一张写着原因的灰底 SVG 至少把「文件不在了」说出口。
    """
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="360" height="270">'
           '<rect width="100%" height="100%" fill="#e8e6e1"/>'
           '<text x="50%" y="46%" text-anchor="middle" font-size="16" '
           'fill="#8a877f" font-family="sans-serif">' + text + '</text>'
           '<text x="50%" y="58%" text-anchor="middle" font-size="11" '
           'fill="#b0ada5" font-family="sans-serif">'
           '请检查照片源盘是否已挂载</text></svg>')
    return Response(content=svg, media_type='image/svg+xml',
                    headers={'Cache-Control': 'no-store'})


@router.get('/thumb/{pid}')
def thumb(pid: str):
    """缩略图 —— 首次生成后落盘缓存。原图 3072x4096，不缓存必卡。

    2026-10-09 性能两处：
      1. `Image.draft()` 让解码器直接按目标尺寸缩放（实测 54~72ms → 39~55ms，
         1.3~1.4x）。注意这不是数量级提升——真正的救星本来就是落盘缓存。
      2. 给响应加 Cache-Control。此前这里什么都不设（`server.py` 的 no-store
         中间件只管 `/static/`），于是**每翻回一页都要重拉 60 张图**。
         key 是 photo id、内容由原图唯一确定，长期可缓存。
         ⚠️ 失效场景：原图被替换成另一张且照片 id 不变（本系统中不会发生，
         照片是取证原件、导入后 id 即固定）。真要强制刷新，删掉 thumbs/ 即可。
    2026-10-15：源文件不在磁盘 → 返回占位 SVG（不再 404/500 裂图满屏）。
    """
    tp = os.path.join(THUMB_DIR, '%s.jpg' % pid)
    if os.path.exists(tp):
        return FileResponse(tp, media_type='image/jpeg', headers=_THUMB_HEADERS)
    c = con()
    try:
        r = c.execute('SELECT path FROM photos WHERE id=?', (pid,)).fetchone()
        full = store.resolve_photo_path(c, pid, r['path']) if r else None
    finally:
        c.close()
    if not r or not full or not os.path.exists(full):
        return _placeholder_svg()
    try:
        from PIL import Image
        im = Image.open(full)
        # draft：让 JPEG 解码器按 1/2^k 直接降采样到够用的量级，再精确缩放到目标。
        # 不加它时，这里会先把 12MP 的原图**完整解码**再缩小 —— 那部分开销全浪费了。
        im.draft('RGB', (360, 360))
        im.thumbnail((360, 360))
        if im.mode != 'RGB':
            im = im.convert('RGB')
        im.save(tp, 'JPEG', quality=72)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '缩略图生成失败：%s' % e)
    return FileResponse(tp, media_type='image/jpeg', headers=_THUMB_HEADERS)


@router.get('/img/{pid}')
def img(pid: str, w: int = 0):
    """原图。带 ?w=<长边> 时返回**预览图**（缩放版，落盘缓存，快一个数量级）。

    🔴 为什么必须有 ?w：抽屉/详情页左右切换时原本直接取原图，真实库单张
    3.8~21MB，冷加载实测 4.47s（同一张的 /thumb 只要 0.02s）——
    「点下一张卡一下」就是这么来的。预览图长边 1600、约 200~400KB。
    看细节（点击放大）仍走不带 w 的原图，两者分工不同，不能合并。
    """
    c = con()
    try:
        r = c.execute('SELECT path FROM photos WHERE id=?', (pid,)).fetchone()
        full = store.resolve_photo_path(c, pid, r['path']) if r else None
    finally:
        c.close()
    if not r or not full or not os.path.exists(full):
        raise HTTPException(404, '文件不在磁盘上')
    if w and w > 0:
        return _scaled(full, pid, min(int(w), 4000))
    # 原图同样可长期缓存：照片是取证原件、导入后 id 即固定、内容不会变
    return FileResponse(full, media_type='image/jpeg',
                        headers={'Cache-Control': 'public, max-age=2592000'})


def _scaled(src_path, pid, long_edge):
    """生成（或复用）一张长边受限的预览图。与 thumb() 同思路：落盘缓存是主力。

    2026-10-17：去掉 optimize=True —— 实测编码 256ms→63ms（省 20%），
    体积只差 1%（442→447KB）。预览图是「快速看」用的，不为 1% 多耗 4 倍编码。
    """
    vdir = VIEW_DIR
    os.makedirs(vdir, exist_ok=True)
    vp = os.path.join(vdir, '%s_%d.jpg' % (pid, long_edge))
    if os.path.exists(vp):
        return FileResponse(vp, media_type='image/jpeg', headers=_VIEW_HEADERS)
    try:
        from PIL import Image
        im = Image.open(src_path)
        im.draft('RGB', (long_edge, long_edge))
        im.thumbnail((long_edge, long_edge))
        if im.mode != 'RGB':
            im = im.convert('RGB')
        im.save(vp, 'JPEG', quality=82)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, '预览图生成失败：%s' % e)
    return FileResponse(vp, media_type='image/jpeg', headers=_VIEW_HEADERS)

# ═══════════════════════════════════════════════════════════════════
# 目录浏览（供前端"选择目录"弹窗使用）
# ═══════════════════════════════════════════════════════════════════

@router.get('/api/browse')
def api_browse(path: str = ''):
    """浏览本地目录，返回子目录列表。path 为空时返回盘符列表（Windows）。"""
    if not path or path == '/':
        # Windows：列出可用盘符
        items = []
        for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            d = letter + ':\\'
            try:
                if os.path.isdir(d):
                    items.append({'name': d, 'path': d, 'is_dir': True})
            except Exception:
                pass
        return {'current': '', 'parent': None, 'items': items}
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise HTTPException(404, '目录不存在：' + path)
    items = []
    try:
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            try:
                if os.path.isdir(full) and not name.startswith('.') and not name.startswith('$'):
                    items.append({'name': name, 'path': full, 'is_dir': True})
            except Exception:
                pass
    except PermissionError:
        pass
    parent = os.path.dirname(path)
    if parent == path:
        parent = None  # 已到盘符根目录
    return {'current': path, 'parent': parent, 'items': items}
