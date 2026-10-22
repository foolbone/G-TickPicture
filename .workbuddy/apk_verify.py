import os, sys, zipfile, datetime

APK = r'D:\G-TickPicture\app\build\app\outputs\flutter-apk\app-release.apk'
out = []
st = os.stat(APK)
out.append(f"SIZE={st.st_size}")
out.append(f"MTIME={datetime.datetime.fromtimestamp(st.st_mtime).isoformat()}")

z = zipfile.ZipFile(APK)
libs = [n for n in z.namelist() if n.endswith('libapp.so')]
out.append(f"LIBAPP_COUNT={len(libs)}: {libs}")
targets = [
    'gallery.last_viewed_id',           # 61: id 主键 SharedPreferences key
    '已回到上次浏览位置附近',             # 修复: 跳转闭环降级文案（第三击新代码指纹）
    '上次浏览的照片已不在',               # 61: 恢复失败 SnackBar
    'gallery.last_bucket',
]
for t in targets:
    encs = {
        'u8': t.encode('utf-8'),
        'u16le': t.encode('utf-16-le'),
    }
    found = [n for n in libs if any(e in z.read(n) for e in encs.values())]
    out.append(f"HIT {t} -> {found if found else 'MISS'}")

with open(r'D:\G-TickPicture\.workbuddy\apk_verify.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('DONE')
