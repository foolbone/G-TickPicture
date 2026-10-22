# -*- coding: utf-8 -*-
"""
report_gen.py -- 装柜监装报告 docx 生成器（2026-10-05 v3）

对齐样例：`SZAE-LOADING REPORT-CNTR#EMCU9914616-Sep-27-2026.docx`
（百达/SZAE 格式，137 页 / 438 图 / 42MB）。版式参数是从样例 document.xml
与 styles.xml 里**量出来**的，不是猜的：

    页面      A4 纵向 11906×16838 twips
    页边距    上下 1.0" / 左右 0.75"   → 版心宽 6.77"
    正文字体  Times New Roman + 宋体（eastAsia）
    表格宽    9653 dxa ≈ 6.7"

八个区块（与样例一一对应）：
    ① 抬头页        标题 + 供应商固定信息块
    ② 项目信息表    Product/Client/Date/Location/Inspector
    ③ 柜汇总表      NO./CONTAINER NO./SEAL NO./Q'ty/REMARKS
    ④ General Info  柜号/封条/订单数量/到货数量/到离柜时间 + 4 张柜况照
    ⑤ Packing list  6 列 + TOTAL 行（按清单**原行**出，不合并同码）
    ⑥ Quantity check 2 列网格，图注 `编码-描述-箱号`
    ⑦ Truck picture 2 列网格，图注是照片角色的固定英文文案
    ⑧ 结尾

    分页（10-07 老板）：④⑤⑥⑦ 各自**从新页开始**；照片网格每页固定
    PHOTOS_PER_PAGE=6 张（2 列 × 3 行），超出的切到下一页。

═══════════════════════════════════════════════════════════════════
照片的**版面**处理全在这里，一个像素都不回写原图（2026-10-05 拍板）
═══════════════════════════════════════════════════════════════════
治理环节只产生元数据（分类 / 标签 / 关联 / 标准图），**永远不碰像素**；
方向矫正、缩放、版位适配全是报告生成的活。理由：
  · 原始照片是取证证据，治理管道一旦写像素，出错不可逆；
  · 同一张图要出素材包（1600px）/ 标准库（裁剪版）/ 报告（版位适配），
    三套尺寸，固化在治理里是错误抽象；
  · 版式改版（2 列 → 3 列）只改本文件的常量，不必重跑治理管道。
人工真要修图走 standard_images（标准资产），本模块**优先用标准图**。
"""
import io
import math
import os
import re

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import (WD_TABLE_ALIGNMENT, WD_ROW_HEIGHT_RULE,
                             WD_CELL_VERTICAL_ALIGNMENT)
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

# 数量列文本 → 数字 / 整数文本：**委托 schema 的单一真源**。
# store.loading_report_data 算页面汇总、report_gen 算 TOTAL 行，两边必须
# 用同一个解析口径 —— 各写一份必然漂（铁律 23：数字同源）。
from tools.productlib.schema import fmt_int as _fmt_int  # noqa: E402
from tools.productlib.schema import to_number as to_num  # noqa: E402
# 照片路径归一（便携化读侧的纯函数，不连库）。store 不反向 import 本模块，
# 无循环依赖；且 server 启动时 store 早已加载，无额外成本。
from tools.productlib.store import photo_rel_path as _photo_rel_path  # noqa: E402

# ── 版式常量（全部来自样例实测）──────────────────────────────────
PAGE_W_IN = 8.27            # A4 宽
PAGE_H_IN = 11.69           # A4 高
CONTENT_W_IN = 6.77         # 版心宽 = 8.27 - 0.75*2
CONTENT_H_IN = 9.69         # 版心高 = 11.69 - 1.0*2（上下页边距各 1.0"）
CELL_W_IN = 3.15            # 2 列网格每格宽（两列 + 列间 + 单元格边距）
CELL_H_MAX_IN = 4.2         # 单格最大高：极端竖图（9:16）按高钳制，不撑爆页面
# 网格照片的**统一显示高**（10-05 老板：报告照片排版要整齐）。
# 旧逻辑高随宽高比自由伸缩，一竖一横同排，行高差一倍，参差难看。
# 现在所有网格照片（④⑥⑦）统一渲染高度：竖图按高收窄、横图按宽铺满、
# 超宽全景钳到格宽 —— 行行齐平，只有图注行数可能差一行。
GRID_PHOTO_H_IN = 2.2
# 🔴 2026-10-18 老板实测断层第二层修复：2.35→2.2。真实渲染（Word COM 转 PDF
#    实测柜 67ee5dd4bf8a）发现「标题 0.4 + 3 行×2.97 + 表后空段 ≈ 9.5」贴着
#    版心 9.69 的临界，Word 累积舍入把③第 3 行挤走 —— ⑥首页 6 张变 5 张、
#    下页 5 张（老板截图 2+5 同款）。留 0.6"+ 余量后每页稳定 6 张。
# ── 照片分页（10-07 老板：一页固定 6 张，新章节另起一页）────────────
# 2 列 × 3 行 = 6 张/页。之所以**显式切页**而不是让 Word 自己流：
# 表格跨页时 Word 会按行高硬切，一页可能塞 4 张也可能挤 7 张，
# 客户拿到的每份报告页数都不一样。显式切页 = 页数可预期。
# ⚠️ 预算校验见 `page_budget_ok()` —— 改 GRID_PHOTO_H / 页边距前先跑它，
#    否则「6 张」会溢出成 4 张（多出来的行被顶到下一页）。
GRID_COLS = 2
PHOTOS_PER_PAGE = 6                       # 每页照片数
GRID_ROWS_PER_PAGE = PHOTOS_PER_PAGE // GRID_COLS   # 3
# 图注限长（2026-10-18 断层修复）：超长品名/多箱号会把行高撑爆、
# Word 挤页断层。见 _caption_check。
CAP_NAME_MAX = 46                          # 品名最多字符（含省略号）
CAP_CARTON_MAX = 2                         # 箱号最多列几个，其余 +N more
# ④柜况多选时的格内竖排：每张最低显示高 + caption 预留（2026-10-18）
# ⚠️ 2026-10-22 老板报「选了多张图片，生成的就有问题」：
#    原来 MIN=1.1"，3 张时 1.1×3 + 0.35 = 3.65" 已经**超过行高 2.82"**，
#    而行高是 EXACTLY → 超出的部分被 Word 直接裁掉（截图里图被切断、
#    caption 掉出格）。改成 0.6" 下限 + 行高按内容抬升（见 t4b 的 row_need）：
#    2 张仍走原预算（0.925" ×2 = 2.2" 正好），3 张各 0.617" 也不裁，
#    张数更多时行高按需长高，绝不再把图压在格子里切掉。
COND_MULTI_MIN_H_IN = 0.6
COND_CAPTION_H_IN = 0.35
# 章节标题带占高：space_before 10pt + 11pt 行高 + space_after 6pt ≈ 0.40"
SECTION_TITLE_H_IN = 0.40
# ── 统一图框（10-05 第二轮：老板「有的横着有的竖着」）────────────────
# 光统一显示高还不够：竖图收窄后两侧大片留白，横竖混排还是乱。
# 现在把每张照片**合成到同一尺寸的白底图框**里（等比缩放居中 + 细边框）——
# 嵌入的每张图像素尺寸完全相同，网格就是刀切一样的齐。
# 用 contain（完整放下）不用 cover（裁切）：报告图是取证材料，
# 标签/箱号不能被裁掉。
FRAME_PX_W = 1080           # 图框像素宽（3.15" @ ~343DPI）
FRAME_PX_H = 806            # 图框像素高（保持 CELL_W : GRID_PHOTO_H = 1.34）
FRAME_INNER_RATIO = 0.985   # 图框内边距（白边）
FRAME_LINE = (0xD3, 0xD9, 0xE2)   # 图框细线颜色
FRAME_BG = (0xFF, 0xFF, 0xFF)

