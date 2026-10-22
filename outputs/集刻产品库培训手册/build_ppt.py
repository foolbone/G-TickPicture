# -*- coding: utf-8 -*-
"""按 DESIGN.md 规范生成《集刻产品库使用培训手册》PPTX。

⚠️ 为什么不用 slidep：它的演示引擎要联网下载 56MB，本机网络受限，
   目录都没建出来（连试 3 次都是「引擎正在后台下载」）。
   python-pptx 是本地库，完全可控 —— 版式照样严格按 DESIGN.md 三区母版。

所有截图都是**真实界面**（对着 8765 真实库抓的），不是示意图。
"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, 'assets')
OUT = os.path.join(BASE, '集刻产品库培训手册.pptx')

# ── DESIGN.md 色板（≤4 hex）──
BLUE = RGBColor(0x25, 0x63, 0xEB)
INK = RGBColor(0x0F, 0x17, 0x2A)
ORANGE = RGBColor(0xEA, 0x58, 0x0C)
BG = RGBColor(0xF8, 0xFA, 0xFC)
GREY = RGBColor(0x47, 0x55, 0x69)
LGREY = RGBColor(0x94, 0xA3, 0xB8)
BORDER = RGBColor(0xE2, 0xE8, 0xF0)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
NAVY = RGBColor(0x0B, 0x1B, 0x3A)

FONT = '微软雅黑'
TOTAL = 24


def px(v):
    return Inches(v / 96.0)


def set_font(run, size, color, bold=False, font=FONT):
    """中文字体要同时设 latin 与 ea，否则中文会回退成宋体。"""
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    f.name = font
    rPr = run._r.get_or_add_rPr()
    for tag in ('a:latin', 'a:ea', 'a:cs'):
        e = rPr.find(qn(tag))
        if e is None:
            e = rPr.makeelement(qn(tag), {})
            rPr.append(e)
        e.set('typeface', font)


def textbox(slide, x, y, w, h, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(px(x), px(y), px(w), px(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    tf.paragraphs[0].alignment = align
    return tb, tf


def put(tf, lines, first=True):
    """lines: [(text, size, color, bold, space_before, line_spacing)]"""
    for i, item in enumerate(lines):
        text, size, color, bold = item[0], item[1], item[2], item[3]
        sb = item[4] if len(item) > 4 else 0
        ls = item[5] if len(item) > 5 else 1.0
        p = tf.paragraphs[0] if (i == 0 and first) else tf.add_paragraph()
        p.space_before = Pt(sb)
        p.line_spacing = ls
        r = p.add_run()
        r.text = text
        set_font(r, size, color, bold)


def rect(slide, x, y, w, h, fill=None, line=None, lw=1, shape=MSO_SHAPE.RECTANGLE,
         radius=None):
    s = slide.shapes.add_shape(shape, px(x), px(y), px(w), px(h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line
        s.line.width = Pt(lw)
    s.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            s.adjustments[0] = radius
        except Exception:
            pass
    tf = s.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(10 / 96.0)
    tf.margin_top = tf.margin_bottom = Inches(6 / 96.0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return s, tf


def pic_fit(slide, name, bx, by, bw, bh, caption=None, border=True):
    """把真实截图按比例塞进 (bx,by,bw,bh) 并居中；返回实际占位。"""
    path = os.path.join(ASSETS, name)
    iw, ih = Image.open(path).size
    cap_h = 22 if caption else 0
    avail_h = bh - cap_h
    scale = min(bw / iw, avail_h / ih)
    w, h = iw * scale, ih * scale
    x = bx + (bw - w) / 2.0
    y = by + (avail_h - h) / 2.0
    if border:
        rect(slide, x - 3, y - 3, w + 6, h + 6, fill=WHITE, line=BORDER, lw=1)
    slide.shapes.add_picture(path, px(x), px(y), px(w), px(h))
    if caption:
        _, tf = textbox(slide, bx, by + avail_h + 4, bw, 18, align=PP_ALIGN.CENTER)
        put(tf, [(caption, 12, LGREY, False)])
    return x, y, w, h


def master(prs, title, subtitle, page):
    """A 标题块 + C 页脚条（全篇严格一致）。返回 slide。"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, 1280, 720, fill=WHITE)
    rect(s, 40, 34, 6, 56, fill=BLUE)              # 标题左侧蓝条（位置全篇一致）
    _, tf = textbox(s, 60, 30, 900, 62)
    put(tf, [(title, 34, INK, True, 0, 1.0)])
    if subtitle:
        _, tf2 = textbox(s, 60, 82, 1000, 26)
        put(tf2, [(subtitle, 15, GREY, False)])
    rect(s, 40, 660, 1200, 1, fill=BORDER)          # 页脚分隔线
    _, tf3 = textbox(s, 40, 676, 700, 20)
    put(tf3, [('集刻产品库 · 使用培训手册', 12, LGREY, False)])
    _, tf4 = textbox(s, 1060, 676, 180, 20, align=PP_ALIGN.RIGHT)
    put(tf4, [('%02d / %d' % (page, TOTAL), 12, LGREY, False)])
    return s


