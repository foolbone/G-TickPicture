# -*- coding: utf-8 -*-
"""手动上传标准图（2026-10-06 老板需求）

一个产品允许多张标准图；上传的标准图与库内照片无关（客户/厂家直接给的图）。
本测试钉住四件事：
  1. 多张都存（不被去重/覆盖）
  2. origin='upload' 与 src_photo_id 哨兵值隔离（绝不污染 standard_for_photo）
  3. 坏文件不阻断整批（一张坏图不能让其余白传）
  4. **导出必须包含上传的图**（老逻辑只走 links→photos，上传=白传），
     且「没关联照片但有上传图」的产品不能被 WHERE photo_count>0 整条漏掉

跑法：python tools/productlib/tests/standard_upload.py
"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from tools.productlib import schema, store  # noqa: E402
from PIL import Image  # noqa: E402

FAILS = []


def chk(name, ok, info=None):
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name
          + ('' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


def jpg(w, h, color=(20, 160, 60)):
    b = io.BytesIO()
    Image.new('RGB', (w, h), color).save(b, format='JPEG')
    return b.getvalue()


tmp = tempfile.mkdtemp(prefix='pl_stdupload_')
con = store.connect(os.path.join(tmp, 't.db'))
store.create_container(con, 'STDC1')

# 一个**没有关联照片**的产品：上传的标准图是它唯一的图像资产
con.execute("INSERT INTO products(code_norm,code,name,spec,source_batch,"
             "created_at,updated_at,review_state,photo_count)"
             " VALUES('UP1','UP1','上传测试件','','b1','2026-10-06','2026-10-06',"
             "'confirmed',0)")
con.commit()

# ── 1. 多张上传都存下来 ──────────────────────────────────────
r1 = store.add_standard_upload(con, 'UP1', 'product', jpg(1600, 1200), 'a.jpg')
r2 = store.add_standard_upload(con, 'UP1', 'label', jpg(900, 1600), 'b.jpg')
r3 = store.add_standard_upload(con, 'UP1', 'product', jpg(800, 800), 'c.jpg')
chk('S1 上传成功返回 id 与尺寸',
    all(r.get('id') and r.get('width') and r.get('height') for r in (r1, r2, r3)),
    [(r.get('width'), r.get('height')) for r in (r1, r2, r3)])
chk('S1b 三张都真实落盘', len({r['file'] for r in (r1, r2, r3)}) == 3
    and all(os.path.exists(r['file']) for r in (r1, r2, r3)))

items = store.standard_images(con, 'UP1')
ups = store.standard_images(con, 'UP1', origin='upload')
chk('S2 一个产品可存多张标准图（3 张都在）',
    len(items) == 3 and len(ups) == 3, '%d / upload %d' % (len(items), len(ups)))
chk('S3 origin 记为 upload，orig_name 留住原始文件名',
    all(s['origin'] == 'upload' for s in ups)
    and sorted(s['orig_name'] for s in ups) == ['a.jpg', 'b.jpg', 'c.jpg'],
    sorted(s['orig_name'] or '' for s in ups))
chk('S4 类别分别保留（product/label/product）',
    sorted(s['kind'] for s in ups) == ['label', 'product', 'product'],
    sorted(s['kind'] for s in ups))

# ── 2. 哨兵值隔离：绝不能被当成 photo_id 匹配到别的照片 ────────
chk('S5 哨兵值不会被 standard_for_photo 命中',
    store.standard_for_photo(con, schema.UPLOAD_SENTINEL) is None)

# 造一张真照片 + 一条裁剪标准图，验证 crop 侧仍按 photo_id 命中
con.execute("INSERT INTO photos(id,file,path,batch_id,taken_at,created_at,"
            "govern_state) VALUES('p_stdupload','x.jpg','D:/x.jpg','b1',"
            "'2026-10-06T10:00:00','2026-10-06','done')")
con.execute("INSERT INTO links(code_norm,photo_id,source,created_at)"
            " VALUES('UP1','p_stdupload','manual','2026-10-06')")
con.commit()
crop = store.add_standard_image(con, 'UP1', 'p_stdupload', 'product',
                                jpg(1000, 1000), 1000, 1000, origin='crop')
_sfp = store.standard_for_photo(con, 'p_stdupload')
chk('S6 裁剪标准图仍能被 standard_for_photo 命中（老机制没坏）',
    _sfp is not None and _sfp['id'] == crop['id'],
    _sfp['id'] if _sfp is not None else None)
chk('S6b 按 origin=crop 过滤只返回裁剪那一张',
    len(store.standard_images(con, 'UP1', origin='crop')) == 1
    and len(store.standard_images(con, 'UP1', origin='upload')) == 3)

# ── 3. 坏文件不阻断整批 ──────────────────────────────────────
bad = store.add_standard_upload(con, 'UP1', 'product', b'not-an-image', 'bad.jpg')
chk('S7 坏文件返回 error 而不是抛异常', bool(bad.get('error')), bad.get('error'))
chk('S7b 坏文件没进库，前面的 3 张不受影响',
    len(store.standard_images(con, 'UP1', origin='upload')) == 3)

# ── 4. 导出必须包含上传的图（老逻辑完全会漏）─────────────────
con.execute("UPDATE products SET photo_count=1 WHERE code_norm='UP1'")
con.commit()
out = os.path.join(tmp, 'export')
res = store.export_standard(con, out)
files = sorted(os.listdir(out))
csv_txt = open(os.path.join(out, 'standard_index.csv'), encoding='utf-8-sig').read()
chk('S8 导出结果含 4 张（3 上传 + 1 照片回退），uploaded=3',
    res['uploaded'] == 3 and res['photos'] == 4 and len(files) == 5,
    '%s | files=%s' % ({k: v for k, v in res.items() if k != 'dir'}, files))
chk('S9 同类多张用 _2/_3 序号，不互相覆盖',
    sum(1 for f in files if f.startswith('UP1_产品')) == 3
    and 'UP1_产品_2.jpg' in files and 'UP1_产品_3.jpg' in files, files)
chk('S10 CSV 记录图源为「标准图(上传:文件名)」可追溯',
    '标准图(上传:a.jpg)' in csv_txt and '标准图(上传:c.jpg)' in csv_txt)

# 关键回归：photo_count=0 但有上传图的产品也要被导出（旧 WHERE 会漏掉整条）
con.execute("UPDATE products SET photo_count=0 WHERE code_norm='UP1'")
con.commit()
out2 = os.path.join(tmp, 'export2')
res2 = store.export_standard(con, out2)
chk('S11 没关联照片（photo_count=0）但有上传图的产品仍被导出',
    res2['products'] == 1 and res2['uploaded'] == 3,
    '%s' % ({k: v for k, v in res2.items() if k != 'dir'},))

con.close()
shutil.rmtree(tmp, ignore_errors=True)

print('----')
print('%d 项检查，%d 失败' % (13, len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')