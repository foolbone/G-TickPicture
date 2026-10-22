# -*- coding: utf-8 -*-
"""
vision.py -- 多模态大模型 provider（第 2 条的「或多模态大模型」）

═══════════════════════════════════════════════════════════════════════
为什么需要它：OCR 的能力边界是实测出来的，不是猜的
═══════════════════════════════════════════════════════════════════════
PP-OCRv6 桌面预演（doc/PP-OCRv6_真实数据基线报告.md，249 张真实照片）：
  · 86.0% 的照片识别出文字，但**只有 4.2% 命中清单编码**
  · 未命中的绝大多数是车辆铭牌（粤B·MM377）、集装箱号（PCIU9352234）、
    公司名（SINOBOOM）—— OCR 工作正常，就是**与产品无关**
  · 物料标识卡上的编码常是**手写**且涂改，PP-OCRv6 是印刷体模型，认不出

多模态模型能补三件 OCR 做不到的事：
  ① **分类**：先判断这张是什么，只对有价值的照片跑 OCR
     → 省算力，且避免把车牌号当编码去匹配
  ② **手写编码**：标识卡上手写的料号，模型能读；OCR 不能
  ③ **语义描述**：产品外观照没有编码，但模型能描述
     "银色金属折弯件，长方体，两端有孔" → 与清单品名做语义匹配，
     让**无码照片第一次获得关联信号**

═══════════════════════════════════════════════════════════════════════
可插拔 + 降级（这条是硬要求）
═══════════════════════════════════════════════════════════════════════
**没配 API key 时，本模块全部返回 None，管道照常跑完。**
降级后分类退化为启发式（见 pipeline.classify_fallback），
只是无码照片拿不到描述、手写码读不出来 —— 功能变弱，不是不能用。

这与项目一贯的降级哲学一致：PP-OCRv6 模型缺失时静默回退 ML Kit，
全流程照常。

═══════════════════════════════════════════════════════════════════════
配置
═══════════════════════════════════════════════════════════════════════
环境变量（也可在 Web 界面「设置」里填，存到 productlib/data/vision.json）：
  VISION_API_BASE   例如 https://api.deepseek.com/v1
  VISION_API_KEY
  VISION_MODEL      例如 deepseek-vl / gpt-4o / qwen-vl-max

接口走 **OpenAI 兼容的 chat/completions + image_url**，
所以 DeepSeek / 通义 / OpenAI / 本地 vLLM / Ollama(兼容层) 都能接。

⚠️ 未实测声明：本机没有可用的视觉模型 API key，本模块的**调用路径未经
真实 API 验证**。已验证的是：未配置时的降级行为、JSON 解析的容错、
图片编码与缩放。配了 key 之后请先用小批量试跑。
"""
import base64
import json
import os
import re

# 🔴 2026-10-06：这里原是「从 __file__ 上溯三级 + 'productlib/data/vision.json'」
#    的硬编码拼接。打包成 exe 后该路径不存在 → **读不到 api_key** →
#    vision.enabled() 恒为 False → 视觉识别整条链路静默降级，
#    表现就是「图片编码读不出来」（用户完全看不出是配置丢了）。
#    现在走 paths.data_dir()，与数据库/标准图同源。
from tools.productlib import paths  # noqa: E402

def config_path():
    """配置文件路径（**每次现算**）。

    ⚠️ 不能做成模块级常量：那是 import 期定死的，PL_HOME / --data 改数据目录
    之后它仍指向旧位置 → 读不到 Key（视觉整条链路静默降级，表现为
    「编码读不出来」）或写进错误的目录。
    """
    return os.path.join(paths.data_dir(), 'vision.json')

# 送进模型的图片长边上限。
# 依据：视觉模型通常把图缩到 512~1024 处理，传原图（3072×4096）不会更准，
# 只会更慢更贵。1024 足够看清标识卡上的字。
VISION_LONG_EDGE = 1024