def bullets(slide, x, y, w, items, size=17, gap=13, dot=BLUE):
    """要点列表：橙色/蓝色小方点 + 文本。items: [(粗体前缀, 正文)] 或 [str]"""
    _, tf = textbox(slide, x, y, w, 40 + len(items) * gap * 2)
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_before = Pt(0 if i == 0 else gap)
        p.line_spacing = 1.35
        r = p.add_run()
        r.text = '▪ '
        set_font(r, size, dot, True)
        if isinstance(it, tuple):
            head, body = it
            if head:
                r1 = p.add_run()
                r1.text = head
                set_font(r1, size, INK, True)
            r2 = p.add_run()
            r2.text = body
            set_font(r2, size, GREY, False)
        else:
            r1 = p.add_run()
            r1.text = it
            set_font(r1, size, GREY, False)
    return tf


def warn(slide, x, y, w, h, text):
    """⚠️ 警告条：橙色左边框 + 浅底。强调色每页只用一次。"""
    rect(slide, x, y, w, h, fill=RGBColor(0xFF, 0xF7, 0xED), line=None)
    rect(slide, x, y, 5, h, fill=ORANGE)
    _, tf = textbox(slide, x + 18, y + 10, w - 34, h - 16, anchor=MSO_ANCHOR.MIDDLE)
    put(tf, [(text, 15, INK, False)], first=True)


def stepbar(slide, x, y, w, steps, active=None, size=14):
    """柜作业五步条：当前步用蓝色实心，其余浅底。"""
    n = len(steps)
    gap = 12
    bw = (w - gap * (n - 1)) / n
    for i, st in enumerate(steps):
        bx = x + i * (bw + gap)
        on = (active is not None and i == active)
        s, tf = rect(slide, bx, y, bw, 40,
                     fill=BLUE if on else BG,
                     line=None if on else BORDER, lw=1,
                     shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.18)
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        put(tf, [(st, size, WHITE if on else GREY, on)])
    return bw


