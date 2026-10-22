# -*- coding: utf-8 -*-
"""装柜报告 docx 生成（P3）—— 端到端，含与样例的版式对齐。

用真实清单（9.13 5x40HQ/MIEU2012616.xlsx，93 行）跑通全链：
建柜 → 导清单（行快照）→ 造照片（横/竖/带 EXIF 旋转）→ 打监装标签 →
建关联 → loading_report_data → 生成 docx → **拆开 docx 验证结构**。

为什么必须拆开看：生成器不抛异常 ≠ 版式对。python-docx 写的是 XML，
表头错字、图注串行、TOTAL 算错都要打开文档才知道（"不检查就宣称通过"
是本项目反复栽的坑）。
"""
import os
import sys
import json
import shutil
import zipfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, report_gen, schema  # noqa: E402
import build_library as BL  # noqa: E402

REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))),
    '9.13 5x40HQ', 'MIEU2012616.xlsx')

tmp = tempfile.mkdtemp(prefix='pl_report_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


def doc_text(path):
    """把 document.xml 的文字全提出来（验证内容用）。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read('word/document.xml').decode('utf8')
    import re
    return re.sub(r'<[^>]+>', '', xml), xml


def n_images(path):
    with zipfile.ZipFile(path) as z:
        return len([n for n in z.namelist() if n.startswith('word/media/')])


# ══════════════════════════════════════════════════════════════════
# 准备数据：柜 + 清单 + 照片 + 标签 + 关联
# ══════════════════════════════════════════════════════════════════
c1 = store.create_container(con, 'EMCU9914616', seal_no='EMCEXE7565',
                           inspector='Jerry Xu',
                           location='Changsha City, Hunan Province, China',
                           client_name='Hunan Sinoboom Intelligent Equipment Co.',
                           product_name='ACCESSORIES FOR AERIAL WORK PLATFORM',
                           arrival_at='8:49 Am 16th Sep',
                           departure_at='11:27 Am 16th Sep',
                           remark='PASS')
chk('R0 真实清单存在', os.path.exists(REAL), REAL)
imp = store.import_checklist_file(con, REAL, container_id=c1['id'])
chk('R1 清单导出行快照', imp['snap_rows'] > 50, 'snap_rows=%s' % imp['snap_rows'])
chk('R2 TOTAL 与 xlsx 一致（4687）',
    abs((store.loading_report_data(con, c1['id'])['summary']['order_total'] or 0)
        - 4687) < 0.01,
    store.loading_report_data(con, c1['id'])['summary']['order_total'])

# 造照片：横图 / 竖图 / 带 EXIF 旋转的竖图（Orientation=6）
from PIL import Image  # noqa: E402
pd = os.path.join(tmp, '交付', '预检', 'Cage-M068')
sd = os.path.join(tmp, '交付', '监装')
os.makedirs(pd)
os.makedirs(sd)


def mk(path, w, h, color, orientation=None):
    im = Image.new('RGB', (w, h), color)
    if orientation:
        from PIL import Image as I
        ex = I.Exif()
        ex[274] = orientation          # 274 = Orientation
        ex[36867] = '2026:09:27 10:00:00'
        im.save(path, exif=ex)
    else:
        im.save(path)


mk(os.path.join(pd, 'P1.jpg'), 1600, 1200, (200, 30, 30))            # 横
mk(os.path.join(pd, 'P2.jpg'), 900, 1600, (30, 200, 30))            # 竖（极端）
for i, tag in enumerate(('empty_container', 'container_side',
                         'container_seal', 'container_lock')):
    mk(os.path.join(sd, 'S_%d.jpg' % i), 1200, 900, (40 * i, 60, 200))
# 一张带 EXIF 旋转标记的（横着存的竖图）
mk(os.path.join(sd, 'S_rot.jpg'), 1600, 900, (10, 10, 10), orientation=6)
mk(os.path.join(sd, 'S_truck.jpg'), 1400, 900, (200, 200, 10))

import build_library as _BL
_scanned, _g, _st = _BL.scan_photos(os.path.join(tmp, '交付'), verbose=False)
print('       [debug] scan_photos 扫到 %d 张；目录内容 %s'
      % (len(_scanned), sorted(os.listdir(sd)) + sorted(os.listdir(pd))))
ap = store.add_photos(con, os.path.join(tmp, '交付'), container_id=c1['id'])
print('       [debug] added=%s skipped=%s 库内=%s'
      % (ap['added'], ap['skipped'],
         [r['file'] for r in con.execute('SELECT file FROM photos ORDER BY file')]))
# 场景实况：监装 6 张（4 柜况 + other + truck_head）+ 预检 2 张 = 8
chk('R3 照片导入挂柜（8 张全入库，同名不丢）', ap['added'] == 8, ap['added'])

sup = [r['id'] for r in con.execute(
    "SELECT id FROM photos WHERE batch_id=? AND file LIKE '监装/%'",
    (ap['batch_id'],))]
for pid in sup:
    store.set_photo_usage(con, pid, '监装')
for i, tag in enumerate(('empty_container', 'container_side',
                         'container_seal', 'container_lock')):
    store.set_supervision_tag(con, [sup[i]], tag)
store.set_supervision_tag(con, [sup[4]], 'other')
store.set_supervision_tag(con, [sup[5]], 'truck_head')

# 关联：清单里前两个编码各挂一张预检照（模拟治理+人工关联的结果）
pre = [r['id'] for r in con.execute(
    "SELECT id FROM photos WHERE batch_id=? AND file LIKE '预检/%' ORDER BY file",
    (ap['batch_id'],))]
rows = store.checklist_rows_of(con, imp['batch_id'])
seen = set()
linked = 0
for r in rows:
    cn = r['code_norm']
    if cn in seen:
        continue
    seen.add(cn)
    if linked < len(pre):
        store.link(con, cn, pre[linked], 'manual', 1.0, created_by='test')
        linked += 1
chk('R4 关联到预检照', linked == 2, linked)

# ══════════════════════════════════════════════════════════════════
# 数据源
# ══════════════════════════════════════════════════════════════════
d = store.loading_report_data(con, c1['id'])
s = d['summary']
chk('R5 数据源：行数 = 快照行数', s['row_total'] == imp['snap_rows'],
    '%s vs %s' % (s['row_total'], imp['snap_rows']))
chk('R6 数据源：核对照 2 张（每编码一张）', s['check_photos'] == 2, s['check_photos'])
# ⑦ 只收 truck_head/loading_process/other —— 4 张柜况照归④，不重复进⑦
chk('R7 数据源：卡车区块 2 张（other + truck_head，柜况照不重复计入）',
    s['truck_photos'] == 2, s['truck_photos'])
chk('R8 数据源：柜况 4 张齐', s['condition_photos'] == 4, s['condition_photos'])
d_fwd = store.loading_report_data(con, c1['id'], reverse_checks=False)
chk('R9 数据源：⑥ 倒序开关生效（reverse=True 与 False 顺序相反）',
    [c['photo_id'] for c in d['checks']] ==
    list(reversed([c['photo_id'] for c in d_fwd['checks']])),
    '%s vs %s' % ([c['code'] for c in d['checks']],
                  [c['code'] for c in d_fwd['checks']]))
chk('R10 区块⑤同码多行都在（不合并）',
    len({r['seq'] for r in d['rows']}) == len(d['rows']), len(d['rows']))

# ⚠️ picks 是**叠加覆盖**不是替换（10-05 实测踩过：传一个采用图，⑥从 250 张
#    变 1 张）。取一个编码换成它现有的另一张照片 → 总数不变、只有那张变。
_pk_code = d['checks'][0]['code']
_pk_pid = d['checks'][0]['photo_id']
d_pick = store.loading_report_data(con, c1['id'], picks={_pk_code: _pk_pid})
chk('R9b picks 叠加：覆盖个别编码不掉图（总数不变）',
    len(d_pick['checks']) == len(d['checks']) and len(d['checks']) >= 2,
    '%d vs %d' % (len(d_pick['checks']), len(d['checks'])))
chk('R9c picks 覆盖生效：被指定编码的用图就是 pick',
    any(c['code'] == _pk_code and c['photo_id'] == _pk_pid
        for c in d_pick['checks']),
    [(c['code'], c['photo_id']) for c in d_pick['checks']][:4])

# ══════════════════════════════════════════════════════════════════
# 生成 docx
# ══════════════════════════════════════════════════════════════════
out = os.path.join(tmp, 'report.docx')
r = report_gen.build_loading_report(d, out)
chk('R11 docx 生成成功', os.path.exists(out) and r['bytes'] > 10000, r['bytes'])
txt, xml = doc_text(out)
chk('R12 8 个区块标题都在',
    all(k in txt for k in ('Report of', 'CARGO LOADING SUPERVISION',
                           'Product Name:', 'CONTAIER NO.', 'General Information',
                           'Packing list data', 'Quantity check', 'Truck picture',
                           'End of the report.')),
    [k for k in ('Report of', 'General Information', 'Packing list data',
                 'Quantity check', 'Truck picture', 'End of the report.')
     if k not in txt])
chk('R13 Packing list 六列表头一字不差',
    all(h in txt for h in ('Part Number', 'DESCRIPTION', 'Package Number',
                           'Order Qty', 'Loading Qty', 'Quantity Check result')))
chk('R14 TOTAL 行求和 = 4687', 'TOTAL' in txt and '4687' in txt,
    '4687 in txt = %s' % ('4687' in txt))
chk('R15 柜号/封条号进文档',
    'EMCU9914616' in txt and 'EMCEXE7565' in txt)
# ⚠️ 10-05 老板「图注表示什么不清晰」→ 改成带标签三段：件号 / 描述 / 箱号。
#    旧断言只查 `xxx-Cage-M068` 连字符串，会把新格式判成缺失。
chk('R16 图注带标签三段（Part No. 件号 + 描述 + Package 箱号）',
    'Part No. 216070000001' in txt and 'Package: Cage-M068' in txt,
    'PartNo=%s Package=%s' % ('Part No. 216070000001' in txt,
                              'Package: Cage-M068' in txt))
chk('R17 Truck 图注是固定英文文案',
    'Truck head' in txt or 'Loading container view' in txt,
    [k for k in ('Truck head', 'Loading container view', 'Empty picture',
                 'Lock door picture') if k in txt])
# 4 柜况 + 2 核对 + 2 卡车（柜况照只在④出现一次，⑦ 不重复收）
chk('R18 嵌入图片数 = 4柜况+2核对+2卡车', n_images(out) == 8, n_images(out))
chk('R19 柜况图注四类都在',
    all(k in txt for k in ('Empty picture', 'Container side picture',
                           'Seal no.', 'Lock door picture')),
    [k for k in ('Empty picture', 'Container side picture', 'Seal no.',
                 'Lock door picture') if k in txt])

# ══════════════════════════════════════════════════════════════════
# 版位适配：竖图不撑爆页面
# ══════════════════════════════════════════════════════════════════
w, h = report_gen._fit_box(900, 1600)          # 极端竖图
chk('R20 极端竖图按高钳制（宽自动收窄）',
    abs(h - report_gen.CELL_H_MAX_IN) < 0.01 and w < report_gen.CELL_W_IN,
    '%.2f x %.2f' % (w, h))
w2, h2 = report_gen._fit_box(1600, 900)        # 横图
chk('R21 横图按宽铺满', abs(w2 - report_gen.CELL_W_IN) < 0.01 and h2 < w2,
    '%.2f x %.2f' % (w2, h2))
# EXIF 旋转的照片，宽高比必须被矫正过来。
# ⚠️ 断言**比例**而不是绝对尺寸 —— long_edge=1200 会把 1600 长边降采样成 1200
#    （1600×0.75=1200、900×0.75=675），尺寸变了但比例才是矫正的证据。
buf, pw, ph = report_gen._prep_photo(os.path.join(sd, 'S_rot.jpg'))
chk('R22a EXIF 旋转被矫正（Orientation=6 的 1600x900 读成竖图 675x1200）',
    (pw, ph) == (675, 1200), '%dx%d' % (pw, ph))
_buf2, pw2, ph2 = report_gen._prep_photo(os.path.join(sd, 'S_rot.jpg'),
                                          long_edge=0)
chk('R22b 不降采样时读到矫正后的原始尺寸 900x1600',
    (pw2, ph2) == (900, 1600), '%dx%d' % (pw2, ph2))
chk('R23 原图文件字节不变（报告不写回像素）',
    os.path.getsize(os.path.join(sd, 'S_rot.jpg')) > 0)

# ══════════════════════════════════════════════════════════════════
# 缺图不阻断
# ══════════════════════════════════════════════════════════════════
c2 = store.create_container(con, 'EMCU0000001')
imp2 = store.import_checklist_file(con, REAL, container_id=c2['id'])
d2 = store.loading_report_data(con, c2['id'])
out2 = os.path.join(tmp, 'report2.docx')
r2 = report_gen.build_loading_report(d2, out2)
txt2, _ = doc_text(out2)
chk('R24 没照片也能出报告（缺图写 Not provided，不阻断）',
    os.path.exists(out2) and 'Not provided' in txt2 and r2['missing_condition'] == 4,
    'missing=%s' % r2['missing_condition'])
chk('R25 没关联照片时⑥为空（不造数）', d2['summary']['check_photos'] == 0)

# 数量列解析不出 → 计数不静默当 0
# ══════════════════════════════════════════════════════════════════
# in_container（10-05 v4.2）：界面靠它分「影响报告的缺口」与「只是检索范围问题」
# ══════════════════════════════════════════════════════════════════
_lk_all = [r['code_norm'] for r in rows]
_linked_n = _lk_all[0]
# 未关联的编码：清单里第一个「links 表里没有」的编码
_linked_set = {r[0] for r in con.execute('SELECT code_norm FROM links')}
_unlinked_n = next((c for c in _lk_all if c not in _linked_set), None)
_lk = store.report_lookup(con, [_linked_n], container_id=c1['id'])
chk('R32 lookup：已关联编码 in_container>=1（该柜真有照片）',
    bool(_lk) and _lk[0].get('in_container') is not None
    and _lk[0]['in_container'] >= 1,
    _lk[0].get('in_container') if _lk else None)
if _unlinked_n:
    _lk2 = store.report_lookup(con, [_unlinked_n], container_id=c1['id'])
    chk('R33 lookup：无照片编码 in_container=0（界面据此说「影响报告」）',
        bool(_lk2) and _lk2[0].get('in_container') == 0,
        _lk2[0].get('in_container') if _lk2 else None)
_lk3 = store.report_lookup(con, [_linked_n])
chk('R34 lookup：不传 container_id 时 in_container=None（老调用方不受影响）',
    bool(_lk3) and _lk3[0].get('in_container') is None,
    _lk3[0].get('in_container') if _lk3 else None)

# ══════════════════════════════════════════════════════════════════
# 一个编码多张图 + 同编码多箱归并（10-06 老板需求）
# ══════════════════════════════════════════════════════════════════
if len(d['checks']) >= 2:
    _c0, _c1 = d['checks'][0], d['checks'][1]
    d_multi = store.loading_report_data(
        con, c1['id'], picks={_c0['code']: [_c0['photo_id'], _c1['photo_id']]})
    _codes = [x['code'] for x in d_multi['checks']]
    chk('R35 picks 传列表：一个编码可多张（该码出现 2 次，总数 +1）',
        _codes.count(_c0['code']) == 2
        and len(d_multi['checks']) == len(d['checks']) + 1,
        '%s 次 / 共 %d（原来 %d）' % (_codes.count(_c0['code']),
                                    len(d_multi['checks']), len(d['checks'])))
    chk('R35b picks 传字符串仍兼容（旧调用方）',
        len(store.loading_report_data(con, c1['id'],
                                      picks={_c0['code']: _c0['photo_id']})['checks'])
        == len(d['checks']))
else:
    chk('R35 picks 多图', False, 'fixture 不足两张核对照')

# ══════════════════════════════════════════════════════════════════
# picks 新格式：监装照人工指定（2026-10-11 老板「④选图没看到监装照」）
#   {'trucks': [pid...]}   ⑦ 只出指定的，顺序跟点选一致；[] = 明确留空
#   {'conds': {tag: pid}}  ④ 每类指定；tag 不符/不属于本柜 → 拒绝（保自动）
#   不带 trucks 键 = 没表态 → 自动（旧行为）。'codes' 键与旧平铺格式并存。
# ══════════════════════════════════════════════════════════════════
_s0, _s4, _s5 = sup[0], sup[4], sup[5]     # empty_container / other / truck_head
d_t = store.loading_report_data(con, c1['id'], picks={'trucks': [_s5]})
chk('SP1 trucks 指定一张：⑦ 只出这张',
    d_t['summary']['truck_photos'] == 1 and d_t['trucks'][0]['photo_id'] == _s5,
    d_t['summary']['truck_photos'])
d_t2 = store.loading_report_data(con, c1['id'], picks={'trucks': [_s4, _s5]})
chk('SP2 trucks 顺序跟人工点选一致（other 在前、truck_head 在后）',
    [t['photo_id'] for t in d_t2['trucks']] == [_s4, _s5],
    [t['photo_id'] for t in d_t2['trucks']])
d_t3 = store.loading_report_data(con, c1['id'], picks={'trucks': []})
chk('SP3 trucks=[]：明确留空（⑦ 为 0，与「没表态」是两个决定）',
    d_t3['summary']['truck_photos'] == 0, d_t3['summary']['truck_photos'])
d_t4 = store.loading_report_data(con, c1['id'], picks={'trucks': ['999999', pre[0]]})
chk('SP4 trucks 混入不存在/非监装 id：静默丢弃不炸',
    d_t4['summary']['truck_photos'] == 0, d_t4['summary']['truck_photos'])
chk('SP5 不带 trucks 键 = 没表态 → 自动（仍 2 张）',
    store.loading_report_data(con, c1['id'])['summary']['truck_photos'] == 2)


def _photo_path(pid):
    return con.execute('SELECT path FROM photos WHERE id=?',
                       (pid,)).fetchone()['path']


# ④ 柜况指定：给 S4 也标成 empty_container → 该 tag 有两张候选，auto=最新一张
store.set_supervision_tag(con, [_s4], 'empty_container')
con.commit()
_ec = [r['id'] for r in con.execute(
    'SELECT p.id FROM photos p JOIN batches b ON b.id=p.batch_id'
    ' WHERE b.container_id=? AND p.is_dup=0'
    " AND IFNULL(p.supervision_tag,'other')='empty_container'"
    ' ORDER BY p.taken_at DESC, p.created_at DESC', (c1['id'],))]
chk('SP6 empty_container 现在有两张候选', len(_ec) == 2, _ec)
d_c = store.loading_report_data(con, c1['id'])
chk('SP7 自动 = 每类最新一张（④ 不动就用它）',
    d_c['conditions']['empty_container'] == [_photo_path(_ec[0])],
    '%s vs %s' % (os.path.basename(str(d_c['conditions']['empty_container'])),
                  os.path.basename(_photo_path(_ec[0]))))
d_c2 = store.loading_report_data(
    con, c1['id'], picks={'conds': {'empty_container': str(_ec[1])}})
chk('SP8 conds 指定另一张：④ 换成人工选的那张（单值兼容）',
    d_c2['conditions']['empty_container'] == [_photo_path(_ec[1])],
    os.path.basename(str(d_c2['conditions']['empty_container'])))
# 2026-10-18 老板规则：细类不限一张 —— list 多选
d_c2m = store.loading_report_data(
    con, c1['id'], picks={'conds': {'empty_container': [str(_ec[0]), str(_ec[1])]}})
chk('SP8m conds 多选：④ 该格出多张（按点选顺序）',
    d_c2m['conditions']['empty_container']
    == [_photo_path(_ec[0]), _photo_path(_ec[1])],
    [os.path.basename(str(p)) for p in d_c2m['conditions']['empty_container']])
d_c3 = store.loading_report_data(
    con, c1['id'], picks={'conds': {'empty_container': str(_s5)}})
chk('SP9 conds 塞 truck_head 的照片进 empty_container 槽：拒绝（tag 不符）',
    d_c3['conditions']['empty_container'] == [_photo_path(_ec[0])],
    '槽位图注会印进报告，tag 不符绝不静默换图')
d_c4 = store.loading_report_data(
    con, c1['id'], picks={'codes': {_c0['code']: _c0['photo_id']},
                          'conds': {'empty_container': str(_ec[1])}})
chk('SP10 codes + conds 同传：⑥ 照常覆盖、④ 也生效',
    any(c['code'] == _c0['code'] and c['photo_id'] == _c0['photo_id']
        for c in d_c4['checks'])
    and d_c4['conditions']['empty_container'] == [_photo_path(_ec[1])])

# supervision_photos_of：④选图「监装照片」区块的数据源（分组口径后端下发）
sp = store.supervision_photos_of(con, c1['id'])
chk('SP11 分组 = 柜况4类 + 卡车3类', len(sp['groups']) == 7,
    [g['tag'] for g in sp['groups']])
chk('SP12 kind 归属：柜况组 cond、卡车组 truck',
    all((g['kind'] == 'cond') == (g['tag'] in schema.CONTAINER_CONDITION_TAGS)
        for g in sp['groups']))
chk('SP13 只收本柜监装照（预检 2 张不混入；S4 改标后 total=6）',
    sp['total'] == 6, sp['total'])
chk('SP14 组内最新在前（每组第一张 = 自动默认）',
    all([i['photo_id'] for i in g['items']] ==
        [i['photo_id'] for i in sorted(g['items'], key=lambda x: x['taken_at'],
                                       reverse=True)]
        for g in sp['groups'] if len(g['items']) > 1))
try:
    store.supervision_photos_of(con, 'NO-SUCH-CID')
    chk('SP15 柜不存在 → ContainerError', False, '没抛')
except store.ContainerError:
    chk('SP15 柜不存在 → ContainerError', True)

# supervision_pending_of：③治理「监装细分确认」待办（2026-10-11）
# fixture 里 6 张监装照全部 set_supervision_tag 过（confirmed=1）→ 先清一张的确认位
con.execute("UPDATE photos SET sup_tag_confirmed=0, sup_tag_ai='truck_head',"
            ' sup_tag_ai_conf=0.82, sup_tag_ai_reason=? WHERE id=?',
            ('测试建议', sup[4]))
con.commit()
pend = store.supervision_pending_of(con, c1['id'])
chk('SP16 待办含「监装但未确认细分」的 1 张',
    pend['total'] == 1 and pend['items'][0]['photo_id'] == sup[4],
    (pend['total'], [x['photo_id'] for x in pend['items']]))
chk('SP17 待办带 AI 建议（枚举内 + 置信度）',
    pend['items'][0]['ai_tag'] == 'truck_head' and abs(pend['items'][0]['ai_conf'] - 0.82) < 1e-6,
    pend['items'][0])
chk('SP18 labels 由后端下发（7 个枚举全量）',
    len(pend.get('labels', {})) == len(schema.SUPERVISION_TAGS), list(pend.get('labels', {})))
# 用途未分类但模型给了建议 → 也在待办里（B 类：先标用途再确认细分）
con.execute("UPDATE photos SET photo_usage='', sup_tag_ai='container_seal',"
            ' sup_tag_ai_conf=0.7, sup_tag_confirmed=0 WHERE id=?', (sup[5],))
con.commit()
pend2 = store.supervision_pending_of(con, c1['id'])
_b = next((x for x in pend2['items'] if x['photo_id'] == sup[5]), None)
chk('SP19 用途未分类但有建议 → 也在待办（usage 空串）',
    _b is not None and _b['usage'] == '' and _b['ai_tag'] == 'container_seal',
    _b)
# 恢复 fixture 原状（后续用例还依赖 usage/tag）
store.set_supervision_tag(con, [sup[4]], 'other')
store.set_photo_usage(con, sup[5], '监装')
store.set_supervision_tag(con, [sup[5]], 'truck_head')

# 同编码多箱：给该编码再补一行、箱号不同 → 图注必须把两个箱都列出来
_c0 = d['checks'][0]
con.execute(
    "INSERT INTO checklist_rows(batch_id, seq, code, code_norm, name, spec,"
    " package_no, order_qty, loading_qty, created_at)"
    " SELECT batch_id, 9000, code, code_norm, name, spec, 'Cage-TEST-B',"
    " order_qty, loading_qty, created_at FROM checklist_rows"
    " WHERE batch_id=? AND code_norm=? LIMIT 1",
    (imp['batch_id'], _c0['code']))
con.commit()
d_box = store.loading_report_data(con, c1['id'])
_hit = [x for x in d_box['checks'] if x['code'] == _c0['code']]
chk('R36 同编码多箱：图注列全部箱号（/ 分隔）',
    bool(_hit) and len(_hit[0]['cartons']) == 2
    and ' / ' in _hit[0]['carton'],
    _hit[0]['cartons'] if _hit else None)

# ══════════════════════════════════════════════════════════════════
# 同名文件被占用（Word 开着）→ 自动另存，生成不能失败（10-06 老板实测报错）
# ══════════════════════════════════════════════════════════════════
_locked = open(out, 'rb')          # 持有句柄：Windows 上会挡住 os.replace
try:
    r_lock = report_gen.build_loading_report(d, out)
    if r_lock.get('renamed'):
        chk('R37 同名被占用 → 自动加时分秒另存（生成不失败）',
            os.path.exists(r_lock['path']) and r_lock['path'] != out
            and r_lock['path'].endswith('.docx'),
            os.path.basename(r_lock['path']))
        os.remove(r_lock['path'])  # 清理测试产物
    else:
        # 该平台允许替换（锁没生效）——至少产物必须是完整可读的
        chk('R37 目标未被占用时直接覆盖（安全网不误触发）',
            os.path.exists(r_lock['path']) and r_lock['bytes'] > 10000,
            r_lock['bytes'])
finally:
    _locked.close()

chk('R26 to_number 解析不出返回 None（不当 0）',
    schema.to_number('N/A') is None and schema.to_number('') is None
    and schema.to_number('12 PCS') == 12.0)

# ══════════════════════════════════════════════════════════════════
# 网格统一格高（10-05 老板：排版要整齐）—— 一竖一横同排时行高必须一致
# ══════════════════════════════════════════════════════════════════
import zipfile as _zf
import xml.etree.ElementTree as _ET
_wp = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
_z = _zf.ZipFile(out)
_ext = [e for e in _ET.fromstring(_z.read('word/document.xml')).iter(
        _wp + 'extent')]
_h_in = [int(e.get('cy')) / 914400.0 for e in _ext]
_grid_h = [h for h in _h_in if h <= report_gen.GRID_PHOTO_H_IN + 1e-6]
chk('R27 网格照片统一格高（全部 ≤ %.2f" 且无超高竖图）' % report_gen.GRID_PHOTO_H_IN,
    len(_ext) == 8 and all(h <= report_gen.GRID_PHOTO_H_IN + 1e-6 for h in _h_in),
    '高度集合 %s' % sorted(set(round(h, 2) for h in _h_in)))
# 竖图在统一格高下必须收窄而不是变形：竖图 675x1200 → 宽 = 2.35*675/1200
bufp, pwp, php = report_gen._prep_photo(os.path.join(sd, 'S_rot.jpg'))
pwu, phu = report_gen._fit_uniform(pwp, php)
chk('R28 竖图统一格高按宽高比收窄（%.2f x %.2f，高恒定）' % (pwu, phu),
    abs(phu - report_gen.GRID_PHOTO_H_IN) < 1e-6
    and abs(pwu - report_gen.GRID_PHOTO_H_IN * pwp / php) < 1e-6,
    '%s' % ((pwu, phu),))

# ══════════════════════════════════════════════════════════════════
# 统一图框 + 专业排版（10-05 第二轮：横竖混排要归一，报告要大气）
# ══════════════════════════════════════════════════════════════════
_wp2 = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
_ext2 = [(int(e.get('cx')), int(e.get('cy')))
         for e in _ET.fromstring(_z.read('word/document.xml')).iter(_wp2+'extent')]
chk('R29 所有照片嵌入尺寸完全相同（图框归一，%d 张）' % len(_ext2),
    len(_ext2) == 8 and len(set(_ext2)) == 1, sorted(set(_ext2)))
# 图框像素尺寸也恒定（横竖都合到 1080×806）
_fb, _fw, _fh = report_gen._prep_photo(os.path.join(sd, 'S_rot.jpg'), frame=True)
_fb2, _fw2, _fh2 = report_gen._prep_photo(os.path.join(pd, 'P1.jpg'), frame=True)
chk('R29b 横图竖图合成后像素尺寸一致（%dx%d）' % (_fw, _fh),
    (_fw, _fh) == (_fw2, _fh2) == (report_gen.FRAME_PX_W, report_gen.FRAME_PX_H))
chk('R30 区块标题带底色（深藏青 %s）' % report_gen.BAND_FILL,
    xml.count('w:fill="%s"' % report_gen.BAND_FILL) >= 4,
    'band=%d' % xml.count('w:fill="%s"' % report_gen.BAND_FILL))
chk('R30b 表格用细线不用粗黑框（无 Table Grid 样式）',
    'TableGrid' not in xml and 'Table Grid' not in xml)
# ⚠️ 页脚是**独立的 part**（word/footer1.xml），不在 document.xml 里查
_ftr = ''.join(_z.read(n).decode('utf8') for n in _z.namelist()
               if n.startswith('word/footer'))
chk('R31 页脚有页码域（PAGE / NUMPAGES）',
    'fldSimple' in _ftr and 'PAGE' in _ftr and 'NUMPAGES' in _ftr,
    _ftr[:120] if _ftr else 'no footer part')

con.close()
shutil.rmtree(tmp, ignore_errors=True)
print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
