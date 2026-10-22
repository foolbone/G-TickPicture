# -*- coding: utf-8 -*-
"""
build_library.py -- 历史预检照片产品库 / 建库工具（P1）

═══════════════════════════════════════════════════════════════════════
这个工具做什么
═══════════════════════════════════════════════════════════════════════
把「一批散乱的历史作业素材」变成「一个可按编码召回的产品库」。

输入（只读，绝不修改）：
  · 一个目录下的历史照片（IMG_20250405_083614.jpg 这类）
  · 一份或多份清单（xls/xlsx，含编码列）
  · 可选：一份或多份报关单（xlsx，含料号列）—— 用于交叉印证

输出：
  · library.db            SQLite：编码 ↔ 照片 ↔ 绑定强度 ↔ 来源
  · _编码对照表.csv        编码 / 品名 / 张数 / 时间 / 绑定级别（人眼过的界面）
  · _待复核.csv            B/C 级记录清单（人工过一遍 → 升级或删除）
  · _建库报告.md           本次建库的统计与"哪些编码没入库"

═══════════════════════════════════════════════════════════════════════
★ 最重要的设计决定：绑定强度分级，且不假装 OCR 很准
═══════════════════════════════════════════════════════════════════════
实测（doc/PP-OCRv6_真实数据基线报告.md，249 张真实照片）：
  · 照片命中率 2.8%，清单覆盖率 21%
  · 唯一高效路径是「装箱单近拍」，一张可命中 13 个编码
  · 标识卡（手写）是纯噪声

因此本工具**不做自动归档**。它对每张照片/每个分组给出一个
绑定级别，级别只决定"人工复核的优先级"，不决定"是否入库"：

  A_strong  人工确认（含既往交付包里的对照表 CSV）
  B_ocr_multi   同一张/同一组里 OCR 命中 ≥2 个编码（大概率是装箱单近拍）
  B_ocr_single  只命中 1 个编码
  C_adjacent    本张无命中，但时间上紧邻有命中的照片（推断，仅供提示）

═══════════════════════════════════════════════════════════════════════
★ 与 APP 的口径一致性（这是本工具最容易被写错的地方）
═══════════════════════════════════════════════════════════════════════
归一化 / 形近纠偏 / 三级匹配 / 编辑距离，全部**逐条复刻**
app/lib/domain/search/code_matcher.dart，不是"差不多就行"：

  · normalize：先全角转半角 → 大写 → 删 [\\s-_·．。,，、/\\.]（顺序不能反）
  · 纠偏表只有 O→0 / I→1 / L→1 / S→5，且**只在原样变体试过之后**才用
  · 纠偏只在「至少含一个数字、长度≥2 的连续段」里生效
  · 三级：exact 0.98 / 子串 0.86 / edit1 0.88 / edit2 0.72，再乘 token 置信度
  · 编辑距离 max=2，token 长度下限 3

若 APP 侧改了这些参数，本文件必须同步改，否则库里存的"建议"和
APP 现场算出来的对不上，人工复核的依据就失真了。

═══════════════════════════════════════════════════════════════════════
用法
═══════════════════════════════════════════════════════════════════════
  # 1) 先干跑，只看统计不落盘（推荐第一次这么用）
  python tools/build_library.py --photos doc/PIDU9352234 --dry-run

  # 2) 真跑（OCR 全量，249 张约 5~10 分钟）
  python tools/build_library.py --photos doc/PIDU9352234 --out library

  # 3) 跳过 OCR，只用清单构建骨架（秒级，用于验证清单解析）
  python tools/build_library.py --photos doc/PIDU9352234 --no-ocr --out library

  # 4) 复用既往 OCR 结果（有 gt_ocr_eval_out.json 时可省掉重跑）
  python tools/build_library.py --photos doc/PIDU9352234 \
      --ocr-cache "%TEMP%/gt_ocr_eval_out.json" --out library

⚠️ 本工具对源照片**只读**（不解码后回写、不改名、不移动）。
   所有输出都落在 --out 指定的目录里。
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════
# 与 APP 的对齐参数（改这里之前先看 app/lib/core/constants.dart）
# ═══════════════════════════════════════════════════════════════════

GROUP_GAP_SEC = 45          # AppConst.groupGap
# 每组张数上限：只作**安全阀** —— 主力那批照片是 0~2 秒一张的连续流
# （p50=0s / p90=2s），45 秒间隔根本切不开（实测无上限时最大组 412 张，
# 同组推荐会一次列出 400 张，没人用得了）。所以保留上限，但 12 → 30：
# 一次连拍十几张是常态，不该被 12 张切断；30 张足够容纳，又不会失控。
# （App 侧 09-29 已改成「按批次一组」，不读这个常量。）
GROUP_MAX_PHOTOS = 30       # AppConst.groupMaxPhotos（仅作安全阀）

MATCH_BASE_EXACT = 0.98     # AppConst.matchBaseExact
MATCH_BASE_PREFIX = 0.86    # AppConst.matchBasePrefix
MATCH_BASE_EDIT1 = 0.88     # AppConst.matchBaseEdit1
MATCH_BASE_EDIT2 = 0.72     # AppConst.matchBaseEdit2
MATCH_MAX_EDIT = 2          # AppConst.matchMaxEditDistance
MATCH_MIN_TOKEN_LEN = 3     # AppConst.matchMinTokenLength

CONFUSABLES = {'O': '0', 'I': '1', 'L': '1', 'S': '5'}

# OCR 参数（与 tools/pc_ocr_probe.py / OnnxPpOcrEngine.kt 一致）
DET_TARGET_PIXELS = 700_000
MAX_REC_CROPS = 40
FOUR_DIR_CONF = 0.85        # 四方向兜底阈值

PHOTO_EXT = ('.jpg', '.jpeg', '.png')

# 编码样式：连续 8~13 位「数字开头」的字母数字串。
# 用于从 OCR token 里粗筛"像编码的东西"，再交给正式匹配。
# 注意用 fullmatch 而不是 search —— `LOT 103011023056A QTY` 这种
# 带上下文的长 token 应该在匹配阶段用"子串模式"处理，不是在这里截。
CODE_LIKE_RE = re.compile(r'[0-9][0-9A-Z]{7,12}')


# ═══════════════════════════════════════════════════════════════════
# 一、归一化与匹配（逐条复刻 code_matcher.dart）
# ═══════════════════════════════════════════════════════════════════

def to_half_width(s):
    """全角 → 半角。U+3000 变普通空格，U+FF01~U+FF5E 平移 0xFEE0。"""
    out = []
    for ch in s:
        r = ord(ch)
        if r == 0x3000:
            out.append(' ')
        elif 0xFF01 <= r <= 0xFF5E:
            out.append(chr(r - 0xFEE0))
        else:
            out.append(ch)
    return ''.join(out)


_SEP_RE = re.compile(r'[\s\-_·．。,，、/\\.]')


def normalize(raw):
    """基础归一化。顺序不可反：先全角转半角，再删分隔符。

    反过来的话，全角 `－` 会躲过删除、转换后残留成 `-`。
    """
    s = to_half_width(raw.strip()).upper()
    return _SEP_RE.sub('', s)


def _apply_confusables(s):
    """只在「至少含一个数字、长度≥2 的连续段」里替换形近字符。

    刻意不做"数字占多数"的严格判定 —— 会把 GHI33OO 这类段漏掉。
    因为纠偏结果只作为备选变体、原样变体永远先试，放宽是安全的。
    """
    seg_re = re.compile('[0-9' + re.escape(''.join(CONFUSABLES.keys())) + ']+')
    buf = []
    i = 0
    while i < len(s):
        m = seg_re.match(s, i)
        if m and len(m.group(0)) >= 2:
            seg = m.group(0)
            if any(c.isdigit() for c in seg):
                buf.append(''.join(CONFUSABLES.get(c, c) for c in seg))
            else:
                buf.append(seg)
            i += len(seg)
        else:
            buf.append(s[i])
            i += 1
    return ''.join(buf)


def _strip_numeric_tail(raw):
    """整数值的数字文本去掉小数点与尾零：`1000000119.0` → `1000000119`。

    ⚠️ 必须在 normalize() **之前**调用。`_SEP_RE` 里含 `\\.`，
       normalize 会把 `1000000119.0` 直接压成 `10000001190`（尾部多一个 0），
       与另一份文件里的文本型 `1000000119` 对不上 —— 这正是 `_cell()`
       文档里描述的假差异陷阱，只是它只在读表时处理，照片 OCR 出的
       **文本**没人管。

    只在「整个串就是数字」时才动（_NUM_TEXT_RE），所以：
      · 编码 `1000000119.0` → `1000000119`（真编码，要匹配）；
      · 规格 `1.20` → `1.2`、`1.5` 原样（本来就是数值，不是编码）；
      · 混合串 `A1000000119.0B` 不动（不是纯数字，不确定就不猜）。
    不用 int() 转换 —— 长编码超过 2^53 会丢精度。
    """
    s = to_half_width(str(raw).strip()).upper()
    if not _NUM_TEXT_RE.match(s):
        return s
    if '.' not in s:
        return s
    head, _, tail = s.partition('.')
    if not tail:
        return s
    stripped = tail.rstrip('0')
    if not stripped:
        # 全是 0（`100.` / `100.000`）→ 整数，去掉点
        return head
    return head + stripped


def variants(raw):
    """匹配变体。第一个永远是原样归一化结果。"""
    basic = normalize(raw)
    out = [basic]
    # 数字尾零形态是**独立变体**，不替换 basic：
    # 清单里可能真有个编码就叫 `1000000119.0`，
    # 原样必须先试（exact 优先），补形态只作兜底。
    alt = normalize(_strip_numeric_tail(raw))
    if alt and alt != basic:
        out.append(alt)
    fixed = _apply_confusables(basic)
    if fixed not in out:
        out.append(fixed)
    return out


def levenshtein(a, b, cap=MATCH_MAX_EDIT):
    """带提前退出的编辑距离。超出 cap 返回 cap+1。"""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    cur = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur[0] = i
        row_min = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j - 1] + cost, prev[j] + 1, cur[j - 1] + 1)
            cur[j] = v
            if v < row_min:
                row_min = v
        if row_min > cap:
            return cap + 1
        prev, cur = cur, prev
    return prev[len(b)] if prev[len(b)] <= cap else cap + 1


class CodeIndex:
    """清单编码索引。等价于 Dart 侧的 CodeMatcher（只保留匹配部分）。"""

    def __init__(self, entries):
        # entries: [(code, name, spec)] —— 归一化后取第一条
        self._index = {}
        self._all = []
        for code, name, spec in entries:
            self._all.append((code, name, spec))
            self._index.setdefault(normalize(code), (code, name, spec))
            # 🔴 数字型编码的**两种形态**都要进索引，不能只存 normalize 结果。
            # `_SEP_RE` 含 `\.`，所以 normalize('1000000119.0') = '10000001190'，
            # 而照片 OCR 出的文本 `1000000119` 归一后是 '1000000119' ——
            # 两者对不上，exact 匹配退化成 edit1（0.817 分，够不着
            # AUTO_LINK_THRESHOLD 0.70 之外的自动关联门槛口径）。
            # 真实场景：xls 里 Model Number 列是数字型、报关单料号列是文本型，
            # 同一批货两个形态都存在（PIDU9352234 实测）。
            # 两侧都归一去尾零后建键，谁先来谁为准。
            alt = normalize(_strip_numeric_tail(code))
            if alt:
                self._index.setdefault(alt, (code, name, spec))

    def __len__(self):
        return len(self._all)

    @property
    def codes(self):
        return [c for c, _, _ in self._all]

    def best(self, token_text, token_conf):
        """返回 (code, name, score, mode) 或 None。"""
        best_cand = None
        for v in variants(token_text):
            if len(v) < MATCH_MIN_TOKEN_LEN:
                continue
            c = self._best_for_variant(v, token_conf)
            if c and (best_cand is None or c[2] > best_cand[2]):
                best_cand = c
        return best_cand

    def _best_for_variant(self, n, token_conf):
        # ① 完全相等
        hit = self._index.get(n)
        if hit:
            return (hit[0], hit[1], min(1.0, MATCH_BASE_EXACT * token_conf), 'exact')

        # ② 清单编码是 token 的子串（照片上多识别出前后缀）
        for key, val in self._index.items():
            if len(key) >= 4 and key in n:
                return (val[0], val[1], min(1.0, MATCH_BASE_PREFIX * token_conf), 'prefix')

        # ③ 编辑距离 ≤ 2（长度差预筛）
        best_cand = None
        for key, val in self._index.items():
            if abs(len(key) - len(n)) > MATCH_MAX_EDIT:
                continue
            d = levenshtein(n, key)
            if d == 0 or d > MATCH_MAX_EDIT:
                continue
            base = MATCH_BASE_EDIT1 if d == 1 else MATCH_BASE_EDIT2
            score = min(1.0, base * token_conf)
            if best_cand is None or score > best_cand[2]:
                best_cand = (val[0], val[1], score, 'edit%d' % d)
        return best_cand


# ═══════════════════════════════════════════════════════════════════
# 二、清单 / 报关单 读取
# ═══════════════════════════════════════════════════════════════════

# 编码列名关键词（与 app/lib/domain/checklist/column_mapper.dart 同源）
CODE_HEADER_HINTS = [
    'modelnumber', 'modelno', 'model', 'partnumber', 'partno',
    'materialcode', 'itemcode', 'itemno', 'code',
    '物料编码', '物料编号', '料号', '编码', '型号', '货号', '品号',
]
NAME_HEADER_HINTS = ['description', 'desc', 'name', '品名', '名称', '描述', '货名']
SPEC_HEADER_HINTS = ['spec', 'specification', '规格', '型号规格', 'modelo']
# ⚠️ 2026-10-05 拆成三个（装柜报告要 Order / Loading 两列 + 核对结果列）。
#
# 为什么必须拆：真实清单表头是
#   `Order Qty | Loading Qty | Quantity Check result`
# 旧版只有一个 `QTY_HEADER_HINTS = ['qty','quantity','数量','pcs']`，
# 归一化后 `orderqty` / `loadingqty` / `quantitycheckresult` 都**包含** `qty`
# —— 单列识别会三花一取（谁分最高算谁），Loading Qty 与核对结果直接丢。
# 现在精确词在前拿到满分，通用词只兜底。
ORDER_QTY_HEADER_HINTS = ['orderqty', 'orderquantity', 'order']
LOADING_QTY_HEADER_HINTS = ['loadingqty', 'loadingquantity', 'loading', 'loadedqty']
CHECK_RESULT_HEADER_HINTS = [
    'quantitycheckresult', 'checkresult', 'quantitycheck', 'check',
    '核对结果', '数量核对', '检验结果', '核对',
]
QTY_HEADER_HINTS = ['qty', 'quantity', '数量', 'pcs']   # 兼容旧调用方（兜底归 order）
CONTAINER_HEADER_HINTS = [
    # ⚠️ 2026-10-05 补 'package*'：真实装柜清单的箱数列叫 **Package Number**
    # （归一化后 `packagenumber`），不含 carton/container/箱 任何一个子串 ——
    # 旧 hints 全部漏掉，装柜报告的 Packing list 第三列会是空的。
    # 报告样例里那一列形如 Cage-M239 / Pallet-M56 / CENTER-M51。
    'packageno', 'packagenumber', 'package', 'packagesno',
    'carton', 'cartonno', 'container', '箱号', '包装箱', '箱', 'pallet', '托盘',
]


def _norm_header(s):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', str(s).lower())


def _score_header(h, hints):
    """表头与关键词的匹配分。返回 -1 表示不匹配。

    精确相等给最高分，包含给次高分，且**关键词越长越可信**
    ——避免 `model` 抢走 `modelnumber` 的列。
    """
    if not h:
        return -1
    best = -1
    for hint in hints:
        hn = _norm_header(hint)
        if not hn:
            continue
        if h == hn:
            best = max(best, 100 + len(hn))
        elif hn in h:
            best = max(best, 50 + len(hn))
    return best


def _read_sheet_rows(path):
    """读 xls/xlsx 的全部 sheet，返回 [(sheet_name, rows[[cell,...]])]。

    不引 pandas —— 建库工具要能在只有 openpyxl + xlrd 的机器上跑，
    而且我们要的是"原始二维表 + 自己做表头推断"，不是 pandas 的语义化表。
    """
    ext = os.path.splitext(path)[1].lower()
    sheets = []
    if ext == '.xlsx':
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            sheets.append((ws.title, rows))
    elif ext == '.xls':
        import xlrd
        wb = xlrd.open_workbook(path)
        for ws in wb.sheets():
            rows = []
            for i in range(ws.nrows):
                rows.append([ws.cell_value(i, j) for j in range(ws.ncols)])
            sheets.append((ws.name, rows))
    else:
        raise ValueError('不支持的表格格式: %s（只支持 .xls / .xlsx，csv 请手动转换）' % ext)
    return sheets


_NUM_TEXT_RE = re.compile(r'^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$')


def _cell(v):
    """单元格 → 字符串。

    ⚠️ 这里有一个必须处理的真实陷阱：xls/xlsx 里**纯数字编码会被存成
    float**，`str(1000000119.0)` → `'1000000119.0'`，归一化后变成
    `10000001190` —— 尾部多一个 0，与另一份文件里的文本型
    `'1000000119'` 对不上，编码集合交集凭空少一条。

    实测（PIDU9352234）：清单的 Model Number 列是数字型，报关单的
    料号列是文本型，同一批货直接出现「清单独有 10000001190 / 报关独有
    1000000119」的假差异。

    处理方式：整数性 float 去掉小数点与尾零，但**不用 int() 转换**
    —— 长编码超过 2^53 会丢精度，也避免把 `1.20` 这种规格值误伤成 `1.2`。
    """
    if v is None:
        return ''
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ''
        if v.is_integer():
            return str(int(v))
        return repr(v).rstrip('0').rstrip('.')
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


def parse_checklist(path, verbose=True):
    """从清单文件里抽出货品条目。

    返回 (items, meta)：
      items = [{code, name, spec, qty, container, seq,
                order_qty, loading_qty, check_result, package_no}]
      meta  = {file, sheet, header_row, col_map, raw_rows, note_rows}

    表头行自动定位：在前 15 行里找「编码列 + 至少一个其它列」同时命中的行。
    这是必要的 —— 实测清单表头在第 0 行，但报关单在前 11 行（前面全是抬头）。

    ⚠️ 2026-10-05 扩列：Order Qty / Loading Qty / Quantity Check result。
    装柜报告的 Packing list 区块要这三列（与客户清单表头一字不差）。
    每列的 hints 独立打分，**同一列不许被两个字段认领** ——
    `orderqty` 与 `loadingqty` 都含 `qty` 子串，不做互斥会出现两列都取到同一列。
    """
    sheets = _read_sheet_rows(path)
    best = None

    for sheet_name, rows in sheets:
        scan = min(15, len(rows))
        for hi in range(scan):
            row = rows[hi]
            cidx = nidx = sidx = qidx = kcidx = -1
            oqidx = lqidx = cridx = -1
            for j, cell in enumerate(row):
                h = _norm_header(_cell(cell))
                if not h:
                    continue
                s = _score_header(h, CODE_HEADER_HINTS)
                if s > 0 and (cidx < 0 or s > _score_header(_norm_header(_cell(row[cidx])), CODE_HEADER_HINTS)):
                    cidx = j
                s = _score_header(h, NAME_HEADER_HINTS)
                if s > 0 and (nidx < 0 or s > _score_header(_norm_header(_cell(row[nidx])), NAME_HEADER_HINTS)):
                    nidx = j
                s = _score_header(h, SPEC_HEADER_HINTS)
                if s > 0 and (sidx < 0 or s > _score_header(_norm_header(_cell(row[sidx])), SPEC_HEADER_HINTS)):
                    sidx = j
                # Order / Loading / Check 三列：先各自打分，再统一做互斥分配
                s = _score_header(h, ORDER_QTY_HEADER_HINTS)
                if s > 0 and (oqidx < 0 or s > _score_header(
                        _norm_header(_cell(row[oqidx])), ORDER_QTY_HEADER_HINTS)):
                    oqidx = j
                s = _score_header(h, LOADING_QTY_HEADER_HINTS)
                if s > 0 and (lqidx < 0 or s > _score_header(
                        _norm_header(_cell(row[lqidx])), LOADING_QTY_HEADER_HINTS)):
                    lqidx = j
                s = _score_header(h, CHECK_RESULT_HEADER_HINTS)
                if s > 0 and (cridx < 0 or s > _score_header(
                        _norm_header(_cell(row[cridx])), CHECK_RESULT_HEADER_HINTS)):
                    cridx = j
                s = _score_header(h, QTY_HEADER_HINTS)
                if s > 0 and (qidx < 0 or s > _score_header(_norm_header(_cell(row[qidx])), QTY_HEADER_HINTS)):
                    qidx = j
                s = _score_header(h, CONTAINER_HEADER_HINTS)
                if s > 0 and (kcidx < 0 or s > _score_header(_norm_header(_cell(row[kcidx])), CONTAINER_HEADER_HINTS)):
                    kcidx = j
            # 互斥分配：Order → Loading → Check → 通用 qty（已被占用的列跳过）
            oqidx, lqidx, cridx, qidx = _dedupe_qty_cols(
                oqidx, lqidx, cridx, qidx, row)
            if cidx < 0:
                continue
            # 至少要两个列名命中，避免把数据行误判成表头
            hits = sum(1 for x in (cidx, nidx, sidx, qidx, oqidx, lqidx, cridx, kcidx) if x >= 0)
            if hits < 2:
                continue
            cand = (hits, sheet_name, hi, cidx, nidx, sidx, qidx, kcidx,
                    oqidx, lqidx, cridx)
            if best is None or cand[0] > best[0]:
                best = cand

    if best is None:
        raise ValueError('在 %s 里找不到清单表头（需要至少一个编码列名 + 一个其它列名）' % path)

    _, sheet_name, hi, cidx, nidx, sidx, qidx, kcidx, oqidx, lqidx, cridx = best
    rows = dict(sheets)[sheet_name]

    def cell_at(row_cells, idx):
        if idx is None or idx < 0 or idx >= len(row_cells):
            return ''
        return row_cells[idx]

    items = []
    note_rows = 0
    carried_container = ''
    for r in rows[hi + 1:]:
        cells = [_cell(c) for c in r]
        # ── 备注行检测：扫**整行**，不能只看编码列 ──
        # 实测（PIDU9352234）最后一行是：
        #   ['NOTE.:1、103006010021CMX loaded into RACK M17;', '', '', '', '', '']
        # 备注文字落在**箱号列**（第 0 列），编码列是空的。
        # 只查编码列的话这行会被静默丢掉、且 note_rows 记成 0，
        # 报告里就看不出"清单里有一行没被当成货品"。
        row_text = ' '.join(cells)
        if re.match(r'^\s*(NOTE|备注|说明)', row_text, re.I) or \
                re.search(r'(NOTES?|备注|说明)\s*[:：.]', row_text, re.I):
            note_rows += 1
            continue

        raw_code = cells[cidx] if cidx < len(cells) else ''
        if not raw_code:
            continue
        ncode = normalize(raw_code)
        if len(ncode) < 4 or not re.search(r'\d', ncode):
            # 不像编码的行（如小计、合计、空行）
            note_rows += 1
            continue

        container = cell_at(cells, kcidx)
        if container:
            carried_container = container   # 向下填充：合并单元格视觉 → 稀疏填写
        name = cell_at(cells, nidx)
        spec = cell_at(cells, sidx)
        qty = cell_at(cells, qidx)
        # Order / Loading / 核对结果：三列都存**文本照抄**。
        # 真实清单里同一列出现过 `12` / `12.0` / "12 PCS" —— 强转数字会丢信息，
        # 而报告的 Packing list 区块要的就是原样。TOTAL 在报告生成时求和。
        order_qty = cell_at(cells, oqidx)
        loading_qty = cell_at(cells, lqidx)
        check_result = cell_at(cells, cridx)

        items.append({
            'code': raw_code,
            'code_norm': ncode,
            'name': name,
            'spec': spec,
            'qty': qty or order_qty,   # 兼容：只有一列 qty 时两个字段都指向它
            'order_qty': order_qty or qty,
            'loading_qty': loading_qty,
            'check_result': check_result,
            'container': carried_container,
            'package_no': carried_container,
            'seq': len(items) + 1,
        })

    meta = {
        'file': os.path.basename(path),
        'sheet': sheet_name,
        'header_row': hi,
        'col_map': {'code': cidx, 'name': nidx, 'spec': sidx, 'qty': qidx,
                    'container': kcidx, 'order_qty': oqidx,
                    'loading_qty': lqidx, 'check_result': cridx},
        'raw_rows': len(rows) - hi - 1,
        'note_rows': note_rows,
    }
    return items, meta


def _dedupe_qty_cols(oqidx, lqidx, cridx, qidx, header_row):
    """数量类列互斥分配：Order → Loading → Check → 通用 qty。

    为什么需要：归一化表头后 `orderqty` / `loadingqty` / `quantitycheckresult`
    都**包含** `qty` 子串，各自打分时都会命中通用 hints，于是三四个字段
    可能全认出同一列 —— 报告的 Loading Qty 会照抄 Order Qty 的值，
    而且这种错在数据上看不出来（两列数值常常相同）。

    规则：按业务优先级从高到低占列，已被占用的列对后面的字段不可见。
    """
    taken = set()

    def claim(idx):
        if idx is None or idx < 0 or idx in taken:
            return -1
        taken.add(idx)
        return idx

    oqidx = claim(oqidx)
    lqidx = claim(lqidx)
    cridx = claim(cridx)
    qidx = claim(qidx)
    # 通用 qty 列被更高优先级的字段占了 → 回退：order 取 loading/check/qty 里
    # 还没被占的那一列都不能乱认，宁可留空（报告里那一格空着，比填错好）
    return oqidx, lqidx, cridx, qidx


def merge_items(items):
    """同编码多行 → 合并（与 P4 诉求 1 的规则一致：数量累加、箱号收集）。"""
    merged = {}
    order = []
    for it in items:
        k = it['code_norm']
        if k not in merged:
            merged[k] = dict(it)
            merged[k]['containers'] = [it['container']] if it['container'] else []
            merged[k]['lines'] = 1
            order.append(k)
        else:
            m = merged[k]
            m['lines'] += 1
            if it['container'] and it['container'] not in m['containers']:
                m['containers'].append(it['container'])
            if not m.get('name') and it.get('name'):
                m['name'] = it['name']
            if not m.get('spec') and it.get('spec'):
                m['spec'] = it['spec']
    out = []
    for i, k in enumerate(order, 1):
        m = merged[k]
        m['seq'] = i
        m['container_summary'] = '、'.join(m['containers'])
        out.append(m)
    return out


# ═══════════════════════════════════════════════════════════════════
# 三、照片扫描：EXIF → 时间 → 分组 → 去重
# ═══════════════════════════════════════════════════════════════════

EXIF_DT_RE = re.compile(r'^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})')


def _exif_datetime(path):
    """读 EXIF DateTimeOriginal。失败返回 None。

    不引 Pillow 之外的依赖；拿不到就退化为文件名时间，再退化为 mtime。
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            # 36867 = DateTimeOriginal, 306 = DateTime
            for tag in (36867, 306):
                v = exif.get(tag)
                if v:
                    m = EXIF_DT_RE.match(str(v))
                    if m:
                        y, mo, d, h, mi, s = (int(x) for x in m.groups())
                        return datetime(y, mo, d, h, mi, s)
    except Exception:
        pass
    return None