def load_config():
    cfg = {
        'api_base': os.environ.get('VISION_API_BASE', ''),
        'api_key': os.environ.get('VISION_API_KEY', ''),
        'model': os.environ.get('VISION_MODEL', ''),
    }
    cp = config_path()
    if os.path.exists(cp):
        try:
            with open(cp, 'r', encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(api_base, api_key, model):
    cp = config_path()
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    with open(cp, 'w', encoding='utf-8') as f:
        json.dump({'api_base': api_base, 'api_key': api_key, 'model': model},
                  f, ensure_ascii=False, indent=2)
    return True


def enabled():
    c = load_config()
    return bool(c.get('api_key') and c.get('model'))


class VisionUnavailable(Exception):
    pass


# 大模型 API 的共享连接池（_call 首次用到时创建；None = 还没建）
_HTTP_CLIENT = None


# ═══════════════════════════════════════════════════════════════════
# 底层调用
# ═══════════════════════════════════════════════════════════════════

def _encode_image(path):
    """读图 → 缩到长边 VISION_LONG_EDGE → JPEG base64。

    缩图用 Pillow；原图可能几十 MB，直接 base64 会撑爆请求体。
    """
    from PIL import Image
    with Image.open(path) as im:
        return _encode_pil(im)


def _encode_pil(im):
    """PIL 图 → 缩到长边 VISION_LONG_EDGE → JPEG base64。

    2026-10-17 新增：支持直接传 PIL 图（OCR 检测裁出的标签区域），
    不必落临时文件再读。
    """
    from PIL import Image
    import io
    im = im.convert('RGB')
    w, h = im.size
    if max(w, h) > VISION_LONG_EDGE:
        r = VISION_LONG_EDGE / float(max(w, h))
        im = im.resize((max(1, int(w * r)), max(1, int(h * r))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format='JPEG', quality=82)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def _call(prompt, image_path=None, max_tokens=400, timeout=60, image=None):
    """[image] 传 PIL 图时优先生用它（标签区域裁剪图），否则读 image_path。"""
    cfg = load_config()
    if not cfg.get('api_key') or not cfg.get('model'):
        raise VisionUnavailable('未配置多模态模型')
    try:
        import httpx
    except ImportError:
        raise VisionUnavailable('缺少 httpx')

    if image is not None:
        b64 = _encode_pil(image)
    else:
        b64 = _encode_image(image_path)
    base = (cfg.get('api_base') or 'https://api.openai.com/v1').rstrip('/')
    url = base + '/chat/completions'
    payload = {
        'model': cfg['model'],
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image_url',
                 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
                {'type': 'text', 'text': prompt},
            ],
        }],
        'max_tokens': max_tokens,
        'temperature': 0,
        # Qwen3 系列（SiliconFlow）：思考模式默认开，实测同一张图 32s → 2.5s。
        # 输出只是一段 JSON，思考纯属烧时间。OpenAI 等不认这个参数的 provider
        # 会 400 → 下面按报错去掉重试，保持 provider 可插拔。
        'enable_thinking': False,
    }
    headers = {'Authorization': 'Bearer ' + cfg['api_key'],
               'Content-Type': 'application/json'}
    # 🔴 复用连接（2026-10-17）：曾经每次 httpx.post 都新建连接 + TLS 握手，
    #    py-spy 实测治理期间 create_ssl_context/do_handshake 占了可观样本，
    #    还拖慢每张图的响应。模块级单例 Client，线程安全（官方支持多线程共享）。
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.Client(timeout=timeout)
    r = _HTTP_CLIENT.post(url, json=payload, headers=headers, timeout=timeout)
    if r.status_code == 400 and 'enable_thinking' in r.text:
        payload.pop('enable_thinking')
        r = _HTTP_CLIENT.post(url, json=payload, headers=headers, timeout=timeout)
    if r.status_code >= 400:
        raise VisionUnavailable('HTTP %d: %s' % (r.status_code, r.text[:200]))
    data = r.json()
    try:
        return data['choices'][0]['message']['content']
    except (KeyError, IndexError):
        raise VisionUnavailable('响应格式异常: %s' % str(data)[:200])


def _parse_json(text):
    """从模型输出里抠出 JSON。

    模型经常在 JSON 外面包 ```json 或加解释文字。
    这里做三次尝试：直接解析 → 去代码块 → 截取首个 { 到末个 }。
    全部失败返回 None（调用方降级，不抛异常打断管道）。
    """
    if not text:
        return None
    s = text.strip()
    for cand in (s,
                 s.replace('```json', '').replace('```', '').strip(),
                 s[s.find('{'):s.rfind('}') + 1] if '{' in s and '}' in s else ''):
        if not cand:
            continue
        try:
            return json.loads(cand)
        except Exception:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════