# ── 专业视觉（10-05：报告要「专业大气」）─────────────────────────
NAVY = (0x1F, 0x38, 0x64)         # 主色（深藏青，印刷友好）
GRAY_TEXT = (0x5A, 0x64, 0x74)    # 次级文字
BAND_FILL = '1F3864'              # 区块标题带底色
HEAD_FILL = 'EDF2F9'              # 表头底色
SUBHEAD_FILL = 'F5F7FA'           # 标签列底色
ZEBRA_FILL = 'F9FBFD'             # 斑马行
TOTAL_FILL = 'E8EEF7'             # 合计行
LINE_COLOR = 'C9D2DE'             # 细线
PHOTO_ROW_H_IN = GRID_PHOTO_H_IN + 0.62   # 图框 + 三段图注（含余量）
PHOTO_LONG_EDGE = 1200      # 嵌入分辨率（格宽 3.15" @300DPI ≈ 945px，1200 已超配）
PHOTO_QUALITY = 82          # JPEG 质量（取证用途，标签与箱号仍清晰）
FONT_ASCII = 'Times New Roman'
FONT_EA = '宋体'

# 报告抬头默认模板（SZAE 那套）。可放 data/report_templates/<名>.json 覆盖。
DEFAULT_TEMPLATE = {
    'title_line1': 'Report of',
    'title_line2': 'CARGO LOADING SUPERVISION',
    'supplier': [
        'Supplier：SHENZHEN A&E CONTAINERTRANSPORTATION CO.,LTD',
        'Contract person:Joyce Hu',
        'Email:joyce.hu@p-scs.com',
        'Website:http://www.ae-first.com',
        'Add: Rm.2108,Overseas Friendship Building,No, 12, YingchunRoad, Luohu，',
        'Shenzhen,China.',
    ],
    'labels': {
        'product': 'Product Name:', 'client': 'Client Name:',
        'date': 'Inspection Date', 'location': 'Inspection Location',
        'inspector': 'Inspector', 'no': 'NO.', 'container': 'CONTAIER NO.',
        'seal': 'SEAL NO.', 'qty': "Q'ty", 'remarks': 'REMARKS',
    },
    'not_provided': 'Not provided',
    'qty_suffix': 'PCS',
}

# ⑦ Truck picture 的固定英文图注（与样例一致）
TRUCK_CAPTIONS = {
    'truck_head': 'Truck head / Truck no',
    'loading_process': 'Loading container view',
    'other': 'Container view',
}
# ④ 柜况 4 图的固定英文图注（样例的 2×2 四格）
CONDITION_CAPTIONS = {
    'empty_container': 'Empty picture',
    'container_side': 'Container side picture',
    'container_seal': 'Seal no.',
    'container_lock': 'Lock door picture',
}



def _set_run_font(run, size=None, bold=False, color=None):
    """字体三件套：ascii / hAnsi / eastAsia。

    ⚠️ python-docx 只设 `font.name` 时**中文会回退到 Calibri**（Word 的
    默认中文回退是宋体，但不同机器/版本不一致）—— 报告要发到客户手上，
    中文（品名/描述可能有中文）必须显式给 eastAsia。
    """
    run.font.name = FONT_ASCII
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn('w:rFonts'))
    if rf is None:
        rf = rpr.makeelement(qn('w:rFonts'), {})
        rpr.append(rf)
    rf.set(qn('w:ascii'), FONT_ASCII)
    rf.set(qn('w:hAnsi'), FONT_ASCII)
    rf.set(qn('w:eastAsia'), FONT_EA)
    if size is not None:
        run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


def _cell_text(cell, text, size=8, bold=False, align=None, color=None):
    """往表格单元格里写一行（清掉默认空段落）。"""
    cell.text = ''
    p = cell.paragraphs[0]
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run('' if text is None else str(text))
    _set_run_font(run, size=size, bold=bold, color=color)
    return p


# ═══════════════════════════════════════════════════════════════════
# OOXML 视觉工具（专业排版需要的能力，python-docx 没有现成 API）
#
# ⚠️ OOXML 的 pPr/tcPr/tblPr 子元素**顺序是 schema 强制的**，乱 append
#    Word 会报「文件损坏」。全部用 insert_element_before(元素, *后继标签)
#    插在正确位置 —— 后继列表就是 schema 里排在它后面的那些元素。
# ═══════════════════════════════════════════════════════════════════

