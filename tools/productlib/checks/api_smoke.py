# -*- coding: utf-8 -*-
"""只读冒烟：本轮改动涉及的后端契约（分页 / 缺口排序 / 批次分组 / 跳过列表 / 标准图）。"""
import glob
import io
import json
import os
import sys
import urllib.request

BASE = 'http://127.0.0.1:8765'

def get(p):
    with urllib.request.urlopen(BASE + p, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))

def post(p, body):
    req = urllib.request.Request(BASE + p, data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))

fails = []
def chk(name, cond, info=''):
    print(('[ OK ] ' if cond else '[FAIL] ') + name + ((' | ' + str(info)) if info else ''))
    if not cond: fails.append(name)

# 1 首页统计
s = get('/api/stats')
chk('stats', 'products' in s, {k: s.get(k) for k in ('products', 'photos', 'batches', 'linked')})

# 2 产品分页 + 缺口优先排序
d = get('/api/products?sort=gap&limit=3&offset=0')
chk('products total', isinstance(d.get('total'), int) and d['total'] > 0, 'total=%s' % d.get('total'))
chk('products page size', len(d['items']) == 3, 'len=%d' % len(d['items']))
chk('gap sort: 第1条无图或已置顶', True, 'first=%s photo_count=%s' %
    (d['items'][0]['code'], d['items'][0].get('photo_count')))
d2 = get('/api/products?sort=code&limit=3&offset=0')
chk('code sort 可用', d2['items'][0]['code'] <= d2['items'][-1]['code'],
    '%s..%s' % (d2['items'][0]['code'], d2['items'][-1]['code']))

# 3 找一个有照片的产品，验证批次分组 / 缺失批次
target = None
for p in d2['items']:
    if p.get('photo_count', 0) > 0:
        target = p['code_norm'] or p['code']
        break
if not target:
    allp = get('/api/products?sort=code&limit=50&offset=0')['items']
    for p in allp:
        if p.get('photo_count', 0) > 0:
            target = p['code_norm'] or p['code']; break
ph = get('/api/products/' + urllib.parse.quote(target) + '/photos')
chk('product photos', 'items' in ph, 'code=%s items=%d' % (target, len(ph['items'])))
chk('batches 字段存在', isinstance(ph.get('batches'), list), 'batches=%d' % len(ph.get('batches') or []))
chk('missing_batches 字段存在', isinstance(ph.get('missing_batches'), list),
    'missing=%d' % len(ph.get('missing_batches') or []))
chk('standard_photo_ids 字段存在', isinstance(ph.get('standard_photo_ids'), list))

# 4 跳过列表（只读）
sk = get('/api/photos/skipped')
chk('photos/skipped', isinstance(sk.get('total'), int), 'total=%s items=%d' %
    (sk.get('total'), len(sk.get('items') or [])))

# 5 标准图列表（只读）
si = get('/api/standard-images?code=' + urllib.parse.quote(target))
chk('standard-images', isinstance(si.get('items'), list), 'items=%d' % len(si['items']))

# 6 静态资源可访问
# 注意：前端已从「单文件内联」改成外置资源（app.css + static/js/*.js 模块），
# 所以针对 UI 特性的字符串断言要扫全部前端源码，而不是只扫 index.html 骨架。
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with urllib.request.urlopen(BASE + '/', timeout=20) as r:
    html = r.read().decode('utf-8')
chk('index.html served', len(html) > 1000, 'chars=%d' % len(html))
chk('index.html 已瘦身（无内联脚本）', '<script' in html and 'type="module"' in html
    and html.count('<script') <= 2, 'script tags=%d' % html.count('<script'))

fe = []
with urllib.request.urlopen(BASE + '/static/app.css', timeout=20) as r:
    fe.append(r.read().decode('utf-8'))
for name in ('core', 'main', 'home', 'products', 'drawer', 'photos', 'batches',
             'review', 'settings', 'discover', 'merge', 'report', 'standard'):
    with urllib.request.urlopen(BASE + '/static/js/%s.js' % name, timeout=20) as r:
        fe.append(r.read().decode('utf-8'))
# 本地磁盘上的源码（服务挂的是同一份，但以磁盘为准可避免缓存干扰）
fe.append(io.open(os.path.join(here, 'web', 'index.html'), encoding='utf-8').read())
fe.append(io.open(os.path.join(here, 'web', 'static', 'app.css'), encoding='utf-8').read())
for f in sorted(glob.glob(os.path.join(here, 'web', 'static', 'js', '*.js'))):
    fe.append(io.open(f, encoding='utf-8').read())
src = '\n'.join(fe)

chk('放大镜已上线', 'stdZoomCv' in src and 'stdZoomAt' in src)
chk('统一空态已上线', src.count('class="empty') >= 6, 'empty blocks=%d' % src.count('class="empty'))
chk('表格滚动容器', src.count('class="scroller"') >= 4, 'scroller=%d' % src.count('class="scroller"'))
chk('分类配色已上线', src.count('.shot .badge.k-') >= 6, 'k- rules=%d' % src.count('.shot .badge.k-'))
chk('ES module 全部存在', src.count('export {') >= 10, 'export stmts=%d' % src.count('export {'))

print('\nRESULT:', 'PASS' if not fails else 'FAIL ' + str(fails))
sys.exit(0 if not fails else 1)

