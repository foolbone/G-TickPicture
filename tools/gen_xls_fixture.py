#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 BIFF8 .xls 测试夹具（供 app/test/checklist_file_reader_test.dart 使用）。

为什么要生成夹具而不是用真实的客户清单：
  客户清单涉及商业信息，不能进仓库；而单测必须能在任何机器上跑。
  所以用一个内容可控、覆盖关键解析分支的小文件。

夹具覆盖的解析分支：
  · SST 共享字符串（含中文 → 走 UTF-16LE 路径）
  · RK 整数编码（20 / 40）
  · RK 浮点编码（18.5）—— 这一项最容易解错，必须有
  · 空工作表（无单元格 → 解析时应被跳过）
  · 多工作表（BOUNDSHEET 索引）

用法：
  python tools/gen_xls_fixture.py
  # 需要 xlwt：pip install xlwt
"""
import base64
import os

try:
    import xlwt
except ImportError:
    raise SystemExit('需要 xlwt：pip install xlwt')

OUT_DART = os.path.join('app', 'test', 'fixtures', 'xls_fixture.dart')
TMP_XLS = os.path.join(os.environ.get('TEMP', '/tmp'), 'gt_fixture.xls')


def build():
    wb = xlwt.Workbook(encoding='utf-8')

    ws = wb.add_sheet('清单')
    header = ['货品编码', '品名', '规格', '数量']
    for c, h in enumerate(header):
        ws.write(0, c, h)
    rows = [
        ['BOX-M11', 'Plate', '100x200', 20],
        ['BOX-M13', '轴套', 'Φ30', 40],
        ['RACK-M8-1', '方管', 'M8', 18.5],
    ]
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row):
            ws.write(r, c, v)

    # 空表：只有名字，没有任何单元格
    wb.add_sheet('空表')

    # 第二个有数据的表：验证多表与 BOUNDSHEET 索引
    ws3 = wb.add_sheet('第二表')
    ws3.write(0, 0, 'A')
    ws3.write(1, 0, 'B')

    wb.save(TMP_XLS)
    return open(TMP_XLS, 'rb').read()


def main():
    raw = build()
    b64 = base64.b64encode(raw).decode()
    lines = [b64[i:i + 72] for i in range(0, len(b64), 72)]
    body = '\n'.join("    '" + l + "'" for l in lines)
    out = (
        '// 自动生成 —— 请勿手改。\n'
        '// 生成方式：tools/gen_xls_fixture.py\n'
        '// 真实 BIFF8 .xls 夹具（xlwt 生成，%d 字节）：\n'
        '//   Sheet「清单」：中文表头 + 3 行数据（含中文、整数、浮点）\n'
        '//   Sheet「空表」：无单元格（解析时应被跳过）\n'
        '//   Sheet「第二表」：2 行单列\n'
        '// ignore_for_file: prefer_single_quotes\n'
        'const String kXlsFixtureBase64 =\n' % len(raw)
    ) + body + ';\n'

    os.makedirs(os.path.dirname(OUT_DART), exist_ok=True)
    with open(OUT_DART, 'w', encoding='utf-8', newline='\n') as f:
        f.write(out)
    print('生成 %s（原始 %d 字节，base64 %d 字符）' % (OUT_DART, len(raw), len(b64)))


if __name__ == '__main__':
    main()