FN_DT_RE = re.compile(r'(\d{8})[_-](\d{6})')


def _filename_datetime(name):
    m = FN_DT_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
    except ValueError:
        return None


def _file_md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def scan_photos(folder, verbose=True):
    """扫描照片目录，做 EXIF 解析、时间确定、分组、去重标记。

    返回 (photos, groups, stats)：
      photos = [{file, path, taken_at, bytes, md5, group_idx, dup_of, burst}]
      groups = [{idx, photo_idxs, start, end}]
    """
    files = []
    for root, _dirs, names in os.walk(folder):
        for n in names:
            if n.lower().endswith(PHOTO_EXT):
                files.append(os.path.join(root, n))
    files.sort()

    photos = []
    fallback_count = 0
    for p in files:
        name = os.path.basename(p)
        dt = _exif_datetime(p)
        src = 'exif'
        if dt is None:
            dt = _filename_datetime(name)
            src = 'filename'
            fallback_count += 1
        if dt is None:
            dt = datetime.fromtimestamp(os.path.getmtime(p))
            src = 'mtime'
            fallback_count += 1
        photos.append({
            'file': name,
            'path': p,
            'taken_at': dt,
            'time_src': src,
            'bytes': os.path.getsize(p),
            'md5': None,
            'group_idx': -1,
            'dup_of': None,
            'burst': bool(re.search(r'_BURST\d+', name)),
        })

    # ── 去重：MD5 完全相同才判重（保守）──
    # 刻意**不做感知哈希去重**：BURST002/003/004 这类"近似同图"是连拍，
    # 属于现场真实拍摄行为，删掉会改变证据链。只在报告中提示，不自动合并。
    seen = {}
    for ph in photos:
        h = _file_md5(ph['path'])
        ph['md5'] = h
        if h in seen:
            ph['dup_of'] = seen[h]
        else:
            seen[h] = ph['file']

    # ── 分组：先用去重后的序列分组，再把重复项挂到同一组 ──
    # 主规则是**拍照时间间隔**（gap > GROUP_GAP_SEC）：同组 = 同一段连拍。
    # 张数上限只作安全阀（12 → 30，10-04）：一次连拍十几张是常态，不该被
    # 12 张切断；但主力那批照片是 0~2 秒一张的连续流，没有上限会切出
    # 412 张的巨型组（实测），同组推荐就没人用得了。
    uniq = [ph for ph in photos if ph['dup_of'] is None]
    uniq.sort(key=lambda x: x['taken_at'])

    groups = []
    cur = []
    for ph in uniq:
        if not cur:
            cur = [ph]
            continue
        gap = (ph['taken_at'] - cur[-1]['taken_at']).total_seconds()
        if gap > GROUP_GAP_SEC or len(cur) >= GROUP_MAX_PHOTOS:
            groups.append(cur)
            cur = [ph]
        else:
            cur.append(ph)
    if cur:
        groups.append(cur)

    for gi, g in enumerate(groups):
        for ph in g:
            ph['group_idx'] = gi

    # 重复项：跟随其原图所在组
    by_file = {ph['file']: ph for ph in photos}
    for ph in photos:
        if ph['dup_of']:
            origin = by_file.get(ph['dup_of'])
            if origin:
                ph['group_idx'] = origin['group_idx']

    stats = {
        'total_files': len(photos),
        'dup_files': sum(1 for ph in photos if ph['dup_of']),
        'uniq_files': len(uniq),
        'time_fallback': fallback_count,
        'group_count': len(groups),
        'bytes_total': sum(ph['bytes'] for ph in photos),
        'bytes_uniq': sum(ph['bytes'] for ph in uniq),
        'burst_files': sum(1 for ph in photos if ph['burst']),
    }
    if verbose:
        print('  照片 %d 个（唯一 %d，重复 %d）· %d 组 · %.1f MB'
              % (stats['total_files'], stats['uniq_files'], stats['dup_files'],
                 stats['group_count'], stats['bytes_total'] / 1048576))
        if fallback_count:
            print('  ⚠ %d 个文件无 EXIF 拍摄时间，已退化为文件名/mtime' % fallback_count)
    return photos, groups, stats


