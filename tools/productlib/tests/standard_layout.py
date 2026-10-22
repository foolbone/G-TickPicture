# -*- coding: utf-8 -*-
"""标准图落盘布局：data/standard/<编码>/<类别>[_n].jpg + 历史扁平迁移。

跑法：python tools/productlib/tests/standard_layout.py
"""
import os, sys, shutil, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from tools.productlib import store, schema  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_stdlayout_')
db = os.path.join(tmp, 't.db')
store.STANDARD_DIR = os.path.join(tmp, 'standard')   # 防污染真实标准图目录
con = store.connect(db)


def chk(name, ok, extra=''):
    print(('[ OK ] ' if ok else '[FAIL] ') + name + ('  ' + extra if extra else ''))


def jpg(b=1234):
    return b'x' * b   # 任意字节，store 不校验图片内容


# ── L1 新图落盘进产品子文件夹、可读命名 ───────────────────────────
r1 = store.add_standard_image(con, '103011013388A', 'p1', 'product', jpg())
exp1 = os.path.join(store.STANDARD_DIR, '103011013388A', '产品.jpg')
chk('L1a 文件落在 <编码>/产品.jpg', r1['file'] == exp1 and os.path.exists(exp1), r1['file'])

r2 = store.add_standard_image(con, '103011013388A', 'p1', 'product', jpg())
exp2 = os.path.join(store.STANDARD_DIR, '103011013388A', '产品_2.jpg')
chk('L1b 同类第2张加 _2', r2['file'] == exp2 and os.path.exists(exp2), r2['file'])

r3 = store.add_standard_image(con, '103011013388A', 'p1', 'label', jpg())
exp3 = os.path.join(store.STANDARD_DIR, '103011013388A', '标识卡.jpg')
chk('L1c 不同类别独立命名', r3['file'] == exp3 and os.path.exists(exp3), r3['file'])

# 另一产品独立文件夹
r4 = store.add_standard_image(con, '2000000222B', 'p2', 'product', jpg())
exp4 = os.path.join(store.STANDARD_DIR, '2000000222B', '产品.jpg')
chk('L1d 不同产品独立文件夹', r4['file'] == exp4 and os.path.exists(exp4), r4['file'])


# ── L2 历史扁平文件迁移进子文件夹 ─────────────────────────────────
legacy_sid = 'aabbccddeeff'
legacy_fp = os.path.join(store.STANDARD_DIR, legacy_sid + '.jpg')
with open(legacy_fp, 'wb') as f:
    f.write(jpg(999))
con.execute('INSERT INTO standard_images(id,code_norm,src_photo_id,kind,file,'
            'width,height,created_at,created_by,origin,orig_name)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (legacy_sid, '103011013388A', 'pX', 'packaging', legacy_fp,
             10, 10, store.now_iso(), 'user', 'crop', None))
con.commit()
chk('L2a 迁移前扁平文件在位', os.path.exists(legacy_fp))

store._migrate_standard_layout(con)
row = con.execute('SELECT file FROM standard_images WHERE id=?', (legacy_sid,)).fetchone()
exp_legacy = os.path.join(store.STANDARD_DIR, '103011013388A', '包装.jpg')
chk('L2b 迁移后文件进子文件夹', row['file'] == exp_legacy and os.path.exists(exp_legacy), row['file'])
chk('L2c 原扁平文件已移走', not os.path.exists(legacy_fp))

# 幂等：再跑一次不应报错、路径不变、不重复移动
store._migrate_standard_layout(con)
row2 = con.execute('SELECT file FROM standard_images WHERE id=?', (legacy_sid,)).fetchone()
chk('L2d 幂等（路径稳定）', row2['file'] == exp_legacy)


# ── L3 删图后空文件夹被清理 ───────────────────────────────────────
# 删掉 2000000222B 的唯一标准图 → 该文件夹应被删
store.delete_standard_image(con, r4['id'])
chk('L3a 删图后产品文件夹被清理', not os.path.exists(os.path.dirname(exp4)))

# 删掉 103011013388A 全部 → 文件夹清理
for sid in (r1['id'], r2['id'], r3['id'], legacy_sid):
    store.delete_standard_image(con, sid)
chk('L3b 全删后产品文件夹被清理', not os.path.exists(os.path.join(store.STANDARD_DIR, '103011013388A')))

shutil.rmtree(tmp, ignore_errors=True)
print('\n[done] standard_layout')