def _shade_cell(cell, fill):
    """单元格底色（表头 / 标签列 / 斑马行 / 合计行）。"""
    tcpr = cell._tc.get_or_add_tcPr()
    for old in tcpr.findall(qn('w:shd')):
        tcpr.remove(old)
    el = parse_xml('<w:shd %s w:val="clear" w:color="auto" w:fill="%s"/>'
                   % (nsdecls('w'), fill))
    tcpr.insert_element_before(el, 'w:noWrap', 'w:tcMar', 'w:textDirection',
                               'w:tcFitText', 'w:vAlign', 'w:hideMark')


def _shade_para(p, fill):
    """段落底色（区块标题带）。"""
    ppr = p._p.get_or_add_pPr()
    for old in ppr.findall(qn('w:shd')):
        ppr.remove(old)
    el = parse_xml('<w:shd %s w:val="clear" w:color="auto" w:fill="%s"/>'
                   % (nsdecls('w'), fill))
    ppr.insert_element_before(el, 'w:tabs', 'w:suppressAutoHyphens',
                              'w:spacing', 'w:ind', 'w:jc', 'w:rPr')


def _rule_para(p, color=LINE_COLOR, sz=6, where='bottom'):
    """给段落加横线（封面标题分隔线 / 结尾线）。"""
    ppr = p._p.get_or_add_pPr()
    for old in ppr.findall(qn('w:pBdr')):
        ppr.remove(old)
    el = parse_xml('<w:pBdr %s><w:%s w:val="single" w:sz="%d" w:space="2" '
                   'w:color="%s"/></w:pBdr>' % (nsdecls('w'), where, sz, color))
    ppr.insert_element_before(el, 'w:shd', 'w:tabs', 'w:spacing', 'w:ind',
                              'w:jc', 'w:rPr')


def _set_table_borders(table, color=LINE_COLOR, sz=4, inside=True):
    """细线表格（替换 'Table Grid' 的粗黑线，专业观感的关键之一）。"""
    tblpr = table._tbl.tblPr
    for old in tblpr.findall(qn('w:tblBorders')):
        tblpr.remove(old)
    parts = ['<w:tblBorders %s>' % nsdecls('w')]
    for edge in ('top', 'left', 'bottom', 'right'):
        parts.append('<w:%s w:val="single" w:sz="%d" w:space="0" w:color="%s"/>'
                     % (edge, sz, color))
    for edge in ('insideH', 'insideV'):
        rule = 'single' if inside else 'none'
        parts.append('<w:%s w:val="%s" w:sz="%d" w:space="0" w:color="%s"/>'
                     % (edge, rule, sz, color))
    parts.append('</w:tblBorders>')
    tblpr.insert_element_before(parse_xml(''.join(parts)), 'w:shd',
                                'w:tblLayout', 'w:tblCellMar', 'w:tblLook')


def _set_no_borders(table):
    """无边框表格（照片网格用：图框自带细线，网格再画线就乱了）。"""
    tblpr = table._tbl.tblPr
    for old in tblpr.findall(qn('w:tblBorders')):
        tblpr.remove(old)
    parts = ['<w:tblBorders %s>' % nsdecls('w')]
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        parts.append('<w:%s w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
                     % edge)
    parts.append('</w:tblBorders>')
    tblpr.insert_element_before(parse_xml(''.join(parts)), 'w:shd',
                                'w:tblLayout', 'w:tblCellMar', 'w:tblLook')


def _set_cell_margins(table, top=40, bottom=40, left=80, right=80):
    """表格内边距（dxa，1/20 pt）—— 默认太挤，图注贴着图框。"""
    tblpr = table._tbl.tblPr
    for old in tblpr.findall(qn('w:tblCellMar')):
        tblpr.remove(old)
    el = parse_xml(
        '<w:tblCellMar %s><w:top w:w="%d" w:type="dxa"/><w:left w:w="%d" '
        'w:type="dxa"/><w:bottom w:w="%d" w:type="dxa"/><w:right w:w="%d" '
        'w:type="dxa"/></w:tblCellMar>' % (nsdecls('w'), top, left, bottom, right))
    tblpr.insert_element_before(el, 'w:tblLook')