# ═══════════════════════════════════════════════════════════════════
# 四、OCR（复用 pc_ocr_probe，可缓存）
# ═══════════════════════════════════════════════════════════════════

def run_ocr(photos, cache_path=None, limit=None, verbose=True):
    """对唯一照片跑 OCR，返回 {file: {texts:[{t,c}], boxes, det_s, rec_s}}。

    有缓存文件时直接读 —— 缓存里缺失的文件才补跑。
    """
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            for r in json.load(f):
                if 'error' not in r:
                    cache[r['file']] = {
                        'texts': r.get('texts', []),
                        'boxes': r.get('boxes', 0),
                        'det_s': r.get('det_s', 0),
                        'rec_s': r.get('rec_s', 0),
                    }
        if verbose:
            print('  从缓存载入 %d 张的 OCR 结果：%s' % (len(cache), cache_path))

    targets = [ph for ph in photos if ph['dup_of'] is None and ph['file'] not in cache]
    if limit:
        targets = targets[:limit]
    if not targets:
        if verbose:
            print('  所有照片的 OCR 结果已在缓存中，跳过')
        return cache

    # 延迟导入：--no-ocr 模式下不该加载 30MB 的 onnx 模型
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pc_ocr_probe as P
    P.FOUR_DIR_CONF = FOUR_DIR_CONF

    if verbose:
        print('  OCR 待跑 %d 张（每张约 1.5~3s）...' % len(targets))
    t0 = time.time()
    for i, ph in enumerate(targets, 1):
        try:
            r = P.run_photo(ph['path'], four_dir=True)
            cache[ph['file']] = {
                'texts': r.get('texts', []),
                'boxes': r.get('boxes', 0),
                'det_s': r.get('det_s', 0),
                'rec_s': r.get('rec_s', 0),
            }
        except Exception as e:  # noqa: BLE001
            cache[ph['file']] = {'texts': [], 'boxes': 0, 'det_s': 0, 'rec_s': 0,
                                 'error': str(e)[:120]}
        if verbose and (i % 20 == 0 or i == len(targets)):
            el = time.time() - t0
            eta = el / i * (len(targets) - i)
            print('    [%3d/%d] 已用 %.0fs，预计还需 %.0fs'
                  % (i, len(targets), el, eta))
    if verbose:
        print('  OCR 完成，用时 %.0fs' % (time.time() - t0))

    # ⚠️ 必须落盘。OCR 是整个建库流程最贵的一步（249 张 ≈ 13 分钟），
    #    而调参（收紧 C_adjacent 规则、改纠偏表、改阈值）是必然要反复做的。
    #    不落盘 = 每调一次参就重跑一次 OCR。原始识别结果与派生结论分开存，
    #    是这里唯一正确的结构。
    if cache_path:
        dump = [dict(file=k, **v) for k, v in sorted(cache.items())]
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(dump, f, ensure_ascii=False, indent=1)
        if verbose:
            print('  OCR 结果已缓存 → %s' % cache_path)
    return cache


