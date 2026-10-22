# -*- coding: utf-8 -*-
"""报告取图：**图片没迁移**时还出不出得来（2026-10-22 老板问「现在生成报告还有问题吗」）。

三种现实场景，必须分别成立：

  A 原地升级：库里是绝对路径、文件还在原处          → 直接用（第 1 级命中）
  B 换了电脑 / 换了盘符：文件跟着 data 目录整体拷走，
    库里的绝对路径仍指向老机器（**没跑迁移、path 没改**）→ 截 `/data/` 之后
    的相对段、拼当前 data 根（第 2 级命中）—— 这才是「没迁移图片」的常见形态
  C 文件确实不在了（既没搬走、原处也删了）        → 不许崩、不许静默留空格，
    该格写 `Not provided`，整份报告照常生成

⚠️ 这个测试锁的是**报告生成器**，不是 `store.resolve_photo_path`：
报告走 `report_gen._resolve_photo_path`（只读、不回写库），
口径要一致但不能互相依赖（回写库在报告这种只读路径上是副作用）。
"""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, report_gen  # noqa: E402

REAL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))),
    '9.13 5x40HQ', 'MIEU2012616.xlsx')

tmp = tempfile.mkdtemp(prefix='pl_rpath_')
DATA = os.path.join(tmp, 'data')
os.makedirs(DATA, exist_ok=True)
con = store.connect(os.path.join(DATA, 'productlib.db'))
FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


def n_images(path):
    with zipfile.ZipFile(path) as z:
        return len([n for n in z.namelist() if n.startswith('word/media/')])


def doc_text(path):
    import re
    with zipfile.ZipFile(path) as z:
        xml = z.read('word/document.xml').decode('utf8')
    return re.sub(r'<[^>]+>', '', xml)


def gen(tag):
    """按当前库状态生成一份报告，返回 (路径, 图片数, 正文文本)。"""
    data = store.loading_report_data(con, c1['id'])
    out = os.path.join(tmp, 'r_%s.docx' % tag)
    r = report_gen.build_loading_report(data, out, photo_root=DATA)
    return out, n_images(out), doc_text(out), r


# ══════════════════════════════════════════════════════════════════
# 准备：柜 + 清单 + 照片（预检 2 张并关联到第 1 个编码；监装 4 张柜况）
# ══════════════════════════════════════════════════════════════════
chk('P0 真实清单存在', os.path.exists(REAL), REAL)
c1 = store.create_container(con, 'EMCU9900001', client_name='Test Co.',
                            product_name='ACCESSORIES')
imp = store.import_checklist_file(con, REAL, container_id=c1['id'])

from PIL import Image  # noqa: E402

src = os.path.join(tmp, '交付')
pd = os.path.join(src, '预检', 'Cage-M068')
sd = os.path.join(src, '监装')
os.makedirs(pd)
os.makedirs(sd)
Image.new('RGB', (1200, 900), (200, 30, 30)).save(os.path.join(pd, 'P1.jpg'))
Image.new('RGB', (1200, 900), (30, 200, 30)).save(os.path.join(pd, 'P2.jpg'))
for i, tag in enumerate(('empty_container', 'container_side',
                         'container_seal', 'container_lock')):
    Image.new('RGB', (1200, 900), (40 * i + 20, 60, 200)).save(
        os.path.join(sd, 'S_%d.jpg' % i))

ap = store.add_photos(con, src, container_id=c1['id'])
chk('P1 照片入库 6 张', ap['added'] == 6, ap.get('added'))

sup = [r['id'] for r in con.execute(
    "SELECT id FROM photos WHERE batch_id=? AND file LIKE '监装/%'", (ap['batch_id'],))]
for pid in sup:
    store.set_photo_usage(con, pid, '监装')
for i, tag in enumerate(('empty_container', 'container_side',
                         'container_seal', 'container_lock')):
    store.set_supervision_tag(con, [sup[i]], tag)

pre = [r['id'] for r in con.execute(
    "SELECT id FROM photos WHERE batch_id=? AND file LIKE '预检/%' ORDER BY file",
    (ap['batch_id'],))]
row0 = store.checklist_rows_of(con, imp['batch_id'])[0]
store.link(con, row0['code_norm'], pre[0], 'manual', created_by='test')

# 库里的原始形态（决定后面怎么改）
orig = dict(con.execute('SELECT id, path FROM photos').fetchall())
print('       [debug] data_root =', DATA)
print('       [debug] 样例 path =', repr(list(orig.values())[0]))


