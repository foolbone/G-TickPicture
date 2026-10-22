# -*- coding: utf-8 -*-
"""复现：61 张照片分页，offset=60 是否返回第 61 张（诊断 chk13）。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

PORT = 8799
DBHOME = os.path.join(tempfile.gettempdir(), 'pl_diag_pagedb')
PY = sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

shutil.rmtree(DBHOME, ignore_errors=True)
os.makedirs(DBHOME, exist_ok=True)
srv = subprocess.Popen([PY, '-m', 'tools.productlib.server', '--port', str(PORT)],
                       env={**os.environ, 'PL_HOME': DBHOME}, cwd=REPO,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def http_json(path, retries=60):
    for _ in range(retries):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d%s' % (PORT, path),
                                        timeout=8) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return None


def post_json(path, obj):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path),
                                 data=json.dumps(obj).encode('utf8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def post_file(path, fields, files):
    b = '----diag' + str(int(time.time()))
    buf = b''
    for k, v in fields.items():
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                % (b, k, v)).encode('utf8')
    for k, fp, fn in files:
        with open(fp, 'rb') as f:
            data = f.read()
        buf += ('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n' % (b, k, fn)).encode('utf8')
        buf += data + b'\r\n'
    buf += ('--%s--\r\n' % b).encode('utf8')
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=buf,
                                 headers={'Content-Type':
                                          'multipart/form-data; boundary=%s' % b})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode('utf-8'))


try:
    http_json('/api/ping')
    post_json('/api/products', {'code': 'DIAG-A1', 'name': 'x'})
    c = post_json('/api/containers', {'container_no': 'DIAG01', 'seal_no': 'S',
                                      'inspector': 'diag'})
    cid = c['id']
    from PIL import Image  # noqa: E402
    tmpd = os.path.join(tempfile.gettempdir(), 'pl_diag_photos')
    shutil.rmtree(tmpd, ignore_errors=True)
    os.makedirs(tmpd)
    files = []
    for i in range(61):
        p = os.path.join(tmpd, 'D_%03d.jpg' % i)
        Image.new('RGB', (1200, 900), (40 + i % 200, 110, 170)).save(p)
        files.append(('files', p, os.path.basename(p)))
    r = post_file('/api/photos/upload', {'container_id': cid}, files)
    print('upload added=%s' % r.get('added'))
    time.sleep(2)
    for off in (0, 55, 59, 60, 61):
        d = http_json('/api/photos?container_id=%s&limit=60&offset=%d' % (cid, off)) or {}
        ids = [x['id'] for x in (d.get('items') or [])]
        print('offset=%-3d total=%s items=%d first=%s last=%s'
              % (off, d.get('total'), len(ids), ids[0][:6] if ids else '-',
                 ids[-1][:6] if ids else '-'))
    # 连续两遍，验确定性
    a = [x['id'] for x in (http_json(
        '/api/photos?container_id=%s&limit=60&offset=60' % cid) or {}).get('items') or []]
    b2 = [x['id'] for x in (http_json(
        '/api/photos?container_id=%s&limit=60&offset=60' % cid) or {}).get('items') or []]
    print('offset=60 两遍一致: %s (%s vs %s)' % (a == b2, len(a), len(b2)))
finally:
    srv.terminate()