# ═══════════════════════════════════════════════════════════════════
# 五、绑定：把 OCR 结果变成「编码 ↔ 照片」的绑定候选
# ═══════════════════════════════════════════════════════════════════

def build_bindings(photos, groups, ocr, index, max_adjacent_per_group=4):
    """产出绑定记录。

    返回 list of {
        code, code_norm, photo_file, group_idx, strength, score, mode,
        matched_token, token_conf, taken_at
    }

    强度判定：
      B_ocr_multi   同一张照片命中 ≥2 编码（装箱单近拍的典型特征）
      B_ocr_single  只命中 1 编码
      C_adjacent    本张无命中，但**同组内有 B 级命中** → 记为参考图

    ── C_adjacent 的收紧规则（实测调出来的，不是拍脑袋）──
    初版实现是"同组内有任何命中就把其余照片全标 C"，跑 249 张真实数据
    后出现两个明显退化：

      ① 组 38：11 张照片 / 1 个编码 —— 那是某个时段旁边恰好拍到了含编码
         的东西，其余 10 张是外观照，标成候选纯属噪声
      ② 组 14：B 级 1 张 + C 级 2 张，都是同一份装箱单的连拍
         （_135203 / _135244 / _135255）—— **这个才是 C 级的真实价值**：
         同一份装箱单连拍多张，只有一张识别成功，其余是同证据的备份

    所以 C 级只在**组内 B 级照片很少**（≤2 张，即"对着一个目标连拍"的形态）
    时才生成，且每组的 C 级照片数设上限。这样 C 级从 106 条压到很窄的范围，
    留下的都是"同一份证据的其他角度"，而不是"这个时段的全部照片"。

    C_adjacent 的语义必须在报告里写死：**它不是"这张照片拍的是这件货"
    的证据**，只是"同一时刻有人拍了同一份装箱单"。所以它不计入
    photo_count（见 verify_library.py 的 A4 断言）。
    """
    bindings = []
    per_photo = {}
    group_b_photos = {}

    # ── 逐张匹配 ──
    for ph in photos:
        if ph['dup_of'] is not None:
            continue
        r = ocr.get(ph['file'])
        if not r:
            continue
        hits = {}
        for t in r.get('texts', []):
            txt = (t.get('t') or '').strip()
            if len(txt) < MATCH_MIN_TOKEN_LEN:
                continue
            conf = float(t.get('c') or 0.0)
            if conf <= 0:
                continue
            cand = index.best(txt, conf)
            if cand:
                code, name, score, mode = cand
                # 同一编码在同一张里保留最高分
                if code not in hits or score > hits[code]['score']:
                    hits[code] = {
                        'code': code,
                        'score': score,
                        'mode': mode,
                        'matched_token': txt,
                        'token_conf': conf,
                    }
        multi = len(hits) >= 2
        strength = 'B_ocr_multi' if multi else ('B_ocr_single' if hits else None)
        for code, h in hits.items():
            bindings.append({
                'code': code,
                'code_norm': normalize(code),
                'photo_file': ph['file'],
                'group_idx': ph['group_idx'],
                'strength': strength,
                'score': round(h['score'], 4),
                'mode': h['mode'],
                'matched_token': h['matched_token'],
                'token_conf': h['token_conf'],
                'taken_at': ph['taken_at'],
            })
        per_photo[ph['file']] = sorted(hits.keys())
        if hits:
            group_b_photos.setdefault(ph['group_idx'], []).append(ph['file'])

    # ── C_adjacent：仅当该组的 B 级照片很少（同一目标的连拍形态）──
    hit_by_group = {}
    for b in bindings:
        hit_by_group.setdefault(b['group_idx'], set()).add(b['code'])
    for gi, bfiles in group_b_photos.items():
        if len(bfiles) > max_adjacent_per_group:
            continue
        gcodes = sorted(hit_by_group.get(gi, set()))
        if not gcodes:
            continue
        n_added = 0
        for ph in photos:
            if ph['dup_of'] is not None or ph['group_idx'] != gi:
                continue
            if per_photo.get(ph['file']):
                continue
            if n_added >= max_adjacent_per_group:
                break
            for code in gcodes:
                bindings.append({
                    'code': code,
                    'code_norm': normalize(code),
                    'photo_file': ph['file'],
                    'group_idx': ph['group_idx'],
                    'strength': 'C_adjacent',
                    'score': 0.0,
                    'mode': 'adjacent',
                    'matched_token': '',
                    'token_conf': 0.0,
                    'taken_at': ph['taken_at'],
                })
            n_added += 1
    return bindings