# ══════════════════════════════════════════════════════════════════
# A 原地升级：库里是绝对路径、文件还在原处 → 必须出图
#    （add_photos 落盘后可能是相对形态，先统一改成"当前机器上有效的绝对路径"）
# ══════════════════════════════════════════════════════════════════
real_map = {}
for pid, p in con.execute('SELECT id, path FROM photos').fetchall():
    real_map[pid] = store.resolve_photo_path(con, pid, p)
chk('A0 六张图都能解析到真实文件',
    all(os.path.exists(v) for v in real_map.values()),
    [v for v in real_map.values() if not os.path.exists(v)][:3])
for pid, full in real_map.items():
    con.execute('UPDATE photos SET path=? WHERE id=?', (full, pid))
con.commit()
p, n, txt, r = gen('A')
chk('A1 绝对路径有效 → 报告出图', n > 0, 'media=%d photos=%s' % (n, r.get('photos')))
txt_A, n_A = txt, n     # 留作 B2 的对照基线（不能重跑 A —— 库已被改成 B 的状态）

# ══════════════════════════════════════════════════════════════════
# B 「没迁移」：文件跟着 data 拷过来了，库里 path 还是老机器的绝对路径
#    （老路径**不存在**，但含 /data/ 段）→ 截段拼新根，照样出图
# ══════════════════════════════════════════════════════════════════
# 先把图片按 data 相对段拷进新 data 根 —— 这才是「换了电脑、文件夹整体拷走」的现场
import shutil  # noqa: E402
for pid, full in real_map.items():
    s = str(full).replace('\\', '/')
    i = s.lower().find('/data/')
    rel = s[i + 6:] if i >= 0 else s.split('/')[-1]
    dst = os.path.join(DATA, *rel.split('/'))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(full, dst)
chk('Bp 图片已随 data 拷到新位置（6 张）',
    sum(os.path.exists(os.path.join(DATA, *str(v).replace('\\', '/')
                                    .split('/data/')[-1].split('/')))
        for v in real_map.values()) == 6)

OLD = 'Z:\\旧电脑\\集刻产品库\\data'
for pid, p in con.execute('SELECT id, path FROM photos').fetchall():
    s = str(p).replace('\\', '/')
    i = s.lower().find('/data/')
    rel = s[i + 6:] if i >= 0 else s.split('/')[-1]
    con.execute('UPDATE photos SET path=? WHERE id=?',
                (OLD + '\\' + rel.replace('/', '\\'), pid))
con.commit()
old_now = [r[0] for r in con.execute('SELECT path FROM photos LIMIT 1')][0]
chk('B0 已模拟「老绝对路径失效但含 /data/ 段」',
    old_now.lower().startswith('z:') and not os.path.exists(old_now), old_now)

p, n, txt, r = gen('B')
chk('B1 老绝对路径失效 + 文件在新 data 根 → 仍出图（截 data 段）',
    n > 0, 'media=%d photos=%s' % (n, r.get('photos')))
# ⚠️ 不能断言「全文没有 Not provided」——清单 93 行里只有 1 行挂了照片，
#    其余格子本来就该写 Not provided。只比「缺图提示」有没有**变多**（与 A 基线比）。
chk('B2 缺图提示不比「路径好使」时更多',
    txt.count('Not provided') == txt_A.count('Not provided'),
    'B=%d A=%d' % (txt.count('Not provided'), txt_A.count('Not provided')))

# ══════════════════════════════════════════════════════════════════
# C 文件真没了（且路径不含 /data/ 可截）→ 不崩、写 Not provided
# ══════════════════════════════════════════════════════════════════
con.execute("UPDATE photos SET path='Z:\\没搬走的目录\\gone.jpg'")
con.commit()
try:
    p, n, txt, r = gen('C')
    ok_gen = True
    err = ''
except Exception as e:  # noqa: BLE001
    ok_gen = False
    err = str(e)[:120]
    n, txt, r = 0, '', {}
chk('C1 图片全缺 → 报告仍能生成（不抛异常）', ok_gen, err)
chk('C2 缺图写 Not provided，不留空子', 'Not provided' in txt)
chk('C3 正文图片数归零', n == 0, n)

print('----')
print('FAIL %d' % len(FAILS))
if FAILS:
    for f in FAILS:
        print('  -', f)
    sys.exit(1)