# 能力一：分类（治理管道第一步）
# ═══════════════════════════════════════════════════════════════════

CLASSIFY_PROMPT = """判断这张仓库/货物照片属于哪一类，并判断拍摄用途和监装细分，只输出 JSON，不要解释。

分类体系（三级）：

用途（最粗粒度）：
- 监装：产品装载到集装箱/货车的全过程照片 —— 货车、集装箱、柜内货物、封条、锁门
- 预检：以货物产品、包装、清单为主的照片 —— 仓库里拍的产品/标签/包装
- 其他：不属于以上两类

预检细分（usage=预检时，kind 只能是以下之一）：
- label：产品（有编码）—— 标识卡清晰、或手写编码可读，画面中有可识别的产品料号
- product：产品（无编码）—— 有产品本体特写，但标识卡小/模糊/没有
- packaging：包装 —— 被纸箱/缠绕膜/木箱覆盖，看不到具体产品，或同时有多款产品混放
- packing_list：清单 —— 白色纸质货品清单/装箱单（整页表格）
- unknown：其他预检照片 —— 属于预检但不属于以上四类

监装细分（usage=监装时，kind 固定为 scene，由 sup_tag 细分）：
- sup_tag=empty_container：空柜 —— 集装箱内部空着，能看到内壁/地板
- sup_tag=container_side：柜侧 —— 集装箱外部两侧壁面
- sup_tag=container_seal：封条 —— 集装箱铅封/封条及安装在门上的照片
- sup_tag=container_lock：锁门 —— 集装箱门关闭上锁的照片
- sup_tag=truck_head：卡车头/车牌号 —— 货车头部带车牌
- sup_tag=loading_process：装柜过程 —— 集装箱内正在装载货物
- sup_tag=other：其他监装照片

输出格式：
{"kind":"label/product/packaging/packing_list/scene/unknown","confidence":0到1的小数,"reason":"一句话说明","usage":"监装/预检/其他","sup_tag":"监装细分之一或null","sup_tag_confidence":0到1的小数,"sup_tag_reason":"一句话说明依据"}

注意：
- 画面主体是集装箱/卡车/人/车牌 → usage=监装，kind=scene
- 画面主体是产品/标签/包装/清单 → usage=预检，kind 按上面细分

【预检细分易混对照（这几组最容易判错，逐条照此判）】
- label vs product：关键看**有没有可读的编码**。
  · 有清晰标识卡/手写码，且码能看清 = label
  · 标识卡贴在产品侧面但只占画面很小、字模糊看不清 = product（不是 label）
  · 画面里能看到产品本体轮廓，旁边有小卡片但卡上字看不清 = product
- product vs packaging：
  · 能看到产品本体轮廓/形状/材质/颜色 = product
  · 只看到纸箱/缠绕膜/木箱整体，看不到里面具体产品 = packaging
  · 多款不同产品混放在托盘上 = packaging
- label vs packing_list：
  · 单张小卡片/标识卡，写一个料号 = label
  · 整页 A4 纸，表格多行多列 = packing_list
- packing_list 识别线索：画面里出现 "PACKING LIST"、"装箱单"、"清单"、"INVOICE" 字样，或整页表格 = packing_list

【OCR 文本辅助判断】
下方「图中已识别文字」是本地 OCR 提取的文字片段（可能有错字/漏字/顺序乱），用作辅助判断线索：
- 如果文字里出现 "PACKING LIST" / "装箱单" / "清单" / "INVOICE" → 倾向 packing_list
- 如果文字里出现符合「数字开头 10~15 位、末尾可能带 1~3 个字母」形态的串（如 101039030015C、2030BG0000098）→ 倾向 label
- 如果文字里只有模糊的产品名/规格、没有料号串 → 倾向 product
- 如果没有识别到任何文字 → 不要强行猜 label，按画面本体判

【监装细分易混对照】
- 空柜 vs 装柜过程：看柜内**有没有货**。空的就是 empty_container，有货/在装就是 loading_process
- 空柜 vs 柜侧：看镜头**朝里还是朝外**。拍到内壁/地板是 empty_container，拍到外壁字样是 container_side
- 封条 vs 锁门：封条是**纸质/塑料封条带 + 一串号码**，锁门是**金属锁杆/凸轮锁扣**。有号码字样的是 container_seal
- 卡车头 vs 柜侧：拍的是**车**（车头、车牌、驾驶室）就是 truck_head；拍的是**集装箱箱体**才是 container_side

【兜底规则】
- 判不准就归 unknown（预检）或 other（监装），confidence 给低分（<0.6），别高置信猜错
- sup_tag 只在 usage=监装 时给，其他情况必须为 null"""