def _section_title(doc, text, sub=None):
    """区块标题带：深藏青底 + 白字。八个区块的视觉骨架。"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.left_indent = Inches(0.06)
    run = p.add_run(text)
    _set_run_font(run, size=11, bold=True, color=(0xFF, 0xFF, 0xFF))
    if sub:
        r2 = p.add_run('   ' + sub)
        _set_run_font(r2, size=8.5, color=(0xD6, 0xE0, 0xF0))
    _shade_para(p, BAND_FILL)
    return p


def _field(paragraph, instr, placeholder='1'):
    """页脚域（PAGE / NUMPAGES）—— python-docx 没有 API，用 fldSimple。"""
    paragraph._p.append(parse_xml(
        '<w:fldSimple %s w:instr=" %s "><w:r><w:t>%s</w:t></w:r></w:fldSimple>'
        % (nsdecls('w'), instr, placeholder)))


def _setup_footer(sec, container_no, total_pages=None):
    """页脚：左「柜号 · LOADING REPORT」，右「Page X of Y」。

    ⚠️ Word 打开时才把域算成真页码（这里写的占位数字 Word 会覆盖）。
    """
    ftr = sec.footer
    ftr.is_linked_to_previous = False
    p = ftr.paragraphs[0]
    p.paragraph_format.tab_stops.add_tab_stop(Inches(CONTENT_W_IN),
                                              WD_TAB_ALIGNMENT.RIGHT)
    _set_run_font(p.add_run('%s  ·  LOADING REPORT' % container_no),
                  size=8, color=GRAY_TEXT)
    _set_run_font(p.add_run('\t'), size=8)
    _set_run_font(p.add_run('Page '), size=8, color=GRAY_TEXT)
    _field(p, 'PAGE')
    _set_run_font(p.add_run(' of '), size=8, color=GRAY_TEXT)
    _field(p, 'NUMPAGES')
    return p


def _fit_box(img_w, img_h, max_w=CELL_W_IN, max_h=CELL_H_MAX_IN):
    """按版位算显示尺寸（inch）。

    规则：宽固定 = max_w；高按宽高比；超高（极端竖图）改为高=max_h、宽自适应。
    只改**显示**尺寸，不改像素 —— 像素在 `_prep_photo` 里按需降采样。
    """
    if img_w <= 0 or img_h <= 0:
        return max_w, max_w
    h = max_w * img_h / img_w
    if h > max_h:
        return max_h * img_w / img_h, max_h
    return max_w, h


def _fit_uniform(img_w, img_h, box_h=GRID_PHOTO_H_IN, max_w=CELL_W_IN):
    """网格照片统一格高：所有图同一显示高度，行行齐平。

    - 正常图：高 = box_h，宽按宽高比（≤ max_w）
    - 超宽全景（宽高比 > max_w/box_h）：钳到格宽，高等比缩小 —— 这一张
      略矮于格高，但保住「不变形、不超格」两条底线，比拉变形强。
    """
    if img_w <= 0 or img_h <= 0:
        return max_w, box_h
    w = box_h * img_w / img_h
    if w > max_w:
        return max_w, max_w * img_h / img_w
    return w, box_h


def _prep_photo(path, long_edge=PHOTO_LONG_EDGE, quality=PHOTO_QUALITY,
                frame=False):
    """读图 → 摆正方向 → 版位处理 → 返回 (BytesIO, 宽, 高)。

    ⚠️ **EXIF 方向必须在这里矫正**（`exif_transpose`）：手机横竖拍存的是
    传感器像素 + Orientation 标记，不转的话 Word 里会躺着 90° 的照片。
    矫正只发生在内存副本上，原文件不写。

    [frame=True] 合成到**统一图框**：白底、等比 contain、居中、描细边，
    输出恒为 FRAME_PX_W × FRAME_PX_H。横图竖图进报告后外观完全一致 ——
    这是「排版整齐」的地基（只统一显示尺寸治不了竖图两侧的大留白）。
    仍**不改原图、不裁内容**。
    """
    from PIL import Image, ImageDraw, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ('RGB', 'L'):
            im = im.convert('RGB')
        if not frame:
            w, h = im.size
            scale = 1.0
            if long_edge and max(w, h) > long_edge:
                scale = long_edge / float(max(w, h))
            if scale < 1.0:
                im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                               Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format='JPEG', quality=quality, optimize=True)
            buf.seek(0)
            return buf, im.size[0], im.size[1]

        # ── 统一图框 ──
        inner_w = int(FRAME_PX_W * FRAME_INNER_RATIO)
        inner_h = int(FRAME_PX_H * FRAME_INNER_RATIO)
        w, h = im.size
        scale = min(inner_w / float(w), inner_h / float(h))
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        if (nw, nh) != (w, h):
            im = im.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new('RGB', (FRAME_PX_W, FRAME_PX_H), FRAME_BG)
        x0, y0 = (FRAME_PX_W - nw) // 2, (FRAME_PX_H - nh) // 2
        canvas.paste(im, (x0, y0))
        d = ImageDraw.Draw(canvas)
        d.rectangle([x0 - 1, y0 - 1, x0 + nw, y0 + nh], outline=FRAME_LINE,
                    width=2)
        buf = io.BytesIO()
        canvas.save(buf, format='JPEG', quality=quality, optimize=True)
        buf.seek(0)
        return buf, FRAME_PX_W, FRAME_PX_H


def _as_caption_lines(caption):
    """图注统一成「多行结构」：str → 单行；list → 逐行。

    多行的意义（10-05 老板：图注不清晰）：`A-B-C` 连成一串看不出哪段是
    件号、哪段是箱号。改成三段带标签：件号加粗 / 描述 / 箱号，一眼可读。
    """
    if caption is None:
        return []
    if isinstance(caption, str):
        return [{'text': caption}]
    return [dict(x) for x in caption if (x or {}).get('text')]


_PHOTO_ROOT = None


def set_photo_root(root):
    """设置照片**相对路径的基准根**（= 库文件所在目录 data/）。

    必须在 build_*_report 之前调用；为空时退回原 path（老行为）。
    """
    global _PHOTO_ROOT
    _PHOTO_ROOT = root or None


def _resolve_photo_path(path):
    """把 photos.path 解析成本机可用的绝对路径（便携化读侧）。

    🔴 2026-10-20 事故（老板报「报告里图片显示不出来」）：便携化改造后
    `photos.path` 是「相对导入根」形态（`origin/GAOU.../xxx.jpg`），而这里
    原来直接 `os.path.exists(path)` —— 相对路径按 **exe 的当前工作目录**解析，
    于是全部判「不存在」，报告里满屏 `Not provided`。源码跑不复现（CWD 恰好
    在仓库根），打包版搬到别的目录必现。

    口径与 store.resolve_photo_path 一致：绝对且存在 → 原样；
    否则归一出相对段、拼 `_PHOTO_ROOT`；仍不行 → 返回原值（上层写 missing）。
    这里不惰性回写库（报告生成是只读路径）。
    """
    p = str(path or '')
    if not p:
        return p
    if os.path.isabs(p) and os.path.exists(p):
        return p
    if not _PHOTO_ROOT:
        return p
    rel = _photo_rel_path(p)
    if not rel:
        return p
    full = os.path.join(_PHOTO_ROOT, *rel.split('/'))
    return full if os.path.exists(full) else p


def _add_photo(cell, path, caption=None, missing_text='Not provided',
               size=8, cap_size=7.5, box_h=None, frame=False, new_para=False):
    """单元格里放一张照片 + 可选图注。照片缺失时写 missing_text（不抛异常）。

    报告**不因为缺图而阻断**（与「交付不设检查」同一拍板）：缺就是缺，
    如实写 Not provided，比留一个空格子让人误以为"这格没内容要求"好。

    [box_h]  传 GRID_PHOTO_H_IN = 网格统一显示高
    [frame]  True = 先合成统一图框（横竖归一，见 `_prep_photo`）
    [caption] str（单行）或 [{'text','size','bold','color'}, ...]（多行）
    [new_para] True = 新起一段落放图（同格多张时用；False 会并排在同一行，
        2026-10-18 柜况多选实测 bug）
    """
    full = _resolve_photo_path(path)
    if not full or not os.path.exists(full):
        _cell_text(cell, missing_text, size=size, align=WD_ALIGN_PARAGRAPH.CENTER,
                   color=(0x99, 0x99, 0x99))
        return False
    try:
        buf, w, h = _prep_photo(full, frame=frame)
    except Exception as e:  # noqa: BLE001 —— 单张图坏掉不能毁掉整份报告
        _cell_text(cell, 'Photo error: %s' % str(e)[:60], size=size,
                   align=WD_ALIGN_PARAGRAPH.CENTER, color=(0xCC, 0x00, 0x00))
        return False
    pw, ph = (_fit_uniform(w, h, box_h) if box_h
              else _fit_box(w, h))
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p = cell.add_paragraph() if new_para else cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_picture(buf, width=Inches(pw), height=Inches(ph))
    for line in _as_caption_lines(caption):
        cp = cell.add_paragraph()
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.paragraph_format.space_before = Pt(1.5 if line is not None else 0)
        cp.paragraph_format.space_after = Pt(0)
        _set_run_font(cp.add_run(line['text']),
                      size=line.get('size', cap_size),
                      bold=line.get('bold', False),
                      color=line.get('color'))
    return True


def _kv_row(table, row_idx, pairs, size=9, label_bold=True):
    """一行里放若干「标签: 值」对（样例区块②④ 都是这个版式）。"""
    cells = table.rows[row_idx].cells
    i = 0
    for label, value in pairs:
        if i >= len(cells):
            break
        _cell_text(cells[i], label, size=size, bold=label_bold, color=NAVY)
        if i + 1 < len(cells):
            _cell_text(cells[i + 1], value, size=size)
        i += 2
    return cells


def _page_break(doc):
    """另起一页。

    ⚠️ 必须**新建段落**再 add_break：Word 里「表格后直接跟表格」会被合并成一个
    表，中间的段落是天然的分隔；分页符打在这个段落上才生效。
    """
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_break(WD_BREAK.PAGE)
    return p


def page_budget_ok():
    """「一页 6 张」是否真装得下（含章节标题）。

    算的是**版心高 vs 标题带 + 3 行照片**，不是目测。改页边距 / 格高 /
    每页张数都要先过这一关 —— 装不下时 Word 会把第四行顶到下一页，
    页面就变成 4 张，而生成器一声不吭（静默降级最难查）。
    """
    return (SECTION_TITLE_H_IN + GRID_ROWS_PER_PAGE * PHOTO_ROW_H_IN
            <= CONTENT_H_IN)


def _grid_table(doc, items, caption_of, missing_text, cols):
    """一页照片网格（2 列 × 3 行 = 6 张）。"""
    rows = (len(items) + cols - 1) // cols
    table = doc.add_table(rows=rows, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_no_borders(table)          # 图框自带细线，网格不再画线
    _set_cell_margins(table, top=60, bottom=80, left=90, right=90)
    n = 0
    for r in range(rows):
        for c in range(cols):
            cell = table.rows[r].cells[c]
            idx = r * cols + c
            if idx < len(items):
                it = items[idx]
                n += 1 if _add_photo(cell, it.get('path'), caption_of(it),
                                     missing_text, box_h=GRID_PHOTO_H_IN,
                                     frame=True) else 0
            else:
                _cell_text(cell, '')
    for row in table.rows:   # 图框恒定 + 图注行数固定 → 行行齐平
        # 🔴 EXACT 而非 AT_LEAST（2026-10-18 老板实测断层第三层）：
        # atLeast 允许行增高，Word 在临界高度会把**行内单个 cell** 劈到
        # 下下页、中间还插一个空页（现场报告 MRSU2065286 实测：⑦表第 3 行
        # 右格单独跑路，页面 5+空+5）。EXACT 钉死行高：放不下整行平移，
        # 行不拆、不增高、不插空页。caption 已被 CAP_* 限长保证单行，
        # 2.2 + 0.33 < 2.82 不会截断文字。
        row.height = Inches(PHOTO_ROW_H_IN)
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        _no_row_split(row)
    return n


def _no_row_split(row):
    """表格行**禁止跨页拆分**（w:cantSplit）。

    🔴 2026-10-18 老板实测断层（一页 2 张、一页 5 张）的第二根因：
    Word 默认允许一行从中间断开 —— 「2 列 × 3 行」的表里某行会被
    拦腰拆成「这张在这页、那张在下页」，页面出现 2+5 / 5+5 的畸形分布，
    而每页 6 张的显式切表完全正确（document.xml 里每表就是 6 张）。
    cantSplit = 整行不拆：放不下就整行去下一页，配合显式切表回到 6 张/页。
    """
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    trPr = row._tr.get_or_add_trPr()
    if trPr.find(qn('w:cantSplit')) is None:
        trPr.append(OxmlElement('w:cantSplit'))


def _grid_photos(doc, items, caption_of, missing_text, cols=GRID_COLS,
                 per_page=PHOTOS_PER_PAGE):
    """照片网格，**每页固定 per_page 张**（默认 6 = 2 列 × 3 行）。

    [items] 每项 {'path':..., 'key':...}；caption_of(item) 返回图注文本。
    图注是这张照片的**身份说明**（编码-描述-箱号 / 角色固定文案），
    不是文件名 —— 报告员靠它判断"这张拍的是哪件货"。

    切成多张表而不是一张长表：Word 让长表自己跨页会按累计行高硬断，
    每页张数随图片比例浮动（4~7 张都有），客户拿到的报告页数不可预期。
    显式切表 + 分页符 = 每页就是 6 张（末页除外）。
    """
    if not items:
        p = doc.add_paragraph()
        _set_run_font(p.add_run('(No photo)'), size=9, color=(0x99, 0x99, 0x99))
        return 0
    per_page = max(cols, int(per_page or PHOTOS_PER_PAGE))
    n = 0
    for start in range(0, len(items), per_page):
        if start:
            _page_break(doc)
        n += _grid_table(doc, items[start:start + per_page], caption_of,
                         missing_text, cols)
    return n


def _save_report(doc, out_path):
    """保存 docx：**先写 .tmp 再原子替换**；目标被占用就换名另存。

    为什么（10-06 实测）：报告文件名按「柜号+日期」固定，同一天重复生成就是
    覆盖同一个文件。老板把上一版拖进 Word 看着呢，Windows 就把目标文件锁住，
    `doc.save(路径)` 直接抛 PermissionError → 整次生成失败、前面 20 秒白跑。
    现在：tmp 落盘 → os.replace 原子替换；被锁就自动加时分秒另存一份并如实
    告诉调用方「另存了哪个名字」。**生成永远不该因为"文档正开着"而失败。**

    返回 (实际路径, 是否因占用而改名)。
    """
    from datetime import datetime
    tmp = out_path + '.tmp'
    doc.save(tmp)                      # .tmp 不会被 Word 锁
    try:
        os.replace(tmp, out_path)      # 原子替换：要么全成功要么原样不动
        return out_path, False
    except PermissionError:
        stem, ext = os.path.splitext(out_path)
        alt = '%s-%s%s' % (stem, datetime.now().strftime('%H%M%S'), ext)
        os.replace(tmp, alt)
        return alt, True


def build_loading_report(data, out_path, template=None, long_edge=PHOTO_LONG_EDGE,
                         photo_root=None):
    """生成装柜报告 docx。

    [data] 全部数据由 store.loading_report_data 组装（**报告页与柜详情页
    共用同一份**，数字不会两处漂）。字段见该函数 docstring。
    [template] 抬头模板（data/report_templates/*.json 或 None → 内置 SZAE）。
    返回 {'path', 'bytes', 'photos', 'missing_condition', 'qty_unparsed'}。

    ⚠️ 数量列**照抄清单原文**（'12.0' 就写 '12.0'），只在 TOTAL 行求和；
    解析不出数字的行计入 qty_unparsed，由报告页提示，**不静默当 0**。

    [photo_root] 照片相对路径的基准根（= 库文件所在目录 data/）。不传就按
    原 path 用 —— 源码跑通常没事（CWD 恰好是仓库根），但**打包版搬到别的
    目录后相对路径全部失效，报告会满屏 Not provided**（2026-10-20 事故）。
    """
    set_photo_root(photo_root)
    tpl = dict(DEFAULT_TEMPLATE)
    if template:
        tpl.update(template or {})
    labels = dict(DEFAULT_TEMPLATE['labels'])
    labels.update((template or {}).get('labels') or {})

    meta = data.get('meta') or {}
    rows = data.get('rows') or []
    checks = data.get('checks') or []
    trucks = data.get('trucks') or []
    cond = data.get('conditions') or {}
    container_no = meta.get('container_no') or ''

    doc = Document()
    sec = doc.sections[0]
    # 🔴 纸型必须**显式设 A4**（2026-10-11 真实报告抓到）：python-docx 的
    #    默认模板是 Letter（8.5×11"），只设页边距不设纸型，版心高只剩
    #    11 - 2 = 9.0"，装不下「标题带 + 3 行照片」（9.45"），第三行被
    #    Word 顶到下一页 —— 每页静默掉成 4 张，而 page_budget_ok 按 A4
    #    算永远是绿的。下面两个常量本来就是按 A4 样例实测的，这里对齐。
    sec.page_width = Inches(PAGE_W_IN)
    sec.page_height = Inches(PAGE_H_IN)
    sec.left_margin = Inches(0.75)
    sec.right_margin = Inches(0.75)
    sec.top_margin = Inches(1.0)
    sec.bottom_margin = Inches(1.0)

    # ── ① 封面 / 抬头（居中标题 + 分隔线 + 供应商信息块）────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(0)
    _set_run_font(p.add_run(tpl['title_line1']), size=13,
                  color=GRAY_TEXT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    _set_run_font(p.add_run(tpl['title_line2']), size=22, bold=True, color=NAVY)
    _rule_para(p, color='1F3864', sz=12, where='bottom')
    for line in tpl['supplier']:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        _set_run_font(p.add_run(line), size=8.5, color=GRAY_TEXT)
    doc.add_paragraph()

    # ── ② 项目信息表 ──────────────────────────────────────────
    t2 = doc.add_table(rows=5, cols=2)
    _set_table_borders(t2)
    _set_cell_margins(t2)
    info = [
        (labels['product'], meta.get('product_name') or meta.get('remark') or ''),
        (labels['client'], meta.get('client_name') or ''),
        (labels['date'], meta.get('inspection_date') or ''),
        (labels['location'], meta.get('location') or ''),
        (labels['inspector'], meta.get('inspector') or ''),
    ]
    for i, (k, v) in enumerate(info):
        _cell_text(t2.rows[i].cells[0], k, size=9, bold=True, color=NAVY)
        _shade_cell(t2.rows[i].cells[0], SUBHEAD_FILL)
        _cell_text(t2.rows[i].cells[1], v or tpl['not_provided'], size=9)
    doc.add_paragraph()

    # ── ③ 柜汇总表 ────────────────────────────────────────────
    t3 = doc.add_table(rows=2, cols=5)
    _set_table_borders(t3)
    _set_cell_margins(t3)
    hdr3 = [labels['no'], labels['container'], labels['seal'],
            labels['qty'], labels['remarks']]
    for i, h in enumerate(hdr3):
        _cell_text(t3.rows[0].cells[i], h, size=9, bold=True,
                   align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY)
        _shade_cell(t3.rows[0].cells[i], HEAD_FILL)
    s = data.get('summary') or {}
    qty_txt = '%s %s' % (_fmt_int(s.get('order_total')),
                         tpl['qty_suffix']) if s.get('order_total') is not None else ''
    vals3 = ['1', container_no, meta.get('seal_no') or '', qty_txt,
             meta.get('remark') or '']
    for i, v in enumerate(vals3):
        _cell_text(t3.rows[1].cells[i], v, size=9,
                   align=WD_ALIGN_PARAGRAPH.CENTER if i < 4 else None)
    doc.add_paragraph()

    # ── ④ General Information ─────────────────────────────────
    # 章节从新页开始（10-07 老板）：每个区块标题带都另起一页，
    # 客户翻报告时「柜况 / 清单 / 核对 / 卡车」各占一段，不会挤在半页里。
    _page_break(doc)
    _section_title(doc, 'General Information', container_no)
    t4 = doc.add_table(rows=3, cols=4)
    _set_table_borders(t4)
    _set_cell_margins(t4)
    _kv_row(t4, 0, [('Container numbers', container_no),
                    ('Seal numbers', meta.get('seal_no') or '')])
    _kv_row(t4, 1, [('Order Quantity', _qty_str(s.get('order_qty_display'))),
                    ('Available Quantity', _qty_str(s.get('loading_qty_display')))])
    _kv_row(t4, 2, [('Arrival time', _fmt_en_date(meta.get('arrival_at')) or ''),
                    ('Departure time',
                     _fmt_en_date(meta.get('departure_at')) or '')])
    for ri in range(3):        # 标签列淡底，数据可读性
        for ci in (0, 2):
            _shade_cell(t4.rows[ri].cells[ci], SUBHEAD_FILL)
    doc.add_paragraph()
    # 柜况 4 图（2×2）：统一图框，缺失 → Not provided（不阻断）
    # 2026-10-18 老板规则：监装细类不限一张 —— cond[tag] 是 [path,...]，
    # 多张时格内竖排均分格高（caption 一段放格底，保持行高可预算）。
    t4b = doc.add_table(rows=2, cols=2)
    _set_no_borders(t4b)
    _set_cell_margins(t4b, top=60, bottom=80, left=90, right=90)
    n_cond_missing = 0
    row_need = {0: 0.0, 1: 0.0}     # 每行「内容实际需要的高度」—— 行高不能小于它
    for i, tag in enumerate(('empty_container', 'container_side',
                             'container_seal', 'container_lock')):
        cell = t4b.rows[i // 2].cells[i % 2]
        cap = [{'text': CONDITION_CAPTIONS.get(tag, tag), 'size': 8, 'bold': True}]
        if tag == 'container_seal' and meta.get('seal_no'):
            cap.append({'text': meta['seal_no'], 'size': 7.5, 'color': GRAY_TEXT})
        paths = cond.get(tag) or []
        if not isinstance(paths, list):
            paths = [paths] if paths else []
        if len(paths) <= 1:
            ok = _add_photo(cell, paths[0] if paths else None, cap,
                            tpl['not_provided'],
                            box_h=GRID_PHOTO_H_IN, frame=True)
        else:
            # 多张：**格内网格**排版（2026-10-22 老板报「选多张就有问题」）。
            # 原来一律竖排 1 列 + 每张至少 1.1" → 3 张就要 3.65"，而行高被
            # EXACTLY 锁在 2.82"，超出部分被 Word 直接裁掉（图断、图注掉格）。
            # 现在：2 张竖排（原预算不变）；≥3 张改 **2 列**，
            # 每张高度 = 可用高 / 行数，图变大 50% 且总高仍不超格。
            cols = 1 if len(paths) == 2 else 2
            rows_n = int(math.ceil(len(paths) / float(cols)))
            avail = GRID_PHOTO_H_IN - COND_CAPTION_H_IN
            per_h = max(COND_MULTI_MIN_H_IN, avail / rows_n)
            row_need[i // 2] = max(row_need[i // 2],
                                   per_h * rows_n + COND_CAPTION_H_IN)
            ok = True
            for pi, pth in enumerate(paths):
                # 只在「换行后的第一张」新起段落；同一行的第 2 张续在同段落里并排
                new_para = (pi % cols == 0) and pi > 0
                if not _add_photo(cell, pth, [] if pi < len(paths) - 1 else cap,
                                  tpl['not_provided'],
                                  box_h=per_h, frame=True, new_para=new_para):
                    ok = False
        if not ok:
            n_cond_missing += 1
    for ri, row in enumerate(t4b.rows):
        # 2×2 行行齐平；但内容真的放不下时**抬升行高**，绝不靠裁剪硬塞
        row.height = Inches(max(PHOTO_ROW_H_IN, row_need[ri]))
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        _no_row_split(row)
    doc.add_paragraph()

    # ── ⑤ Packing list ────────────────────────────────────────
    _page_break(doc)
    # 2026-10-22 老板：标题只留「Packing list data」，去掉右边的「N lines」
    # （行数在清单区块已经表达过，标题带数字反而抢视线）。
    _section_title(doc, 'Packing list data')
    headers5 = ['Part Number', 'DESCRIPTION', 'Package Number',
                'Order Qty', 'Loading Qty', 'Quantity Check result']
    t5 = doc.add_table(rows=1, cols=6)
    _set_table_borders(t5)
    _set_cell_margins(t5, top=20, bottom=20, left=70, right=70)
    for i, h in enumerate(headers5):
        _cell_text(t5.rows[0].cells[i], h, size=8, bold=True, color=NAVY)
        _shade_cell(t5.rows[0].cells[i], HEAD_FILL)
    qty_unparsed = 0
    tot_o = tot_l = 0.0
    have_o = have_l = False
    for ri, r in enumerate(rows):
        # ⚠️ 按**清单原行**出，不合并同码：同码多行 = 不同的件。
        #    合并视图（products）给不出这个行数，报告数量会与清单对不上。
        cells = t5.add_row().cells
        _cell_text(cells[0], r.get('code') or '', size=7.5)
        _cell_text(cells[1], r.get('name') or '', size=7.5)
        _cell_text(cells[2], r.get('package_no') or '', size=7.5)
        _cell_text(cells[3], r.get('order_qty') or '', size=7.5,
                   align=WD_ALIGN_PARAGRAPH.CENTER)
        _cell_text(cells[4], r.get('loading_qty') or '', size=7.5,
                   align=WD_ALIGN_PARAGRAPH.CENTER)
        _cell_text(cells[5], r.get('check') or '', size=7.5,
                   align=WD_ALIGN_PARAGRAPH.CENTER)
        if ri % 2 == 1:        # 斑马行：1000+ 行的表靠它才好读
            for c in cells:
                _shade_cell(c, ZEBRA_FILL)
        ov, lv = to_num(r.get('order_qty')), to_num(r.get('loading_qty'))
        if ov is not None:
            tot_o += ov
            have_o = True
        elif (r.get('order_qty') or '').strip():
            qty_unparsed += 1
        if lv is not None:
            tot_l += lv
            have_l = True
        elif (r.get('loading_qty') or '').strip():
            qty_unparsed += 1
    cells = t5.add_row().cells
    _cell_text(cells[0], 'TOTAL', size=8, bold=True, color=NAVY)
    _cell_text(cells[1], '', size=8)
    _cell_text(cells[2], '', size=8)
    _cell_text(cells[3], _fmt_int(tot_o) if have_o else '', size=8, bold=True,
               align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY)
    _cell_text(cells[4], _fmt_int(tot_l) if have_l else '', size=8, bold=True,
               align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY)
    _cell_text(cells[5], '', size=8)
    for c in cells:
        _shade_cell(c, TOTAL_FILL)
    doc.add_paragraph()

    # ── ⑥ Quantity check ──────────────────────────────────────
    _page_break(doc)
    _section_title(doc, 'Quantity check', '%d photos' % len(checks))
    _grid_photos(doc, checks,
                 lambda it: it.get('caption') or _caption_check(it),
                 tpl['not_provided'])
    doc.add_paragraph()

    # ── ⑦ Truck picture ───────────────────────────────────────
    if trucks:
        _page_break(doc)
        _section_title(doc, 'Truck picture', '%d photos' % len(trucks))
        _grid_photos(doc, trucks,
                     lambda it: it.get('caption')
                     or [{'text': TRUCK_CAPTIONS.get(it.get('tag'), ''), 'size': 8,
                          'bold': True}],
                     tpl['not_provided'])
        doc.add_paragraph()

    # ── ⑧ 结尾 ────────────────────────────────────────────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(14)
    _set_run_font(p.add_run('End of the report.'), size=10, bold=True,
                  color=NAVY)
    _rule_para(p, color='1F3864', sz=8, where='top')

    _setup_footer(sec, container_no)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out_path, renamed = _save_report(doc, out_path)
    return {
        'path': out_path,
        'renamed': renamed,
        'bytes': os.path.getsize(out_path),
        'rows': len(rows),
        'photos': len(checks) + len(trucks) + sum(
            1 for v in cond.values() if v),
        'missing_condition': n_cond_missing,
        'qty_unparsed': qty_unparsed,
    }


def _caption_check(item):
    """⑥ 图注（结构化三行）：件号 / 描述 / 箱号。

    10-05 老板：「图片下方文字的具体表示什么也不清晰」—— 旧的
    `A-B-C` 连字符串三段看不出谁是谁。现在带标签分行：
        **Part No. 213050000126**
        Hose ROCKMASTER 1SC 1SN10 DKOL90-18-06-D
        *Package: Cage-M3009*
    ⛔ 不用文件名/时间戳当图注 —— 报告员靠图注判断"这张拍的是哪件货"。

    🔴 2026-10-18 老板实测断层修复：品名/箱号**必须限长**。
      真实数据里品名 40~60 字符（"Disconnect ECU power 2 minutes after
      shutdown only"）、一个编码分装多箱时箱号 join 能到 5+ 个 —— 图注
      从 3 行涨到 6+ 行，行高超出 PHOTO_ROW_H_IN 的 0.62" 预算，Word
      把整行挤到下一页：页面出现「一页 2 张、一页 5 张」的断层。
      品名截断到 CAP_NAME_MAX（省略号收尾）；箱号最多列 CAP_CARTON_MAX
      个，其余收成「+N more」—— 报告员要看全量去清单区块⑤。
    """
    lines = []
    if item.get('code'):
        lines.append({'text': 'Part No. %s' % item['code'], 'size': 8,
                      'bold': True})
    if item.get('name'):
        name = str(item['name']).strip()
        if len(name) > CAP_NAME_MAX:
            name = name[:CAP_NAME_MAX - 1].rstrip() + '…'
        lines.append({'text': name, 'size': 7.5})
    cartons = [str(c).strip() for c in (item.get('cartons') or []) if str(c).strip()]
    if not cartons and item.get('carton'):
        cartons = [str(item['carton']).strip()]
    if cartons:
        shown = ' / '.join(cartons[:CAP_CARTON_MAX])
        more = len(cartons) - CAP_CARTON_MAX
        pkg = 'Package: %s%s' % (shown, ('  +%d more' % more) if more > 0 else '')
        lines.append({'text': pkg, 'size': 7, 'color': GRAY_TEXT})
    return lines


_EN_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def _fmt_en_date(v):
    """把日期串转客户报告格式 'Oct.8 2026'（老板样例，2026-10-18）。

    接受 2026-10-08 / 2026/10/8 / 2026.10.8；其它（已是英文、时刻、
    自由文本）原样返回 —— 字段是自由登记，别把用户手写的改坏。
    """
    m = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$',
                 str(v or '').strip())
    if not m:
        return v
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if 1 <= mo <= 12 and 1 <= d <= 31:
        return '%s.%d %d' % (_EN_MONTHS[mo - 1], d, y)
    return v


def _qty_str(v):
    if v is None or v == '':
        return ''
    return '%s %s' % (_fmt_int(v), DEFAULT_TEMPLATE['qty_suffix'])


def load_template(name, base_dir):
    """读 data/report_templates/<name>.json；读不到用内置默认。

    ⚠️ 读不到就**回落到内置 SZAE** 而不是报错：抬头写错一个字不该
    让整份报告出不来（报告是取证材料，卡住它没有好处）。
    """
    if not name:
        return dict(DEFAULT_TEMPLATE)
    p = os.path.join(base_dir, 'report_templates', '%s.json' % name)
    try:
        import json
        with open(p, encoding='utf8') as f:
            t = json.load(f)
        t = dict(t)
        t['labels'] = dict(DEFAULT_TEMPLATE['labels'], **(t.get('labels') or {}))
        return t
    except Exception:  # noqa: BLE001
        return dict(DEFAULT_TEMPLATE)