def parse_prior_delivery(folder, verbose=True):
    """读既往交付包里的 _对照表.csv，产出 A_strong 绑定。

    这是建库最划算的一步：既往交付包里的对照表是**已经人工确认过的**
    编码↔照片对应关系，直接就是 A 级证据，比跑 OCR 可靠得多。

    期望的 CSV 列（M5 交付格式）：文件名,货品序号,编码,品名,规格,数量,单位,该品第几张,拍摄时间
    从宽处理：只要同时有「文件名」和「编码」两列就接受。
    """
    found = []
    if not os.path.isdir(folder):
        return found
    for root, _d, names in os.walk(folder):
        for n in names:
            if not n.lower().endswith('.csv'):
                continue
            p = os.path.join(root, n)
            try:
                with open(p, 'r', encoding='utf-8-sig', newline='') as f:
                    rd = csv.reader(f)
                    rows = list(rd)
            except Exception:
                continue
            if not rows:
                continue
            header = [normalize(_cell(c)) for c in rows[0]]
            fi = ci = ni = -1
            for j, h in enumerate(header):
                if fi < 0 and ('文件名' in h or h in ('file', 'filename')):
                    fi = j
                if ci < 0 and ('编码' in h or h in ('code', 'itemcode')):
                    ci = j
                if ni < 0 and ('品名' in h or h in ('name', 'description')):
                    ni = j
            if fi < 0 or ci < 0:
                continue
            cnt = 0
            for r in rows[1:]:
                if len(r) <= max(fi, ci):
                    continue
                fn = _cell(r[fi])
                code = _cell(r[ci])
                if not fn or not code or fn.startswith('(无照片)') or fn.startswith('#'):
                    continue
                found.append({
                    'file': fn,
                    'code': code,
                    'name': _cell(r[ni]) if 0 <= ni < len(r) else '',
                    'source_csv': p,
                })
                cnt += 1
            if verbose and cnt:
                print('  既往对照表 %s：%d 条已确认绑定' % (n, cnt))
    return found


# ═══════════════════════════════════════════════════════════════════
# 六、落库
# ═══════════════════════════════════════════════════════════════════

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 产品库元信息（一次建库一行）
CREATE TABLE IF NOT EXISTS library_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);

-- 编码主表
CREATE TABLE IF NOT EXISTS products (
    code_norm   TEXT PRIMARY KEY,
    code        TEXT NOT NULL,
    name        TEXT,
    spec        TEXT,
    container   TEXT,
    qty         TEXT,
    merged_lines INTEGER DEFAULT 1,
    source_file TEXT,             -- 编码来自哪份清单
    in_checklist INTEGER DEFAULT 1,
    in_customs   INTEGER DEFAULT 0,
    photo_count  INTEGER DEFAULT 0,  -- B 级以上绑定数（不含 C）
    created_at  TEXT NOT NULL
);

-- 照片索引
CREATE TABLE IF NOT EXISTS photos (
    file        TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    taken_at    TEXT NOT NULL,
    time_src    TEXT,
    bytes       INTEGER,
    md5         TEXT,
    is_dup      INTEGER DEFAULT 0,
    dup_of      TEXT,
    is_burst    INTEGER DEFAULT 0,
    group_idx   INTEGER
);

-- 绑定：编码 ↔ 照片
CREATE TABLE IF NOT EXISTS bindings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code_norm   TEXT NOT NULL,
    photo_file  TEXT NOT NULL,
    group_idx   INTEGER,
    strength    TEXT NOT NULL,    -- A_strong / B_ocr_multi / B_ocr_single / C_adjacent
    score       REAL DEFAULT 0,
    mode        TEXT,             -- exact / prefix / edit1 / edit2 / adjacent
    matched_token TEXT,
    token_conf  REAL DEFAULT 0,
    reviewed    INTEGER DEFAULT 0,-- 人工复核过没有
    review_note TEXT,
    UNIQUE(code_norm, photo_file)
);

