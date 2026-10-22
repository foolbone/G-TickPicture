# -*- coding: utf-8 -*-
"""候选映射的落盘缓存与内容戳（2026-10-17，为「照片库/③打开卡 4 秒」修）。

冷启动不再重算 cand_code_map（真实库 3 秒级）—— 靠 <数据目录>/_cand_cache.json。
本测试锁死四件事：
  1 冷算 → 落盘 → 清内存后再取 = 磁盘命中（且内容一致）；
  2 戳覆盖**过滤载荷维度**：改 photo_usage 必须让缓存失效（usage 进了
    _cand_filter_sql，漏了它磁盘缓存会永久撒谎 —— invalidate 只有 reject
    端点会调，覆盖不到改用途这条写路径）；
  3 _CAND_CACHE_VER 版本号不匹配 → 旧文件作废（过滤逻辑升级的防呆）；
  4 缓存文件损坏/不是 JSON → 静默重算，不炸。
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
# ⚠️ 顺序要紧：store.py 自己会把 tools/ 塞进 sys.path，build_library 才能被
#    import。先 import store。
from tools.productlib import store  # noqa: E402
import build_library as BL  # noqa: E402

tmp = tempfile.mkdtemp(prefix='pl_candcache_')
con = store.connect(os.path.join(tmp, 't.db'))
FAILS = []
CNT = [0]


def chk(name, ok, info=None):
    CNT[0] += 1
    print(('  [ OK ] ' if ok else '  [FAIL] ') + name + (
        '' if info is None else '  -> %s' % (info,)))
    if not ok:
        FAILS.append(name)


con.execute("INSERT INTO batches(id,name,kind,created_at)"
            " VALUES('b1','柜A','photos','2026-10-01')")
for c in ('C-AAA1', 'C-BBB2'):
    con.execute("INSERT INTO products(code,code_norm,name,created_at,updated_at)"
                " VALUES(?,?,?, '2026-10-01','2026-10-01')",
                (c, BL.normalize(c), '品' + c))


def mk(pid, vision=None, usage=None, kind='label'):
    con.execute(
        'INSERT INTO photos(id,file,path,batch_id,taken_at,time_src,bytes,md5,'
        'width,height,is_dup,group_idx,govern_state,photo_kind,vision_codes,'
        'created_at,photo_usage) '
        "VALUES(?,?,?,?,'2026-10-01T10:00:00','exif',100,?,"
        "800,600,0,0,'done',?,?,'2026-10-01T10:00:00',?)",
        (pid, '/x/' + pid, '/x/' + pid, 'b1', 'm' + pid, kind,
         json.dumps(vision) if vision else None, usage))
    return pid


mk('p_a', vision=['C-AAA1'])                  # 未分类 → 进候选
mk('p_sup', vision=['C-BBB2'], usage='监装')   # 监装 → 不进候选（10-16 口径）
con.commit()

N_A, N_B = BL.normalize('C-AAA1'), BL.normalize('C-BBB2')
cache_file = os.path.join(tmp, '_cand_cache.json')

# ── 1 冷算 → 落盘 → 磁盘命中 ──
store._CAND_CACHE.clear()
m1 = store.cand_code_map(con, force=True)
chk('1a 冷算结果正确（监装照片不进候选）',
    N_A in m1 and N_B not in m1, sorted(m1.keys()))
chk('1b 算完落盘', os.path.exists(cache_file))

store._CAND_CACHE.clear()               # 模拟重启：清掉进程内缓存
m2 = store.cand_code_map(con)
chk('1c 重启后磁盘命中且内容一致', m2 == m1,
    '%d vs %d 个编码' % (len(m2), len(m1)))
chk('1d 落盘文件带当前逻辑版本号',
    json.load(open(cache_file, encoding='utf-8')).get('ver')
    == store._CAND_CACHE_VER)

# ── 2 用途维度进戳 ──
store.set_photo_usage(con, 'p_sup', '预检', by='test')   # 监装 → 预检
con.commit()
store._CAND_CACHE.clear()
m3 = store.cand_code_map(con)
chk('2a 改用途后缓存失效（照片进候选了）', N_B in m3, sorted(m3.keys()))
store.set_photo_usage(con, 'p_sup', '监装', by='test')   # 改回去，还原现场
con.commit()

# ── 3 版本号防呆 ──
d = json.load(open(cache_file, encoding='utf-8'))
d['ver'] = store._CAND_CACHE_VER - 1        # 旧逻辑版本
with open(cache_file, 'w', encoding='utf-8') as f:
    json.dump(d, f)
store._CAND_CACHE.clear()
m4 = store.cand_code_map(con)
chk('3 版本号过期 → 旧文件作废、重算（内容仍正确）',
    N_A in m4 and N_B not in m4, sorted(m4.keys()))

# ── 4 损坏文件兜底 ──
with open(cache_file, 'w', encoding='utf-8') as f:
    f.write('{这不是 JSON')
store._CAND_CACHE.clear()
try:
    m5 = store.cand_code_map(con)
    chk('4 缓存损坏 → 静默重算不炸',
        N_A in m5 and N_B not in m5, sorted(m5.keys()))
except Exception as e:  # noqa: BLE001
    chk('4 缓存损坏 → 静默重算不炸', False, repr(e))

con.close()
shutil.rmtree(tmp, ignore_errors=True)
print('\n%d 项检查，%d 失败' % (CNT[0], len(FAILS)))
if FAILS:
    print('FAILED: ' + '; '.join(FAILS))
    sys.exit(1)
print('ALL PASS')