def classify(image_path, ocr_text=None):
    """返回 (kind, conf, reason, usage, sup_tag, sup_tag_conf, sup_tag_reason) 或 None。

    ocr_text: 本地 PaddleOCR 提取的文字片段（多行字符串），拼进 prompt 辅助分类。
              OCR 可能有错字/漏字，仅作线索，不让模型盲信。
    """
    from . import schema
    prompt = CLASSIFY_PROMPT
    if ocr_text:
        # 截断过长 OCR 文本，避免挤占图片 token
        snippet = ocr_text.strip()[:1500]
        prompt += "\n\n【图中已识别文字（OCR 结果，仅供参考）】\n" + snippet
    try:
        raw = _call(prompt, image_path, max_tokens=400)
    except VisionUnavailable:
        return None
    except Exception:
        return None
    d = _parse_json(raw)
    if not isinstance(d, dict):
        return None
    kind = str(d.get('kind') or '').strip().lower()
    if kind not in schema.PHOTO_KINDS:
        kind = 'unknown'
    try:
        conf = float(d.get('confidence') or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    usage_raw = str(d.get('usage') or '').strip()
    usage = usage_raw if usage_raw in ('监装', '预检', '其他') else None

    sup_raw = str(d.get('sup_tag') or '').strip()
    sup_reason = str(d.get('sup_tag_reason') or '')[:200]
    sup_tag = sup_raw if usage == '监装' and sup_raw in schema.SUPERVISION_TAGS else None
    try:
        sup_conf = float(d.get('sup_tag_confidence') or 0.0)
    except (TypeError, ValueError):
        sup_conf = 0.0
    sup_conf = max(0.0, min(1.0, sup_conf))
    if not sup_tag:
        # 用途不对/值编造/没给 → 三件套一起清空，别留半截数据
        sup_tag, sup_conf, sup_reason = None, 0.0, ''
    return (kind, max(0.0, min(1.0, conf)), str(d.get('reason') or '')[:200],
            usage, sup_tag, sup_conf, sup_reason)


# ═══════════════════════════════════════════════════════════════════
# 能力二：描述 + 读码（对无码/手写照片）
# ═══════════════════════════════════════════════════════════════════

DESCRIBE_PROMPT_CODES = """看这张仓库货品照片，只输出 JSON，不要解释。

这张照片属于「装箱单 / 物料标识卡 / 标签」类，画面里**应该**有产品编码。

任务：
1. 如果画面里有**产品编码 / 料号 / 物料编号**（可能是打印体，也可能是**手写在标识卡上**），
   把它们原样读出来放进 codes 数组。**只抄写你确实在图里看到的字符，绝不猜测、绝不补全**。
   🔴 逐字符核对（2026-10-18 老板实测：模型把 203160000002 读成 20316000002，
   少一个 0）：编码通常 10~18 位，含数字与字母；读数时逐位核对长度与字符，
   不确定的字符不要编；位数数不准时宁可不给这个码，也不要给错码。
2. 用中文描述画面里的产品本体：是什么东西、材质、颜色、大致形状。
3. 从标签/标识卡上尽可能提取结构化产品信息，放进 meta 对象：
   - name：产品名称（如"不锈钢弯头""碳钢法兰"）
   - spec：规格/型号/尺寸（如"DN50 PN16""φ108×4"）
   - brand：品牌/厂家
   - material：材质（如"304不锈钢""Q235"）
   - unit：单位（如"个""件""套""米"）
   - category：类别/大类（如"管件""阀门""紧固件"）
   只填你确实在图里看到的字段，看不到的字段不要写（留空或省略）。
   不要把编码、数量、批号、生产日期填进这些字段。

输出格式：
{"codes":["编码1","编码2"],"desc":"中文描述","has_product":true或false,"meta":{"name":"...","spec":"..."}}

注意：
- 编码通常是 10~15 位，数字开头，可能带末尾 1~3 个字母，如 103006010017BM、1000000119
- **不要把**集装箱号（如 PCIU9352234）、车牌号、电话号码、数量当成产品编码
- 手写编码也要尝试读，认不全就不写这一条
- 如果这张图根本没有编码（纯外观/纯文字描述），codes 留空数组
- meta 里每个字段都必须来自图中文字，不要根据 desc 推断"""

DESCRIBE_PROMPT_DESC = """看这张仓库货品照片，只输出 JSON，不要解释。

这张照片属于「产品本体 / 外包装」类，**画面里通常没有物料编码标签**，
所以这一张不要求你读编码（读了也大概率是你猜的，不要写）。

任务：用中文描述画面里的产品本体：是什么东西、材质、颜色、大致形状、有无明显标识。
如果画面里没有具体产品（只有车辆、集装箱、空场地、人物），desc 写 "无产品"。

输出格式：
{"desc":"中文描述","has_product":true或false}"""


# 编码形态过滤（2026-10-18 放宽，与 store._LOOKS_CODE_RE 同步）：
# 真实库 399/400 是「数字+字母」混合形态（101039030015C / 2030BG0000098），
# 旧正则只认纯数字+≤3 字母后缀，把主流形态全滤掉。新规则：数字开头、
# 8~18 位、数字字母任意混合。
_CODE_RE = re.compile(r'^[1-9][0-9A-Z]{7,17}$')
_PREFIX_RE = re.compile(r'^(编码|物料|料号|编号|物品编码|ITEM|NO\.?|PART|PARTS|PN|P/N|P\.N\.?|CODE|SN)'
                        r'[:：-]?\s*', re.IGNORECASE)


def _clean_codes(raw_list):
    """把模型返回的 codes 收一道口子：去前缀、去空格、按形态过滤。"""
    out = []
    for c in (raw_list or []):
        c = str(c).strip().upper()
        c = _PREFIX_RE.sub('', c)
        c = c.replace(' ', '').replace('　', '').replace('，', '').replace(',', '')
        if not c:
            continue
        if _CODE_RE.match(c):
            out.append(c)
    # 去重保序
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def describe(image_path=None, expect_codes=True, image=None):
    """返回 (codes, desc, has_product, meta) 或 None。

    [expect_codes]=True：读码 + 描述 + 标签结构化提取（用于装箱单/标识卡/未知类）。
    [expect_codes]=False：只出描述，不读码（用于产品/外包装本体照——
        这类照上没有标签，模型会"脑补"编码，所以干脆不请求）。
    meta 是 dict，可能含 name/spec/brand/material/unit/category，只在
    expect_codes=True 且模型返回了 meta 时非空。
    [image]：PIL 图（可选）—— 2026-10-17 起治理管道会把 PaddleOCR 检测出的
        标签区域裁剪放大后传进来，替代整张缩略图：标签在整图里往往只占
        一小块，模型看整图读小字容易漏；裁剪放大后读码/元信息提取更准。
        无区域时照旧传整图路径。
    """
    prompt = DESCRIBE_PROMPT_CODES if expect_codes else DESCRIBE_PROMPT_DESC
    try:
        raw = _call(prompt, image_path, max_tokens=400 if expect_codes else 200,
                    image=image)
    except VisionUnavailable:
        return None
    except Exception:
        return None
    d = _parse_json(raw)
    if not isinstance(d, dict):
        return None
    if expect_codes:
        codes = _clean_codes(d.get('codes'))
    else:
        codes = []
    desc = str(d.get('desc') or '')[:500]
    has = bool(d.get('has_product'))
    meta = {}
    if expect_codes and isinstance(d.get('meta'), dict):
        for k in ('name', 'spec', 'brand', 'material', 'unit', 'category'):
            v = d['meta'].get(k)
            if v and str(v).strip():
                meta[k] = str(v).strip()[:100]
    return codes, desc, has, meta