CREATE INDEX IF NOT EXISTS idx_bind_code ON bindings(code_norm);
CREATE INDEX IF NOT EXISTS idx_bind_strength ON bindings(strength);
CREATE INDEX IF NOT EXISTS idx_photos_group ON photos(group_idx);
"""


def write_library(out_dir, meta, products, photos, bindings):
    os.makedirs(out_dir, exist_ok=True)
    db_path = os.path.join(out_dir, 'library.db')
    if os.path.exists(db_path):
        os.remove(db_path)

    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    now = datetime.now().isoformat(timespec='seconds')

    for k, v in meta.items():
        con.execute('INSERT OR REPLACE INTO library_meta(key,value) VALUES (?,?)',
                    (k, json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v))

    for p in products:
        con.execute(
            'INSERT OR REPLACE INTO products'
            '(code_norm,code,name,spec,container,qty,merged_lines,source_file,'
            ' in_checklist,in_customs,photo_count,created_at)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (p['code_norm'], p['code'], p.get('name'), p.get('spec'),
             p.get('container_summary'), p.get('qty'), p.get('lines', 1),
             p.get('source_file'), 1 if p.get('in_checklist') else 0,
             1 if p.get('in_customs') else 0, p.get('photo_count', 0), now))

    for ph in photos:
        con.execute(
            'INSERT OR REPLACE INTO photos'
            '(file,path,taken_at,time_src,bytes,md5,is_dup,dup_of,is_burst,group_idx)'
            ' VALUES (?,?,?,?,?,?,?,?,?,?)',
            (ph['file'], ph['path'], ph['taken_at'].isoformat(), ph.get('time_src'),
             ph['bytes'], ph['md5'], 1 if ph['dup_of'] else 0, ph['dup_of'],
             1 if ph['burst'] else 0, ph['group_idx']))

    for b in bindings:
        con.execute(
            'INSERT OR IGNORE INTO bindings'
            '(code_norm,photo_file,group_idx,strength,score,mode,matched_token,token_conf)'
            ' VALUES (?,?,?,?,?,?,?,?)',
            (b['code_norm'], b['photo_file'], b['group_idx'], b['strength'],
             b['score'], b['mode'], b['matched_token'], b['token_conf']))

    con.commit()
    con.close()
    return db_path


def write_cross_reference(out_dir, products, photo_map, bindings):
    """生成 _编码对照表.csv —— 人工复核的主要界面。

    列顺序按"人怎么看"排：编码 → 品名 → 级别 → 照片 → 时间 → 依据。
    """
    by_code = {}
    for b in bindings:
        by_code.setdefault(b['code_norm'], []).append(b)
    rank = {'A_strong': 0, 'B_ocr_multi': 1, 'B_ocr_single': 2, 'C_adjacent': 3}

    path = os.path.join(out_dir, '_编码对照表.csv')
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['编码', '品名', '规格', '箱号', '绑定级别', '照片文件名',
                    '拍摄时间', '匹配分', '匹配方式', '命中文本', '已复核'])
        for p in products:
            bs = sorted(by_code.get(p['code_norm'], []), key=lambda x: (rank[x['strength']], -x['score']))
            if not bs:
                w.writerow([p['code'], p.get('name') or '', p.get('spec') or '',
                            p.get('container_summary') or '', '(无)', '', '', '', '', '', ''])
                continue
            for b in bs:
                ph = photo_map.get(b['photo_file'])
                w.writerow([
                    p['code'], p.get('name') or '', p.get('spec') or '',
                    p.get('container_summary') or '',
                    b['strength'], b['photo_file'],
                    ph['taken_at'].strftime('%Y-%m-%d %H:%M:%S') if ph else '',
                    '%.3f' % b['score'] if b['score'] else '',
                    b['mode'], b['matched_token'], '',
                ])
    return path


def write_review_queue(out_dir, products, photo_map, bindings):
    """生成 _待复核.csv —— 只列 B/C 级，供人工过一遍。

    ⚠️ 「动作」列**预填为空**，这是刻意的。

    初版实现预填了 `确认`（B 级）/ `核对`（C 级），跑完发现一个危险的后果：
    `apply_review` 扫描 CSV 时会把**预填值当成人给出的决定** —— 人只改了
    前 5 行，其余 28 行带着预填的 `确认` 被一并回写，"只由人驱动"这条规则
    当场失效。所以动作列必须由人显式填写，工具不自作主张。

    「优先级」列代替原来的预填动作：它只提示该花多少注意力，不是决定。
    """
    pmap = {p['code_norm']: p for p in products}
    path = os.path.join(out_dir, '_待复核.csv')
    todo = [b for b in bindings if b['strength'] != 'A_strong']
    # 排序：multi 优先（一次确认一批），其次 single，最后 adjacent；同级按分数降序
    prio = {'B_ocr_multi': 0, 'B_ocr_single': 1, 'C_adjacent': 2}
    todo.sort(key=lambda x: (prio[x['strength']], -x['score'], x['code_norm']))
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['动作', '优先级', '编码', '品名', '照片文件名', '拍摄时间',
                    '级别', '匹配分', '命中文本', '备注'])
        for b in todo:
            p = pmap.get(b['code_norm'], {})
            ph = photo_map.get(b['photo_file'])
            w.writerow([
                '',  # ← 空着，等人填「确认」或「否决」
                b['strength'],
                p.get('code', ''), p.get('name') or '', b['photo_file'],
                ph['taken_at'].strftime('%Y-%m-%d %H:%M:%S') if ph else '',
                b['strength'], '%.3f' % b['score'] if b['score'] else '',
                b['matched_token'], '',
            ])
    return path


def write_report(out_dir, meta, stats, products, bindings, photos, ocr_stats):
    rank = {'A_strong': 0, 'B_ocr_multi': 1, 'B_ocr_single': 2, 'C_adjacent': 3}
    bound = {b['code_norm'] for b in bindings if b['strength'] != 'C_adjacent'}
    b_multi = {b['code_norm'] for b in bindings if b['strength'] == 'B_ocr_multi'}
    b_single = {b['code_norm'] for b in bindings if b['strength'] == 'B_ocr_single'}
    c_adj = {b['code_norm'] for b in bindings if b['strength'] == 'C_adjacent'}
    a_strong = {b['code_norm'] for b in bindings if b['strength'] == 'A_strong'}

    lines = []
    A = lines.append
    A('# 产品库建库报告')
    A('')
    A('**生成时间**：%s' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    A('')
    A('## 一、素材')
    A('')
    A('| 项 | 值 |')
    A('|---|---|')
    A('| 照片文件 | %d 个 |' % stats['total_files'])
    A('| 去重后唯一 | %d 个（重复 %d 个，MD5 完全相同）|'
      % (stats['uniq_files'], stats['dup_files']))
    A('| 连拍文件 | %d 个 |' % stats['burst_files'])
    A('| 总体积 | %.1f MB（去重后 %.1f MB）|'
      % (stats['bytes_total'] / 1048576, stats['bytes_uniq'] / 1048576))
    A('| 分组 | %d 组（间隔 >%ds 切分，每组最多 %d 张）|'
      % (stats['group_count'], GROUP_GAP_SEC, GROUP_MAX_PHOTOS))
    if stats['time_fallback']:
        A('| ⚠ 无 EXIF 时间 | %d 个（已退化用文件名/mtime）|' % stats['time_fallback'])
    A('')
    A('## 二、清单与报关单')
    A('')
    A('| 来源 | sheet | 表头行 | 数据行 | 备注行 | 唯一编码 |')
    A('|---|---|---|---|---|---|')
    for m in meta.get('sources', []):
        A('| %s | %s | %d | %d | %d | %d |'
          % (m['file'], m['sheet'], m['header_row'], m['raw_rows'],
             m['note_rows'], m['unique_codes']))
    A('')
    A('清单编码 %d 个；报关单料号 %d 个；**两者交集 %d**。'
      % (meta['checklist_codes'], meta['customs_codes'], meta['intersection']))
    A('')
    if meta['checklist_only']:
        A('- 仅清单有（%d）：%s' % (len(meta['checklist_only']),
                                   ', '.join(meta['checklist_only'][:12])))
    if meta['customs_only']:
        A('- 仅报关有（%d）：%s' % (len(meta['customs_only']),
                                   ', '.join(meta['customs_only'][:12])))
    if not meta['checklist_only'] and not meta['customs_only']:
        A('- 两份文件的编码集合完全一致 —— 可互相印证。')
    A('')
    A('## 三、OCR 与绑定')
    A('')
    A('| 指标 | 数值 |')
    A('|---|---|')
    A('| OCR 跑过 | %d 张 |' % ocr_stats['ran'])
    A('| 识别出文字 | %d 张（%.1f%%）|'
      % (ocr_stats['with_text'], 100.0 * ocr_stats['with_text'] / max(1, ocr_stats['ran'])))
    A('| 至少命中 1 编码 | %d 张（%.1f%%）|'
      % (ocr_stats['hit_photos'], 100.0 * ocr_stats['hit_photos'] / max(1, ocr_stats['ran'])))
    A('| 绑定记录 | %d 条 |' % len(bindings))
    A('')
    A('**绑定强度分布**')
    A('')
    A('> 一个编码可以同时有多个级别的绑定。下表「编码数」是**去重后**的，')
    A('> 各行不能相加 —— 一个编码可能既有 B_ocr_multi 又有 C_adjacent。')
    A('')
    A('| 级别 | 编码数 | 绑定条数 | 说明 |')
    A('|---|---|---|---|')
    for key, desc in (
            ('A_strong', '人工确认过（既往交付对照表）—— 可直接用'),
            ('B_ocr_multi', '单张命中 ≥2 编码，大概率装箱单近拍 —— 扫一眼即可确认'),
            ('B_ocr_single', '只命中 1 编码 —— 需逐条核对'),
            ('C_adjacent', '时序推断，**不是证据**，仅供提示')):
        cs = {b['code_norm'] for b in bindings if b['strength'] == key}
        ns = sum(1 for b in bindings if b['strength'] == key)
        A('| %s | %d | %d | %s |' % (key, len(cs), ns, desc))
    A('| **B 级合计（可人工快速确认）** | **%d** | %d | 一个编码可能同时命中 multi 与 single |'
      % (len(b_multi | b_single), len([b for b in bindings if b['strength'].startswith('B')])))
    A('| **A+B 合计（可用）** | **%d** | | 产品库里真正有图可召回的编码 |'
      % len(a_strong | b_multi | b_single))
    A('')
    A('**B 级命中的匹配方式分布**（说明识别质量）')
    A('')
    A('| 方式 | 条数 | 含义 |')
    A('|---|---|---|')
    mode_desc = {
        'exact': '完全相等 —— 质量最高',
        'prefix': '清单编码是 OCR 文本的子串',
        'edit1': '编辑距离 1 —— 1 个字符识别偏差',
        'edit2': '编辑距离 2 —— 2 个字符识别偏差，**复核时优先看这批**',
        'prior_delivery': '来自既往交付对照表',
    }
    modes = {}
    for b in bindings:
        if b['strength'].startswith('B') or b['strength'] == 'A_strong':
            modes[b['mode']] = modes.get(b['mode'], 0) + 1
    for m in sorted(modes, key=lambda x: -modes[x]):
        A('| %s | %d | %s |' % (m, modes[m], mode_desc.get(m, '')))
    A('')
    A('## 四、入库结果')
    A('')
    A('清单内编码 %d 个，其中 **%d 个有 A/B 级绑定**（%.1f%%），%d 个只有 C 级或完全无照片。'
      % (len(products), len(bound), 100.0 * len(bound) / max(1, len(products)),
         len(products) - len(bound)))
    A('')

    # ── 已入库编码明细：复盘时最需要的一眼结论 ──
    if bound:
        A('### 4.1 已入库的编码（%d 个）' % len(bound))
        A('')
        A('| 编码 | 品名 | 最高级别 | A/B 张数 | 跨时段 |')
        A('|---|---|---|---|---|')
        pby = {p['code_norm']: p for p in products}
        for cn in sorted(bound):
            p = pby.get(cn, {})
            bs = [b for b in bindings
                  if b['code_norm'] == cn and b['strength'] != 'C_adjacent']
            lv = min((b['strength'] for b in bs), key=lambda x: rank[x]) if bs else '-'
            groups_n = len({b['group_idx'] for b in bs})
            A('| %s | %s | %s | %d | %d |'
              % (p.get('code', cn), p.get('name') or '', lv, len(bs), groups_n))
        A('')
        A('> 「跨时段」> 1 表示这个编码在不同时间点被拍到过多次。')
        A('> 召回时必须**并列展示让报告员挑**，不能随便给一张。')
        A('')

    missing = [p for p in products if p['code_norm'] not in bound]
    if missing:
        A('### 4.2 无可用照片的编码（%d 个）' % len(missing))
        A('')
        A('这批编码在本批历史素材里找不到可信照片。产品库里它们只有名字、没有图。')
        A('')

        # ── 按箱号聚集分析 ──
        # 实测很有价值：53 个无照片编码里有 48 个集中在两个箱子（BOX-M22 35 个、
        # BOX-M12 13 个），说明**不是零散漏拍，而是整箱没被拍到**。
        # 这直接决定补救动作：零散漏拍要补拍零散几张；整箱缺失要确认箱子
        # 本身是什么情况（未开箱 / 未到 / 已提走）。不点出来，看报告的人
        # 会对着一长串编码逐个猜。
        by_container = {}
        for p in missing:
            k = p.get('container_summary') or '(清单未给箱号)'
            by_container.setdefault(k, []).append(p)
        if len(by_container) > 1 or '(清单未给箱号)' not in by_container:
            A('**按箱号分布**（看是不是整箱缺失）：')
            A('')
            A('| 箱号 | 无照片编码数 | 占比 |')
            A('|---|---|---|')
            for k in sorted(by_container, key=lambda x: -len(by_container[x])):
                v = by_container[k]
                A('| %s | %d | %.0f%% |' % (k, len(v), 100.0 * len(v) / len(missing)))
            A('')
            top_k = max(by_container, key=lambda x: len(by_container[x]))
            top_n = len(by_container[top_k])
            if top_n >= len(missing) * 0.5:
                A('> ⚠️ **%d/%d（%.0f%%）的无照片编码集中在 `%s`** —— 这不像零散漏拍，'
                  % (top_n, len(missing), 100.0 * top_n / len(missing), top_k))
                A('> 更像该箱整体没有被拍到。补救动作与"缺几张特写"完全不同：')
                A('> 应先确认这个箱子本身的情况（未开箱 / 未到货 / 已提走），再决定是否补拍。')
                A('')
        A('| 编码 | 品名 | 箱号 |')
        A('|---|---|---|')
        for p in missing[:60]:
            A('| %s | %s | %s |' % (p['code'], p.get('name') or '',
                                    p.get('container_summary') or ''))
        if len(missing) > 60:
            A('| ... | 另有 %d 个，见 library.db | |' % (len(missing) - 60))
        A('')

    # 多照片编码：一个编码对应多个时段 → 召回时要并列展示
    per_code = {}
    for b in bindings:
        if b['strength'] == 'C_adjacent':
            continue
        per_code.setdefault(b['code_norm'], set()).add(b['group_idx'])
    multi = {k: v for k, v in per_code.items() if len(v) > 1}
    A('### 4.3 跨时段出现的编码（%d 个）' % len(multi))
    A('')
    A('同一个编码在不同时间点被拍到多次。**召回时必须并列展示让报告员挑**，')
    A('不能随便给一张 —— 不同时段可能对应不同的货或不同的包装状态。')
    A('')
    if multi:
        A('| 编码 | 出现时段数 |')
        A('|---|---|')
        for k in list(multi)[:30]:
            A('| %s | %d |' % (k, len(multi[k])))
        if len(multi) > 30:
            A('| ... | 另有 %d 个 |' % (len(multi) - 30))
    else:
        A('（无）')
    A('')
    A('## 五、下一步：人工复核')
    A('')
    A('复核是整个建库流程**不可省略**的一步 —— 库里 76% 的绑定来自 OCR，')
    A('而 OCR 的判断只到"这张照片里出现了这个编码的文本"这一层。')
    A('')
    A('### 5.1 怎么过')
    A('')
    A('打开 `_待复核.csv`，**在「动作」列亲自填字**（该列初始为空，这是刻意的）：')
    A('')
    A('| 填什么 | 什么情况下这么填 | 回写效果 |')
    A('|---|---|---|')
    A('| `确认` | 照片确实是装箱单/该货品的近拍，编码对应关系成立 | `reviewed=1`，保留 |')
    A('| `否决` | 照片与这个编码无关（时序推断误标、OCR 认错） | **删除该条绑定** |')
    A('| 留空 | 还没看到 / 拿不准 | 保持不变 |')
    A('')
    A('> ⚠️ **留空 = 跳过，不是确认。** 动作列初始为空是刻意的设计 ——')
    A('> 若预填「确认」，一次误保存就会把整表当成人工确认全部回写，')
    A('> "只由人驱动"这条规则当场失效。所以只有你亲手敲进去的字才算数。')
    A('')
    A('填完执行：')
    A('')
    A('```powershell')
    A('python tools\\build_library.py --photos <照片目录> --out library \\')
    A('    --apply-review library\\_待复核.csv')
    A('```')
    A('')
    A('这是**唯一**修改既有绑定的入口。工具只会执行你给出的动作，')
    A('永远不会把 B/C 级悄悄升级成 A 级。')
    A('')
    A('### 5.2 复核优先级')
    A('')
    A('1. **先过 `B_ocr_multi`（%d 条 / %d 个编码）** —— 一次能确认一批，'
      % (len([b for b in bindings if b['strength'] == 'B_ocr_multi']), len(b_multi)))
    A('   性价比最高。本批实测这 23 个编码只来自 2 张装箱单近拍。')
    A('2. **再过 `B_ocr_single`（%d 条）** —— 逐条看，一般是单件货的标识卡或包装标签。'
      % len([b for b in bindings if b['strength'] == 'B_ocr_single']))
    A('3. **最后处理 `edit2` 匹配的（%d 条）** —— 编辑距离 2 意味着 2 个字符识别偏差，'
      % len([b for b in bindings if b.get('mode') == 'edit2']))
    A('   是最可能认错的批次，必须逐条核对。')
    A('4. **`C_adjacent`（%d 条）建议整体批量否决或保留** —— 它只是"同一时刻拍了'
      % len([b for b in bindings if b['strength'] == 'C_adjacent']))
    A('   同一份装箱单"的提示。这些照片往往是有效证据（连拍里只有一张识别成功），')
    A('   但**必须人眼看过才能用**；长期没人确认的，直接删掉，别留着污染召回结果。')
    A('')
    A('### 5.3 库的成熟度')
    A('')
    A('复核完成后建议重跑一次 `verify_library.py` 自检。')
    A('**一个未经复核的库不应进入生产使用** —— 召回时给出的"这张照片是编码 X"')
    A('如果本身就是错的，比"没有照片"更危险。')
    A('')
    A('> ⚠️ 产品库的照片只证明「历史上这个编码长什么样」，')
    A('>    不能证明「本次这批货的状态」。复用照片进交付包时必须在')
    A('>    文件名与对照表里标明来源，最终是否采用由报告员决定。')
    A('')

    path = os.path.join(out_dir, '_建库报告.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path


# ═══════════════════════════════════════════════════════════════════
# 七、主流程
# ═══════════════════════════════════════════════════════════════════

def write_manifest(out_dir, meta, products, photos, bindings):
    """生成 manifest.json —— 程序可读的全量快照。

    与 M5 交付包的 manifest 同构：便于"库 ↔ 交付包"之间的来源追溯。
    """
    stat = {}
    for b in bindings:
        stat[b['strength']] = stat.get(b['strength'], 0) + 1
    doc = {
        'kind': 'gtick_photo_library',
        'schemaVersion': 1,
        'generatedAt': meta['generated_at'],
        'source': {
            'photoDir': meta['photo_dir'],
            'checklists': [m['file'] for m in meta['sources']],
            'checklistCodes': meta['checklist_codes'],
            'customsCodes': meta['customs_codes'],
            'intersection': meta['intersection'],
        },
        'params': {
            'groupGapSec': GROUP_GAP_SEC,
            'groupMaxPhotos': GROUP_MAX_PHOTOS,
            'matchMaxEditDistance': MATCH_MAX_EDIT,
            'matchMinTokenLength': MATCH_MIN_TOKEN_LEN,
        },
        'counts': {
            'products': len(products),
            'photos': len(photos),
            'photosUnique': meta['photo_stats']['uniq_files'],
            'photosDuplicate': meta['photo_stats']['dup_files'],
            'groups': meta['photo_stats']['group_count'],
            'bindings': len(bindings),
            'byStrength': stat,
        },
        'ocr': meta['ocr_stats'],
        'disclaimer': (
            '本库照片为历史作业素材，仅用于证明「该编码历史上长什么样」，'
            '不能作为「本次这批货状态」的证据。复用进交付包时必须在'
            '文件名与对照表中标明来源，是否采用由报告员决定。'
        ),
    }
    path = os.path.join(out_dir, 'manifest.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return path


def apply_review(db_path, review_csv, verbose=True):
    """把人工复核后的 `_待复核.csv` 回写到库。

    约定「动作」列取值（**白名单，其余一律跳过**）：
      确认 / 保留 / ok  → bindings.reviewed = 1, review_note = 'confirmed'
      否决 / 删除 / no  → 删除该条绑定（它会污染召回结果，留着有害）
      空 / 其它         → 跳过，保持不变

    两条必须守住的规则：

      ① **空值必须跳过。** `_待复核.csv` 的动作列预填为空（见
         write_review_queue 的说明），但 CSV 是会被人和表格软件反复编辑的
         —— 只要允许"空 = 确认"，一次误保存就会把整表当成全部确认。
      ② **报告的是实际影响行数，不是 execute 调用次数。** 用
         `cursor.rowcount`。初版统计的是调用次数，遇到"同一 (code, photo)
         不存在"这类空操作时数字会虚高，让人以为改了一堆其实什么都没改。

    这是**唯一**修改既有绑定的入口，且只由人给出的 CSV 驱动 ——
    工具自己永远不会把 B/C 级悄悄升级成 A 级。
    """
    if not os.path.exists(review_csv):
        print('  [FAIL] 复核文件不存在: %s' % review_csv)
        return False
    if not os.path.exists(db_path):
        print('  [FAIL] 库不存在: %s' % db_path)
        return False

    con = sqlite3.connect(db_path)
    n_ok = n_del = n_skip = 0
    unknown_actions = set()
    with open(review_csv, 'r', encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        for row in rd:
            action = (row.get('动作') or '').strip()
            code = (row.get('编码') or '').strip()
            photo = (row.get('照片文件名') or '').strip()
            if not action or not code or not photo:
                n_skip += 1
                continue
            cn = normalize(code)
            if action in ('确认', '保留', 'ok', 'OK'):
                cur = con.execute(
                    'UPDATE bindings SET reviewed=1, review_note=? '
                    'WHERE code_norm=? AND photo_file=?',
                    ('confirmed', cn, photo))
                n_ok += cur.rowcount
                if cur.rowcount == 0:
                    n_skip += 1
            elif action in ('否决', '删除', '删除绑定', 'no', 'NO'):
                cur = con.execute(
                    'DELETE FROM bindings WHERE code_norm=? AND photo_file=?',
                    (cn, photo))
                n_del += cur.rowcount
                if cur.rowcount == 0:
                    n_skip += 1
            else:
                unknown_actions.add(action)
                n_skip += 1

    # 复核后重算 photo_count（口径与 verify_library.py 的 A4 一致）
    con.execute("""
        UPDATE products SET photo_count = (
            SELECT COUNT(*) FROM bindings b
            WHERE b.code_norm = products.code_norm AND b.strength != 'C_adjacent'
        )
    """)
    con.commit()
    n_bind = con.execute('SELECT COUNT(*) FROM bindings').fetchone()[0]
    n_reviewed = con.execute(
        'SELECT COUNT(*) FROM bindings WHERE reviewed=1').fetchone()[0]
    con.close()

    if verbose:
        print('  复核回写：确认 %d 行 / 删除 %d 行 / 跳过 %d 行' % (n_ok, n_del, n_skip))
        if unknown_actions:
            print('  [WARN] 无法识别的动作值（已跳过）：%s'
                  % ', '.join(sorted(unknown_actions)[:8]))
            print('         合法值只有：确认 / 否决（留空=跳过）')
        print('  库现状：绑定 %d 条，其中已复核 %d 条' % (n_bind, n_reviewed))
    return True


def main():
    ap = argparse.ArgumentParser(
        description='历史预检照片产品库 / 建库工具（P1）',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--photos', required=True, help='历史照片目录（只读）')
    ap.add_argument('--checklist', action='append', default=[],
                    help='清单文件 .xls/.xlsx（可多次指定）')
    ap.add_argument('--customs', action='append', default=[],
                    help='报关单 .xlsx（可选，用于交叉印证）')
    ap.add_argument('--prior-delivery', default=None,
                    help='既往交付包目录（含 _对照表.csv → A 级绑定）')
    ap.add_argument('--out', default='library', help='输出目录（默认 ./library）')
    ap.add_argument('--ocr-cache', default=None,
                    help='OCR 结果缓存 JSON（默认写到 <out>/_ocr_cache.json；'
                         '存在则复用，缺失的才补跑）')
    ap.add_argument('--no-ocr', action='store_true', help='跳过 OCR，只建骨架')
    ap.add_argument('--ocr-limit', type=int, default=None, help='只跑前 N 张的 OCR（调试）')
    ap.add_argument('--dry-run', action='store_true', help='只统计不落盘')
    ap.add_argument('--apply-review', default=None,
                    help='把人工复核后的 _待复核.csv 回写到已有库（不重建库）')
    ap.add_argument('--no-adjacent', action='store_true',
                    help='不生成 C_adjacent 推断绑定（推荐：它只是提示，不是证据）')
    args = ap.parse_args()

    # ── 复核回写模式：只改库，不重新建库 ──
    if args.apply_review:
        print('=' * 64)
        print('产品库 · 复核回写')
        print('=' * 64)
        db = os.path.join(args.out, 'library.db')
        print('  目标库: %s' % db)
        ok = apply_review(db, args.apply_review)
        return 0 if ok else 2

    t_start = time.time()
    print('=' * 64)
    print('历史预检照片产品库 · 建库工具')
    print('=' * 64)

    # ── 1. 清单位置自动发现（没显式指定时）──
    if not args.checklist:
        for n in sorted(os.listdir(args.photos)):
            if n.lower().endswith(('.xls', '.xlsx')) and '数量' in n:
                args.checklist.append(os.path.join(args.photos, n))
        if not args.checklist:
            cand = [os.path.join(args.photos, n) for n in sorted(os.listdir(args.photos))
                    if n.lower().endswith(('.xls', '.xlsx'))]
            args.checklist = cand[:1]
    if not args.checklist:
        print('[FAIL] 没找到清单文件，请用 --checklist 指定')
        return 2

    # ── 2. 清单 ──
    print('\n[1/6] 解析清单与报关单')
    sources = []
    checklist_items = []
    for p in args.checklist:
        items, m = parse_checklist(p)
        for it in items:
            it['source_file'] = os.path.basename(p)
        checklist_items.extend(items)
        m['unique_codes'] = len({i['code_norm'] for i in items})
        sources.append(m)
        print('  清单 %s ← sheet「%s」表头第 %d 行，%d 数据行 / %d 备注行 → %d 唯一编码'
              % (m['file'], m['sheet'], m['header_row'], m['raw_rows'],
                 m['note_rows'], m['unique_codes']))

    customs_codes = set()
    for p in args.customs:
        try:
            items, m = parse_checklist(p)
            customs_codes |= {i['code_norm'] for i in items}
            m['unique_codes'] = len({i['code_norm'] for i in items})
            sources.append(m)
            print('  报关 %s ← sheet「%s」表头第 %d 行 → %d 唯一料号'
                  % (m['file'], m['sheet'], m['header_row'], m['unique_codes']))
        except Exception as e:  # noqa: BLE001
            print('  [WARN] 报关单解析失败（跳过）：%s — %s' % (os.path.basename(p), e))

    products = merge_items(checklist_items)
    ck_codes = {p['code_norm'] for p in products}
    print('  合并后：%d 件（原 %d 行）· 唯一编码 %d'
          % (len(products), len(checklist_items), len(ck_codes)))
    if customs_codes:
        inter = ck_codes & customs_codes
        print('  与报关单交集 %d / 清单独有 %d / 报关独有 %d'
              % (len(inter), len(ck_codes - customs_codes), len(customs_codes - ck_codes)))

    # ── 3. 照片 ──
    print('\n[2/6] 扫描照片')
    photos, groups, pstats = scan_photos(args.photos)

    # ── 4. OCR ──
    print('\n[3/6] OCR 识别')
    ocr = {}
    if args.no_ocr:
        print('  --no-ocr：跳过')
    else:
        cache_path = args.ocr_cache or os.path.join(args.out, '_ocr_cache.json')
        os.makedirs(args.out, exist_ok=True)
        ocr = run_ocr(photos, cache_path=cache_path, limit=args.ocr_limit)

    # ── 5. 绑定 ──
    print('\n[4/6] 匹配与绑定')
    index = CodeIndex([(p['code'], p.get('name'), p.get('spec')) for p in products])
    bindings = build_bindings(photos, groups, ocr, index)
    if args.no_adjacent:
        n0 = len(bindings)
        bindings = [b for b in bindings if b['strength'] != 'C_adjacent']
        print('  --no-adjacent：丢弃 %d 条时序推断绑定' % (n0 - len(bindings)))
    print('  清单索引 %d 条，产出 B/C 级绑定 %d 条' % (len(index), len(bindings)))

    prior = []
    if args.prior_delivery:
        prior = parse_prior_delivery(args.prior_delivery)
        by_name = {ph['file']: ph for ph in photos}
        kept = 0
        for r in prior:
            pn = normalize(r['code'])
            if pn not in {p['code_norm'] for p in products}:
                continue
            ph = by_name.get(r['file'])
            if not ph:
                continue
            bindings.append({
                'code': r['code'], 'code_norm': pn, 'photo_file': ph['file'],
                'group_idx': ph['group_idx'], 'strength': 'A_strong',
                'score': 1.0, 'mode': 'prior_delivery', 'matched_token': '',
                'token_conf': 1.0, 'taken_at': ph['taken_at'],
            })
            kept += 1
        print('  A 级（既往交付对照表）：%d 条可用' % kept)

    # 去重（A 级优先覆盖 B/C）
    rank = {'A_strong': 0, 'B_ocr_multi': 1, 'B_ocr_single': 2, 'C_adjacent': 3}
    dedup = {}
    for b in bindings:
        k = (b['code_norm'], b['photo_file'])
        if k not in dedup or rank[b['strength']] < rank[dedup[k]['strength']]:
            dedup[k] = b
    bindings = list(dedup.values())

    bset = {b['code_norm'] for b in bindings if b['strength'] != 'C_adjacent'}
    for p in products:
        p['photo_count'] = sum(1 for b in bindings
                               if b['code_norm'] == p['code_norm'] and b['strength'] != 'C_adjacent')
    print('  去重后 %d 条；覆盖 %d/%d 编码（%.1f%%）'
          % (len(bindings), len(bset), len(products),
             100.0 * len(bset) / max(1, len(products))))

    # OCR 统计
    ran = 0
    with_text = 0
    hit_photos = 0
    hit_files = {b['photo_file'] for b in bindings if b['strength'].startswith('B')}
    for ph in photos:
        r = ocr.get(ph['file'])
        if not r:
            continue
        ran += 1
        if r.get('texts'):
            with_text += 1
        if ph['file'] in hit_files:
            hit_photos += 1
    ocr_stats = {'ran': ran, 'with_text': with_text, 'hit_photos': hit_photos}

    meta = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'photo_dir': os.path.abspath(args.photos),
        'sources': sources,
        'checklist_codes': len(ck_codes),
        'customs_codes': len(customs_codes),
        'intersection': len(ck_codes & customs_codes) if customs_codes else 0,
        'checklist_only': sorted(ck_codes - customs_codes) if customs_codes else [],
        'customs_only': sorted(customs_codes - ck_codes) if customs_codes else [],
        'photo_stats': pstats,
        'ocr_stats': ocr_stats,
        'group_gap_sec': GROUP_GAP_SEC,
        'group_max_photos': GROUP_MAX_PHOTOS,
    }

    # ── 6. 落盘 ──
    print('\n[5/6] 写出产品库')
    if args.dry_run:
        print('  --dry-run：不落盘。以下是要写出的内容：')
        print('    library.db（%d 编码 / %d 照片 / %d 绑定）'
              % (len(products), len(photos), len(bindings)))
        print('    _编码对照表.csv, _待复核.csv, _建库报告.md')
    else:
        db = write_library(args.out, meta, products, photos, bindings)
        pmap = {ph['file']: ph for ph in photos}
        cr = write_cross_reference(args.out, products, pmap, bindings)
        rq = write_review_queue(args.out, products, pmap, bindings)
        mf = write_manifest(args.out, meta, products, photos, bindings)
        rp = write_report(args.out, meta, pstats, products, bindings, photos, ocr_stats)
        print('  %s' % db)
        print('  %s' % cr)
        print('  %s' % rq)
        print('  %s' % mf)
        print('  %s' % rp)

    print('\n[6/6] 完成，用时 %.0fs' % (time.time() - t_start))
    print('=' * 64)
    return 0


if __name__ == '__main__':
    sys.exit(main())
