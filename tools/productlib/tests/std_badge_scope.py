# -*- coding: utf-8 -*-
"""「标准图」徽标的作用域（2026-10-21 老板反馈修复）

老板反馈：「这个产品的关联编码只有一张标准图，可是图片下方同产品的其他图片
都被标上了标准图。」根因：前端按「产品有没有标准图」给同编码**所有**照片打
徽标（产品级判断）。修法：逐张比 src_photo_id，只有真的被做成标准图的那张
**源照片**才打（旧版 drawer.js 同编码参考块 / 新版 PhotoDrawer.vue 同步改）。

本测试锁死后端口径（routes.products.api_product_photos，前端两个徽标的唯一数据源）：
  B1 standard_photo_ids 只含裁剪标准图的源照片 id
  B2 上传标准图的哨兵值 _UPLOADED_ 绝不混进 standard_photo_ids
  B3 standard_count = 裁剪 + 上传总张数（标题「N 张标准图」用它，别用集合大小）
  B4 一个源照片多个版本 → id 集合去重后仍 1 个，count 按张算
  B5 没有标准图时 standard_photo_ids=[] 且 standard_count=0

跑法：python tools/productlib/tests/std_badge_scope.py
"""
import io
import os
import shutil
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix='pl_stdbadge_')
# ⚠️ 必须在 import routes 之前设：deps.con() 在导入时算 DEFAULT_DB
os.environ['PL_HOME'] = tmp
os.environ['PL_DB'] = os.path.join(tmp, 'badge.db')

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import schema, store  # noqa: E402
from tools.productlib.routes import products as RP  # noqa: E402
from PIL import Image  # noqa: E402

FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name
          + ('' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


def jpg(w, h, color=(200, 60, 60)):
    b = io.BytesIO()
    Image.new('RGB', (w, h), color).save(b, format='JPEG')
    return b.getvalue()


con = store.connect(os.path.join(tmp, 'badge.db'))

# 一个产品 + 两张已关联照片（同编码「其他照片」的真实场景）
con.execute("INSERT INTO products(code_norm,code,name,spec,created_at,"
            "updated_at,review_state,photo_count)"
            " VALUES('STDB1','STDB1','徽章作用域件','','2026-10-21',"
            "'2026-10-21','confirmed',2)")
for pid, tk in (('p_std_a', '2026-10-20T10:00:00'),
                ('p_std_b', '2026-10-20T10:00:05')):
    con.execute("INSERT INTO photos(id,file,path,batch_id,taken_at,"
                "created_at,govern_state,bytes) VALUES(?,?,?,?,?,?,?,?)",
                (pid, pid + '.jpg', 'D:/x/' + pid + '.jpg', 'b1', tk,
                 '2026-10-20', 'done', 123456))
    con.execute("INSERT INTO links(code_norm,photo_id,source,created_at)"
                " VALUES('STDB1',?, 'manual','2026-10-21')", (pid,))
con.commit()

# ── B5：还没有任何标准图 ────────────────────────────────────────
d0 = RP.api_product_photos('STDB1')
chk('B5 无标准图时 ids=[] 且 count=0',
    d0['standard_photo_ids'] == [] and d0['standard_count'] == 0,
    (d0['standard_photo_ids'], d0['standard_count']))

# ── 只有 1 张裁剪标准图（源照片 = p_std_a）+ 2 张上传 ────────────
store.add_standard_image(con, 'STDB1', 'p_std_a', 'product',
                         jpg(1000, 1000), 1000, 1000, origin='crop')
store.add_standard_upload(con, 'STDB1', 'product', jpg(900, 900), 'up1.jpg')
store.add_standard_upload(con, 'STDB1', 'label', jpg(900, 900), 'up2.jpg')

d1 = RP.api_product_photos('STDB1')
ids = d1['standard_photo_ids']
chk('B1 standard_photo_ids 只含裁剪源照片 p_std_a',
    ids == ['p_std_a'], ids)
chk('B2 哨兵值 _UPLOADED_ 不混进 standard_photo_ids',
    schema.UPLOAD_SENTINEL not in ids, ids)
chk('B3 standard_count = 裁剪+上传共 3 张',
    d1['standard_count'] == 3, d1['standard_count'])
chk('B3b 同编码其他照片（p_std_b）不会被打上标准图',
    'p_std_b' not in ids, ids)

# ── B4：同一源照片再存一个版本 → 集合仍 1 个 id，count 按张算 ─────
store.add_standard_image(con, 'STDB1', 'p_std_a', 'product',
                         jpg(1000, 1000), 1000, 1000, origin='crop')
d2 = RP.api_product_photos('STDB1')
chk('B4 同源照片多版本：id 集合去重仍 1 个，count 变 4',
    d2['standard_photo_ids'] == ['p_std_a'] and d2['standard_count'] == 4,
    (d2['standard_photo_ids'], d2['standard_count']))

# ── 第二个产品也做一张 → 互不串味 ──────────────────────────────
con.execute("INSERT INTO products(code_norm,code,name,spec,created_at,"
            "updated_at,review_state,photo_count)"
            " VALUES('STDB2','STDB2','另一件','','2026-10-21',"
            "'2026-10-21','confirmed',1)")
con.execute("INSERT INTO photos(id,file,path,batch_id,taken_at,created_at,"
            "govern_state,bytes) VALUES('p_std_c','c.jpg','D:/x/c.jpg','b1',"
            "'2026-10-20T11:00:00','2026-10-20','done',123)")
con.execute("INSERT INTO links(code_norm,photo_id,source,created_at)"
            " VALUES('STDB2','p_std_c','manual','2026-10-21')")
con.commit()
store.add_standard_image(con, 'STDB2', 'p_std_c', 'product',
                         jpg(800, 800), 800, 800, origin='crop')
d3 = RP.api_product_photos('STDB2')
chk('B6 产品间不串：STDB2 只认自己的源照片',
    d3['standard_photo_ids'] == ['p_std_c'] and d3['standard_count'] == 1,
    (d3['standard_photo_ids'], d3['standard_count']))

con.close()
shutil.rmtree(tmp, ignore_errors=True)

print('----')
print('%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
