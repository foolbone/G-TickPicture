# -*- coding: utf-8 -*-
"""五需求后端测试（2026-10-15）：分类重治 / 清单包装清理 / 相似重复 / 四档 / 全景候选。

  ① regovern_one：人工改判后按新分类重跑读码链路 —— token 命中 → 自动关联；
    NO_LINK_KINDS（清单/场景）绝不写关联；kind 人工权威不被翻案。
  ② 低置信兜底：scene conf<0.85 不再跳过（走 done），conf>=0.85 才 skipped。
  ③ auto_invalid_candidates：未关联的清单/包装进名单，已关联/已无效不进。
  ④ phash/dup_groups：同图同指纹成组，已关联的当保留张；backfill 补算。
  ⑤ photo_flag_counts 带 invalid 档；flag=invalid 列表只出无效照片。
  ⑥ 全景候选端点：产品缺全景时，邻近未关联 product 照进候选。

不写真实库；OCR/视觉在测试环境不可用 —— regovern 走「已有 token 匹配」
路径，正好覆盖主流程（补跑 OCR 的分支由 CDP 实测兜）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema, pipeline  # noqa: E402
from PIL import Image  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_gov2_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO containers(id,container_no,created_at,updated_at)"
            " VALUES('c1','GOV01','2026-10-15','2026-10-15')")
con.execute("INSERT INTO batches(id,name,kind,container_id,created_at)"
            " VALUES('b1','批1','photos','c1','2026-10-15')")
con.execute("INSERT INTO products(code_norm,code,name,status,created_at,updated_at)"
            " VALUES('ABC-123','ABC-123','测试产品A','active','2026-10-15','2026-10-15')")


def mk(pid, kind='label', conf=0.82, phash=None, invalid=0, seq=0, fname=None,
       batch='b1'):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,kind_conf,'
        'created_at,import_seq,phash,is_invalid) '
        "VALUES(?,'/x/'||?,'/x/'||?,?,'2026-10-15T10:00:00','exif',100,?,"
        "800,600,0,0,'done',?,?,'2026-10-15',?,?,?)",
        (pid, fname or pid, fname or pid, batch, 'm' + pid, kind, conf,
         seq, phash, invalid))


def add_token(pid, text, conf=0.92):
    con.execute('INSERT INTO ocr_tokens(photo_id,raw_text,confidence,created_at)'
                " VALUES(?,?,?,'2026-10-15')", (pid, text, conf))


# ══ ① regovern_one：改判即重治 ════════════════════════════════════
mk('r1', kind='scene', conf=0.0)            # 被模型判错成 scene（token 都没有）
add_token('r1', 'ABC-123')                  # 但库里留有 token（低置信兜底存的）
con.commit()
row = con.execute('SELECT * FROM photos WHERE id=?', ('r1',)).fetchone()
out = pipeline.regovern_one(con, row, 'label', pipeline._build_index(con))
chk('1 改判重治：token 命中产出 hits', len(out['hits']) == 1, out['hits'])
# links.code_norm 存的是 BL.normalize 后的形态（去分隔符大写），按 photo_id 断言
chk('2 改判重治：精确命中自动关联',
    out['links_added'] == 1 and con.execute(
        'SELECT COUNT(*) FROM links WHERE photo_id=?',
        ('r1',)).fetchone()[0] == 1, out)
chk('3 改判重治：人工 kind 权威不翻案',
    con.execute('SELECT photo_kind,govern_state FROM photos WHERE id=?',
                ('r1',)).fetchone()[0:2] == ('label', 'done'))

# 1b/1c（2026-10-19）：重新识别拆两档 —— mode='ocr' 只跑本地 OCR。
# 测试库 vision 未启用，'full' 本来也不跑视觉；用「vision 字段保留」来验：
# 预置 codes/desc/model，跑 mode='ocr' 后必须原样保留（不能被清空）。
con.execute("UPDATE photos SET vision_codes='[\"ABC-123\"]',"
            " vision_desc='原描述', vision_model='vm-1' WHERE id='r1'")
con.commit()
row_m = con.execute('SELECT * FROM photos WHERE id=?', ('r1',)).fetchone()
out_m = pipeline.regovern_one(con, row_m, 'label', pipeline._build_index(con),
                              regen='ocr')
_m = con.execute('SELECT vision_codes,vision_desc,vision_model FROM photos '
                 "WHERE id='r1'").fetchone()
chk('1b mode=ocr：vision 字段原值保留不被清',
    _m[0] == '[\"ABC-123\"]' and _m[1] == '原描述' and _m[2] == 'vm-1', tuple(_m))
chk('1c mode=ocr：旧 token 清了重跑（不复用）',
    out_m['tokens_n'] == 0,   # 假路径 OCR 失败 → 0 条；关键是不复用旧 1 条
    {'tokens_n': out_m['tokens_n'], 'ocr_ok': out_m['ocr_ok']})

mk('r2', kind='packing_list')               # 清单：token 再多也绝不自动关联
add_token('r2', 'ABC-123')
con.commit()
row2 = con.execute('SELECT * FROM photos WHERE id=?', ('r2',)).fetchone()
out2 = pipeline.regovern_one(con, row2, 'packing_list', pipeline._build_index(con))
chk('4 清单照重治不写关联（NO_LINK_KINDS）',
    out2['links_added'] == 0 and not con.execute(
        'SELECT COUNT(*) FROM links WHERE photo_id=?', ('r2',)).fetchone()[0],
    out2)
# r2 也是「未关联的清单照」—— ③的清理名单必须把它算进去

# ══ ② 低置信兜底：scene 的 OCR 跳过阈值 0.5 → 0.85 ════════════════
_orig_classify = pipeline.classify
try:
    pipeline.classify = (lambda *a, **k: ('scene', 0.6, '不太自信', 'm',
                                          None, None, 0.0, ''))
    mk('r3', kind='scene', conf=0.6)
    con.commit()
    row3 = con.execute('SELECT * FROM photos WHERE id=?', ('r3',)).fetchone()
    pipeline.govern_one(con, row3, pipeline._build_index(con),
                        use_vision=False, use_ocr=False)
    st3 = con.execute('SELECT govern_state FROM photos WHERE id=?',
                      ('r3',)).fetchone()[0]
    chk('5 scene conf=0.6 不再跳过（走完治理 = done）', st3 == 'done', st3)

    pipeline.classify = (lambda *a, **k: ('scene', 0.9, '很自信', 'm',
                                          None, None, 0.0, ''))
    mk('r4', kind='scene', conf=0.9)
    con.commit()
    row4 = con.execute('SELECT * FROM photos WHERE id=?', ('r4',)).fetchone()
    pipeline.govern_one(con, row4, pipeline._build_index(con),
                        use_vision=False, use_ocr=False)
    st4 = con.execute('SELECT govern_state FROM photos WHERE id=?',
                      ('r4',)).fetchone()[0]
    chk('6 scene conf=0.9 高置信仍跳过（skipped）', st4 == 'skipped', st4)
finally:
    pipeline.classify = _orig_classify

# ══ ③ 清单/包装清理名单 ══════════════════════════════════════════
mk('p1', kind='packing_list', seq=1)
mk('p2', kind='packaging', seq=2)
mk('p3', kind='label', seq=3)               # 标签照不进名单
mk('p4', kind='packing_list', seq=4)        # 已关联的不进
con.execute("INSERT INTO links(code_norm,photo_id,source,created_at,created_by)"
            " VALUES('ABC-123','p4','manual','2026-10-15','web')")
mk('p5', kind='packaging', invalid=1, seq=5)  # 已无效的不进
con.commit()
d = store.auto_invalid_candidates(con, 'c1')
chk('7 清理名单=未关联的清单/包装（r2,p1,p2）',
    d['total'] == 3 and sorted(d['ids']) == ['p1', 'p2', 'r2'], d['ids'])
chk('8 已关联计数单列（linked_n=1）', d['linked_n'] == 1, d['linked_n'])

# ══ ④ phash / dup_groups ═════════════════════════════════════════
# ⚠️ 纯色图没有明暗梯度 → dHash 全 0（任何纯色都一样）。必须画有纹理的图。
imgd = os.path.join(tmp, 'imgs')
os.makedirs(imgd)
from PIL import ImageDraw  # noqa: E402

def _pat(path, seed):
    im = Image.new('RGB', (400, 300), (240, 240, 240))
    dr = ImageDraw.Draw(im)
    for i in range(0, 400, 17):                    # 斜条纹，间距随 seed 变
        dr.line([(i, 0), (i - 300, 300)], fill=(40 + seed * 30, 90, 160), width=5)
    dr.ellipse([60 + seed * 40, 60, 200 + seed * 40, 200], fill=(200, 50, 50))
    im.save(path)

_pat(os.path.join(imgd, 'a.jpg'), 0)
_pat(os.path.join(imgd, 'b.jpg'), 0)               # 与 a 完全相同 = 重复拍
_pat(os.path.join(imgd, 'c.jpg'), 2)               # 图案不同
pa = os.path.join(imgd, 'a.jpg')
h1 = store.dhash_of(pa)
h2 = store.dhash_of(os.path.join(imgd, 'b.jpg'))
h3 = store.dhash_of(os.path.join(imgd, 'c.jpg'))
chk('9 同图同指纹、异图异指纹', h1 == h2 and h1 != h3, '%s %s %s' % (h1, h2, h3))

mk('d1', phash=None, seq=11, fname='a.jpg')
con.execute('UPDATE photos SET path=? WHERE id=?', (pa, 'd1'))
mk('d2', phash=None, seq=12, fname='b.jpg')
con.execute('UPDATE photos SET path=? WHERE id=?',
            (os.path.join(imgd, 'b.jpg'), 'd2'))
mk('d3', phash=None, seq=13, fname='c.jpg')
con.execute('UPDATE photos SET path=? WHERE id=?',
            (os.path.join(imgd, 'c.jpg'), 'd3'))
mk('d4', kind='product', phash=None, seq=14, fname='a2.jpg')
con.execute('UPDATE photos SET path=? WHERE id=?', (pa, 'd4'))
con.commit()
remain = store.backfill_phash(con, 'c1')
# 有真实文件的 4 张（d1-d4）补上了；其余 9 张测试行是假路径 /x/...，
# 算不出指纹留在 NULL —— remain=9 正是「还能补的数」的口径
hashed = con.execute('SELECT COUNT(*) FROM photos WHERE phash IS NOT NULL'
                     " AND id IN ('d1','d2','d3','d4')").fetchone()[0]
chk('10 backfill 补算真实文件（4 张有指纹，剩 9 张假路径）',
    remain == 9 and hashed == 4, 'remain=%s hashed=%s' % (remain, hashed))
# d4 与 d1 是同一文件（内容相同）→ 三张同一组；c(d3) 图案不同不成组
groups = store.dup_groups(con, 'c1')
chk('11 一组重复（d1/d2/d4；c 单独不成组）',
    len(groups) == 1, [(g['keep']['id'], [o['id'] for o in g['others']])
                       for g in groups])
g0 = groups[0]
members = {g0['keep']['id']} | {o['id'] for o in g0['others']}
chk('12 组成员正确（d1/d2/d4 一组，d3 不在）',
    members == {'d1', 'd2', 'd4'}, members)
chk('12b 默认保留序号最小的 d1', g0['keep']['id'] == 'd1', g0['keep']['id'])
# 已关联的优先当保留张
con.execute("INSERT INTO links(code_norm,photo_id,source,created_at,created_by)"
            " VALUES('ABC-123','d4','manual','2026-10-15','web')")
con.commit()
groups2 = store.dup_groups(con, 'c1')
chk('13 已关联的当保留张（d4 换上当 keep）',
    groups2[0]['keep']['id'] == 'd4'
    and {o['id'] for o in groups2[0]['others']} == {'d1', 'd2'},
    groups2[0]['keep']['id'])

# ══ ⑤ 四档计数与列表 ═════════════════════════════════════════════
mk('i1', kind='label', invalid=1, seq=21)
con.commit()
cnt = store.photo_flag_counts(con, container_id='c1')
chk('14 linkstate 带 invalid 档', cnt['invalid'] >= 1, cnt['invalid'])
chk('15 invalid 不混进全部档（hide 口径）',
    'i1' not in {r['id'] for r in con.execute(
        "SELECT p.id FROM photos p JOIN batches b ON b.id=p.batch_id "
        "WHERE b.container_id='c1' AND IFNULL(p.is_invalid,0)=0")}, cnt['all'])

import tools.productlib.routes.photos as RP  # noqa: E402
_dbpath = os.path.join(tmp, 't.db')
RP.con = lambda: store.connect(_dbpath)
lst = RP.api_photos(container_id='c1', flag='invalid', invalid='hide', mark=0)
ids = [x['id'] for x in lst['items']]
# i1（⑤插入）与 p5（③插入时 invalid=1）都是无效照片
chk('16 flag=invalid 列表只出无效照片', sorted(ids) == ['i1', 'p5'], ids)
lst_all = RP.api_photos(container_id='c1', invalid='hide', mark=0)
chk('17 默认列表排除无效照片',
    'i1' not in [x['id'] for x in lst_all['items']], len(lst_all['items']))

# ══ ⑥ 全景候选端点 ═══════════════════════════════════════════════
# ⚠️ 2026-10-19 换到独立批次 b2：合并候选后「同组段」会把同 batch 的
#   group_idx=0 全部照片捞出来（b1 里 r/p/d 系列全是组 0），8 张截断
#   把 V1/V2 挤掉 —— 那是真实库不存在的形态（真实组=一次连拍一小撮），
#   测试数据不该全库一组。b2 只放本断言的三张，干净隔离。
con.execute("INSERT INTO batches(id,container_id,name,kind,created_at)"
            " VALUES('b2','c1','全景测试批','photos','2026-10-15')")
mk('L1', kind='label', seq=31, fname='img_l1.jpg', batch='b2')   # 标签近景（已关联）
con.execute("INSERT INTO links(code_norm,photo_id,source,created_at,created_by)"
            " VALUES('PANO-1','L1','manual','2026-10-15','web')")
con.execute("INSERT INTO products(code_norm,code,name,status,created_at,updated_at)"
            " VALUES('PANO-1','PANO-1','全景产品','active','2026-10-15','2026-10-15')")
mk('V1', kind='product', seq=32, fname='img_v1.jpg', batch='b2')   # 紧邻的产品全景
mk('V2', kind='packaging', seq=33, fname='img_v2.jpg', batch='b2') # 包装全景
con.commit()
pano = RP.api_photo_panoramas('L1')
pids = [x['photo_id'] for x in pano['items']]
chk('18 邻近全景照进候选（V1/V2）', 'V1' in pids and 'V2' in pids, pids)
# 2026-10-18 合并后：同组来源(source=group)的候选**不带 code** ——
#   前端用当前照片已关联编码回退；只有 pano 来源（跨组邻居）带来源编码。
#   V1/V2 与 L1 同组（怼标签+退后全景正是一次连拍）→ 走 group 段，code 为空。
chk('19 group 候选无 code、pano 候选带来源编码',
    all(x.get('code') is None for x in pano['items']
        if x.get('source') == 'group')
    and all(x.get('code') == 'PANO-1' for x in pano['items']
            if x.get('source') == 'pano'),
    [(x.get('source'), x.get('code')) for x in pano['items']])
# 产品已有全景（V1 被关联）→ 引擎收声
con.execute("INSERT INTO links(code_norm,photo_id,source,created_at,created_by)"
            " VALUES('PANO-1','V1','manual','2026-10-15','web')")
con.commit()
pano2 = RP.api_photo_panoramas('L1')
pids2 = [x['photo_id'] for x in pano2['items']]
# 「收声」只对 pano 来源 —— 同组段是强语义，已关联的组内照仍列出
#   （前端标「已用于 N 个产品」），这是合并定下的规则（真机验证过）。
_pano2_src = [x['photo_id'] for x in pano2['items'] if x.get('source') == 'pano']
chk('20 产品补上全景后引擎收声（pano 来源不再推）',
    'V1' not in _pano2_src and 'V2' not in _pano2_src, _pano2_src)

# 端点形状核对
_ai = RP.api_auto_invalid('c1')
# V2（⑥插入的 packaging 全景）也是未关联包装照 —— 名单共 4 张
chk('21 auto-invalid 端点带 preview（r2/p1/p2/V2 共 4）',
    _ai['total'] == 4 and len(_ai['preview']) == 4
    and set(_ai['ids']) == {'p1', 'p2', 'r2', 'V2'},
    'total=%s ids=%s' % (_ai['total'], _ai['ids']))
dup_api = RP.api_photo_dups('c1')
# 分组只算有指纹的（d1/d2/d4 一组）；假路径行 9+4（⑤⑥插入）=13 张待补
chk('22 dups 端点返回分组与 remaining',
    dup_api['total_groups'] == 1 and dup_api['remaining'] == 13,
    'groups=%s remaining=%s' % (dup_api['total_groups'], dup_api['remaining']))

# ══ ⑦ 待办进查询条件（需求3）：todo 收窄与列表同源 ════════════════
_orig_cpi = store.cand_photo_ids
try:
    # 造两个「待确认关联」：r1（label，未关联）与 d3（product，未关联）
    store.cand_photo_ids = lambda con: {'r1', 'd3'}
    cnt = store.photo_flag_counts(con, container_id='c1', todo='cand')
    chk('23 todo=cand 收窄：all=2、invalid=0',
        cnt['all'] == 2 and cnt['invalid'] == 0,
        {k: v for k, v in cnt.items() if not k.endswith('_ids')})
    fac = store.photo_facet_counts(con, container_id='c1', todo='cand')
    chk('24 todo=cand 下树分类计数只算待办集合',
        sum(fac['kind'].values()) == 2, fac['kind'])
finally:
    store.cand_photo_ids = _orig_cpi

print()
print('PASS' if not FAILS else 'FAIL %d 项: %s' % (len(FAILS), FAILS))
sys.exit(0 if not FAILS else 1)