def build():
    prs = Presentation()
    prs.slide_width = Inches(1280 / 96.0)
    prs.slide_height = Inches(720 / 96.0)

    # ══ 01 封面（hero）══
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, 1280, 720, fill=NAVY)
    pic_fit(s, '01_containers.png', 560, 96, 700, 470, border=False)
    rect(s, 0, 0, 620, 720, fill=NAVY)
    _, tf = textbox(s, 72, 150, 480, 60)
    put(tf, [('集刻产品库', 54, WHITE, True)])
    _, tf = textbox(s, 72, 228, 480, 40)
    put(tf, [('使用培训手册', 30, RGBColor(0x93, 0xC5, 0xFD), True)])
    rect(s, 72, 300, 72, 5, fill=ORANGE)
    _, tf = textbox(s, 72, 330, 470, 120)
    put(tf, [('仓库预检监装照片的治理与复用', 19, WHITE, False, 0, 1.5),
             ('从安装、升级，到建柜出报告的完整流程', 19, WHITE, False, 4, 1.5)])
    _, tf = textbox(s, 72, 600, 480, 40)
    put(tf, [('内部培训资料 · 2026-10', 14, RGBColor(0x64, 0x74, 0x8B), False)])

    # ══ 02 目录 ══
    s = master(prs, '目录', '按「第一次真实上手」的时间线编排，跟着做一遍就通', 2)
    items = [
        ('01', '开始之前', '这套工具解决什么问题、一次完整作业长什么样'),
        ('02', '安装', '绿色包解压、启动、首次配置多模态模型'),
        ('03', '认识界面', '六个页面各管什么、顶栏「当前柜」的作用'),
        ('04', '柜作业五步', '建柜 → 导清单 → 照片治理 → 选图 → 出报告'),
        ('05', '三个资产页', '产品库 / 照片库 / 报告档案'),
        ('06', '升级与数据', '备份、换新版本、换端口与换数据位置'),
        ('07', '常见问题', '启动失败、杀毒拦截、照片路径失效等'),
    ]
    for i, (no, t, sub) in enumerate(items):
        col, row = i % 2, i // 2
        x = 60 + col * 600
        y = 150 + row * 128
        rect(s, x, y, 560, 108, fill=BG, line=BORDER, lw=1,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
        _, tfn = textbox(s, x + 24, y + 22, 70, 60)
        put(tfn, [(no, 34, BLUE, True)])
        _, tft = textbox(s, x + 96, y + 24, 440, 30)
        put(tft, [(t, 20, INK, True)])
        _, tfs = textbox(s, x + 96, y + 58, 440, 34)
        put(tfs, [(sub, 14, GREY, False)])

    # ══ 03 培训目标 ══
    s = master(prs, '本次培训你将学会', '看完能独立完成一整柜的作业', 3)
    goals = [
        ('装得上', '把绿色包解压、启动，浏览器正常打开界面'),
        ('装得对', '配好多模态模型，让照片能自动分类与读码'),
        ('干得完', '独立走完：建柜 → 导清单 → 导照片 → 治理 → 出报告'),
        ('保得住', '知道数据在哪、怎么备份、升级时会不会丢'),
        ('排得掉', '遇到启动失败、端口占用、路径失效能自己解决'),
    ]
    for i, (t, d) in enumerate(goals):
        y = 150 + i * 98
        rect(s, 60, y, 1160, 82, fill=BG, line=BORDER, lw=1,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
        rect(s, 60, y, 6, 82, fill=BLUE)
        _, tfa = textbox(s, 90, y + 26, 150, 34)
        put(tfa, [(t, 21, BLUE, True)])
        _, tfb = textbox(s, 250, y + 29, 940, 34)
        put(tfb, [(d, 17, GREY, False)])
    _, tf = textbox(s, 60, 646, 1160, 20)
    put(tf, [('建议：边听边操作，每完成一步就在自己的电脑上跟做一遍。',
              14, LGREY, False)])

    # ══ 04 这套工具解决什么问题（hero）══
    s = master(prs, '这套工具解决什么问题',
               '现场拍回来的大批照片，人工归类是做不完的', 4)
    pic_fit(s, '06_govern.png', 40, 150, 700, 420,
            caption='真实界面：照片治理面板 —— 自动分类、读码、关联，一次跑完上千张')
    rect(s, 780, 150, 460, 130, fill=NAVY,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    _, tf = textbox(s, 806, 172, 410, 90)
    put(tf, [('2738', 54, WHITE, True), ('张照片', 20, RGBColor(0x93, 0xC5, 0xFD), False)])
    _, tf = textbox(s, 780, 302, 460, 40)
    put(tf, [('本机真实库存量（照片 / 关联 / 柜况图）', 14, LGREY, False)])
    bullets(s, 780, 356, 460, [
        ('人工归类不可行：', '几千张图要一张张对到货品编码上'),
        ('工具做的事：', '分类 → 读出编码 → 关联到清单 → 出报告'),
        ('额外收益：', '同一个编码跨柜复用历史照片，不用重拍'),
    ], size=16, gap=15)

    # ══ 05 一次完整作业长什么样 ══
    s = master(prs, '一次完整作业长什么样', '所有动作都围绕「一个柜号」展开', 5)
    stepbar(s, 60, 170, 1160, ['① 建柜', '② 导清单', '③ 导照片', '④ 选图', '⑤ 出报告'],
            active=0, size=17)
    pic_fit(s, '08_wiz_step5.png', 60, 250, 660, 340,
            caption='真实界面：柜作业第⑤步 —— 一键按柜生成装柜报告')
    bullets(s, 760, 258, 460, [
        ('为什么以柜为主线：', '报告是「按柜」出的，照片和清单也都挂在柜号下'),
        ('顶栏那个下拉：', '切换它，全站都以这个柜为准'),
        ('五步可以跳着走：', '状态实时显示，可随时回上一步补东西'),
        ('做完第⑤步：', '报告存进 data\\reports，同时出现在「报告档案」'),
    ], size=16, gap=16)

    # ══ 06 下载与解压 ══
    s = master(prs, '安装 ①：下载与解压', '绿色免安装版 —— 不用装、不写注册表', 6)
    pic_fit(s, 'install_tree.png', 40, 148, 700, 420,
            caption='解压后的真实目录结构')
    bullets(s, 780, 156, 460, [
        ('拿到包：', '集刻产品库_绿色包.zip，约 240 MB'),
        ('解压到固定目录：', '建议 D:\\集刻产品库，别放桌面、别放太深的中文路径'),
        ('要完整解压：', '_internal 里是程序本体，缺了就打不开'),
        ('别单独拷 exe：', '程序依赖 _internal，单独拷会启动失败'),
    ], size=16, gap=16)
    warn(s, 780, 540, 460, 78,
         'data\\ 文件夹是你的数据。解压时如果目标目录已有 data\\，'
         '选择「合并」而不是「替换」。')

    # ══ 07 启动（hero）══
    s = master(prs, '安装 ②：双击启动', '黑色窗口别关 —— 关掉它就等于关闭产品库', 7)
    pic_fit(s, '01_containers.png', 40, 148, 720, 440,
            caption='启动后浏览器自动打开的界面')
    rect(s, 800, 148, 440, 118, fill=BLUE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    _, tf = textbox(s, 826, 166, 390, 84)
    put(tf, [('127.0.0.1:8765', 30, WHITE, True),
             ('浏览器会自动打开这个地址', 15, RGBColor(0xDB, 0xEA, 0xFE), False, 6)])
    bullets(s, 800, 292, 440, [
        ('双击对象：', '集刻产品库.exe 或 启动产品库.cmd，二选一'),
        ('看到黑窗口：', '说明程序在跑，别关'),
        ('端口被占用：', '会自动往后找，窗口里显示实际地址'),
        ('关闭产品库：', '关掉黑窗口；或直接关掉浏览器不够'),
    ], size=16, gap=16)

    # ══ 08 首次配置 ══
    s = master(prs, '安装 ③：首次打开先配一件事',
               '配置多模态模型 —— 决定照片要不要人工分类', 8)
    pic_fit(s, '14_settings.png', 40, 148, 700, 430,
            caption='真实界面：设置页 —— 多模态大模型配置区')
    bullets(s, 780, 156, 460, [
        ('在哪配：', '设置 → 多模态大模型，填 API Base / API Key / 模型名'),
        ('不配也能用：', '仍可手工关联、仍可出报告'),
        ('不配的后果：', '照片不会自动分类，也不会自动读出编码'),
        ('安全提醒：', 'API Key 只存在本机 data\\ 下，别把 data 发给外人'),
    ], size=16, gap=16)
    warn(s, 780, 560, 460, 60, 'Key 泄露 = 别人可以用你的额度。填完点「测试」确认通。')

    # ══ 09 六个页面 ══
    s = master(prs, '认识界面：六个页面各管什么', '一句话说清职责，避免「我该点哪个」', 9)
    pic_fit(s, '01_containers.png', 40, 150, 620, 400,
            caption='顶栏导航 + 当前柜下拉')
    pages = [
        ('柜', '所有柜在这里；点每行的「柜作业 →」进入该柜的五步'),
        ('产品库', '跨柜复用的货品资产：编码、品名、规格、标准图'),
        ('照片库', '按柜/批次浏览照片，逐条维护用途与关联'),
        ('报告档案', '生成过的装柜报告都在这，可下载'),
        ('设置', '多模态模型、标准图落盘目录等全局配置'),
        ('概览', '全库统计：多少柜、多少产品、多少照片'),
    ]
    for i, (t, d) in enumerate(pages):
        y = 152 + i * 78
        rect(s, 700, y, 540, 66, fill=BG, line=BORDER, lw=1,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.12)
        rect(s, 700, y, 5, 66, fill=BLUE)
        _, tfa = textbox(s, 722, y + 10, 120, 30)
        put(tfa, [(t, 18, BLUE, True)])
        _, tfb = textbox(s, 722, y + 38, 500, 24)
        put(tfb, [(d, 13, GREY, False)])

    # ══ 10 顶栏当前柜 ══
    s = master(prs, '认识界面：顶栏的「当前柜」', '它是全站的主线锚点', 10)
    pic_fit(s, '03_wiz_step1.png', 40, 148, 700, 420,
            caption='真实界面：柜作业第①步 —— 柜号贯穿全流程')
    bullets(s, 780, 160, 460, [
        ('它是什么：', '当前正在作业的那个柜'),
        ('切它会连带切：', '照片、清单、选图、报告，全部换成这个柜的'),
        ('为什么强调：', '报告是按柜出的 —— 柜号错了，报告就整份错'),
        ('找不到柜时：', '用这个下拉切；柜是「先建后用」，没建就没有'),
    ], size=16, gap=18)

    # ══ 11 ①建柜 ══
    s = master(prs, '柜作业 ①：建柜', '柜号是整条主线，必须先有柜', 11)
    stepbar(s, 60, 142, 1160, ['① 建柜', '② 导清单', '③ 导照片', '④ 选图', '⑤ 出报告'],
            active=0, size=15)
    pic_fit(s, '02_new_container.png', 40, 208, 680, 400,
            caption='真实界面：新建柜 —— 柜号必填，其余可后补')
    bullets(s, 760, 214, 480, [
        ('入口：', '柜页右上「＋ 新建柜」'),
        ('必填：', '柜号（ISO 6346，如 EMCU9914616）'),
        ('可后补：', '封条号、客户、Inspector、Location、到离柜时间'),
        ('这些字段进报告：', 'General Information 区块，缺项标橙提醒'),
        ('建完会怎样：', '顶部出现提示条，点「进入柜作业 →」直接开工'),
    ], size=15, gap=13)
    warn(s, 760, 560, 480, 60, '柜必须先由人建。导入照片不会自动建柜（会缺封条号等必填项）。')

    # ══ 12 ②导入清单 ══
    s = master(prs, '柜作业 ②：导入清单', '把货品清单（Excel）导进本柜', 12)
    stepbar(s, 60, 142, 1160, ['① 建柜', '② 导清单', '③ 导照片', '④ 选图', '⑤ 出报告'],
            active=1, size=15)
    pic_fit(s, '04_wiz_step2.png', 40, 208, 700, 400,
            caption='真实界面：柜作业第②步 —— 导入清单（本柜 1003 行）')
    bullets(s, 780, 214, 460, [
        ('导入内容：', '编码、品名、规格、数量、箱号'),
        ('清单列编码：', '就是产品库的主键 —— 照片靠它关联'),
        ('在这里可改：', '品名/规格写进产品库；核对结论只写本柜快照'),
        ('核对：', '逐行核对 Loading 数量，报告的 Quantity check 用它'),
    ], size=15, gap=14)

    # ══ 13 ③照片（hero）══
    s = master(prs, '柜作业 ③：照片', '导入 → 跑治理 → 浏览照片，三件事在这一步做完', 13)
    stepbar(s, 60, 142, 1160, ['① 建柜', '② 导清单', '③ 导照片', '④ 选图', '⑤ 出报告'],
            active=2, size=15)
    pic_fit(s, '05_wiz_step3.png', 40, 206, 760, 410,
            caption='真实界面：柜作业第③步 —— 照片网格与治理入口')
    bullets(s, 840, 212, 400, [
        ('导入：', '标准采集格式可自动认柜号与箱号'),
        ('治理：', '分类 → 读码 → 关联，一键跑完'),
        ('浏览：', '点开任一张看明细'),
        ('本柜实况：', '1060 张，治理已完成 1059/1060'),
    ], size=15, gap=15)
    warn(s, 840, 540, 400, 76,
         '治理很吃 API 额度。建议分批跑，确认效果后再全量。')

    # ══ 14 治理面板细讲 ══
    s = master(prs, '柜作业 ③细讲：照片治理', '三段流水线 —— 分类、读码、关联', 14)
    pic_fit(s, '06_govern.png', 40, 148, 700, 430,
            caption='真实界面：治理面板 —— 网格 + 治理/重置/仅看未关联')
    steps = [
        ('① 分类', '判断这张是标签卡 / 产品 / 外包装 / 装箱单 / 场景'),
        ('② 读码', 'OCR + 大模型双重读出产品编码，降低漏读'),
        ('③ 关联', '精确匹配自动挂；模糊的进「待确认」等人工点'),
    ]
    for i, (t, d) in enumerate(steps):
        y = 156 + i * 108
        rect(s, 780, y, 460, 92, fill=BG, line=BORDER, lw=1,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
        _, tfa = textbox(s, 802, y + 12, 420, 28)
        put(tfa, [(t, 19, BLUE, True)])
        _, tfb = textbox(s, 802, y + 44, 420, 40)
        put(tfb, [(d, 14, GREY, False, 0, 1.3)])
    warn(s, 780, 490, 460, 88,
         '装箱单/场景照不会自动关联产品 —— 把整页清单关联到某个产品是错的。')

    # ══ 15 ④选图 ══
    s = master(prs, '柜作业 ④：选图', '为报告挑每件货的代表图', 15)
    stepbar(s, 60, 142, 1160, ['① 建柜', '② 导清单', '③ 导照片', '④ 选图', '⑤ 出报告'],
            active=3, size=15)
    pic_fit(s, '07_wiz_step4.png', 40, 208, 700, 400,
            caption='真实界面：柜作业第④步 —— 逐编码挑用图')
    bullets(s, 780, 214, 460, [
        ('这一步干什么：', '给报告的 Quantity check 区块挑用图'),
        ('不选会怎样：', '也能出报告，系统按编码自动取一张'),
        ('为什么建议选：', '自动取的那张未必是标签特写，报告说服力弱'),
        ('已选状态：', '按柜保存，刷新/切步骤都不丢'),
    ], size=15, gap=15)

    # ══ 16 ⑤出报告（hero）══
    s = master(prs, '柜作业 ⑤：生成报告', '一键按柜出可交付的装柜报告', 16)
    stepbar(s, 60, 142, 1160, ['① 建柜', '② 导清单', '③ 导照片', '④ 选图', '⑤ 出报告'],
            active=4, size=15)
    pic_fit(s, '08_wiz_step5.png', 40, 206, 720, 400,
            caption='真实界面：第⑤步 —— 已生成 4 份报告，可下载')
    rect(s, 800, 206, 440, 132, fill=BLUE,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    _, tf = textbox(s, 826, 224, 390, 100)
    put(tf, [('4 份', 40, WHITE, True),
             ('本柜已生成的报告', 16, RGBColor(0xDB, 0xEA, 0xFE), False, 4)])
    bullets(s, 800, 366, 440, [
        ('报告含：', 'Packing list + Quantity check + 柜况/卡车照片'),
        ('柜况照片来自：', '监装照片的「监装细分」标签'),
        ('存哪：', 'data\\reports\\，同时进「报告档案」页'),
        ('同名会怎样：', '自动加 _2 后缀，绝不覆盖旧报告'),
    ], size=15, gap=15)

    # ══ 17 产品库 ══
    s = master(prs, '产品库：跨柜复用的资产', '同一个编码，不用重复拍照', 17)
    pic_fit(s, '09_products.png', 40, 148, 720, 420,
            caption='真实界面：产品库 —— 786 件产品，可按柜号/状态筛选')
    bullets(s, 800, 156, 440, [
        ('它是什么：', '货品主数据：编码、品名、规格、材质、品牌'),
        ('跨柜复用：', 'A 柜拍过的照片，B 柜同编码直接用'),
        ('柜号筛选：', '「全部柜号」含所有柜，空柜也在（可查「为什么一件都没有」）'),
        ('状态筛选：', '有照片 / 无照片 / 有待确认 / 无标准图'),
        ('可编辑：', '品名规格改一处，所有引用它的柜都跟着更新'),
    ], size=15, gap=14)

    # ══ 18 照片库 ══
    s = master(prs, '照片库：浏览与逐条维护', '五档选项卡看全所有照片', 18)
    pic_fit(s, '11_photos.png', 40, 148, 620, 380,
            caption='真实界面：照片库 —— 全部/已关联/未关联/待确认/新产品')
    # 抽屉只占整图右侧一小条，用 15b（裁到抽屉区域）才看得清「监装细分」那几行
    pic_fit(s, '15b_supervision_zoom.png', 700, 148, 540, 380,
            caption='真实界面：监装照片详情 —— 监装细分')
    bullets(s, 40, 556, 1200, [
        ('监装细分：', '空柜 / 柜侧 / 封条 / 锁门 / 卡车头 / 装柜过程 / 其他 —— '
                    '报告的柜况区块靠它选代表性照片，只能人工给'),
    ], size=15, gap=10)

    # ══ 19 报告档案 ══
    s = master(prs, '报告档案', '生成过的报告都在这，可随时下载', 19)
    pic_fit(s, '13_reports.png', 40, 148, 760, 420,
            caption='真实界面：报告档案 —— 按柜归集，可下载')
    bullets(s, 840, 160, 400, [
        ('这里放什么：', '每份生成的装柜报告 docx'),
        ('怎么命名：', '含柜号与时间，便于识别'),
        ('下载后能改：', '就是标准 Word 文档，可直接补盖章页'),
        ('找历史版本：', '同名重生成会加 _2 后缀，旧版仍在'),
    ], size=15, gap=16)

    # ══ 20 备份（hero）══
    s = master(prs, '备份：只需要拷一个文件夹', '换电脑、换硬盘，只拷 data\\ 就够', 20)
    pic_fit(s, 'install_tree.png', 40, 150, 660, 380,
            caption='真正需要备份的，只有 data\\ 这一块')
    rect(s, 740, 150, 500, 134, fill=NAVY,
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
    _, tf = textbox(s, 766, 166, 450, 104)
    put(tf, [('data\\', 36, WHITE, True),
             ('柜 · 清单 · 产品 · 关联 · 报告 · 标准图', 15,
              RGBColor(0x93, 0xC5, 0xFD), False, 6)])
    bullets(s, 740, 312, 500, [
        ('怎么备份：', '关掉程序，把整个 data\\ 文件夹拷走'),
        ('怎么恢复：', '放回新位置，启动时用 --data 指过去'),
        ('不含什么：', '原始照片不在包里 —— 照片库是引用原照片目录的'),
    ], size=16, gap=17)
    warn(s, 40, 556, 1160, 62,
         '换机器后照片路径会失效，需要在新机器上重新导入照片批次；'
         '但柜、清单、产品、关联、报告都还在。')

    # ══ 21 升级 ══
    # 🔴 2026-10-10 修正：覆盖安装（解压到同一个目录）与包内说明相反，已改。
    #    2026-10-10 再修正：升级已**集成进启动脚本**——双击「启动产品库.cmd」
    #    会自动备份+升级+核对行数，不用再单独跑升级助手。升级助手.cmd 仅作手动可选。
    s = master(prs, '升级：换新版，不丢数据',
               '解压到另一个目录 → 拷 data\\ → 双击启动即自动升级', 21)
    pic_fit(s, 'install_tree.png', 40, 148, 640, 400,
            caption='程序文件整包换新，data\\ 整块搬过去')
    up = [('1', '关掉正在运行的黑色窗口'),
          ('2', '把新版本解压到**另一个目录**（别覆盖旧的）'),
          ('3', '把旧目录的 data\\ 整个拷进新目录'),
          ('4', '双击「启动产品库.cmd」—— 自动备份+升级库+核对，然后直接打开'),
          ('5', '确认版本号已更新（黑窗口里会打印）')]
    for i, (no, t) in enumerate(up):
        y = 152 + i * 92
        rect(s, 720, y, 520, 78, fill=BG, line=BORDER, lw=1,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.1)
        _, tfa = textbox(s, 742, y + 22, 44, 36)
        put(tfa, [(no, 24, BLUE, True)])
        _, tfb = textbox(s, 792, y + 26, 430, 30)
        put(tfb, [(t.replace('**', ''), 15, GREY, False)])
    warn(s, 40, 556, 640, 78,
         '别直接解压覆盖（旧程序文件会残留，把程序弄乱）；'
         '也别只拷 productlib.db —— 标准图、报告、缩略图都在 data\\ 里。')

    # ══ 22 换端口 / 换数据位置 ══
    s = master(prs, '进阶：换端口与换数据位置', '命令行参数两个就够', 22)
    rect(s, 60, 160, 560, 170, fill=RGBColor(0x0B, 0x1B, 0x3A),
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    _, tf = textbox(s, 90, 186, 500, 40)
    put(tf, [('换端口', 19, RGBColor(0x93, 0xC5, 0xFD), True)])
    _, tf = textbox(s, 90, 232, 500, 40)
    put(tf, [('集刻产品库.exe --port 8800', 19, WHITE, True)])
    _, tf = textbox(s, 90, 276, 500, 40)
    put(tf, [('默认 8765；被占用时启动脚本会自动往后找',
              14, RGBColor(0x94, 0xA3, 0xB8), False)])

    rect(s, 660, 160, 560, 170, fill=RGBColor(0x0B, 0x1B, 0x3A),
         shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
    _, tf = textbox(s, 690, 186, 500, 40)
    put(tf, [('换数据目录', 19, RGBColor(0x93, 0xC5, 0xFD), True)])
    _, tf = textbox(s, 690, 232, 500, 40)
    put(tf, [('集刻产品库.exe --data D:\\某目录', 19, WHITE, True)])
    _, tf = textbox(s, 690, 276, 500, 40)
    put(tf, [('也可用环境变量 PL_HOME / PL_DB', 14, RGBColor(0x94, 0xA3, 0xB8), False)])

    bullets(s, 60, 380, 1160, [
        ('常见用途：', '同时开两个库做对比；或把数据放到机械盘/共享盘'),
        ('注意：', '换数据目录后，旧目录里的 data\\ 要自己搬过去或保留'),
        ('不要做：', '两个程序实例同时指向同一个 data\\ —— 会互相锁库'),
    ], size=16, gap=18)

    # ══ 23 常见问题 ══
    s = master(prs, '常见问题速查', '遇到问题先看这一页', 23)
    faq = [
        ('双击没反应', '看黑色窗口里的报错；多半是端口被占，关掉旧窗口再试'),
        ('杀毒软件拦', '本程序未做数字签名，被拦时加信任即可'),
        ('界面打开但功能 404', '说明打包漏了模块，把报错发给技术支持'),
        ('照片路径失效', '换机器后照片不在包里，需要重新导入照片批次'),
        ('某个柜找不到', '柜必须先建；用顶栏下拉切柜，或先「＋ 新建柜」'),
        ('照片没自动分类', '设置里没配多模态模型，或这张本来就该人工判定'),
        ('报告里图片不对', '检查该照片的「监装细分」标签是否贴对'),
    ]
    for i, (q, a) in enumerate(faq):
        col, row = i % 2, i // 2
        x = 60 + col * 600
        y = 152 + row * 108
        rect(s, x, y, 560, 92, fill=BG, line=BORDER, lw=1,
             shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08)
        rect(s, x, y, 5, 92, fill=ORANGE if col == 0 and row < 2 else BLUE)
        _, tfq = textbox(s, x + 24, y + 14, 520, 28)
        put(tfq, [(q, 17, INK, True)])
        _, tfa = textbox(s, x + 24, y + 46, 520, 40)
        put(tfa, [(a, 13, GREY, False, 0, 1.3)])
    _, tf = textbox(s, 60, 622, 1160, 20)
    put(tf, [('还有别的问题 → 把报错截图发给技术支持，别自己猜着改数据库。',
              13, LGREY, False)])

    # ══ 24 收尾（hero）══
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, 1280, 720, fill=NAVY)
    rect(s, 80, 120, 6, 56, fill=ORANGE)
    _, tf = textbox(s, 104, 116, 1000, 60)
    put(tf, [('记住这一条主线就够了', 40, WHITE, True)])
    stepbar(s, 104, 230, 1070, ['装好', '建柜', '导清单', '导照片', '出报告'],
            active=4, size=19)
    rect(s, 104, 320, 1070, 1, fill=RGBColor(0x1E, 0x3A, 0x5F))
    _, tf = textbox(s, 104, 356, 1000, 120)
    put(tf, [('数据在 data\\ —— 备份拷它，升级搬到新目录，别删它。',
              26, RGBColor(0x93, 0xC5, 0xFD), True, 0, 1.6),
             ('照片治理是省人力的大头，值得把 API Key 配好。',
              26, RGBColor(0x93, 0xC5, 0xFD), True, 6, 1.6)])
    _, tf = textbox(s, 104, 560, 1000, 40)
    put(tf, [('内部培训资料 · 集刻产品库', 15, RGBColor(0x64, 0x74, 0x8B), False)])
    _, tf = textbox(s, 104, 676, 1076, 20, align=PP_ALIGN.RIGHT)
    put(tf, [('%02d / %d' % (TOTAL, TOTAL), 12, RGBColor(0x47, 0x55, 0x69), False)])

    prs.save(OUT)
    return prs


if __name__ == '__main__':
    p = build()
    print('slides =', len(p.slides.__iter__.__self__._sldIdLst))
    print('saved  =', OUT)
    print('size   = %.1f MB' % (os.path.getsize(OUT) / 1048576.0))