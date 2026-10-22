// drawer.js —— 由 index.html 内联脚本拆分而来，逻辑未改
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, onEscape, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS, fmtTaken, fmtGap, diffSec } from './core.js';
import { openStdEditor, stdSuggest } from './standard.js';
import { loadStats } from './home.js';
import { resetViewer } from './photos.js';
// 注意：产品列表工具栏 / 清单导入属于 products.js，不在这里（曾因机械拆分串到这里，
// 导致 loadProducts 未定义 —— 已迁回 products.js）

/* ── 照片详情抽屉（支持 ←/→ 相邻切换）── */
let _drawerList = [];          // 当前网格的照片 id 序列
let _drawerIdx = -1;
const _drawerCache = new Map();  // 已取过的详情，切换时直接复用，少一次往返

/* 大图查看器（只放大看细节，不换详情页）。
   同组连拍照点一下就该看到大图 —— 这是「看清细节」的入口，
   不是「切换到另一张照片」的入口。 */
let _viewerPid = '';
/** takenAt 传了就显示在图注里 —— 大图也是「展示图片的地方」，同样要能看到
 *  拍照时间（10-05）。缺时间不编造，只显示文件名。 */
/** 柜作业④「选图」也用这个查看器 —— 两处共用同一份实现，别各写一套。
 *  ⚠️ 导出在文件**末尾的 export {} 列表**里（第 499 行），此处**不要再写 export** ——
 *     「定义处 export + 末尾列表里再 export 一次」= Duplicate export，
 *     会让整个模块图挂掉、全站白屏，而单文件语法检查查不出来（本项目踩过）。 */
function openViewer(src, cap, takenAt){
  _viewerPid = '';
  const m = String(src||'').match(/\/img\/([^/?]+)/);
  if(m) _viewerPid = m[1];
  const el = $('#maskImg');
  el.src = src;
  // 看大图要的是细节（原图），但原图 4MB 冷加载要好几秒 ——
  // 先用已缓存的预览图顶上，原图到位再换，别让人对着空白等。
  if(_viewerPid){
    el.src = '/img/' + _viewerPid + '?w=1600';
    const big = new Image();
    big.onload = ()=>{
      if(_viewerPid === m[1] && $('#mask').classList.contains('on')) el.src = src;
    };
    big.src = src;
  }
  $('#maskCap').textContent = takenAt
    ? ((cap? cap+' · ':'')+fmtTaken(takenAt, {full:true}))
    : (cap || '');
  resetViewer();
  $('#mask').classList.add('on');
  const btn = $('#maskToDetail');
  // 只有知道 pid 时才给「打开详情」出口
  if(btn) btn.style.display = _viewerPid ? '' : 'none';
}

/* 抽屉大图渐进加载：先缩略图占位，再换预览图。
   ⚠️ 换之前必须核对 data-pid —— 连点「下一张」时会同时有几个请求在飞，
   不核对就会用上一张的图盖住当前这张（看着像"图跳错了"）。 */
function _dwImgProgressive(p){
  const img = $('#dwImg');
  if(!img) return;
  const view = p.view || p.full;
  if(!p.thumb || view === p.thumb) return;
  img.src = p.thumb;
  const pre = new Image();
  pre.onload = ()=>{
    const cur = $('#dwImg');
    if(cur && cur.dataset.pid === String(p.id)) cur.src = view;
  };
  pre.src = view;
}

/* 抽屉重绘时保持滚动位置：关联/解除后 openDrawer 会整体重换 #dwBody，
   .db（overflow:auto）的 scrollTop 随之归零 —— 用户正看着「文件信息」呢，
   一下被弹回图顶（2026-10-14 老板反馈：刷新要保持当前位置）。
   只在「同一抽屉重开」时记录；新开一张照片仍然从顶部开始看。 */
let _dwKeepScroll = -1;
async function openDrawer(pid){
  const db = $('#drawer .db');
  // 抽屉开着 = 重绘刷新（记下位置）；没开 = 新开一张（从头看）。
  // ⚠️ 必须无条件赋值：留着上次的旧值，会在下一次新开时误恢复到那个位置。
  _dwKeepScroll = (db && $('#drawer').classList.contains('on')) ? db.scrollTop : -1;
  let p = _drawerCache.get(pid);
  if(!p){
    try{ p = await api('/api/photos/'+pid); }
    catch(e){ return toast('打开失败：'+e.message,'err'); }
    _drawerCache.set(pid, p);
  }
  _drawerIdx = _drawerList.indexOf(pid);
  // 预取相邻两张：详情 JSON + **图片本身**都要预取，否则切过去还是现下大图。
  // 图片用 Image() 预热浏览器缓存，真正切换时命中缓存 = 秒开。
  [-1, 1].forEach(d=>{
    const nid = _drawerList[_drawerIdx + d];
    if(!nid) return;
    if(!_drawerCache.has(nid)){
      api('/api/photos/'+nid).then(x=>{
        _drawerCache.set(nid, x);
        const im = new Image(); im.src = x.view || x.full;    // 预热
      }).catch(()=>{});
    } else {
      const c = _drawerCache.get(nid);
      const im = new Image(); im.src = c.view || c.full;
    }
  });
  const has = _drawerList.length > 1;
  $('#dwPrev').style.display = (has && _drawerIdx > 0) ? '':'none';
  $('#dwNext').style.display = (has && _drawerIdx >= 0 && _drawerIdx < _drawerList.length-1) ? '':'none';
  $('#dwPos').textContent = has ? ((_drawerIdx+1)+' / '+_drawerList.length) : '';

  // ── 布局（2026-10-13 老板：左右两栏 —— 左边图片，右边信息+操作）──
  // 原来是单列长滚动：大图下面串一长串等权重的信息，找个操作要滚半天。
  // 现在左栏只放图（sticky，右边滚它不动），右栏按**使用频率**排序：
  //   ① 用途 / 监装细分（高频操作置顶）  ② 已关联 / 建议关联  ③ 标准图
  //   ④ 分类与文件信息  ⑤ 低频识别细节（默认折叠，点开才占位）
  let left = '';
  // 🔴 显示用 view（长边受限的预览图），**不是**原图：原图 3.8~21MB，
  //    切换上一张/下一张时每次重下整张，实测冷加载 4.47s —— 卡就是这么来的。
  //    data-full 留着原图，点它才是「看细节」。
  left += '<div class="dw-main">';
  left += '<div class="dw-imgwrap"><img id="dwImg" data-pid="'+esc(p.id)+'" src="'+
          esc(p.view||p.thumb||p.full)+'" data-full="'+esc(p.full)+'">'+
          '<div class="dw-zoomhint" title="点击看大图">点击看大图</div></div>';
  // 来源信息放在大图正下方 —— 柜号批次是「这张照片从哪来」的第一答案
  const b = p.batch || {};
  const containerNo = b.container_no || p.container_no || '';
  left += '<div class="dw-src">';
  // 文件名：第一眼看是哪张图（2026-10-20 老板：突出展示文件名紧挨图片）
  left += '<span class="dw-fname" title="'+esc(p.file||'')+'">'+esc(p.file||'')+'</span>';
  left += '<span class="tag">'+(containerNo? esc(containerNo) : '未标柜号')+'</span>';
  if(b.name) left += '<span class="faint">'+esc(b.name)+'</span>';
  if(p.carton_no) left += '<span class="tag ok">箱号 '+esc(p.carton_no)+'</span>';
  // 拍照时间：到秒 + 与上一张的间隔（同组连拍就靠它判断是不是真连拍）
  // prev 从同组照片里按时间找前一张 —— 后端已返回 group_photos，不用再加字段
  const _gp = (p.group_photos||[]).slice()
    .sort((a,b)=>String(a.taken_at||'').localeCompare(String(b.taken_at||'')));
  const _gi = _gp.findIndex(x=>x.id===p.id);
  const prevT = (_gi>0) ? _gp[_gi-1].taken_at : (p.prev_taken_at||null);
  const gapTxt = fmtGap(diffSec(prevT, p.taken_at));
  // 2026-10-19 老板需求2：时间是最重要的线索，**加粗加大**突出
  // （判断两张图是不是同一件货的两个视角，第一眼就要看到时间）。
  left += '<span class="dw-taken" title="EXIF/文件时间：'+esc(p.taken_at||'无')+'">'+
          fmtTaken(p.taken_at, {full:true})+
          (gapTxt? ' · 距上一张 '+gapTxt : '')+'</span>'+
          '<span class="faint"> · '+p.size_mb+' MB</span>';
  left += '</div>';
  // 同产品编码的其他图片：**大图正下方**（2026-10-19 老板需求1：
  // 「在图片下方，以缩略小图的方式展示」—— 原来在右栏底部，老板找不到）。
  // 懒加载占位，数据与渲染在下方 panoramas 回调里填（#dwSibs）。
  // 标准图标识：同编码有标准图时打「标准图」徽标（复用标准图接口数据）。
  left += '<div id="dwSibsSec" class="dsec" style="display:none;margin-top:6px">'+
    '<h4 style="font-size:13px">同编码其他照片</h4>'+
    '<div id="dwSibs"></div></div>';
  left += '</div>';

  const kind = p.photo_kind||'unknown';
  const codes = (p.vision_codes && p.vision_codes!=='[]') ? (typeof p.vision_codes==='string'?JSON.parse(p.vision_codes):p.vision_codes) : [];
  const conf = (p.kind_conf||0);
  const tok = (p.tokens||[]).filter(t=>(t.raw_text||'').length>=3);
  const links = p.links||[];
  const linkedSet = new Set(links.map(l=>l.code_norm));
  const isDoc = (kind==='packing_list');
  const kindLabel = isDoc ? '0204 清单（参考文档 · 不关联产品）'
                 : (kind==='scene' ? '场景照（监装照 · 细分见「监装细分」）' : kind);
  const isProduct = (kind==='label' || kind==='product');

  let right = '';
  // ⓪' 照片分类（清单/产品/场景…）：它是这张照片「是什么」的
  //   第一属性，用途/关联都跟着它走（2026-10-15 老板需求）。
  const kindOpts = Object.keys(KIND_LABELS).map(k=>
    '<option value="'+esc(k)+'"'+(kind===k?' selected':'')+'>'+esc(KIND_LABELS[k])+'</option>').join('');
  const confTxt = conf ? ('模型判定 '+kindName(kind)+' '+Math.round(conf*100)+'%（可改）')
                       : '人工已确认（或模型未判定）';
  right += '<div class="kv"><span class="k">分类</span>'+
           '<select id="dwKind" style="padding:2px 6px;font-size:13px"'+
           ' title="模型识别不一定准 —— 这里可以改判">'+kindOpts+'</select>'+
           ' <span class="faint" id="dwKindMsg">'+esc(confTxt)+'</span></div>';
  // ① 用途分类：高频操作放最上面（2026-10-13）。
  //   顺序 = 老板分类表编号序（01 监装 → 02 预检 → 03 其他）；文案不带编号。
  const usage = p.photo_usage || '';
  right += '<div class="kv"><span class="k">用途</span>'+
          '<select id="dwUsage" style="padding:2px 6px;font-size:13px">'+
          '<option value="">未分类</option>'+
          '<option value="监装"'+(usage==='监装'?' selected':'')+'>监装照片</option>'+
          '<option value="预检"'+(usage==='预检'?' selected':'')+'>预检照片</option>'+
          '<option value="其他"'+(usage==='其他'?' selected':'')+'>其他照片</option>'+
          '</select> <span class="faint" id="dwUsageMsg"></span></div>';
  // 监装细分（v3）：只服务报告区块④⑦ —— 键序 = 编号序 0101→0107。
  // 仅在用途=监装时可见（预检照没有这些角色）；空 = 未标注。
  const SUPTAGS = {
    empty_container:'空柜', container_side:'柜侧', container_seal:'封条',
    container_lock:'锁门', truck_head:'卡车头/车牌号',
    loading_process:'装柜过程', other:'其他监装照片',
  };
  const suptag = p.supervision_tag || '';
  right += '<div class="kv" id="dwSuptagRow" style="display:'+(usage==='监装'?'':'none')+'">'+
          '<span class="k">监装细分</span>'+
          '<select id="dwSuptag" style="padding:2px 6px;font-size:13px">'+
          '<option value="">未标注</option>'+
          Object.keys(SUPTAGS).map(k=>'<option value="'+k+'"'+(suptag===k?' selected':'')+'>'+
            esc(SUPTAGS[k])+'</option>').join('')+
          '</select> <span class="faint" id="dwSuptagMsg"></span></div>';

  // 大模型建议（2026-10-07）：治理阶段顺带问出来的，**不自动生效**。
  // 三种状态要分得清，别混成一个「已标注」：
  //   ① 人工已确认（confirmed=1）→ 只在标签右边挂一个小「已确认」标记
  //   ② 有建议、还没确认        → 建议值 + 置信度 + 依据 + 「采用建议」按钮
  //   ③ 压根没建议              → 不渲染这一块（不是「没意见」，是没问过）
  // ⚠️ ② 里绝对不能把建议值预填进 select —— 那等于让机器替人拍板，
  //    而这张图可能直接被印进正式报告。
  const sugTag = (p.sup_tag_ai && Object.prototype.hasOwnProperty.call(SUPTAGS, p.sup_tag_ai))
      ? p.sup_tag_ai : null;
  const sugConf = Math.round((p.sup_tag_ai_conf || 0) * 100);
  const sugConfirmed = !!p.sup_tag_confirmed;
  if(usage==='监装'){
    right += '<div class="kv" id="dwSuptagAiRow" style="padding-left:8px">'+
            '<span class="k faint" style="font-size:12px">模型建议</span><span>';
    if(sugConfirmed){
      right += '<span class="chip acc" title="人工已确认细分">已确认</span>';
      if(sugTag) right += '<span class="faint" style="font-size:12px">建议过「'+
        esc(SUPTAGS[sugTag])+'」</span>';
    }else if(sugTag){
      right += '<span class="chip">'+esc(SUPTAGS[sugTag])+'</span>'+
        '<span class="faint" style="font-size:12px">置信 '+sugConf+'%'+
        (sugConf<60?'（偏低，建议核对）':'')+'</span>'+
        (p.sup_tag_ai_reason?'<span class="faint" style="font-size:12px">：'+
          esc(p.sup_tag_ai_reason)+'</span>':'')+
        ' <button class="btn" id="dwSuptagAccept" style="padding:1px 8px;font-size:12px">'+
        '采用建议</button>';
    }else{
      right += '<span class="faint" style="font-size:12px">无（模型未给出，可能没跑过多模态治理）</span>';
    }
    right += '</span></div>';
  }

  // ② 操作区（无效 / 忽略 / 重新识别）—— 2026-10-21 老板：挪到顶部导航行
  //   （#dwTopActions），右栏不再占一块。
  //   重新识别拆成两个（2026-10-19 老板要求）：
  //   「OCR 识别」—— 本地小模型，强制重跑文字提取 + 编码匹配，一分钱不花；
  //   「大模型识别」—— 完整链路含视觉读码/描述，花多模态额度，留给
  //     OCR 提不出的疑难图。
  const topAct = $('#dwTopActions');
  if(topAct){
    topAct.style.display = 'inline-flex';
    topAct.innerHTML =
      (p.is_invalid ? '<span class="tag err">已无效</span>' : '')+
      (p.photo_ignored ? '<span class="tag warn">已忽略</span>' : '')+
      '<button class="btn sm ghost" id="dwRegovOcr"'+
        ' title="按当前分类强制重跑本地 OCR + 编码匹配（清掉旧文字重新提，不花多模态额度）">OCR 识别</button>'+
      '<button class="btn sm ghost" id="dwRegov"'+
        ' title="按当前分类跑完整识别链路：本地 OCR + 大模型视觉读码与描述（花多模态额度，留给疑难图）">大模型识别</button>'+
      '<button class="btn sm '+(p.photo_ignored?'':'ghost')+'" id="dwIgnore"'+
        ' title="本次忽略：新产品暂不入库、退出关联队列；可在「已忽略」档恢复">'+
        (p.photo_ignored?'恢复忽略':'本次忽略')+'</button>'+
      '<button class="btn sm '+(p.is_invalid?'ghost':'')+'" id="dwInvalid">'+
      (p.is_invalid?'取消无效标记':'标记为无效')+'</button>';
  }

  // ⓪ 关联产品（2026-10-20 老板：从置顶移到识别按钮下方 —— 先看「这是什么、
  //   要不要处理」再给关联。手输 + 已关联 + 建议候选合成一块，已关联的照片
  //   也有手输入口（旧版只在未关联时给，想加第二个编码没地方输）。）
  if(isProduct || links.length){
    right += '<div class="dsec dw-topsec">'+
      '<h4>关联产品<span class="sub">输入编码后回车，可输后几位联想</span></h4>'+
      '<div class="row" style="gap:6px">'+
        '<input type="text" id="dwCode" placeholder="产品编码" autocomplete="off" '+
          'style="flex:1;padding:3px 8px">'+
        '<button class="btn sm" id="dwLink">关联</button></div>';
    // 已关联列表（就在这块里，不用再滚到中间去找）
    right += '<div style="margin-top:6px">'+
      (links.length
        ? links.map(l=>'<div class="linkrow"><span class="c">'+esc(l.code_norm)+'</span>'+
            '<span class="muted">'+esc(l.name||'')+'</span>'+
            '<span class="src">'+esc(l.source)+' · '+(l.created_by||'')+'</span>'+
            '<span class="un" data-un="'+esc(l.code_norm)+'">解除</span></div>').join('')
        : '<div class="faint">尚未关联 —— 用上方输入框，或点下面的建议编码。</div>')+
      '</div>';
    // 建议关联：只有「产品图 + 还没关联」才请求（已关联的别再刷候选，
    // 那是在诱导重复关联）。占位先给，异步填。
    if(isProduct && links.length === 0){
      right += '<div id="dwCands" style="margin-top:6px">读取中…</div>';
    }
    right += '</div>';
  } else {
    right += '<div class="dsec"><div class="faint">只有产品图（有编码 / 无编码）才需要关联产品 —— '+
             '上方分类改判为产品图后，这里会出现关联入口。</div></div>';
  }

  // ②' 同组连拍 + 可能的全景图（2026-10-18 老板要求合并成一块）：懒加载占位。
  //    合并前这里只显示「可能的全景图」，而下方「识别细节」里另有一块同组连拍
  //    —— 两块回答同一个问题（这几张是不是同一件货），老板要点两次。
  //    现在一块列表按来源打标签（同组连拍 / 可能的全景图），规则见
  //    routes/photos.py:api_photo_panoramas。懒加载条件也放宽：
  //    同组连拍与有没有关联产品无关。
  right += '<div class="dsec" id="dwPanoSec" style="display:none">'+
    '<h4>同组连拍 · 可能的全景图<span class="sub">同一件货？勾选后可一并关联到产品</span></h4>'+
    '<div class="row" id="dwPanoBar" style="display:none;gap:6px;align-items:center;margin-bottom:8px">'+
      '<label class="faint" style="font-size:12px;cursor:pointer"><input type="checkbox" id="dwPanoAll"> 全选</label>'+
      '<button class="btn sm ghost" id="dwPanoLink" disabled>关联选中到产品</button>'+
      '<input type="text" id="dwPanoCode" placeholder="产品编码" style="width:150px;margin-left:auto;padding:3px 8px">'+
    '</div>'+
    '<div id="dwPano" class="dw-pano"><span class="faint">读取中…</span></div>'+
    '<div id="dwGroupMore" style="margin-top:6px"></div>'+
    '<div id="dwGroupAllGrid" style="display:none;margin-top:8px"></div>'+
    // dwSibs 已移到左栏大图正下方（#dwSibsSec 内），这里不再占位
    '</div>';

  // 「建议关联」的候选已并入顶部「关联产品」块（#dwCands），这里不再重复。

  // ③ 以下都是低频内容 —— 2026-10-20 老板「初始一屏不用滚动」：
  //    标准图 / 文件信息 / 识别细节 全部折进一个 details，首屏只留一行摘要。
  //    ⚠️ 折叠不影响任何 id 绑定（DOM 一直在，只是不渲染），
  //       异步回填（#dwStdList）也照常写。
  right += '<details class="dw-more"><summary>更多（标准图 / 文件信息 / 识别细节）</summary>';

  // 标准图：裁剪后入产品库，导出时优先采用 —— 只有产品图才有意义
  //   （2026-10-17：与「只有产品需要关联」同口径；曾经的 scene/清单排除
  //   被白名单取代 —— 包装/其他预检也不该做标准图）。
  const stdAllowed = isProduct;
  const firstProd = links.length ? links[0].code_norm : '';
  if(stdAllowed){
    right += '<div class="dsec dw-std">';
    right += '<div class="row"><button class="btn" id="dwStd">制作标准图</button>'+
      '<span class="faint">裁剪后入产品库，导出时优先采用</span></div>';
    if(firstProd){
      right += '<div id="dwStdList" style="margin-top:8px"><span class="faint">读取该产品的标准图…</span></div>';
    }else{
      right += '<div class="faint" style="margin-top:4px">这张照片还没关联产品 —— '+
        '先关联，保存的标准图才知道挂给谁。</div>';
    }
    right += '</div>';
  }

  // ④ 分类与文件信息（低频，放操作区后面）
  right += '<div class="kv"><span class="k">文件</span>'+esc(p.file)+'</div>';
  right += '<div class="kv"><span class="k">分类</span><span class="tag '+kindCls(kind)+'" id="dwKindTag">'+esc(kindLabel)+'</span>'+
          (conf? ' <span class="faint">置信 '+conf.toFixed(2)+'</span>':'')+
          (p.vision_model?' <span class="faint">· '+esc(p.vision_model)+'</span>':'')+
          (p.govern_state!=='done'?' <span class="tag '+((p.govern_state==='failed')?'err':'')+'">'+esc(p.govern_state)+'</span>':'')+'</div>';

  // 识别细节（编码 / OCR / 描述 / 标签提取）—— 已在「更多」details 内，
  // 不再自己套一层（嵌套 details 会让人点两次）。
  right += '<div class="dsec"><h4>大模型提取到的编码'+(codes.length?'':'（无）')+'</h4>';
  if(codes.length){
    right += codes.map(c=>{
      const linked = linkedSet.has(c);
      return '<span class="chip '+(linked?'acc':'')+'">'+esc(c)+(linked?' ✓':'')+'</span>';
    }).join('');
  } else if(isDoc){
    right += '<div class="faint">这是物料清单（参考文档），上面的编码见下方「OCR 文本」，作为参考<b>不自动关联</b>产品。</div>';
  } else {
    right += '<div class="faint">这张照片没有读到编码'+
      ((kind==='scene'||kind==='product'||kind==='packaging')?'（正常：'+esc(kind)+' 类通常无标签）':'')+'。</div>';
  }
  right += '</div>';

  right += '<div class="dsec"><h4>OCR 文本（前 8 条，高到低）</h4>';
  if(tok.length){
    right += tok.slice(0,8).map(t=>'<span class="chip">'+esc(t.raw_text)+' <span class="faint">'+Math.round((t.confidence||0)*100)+'%</span></span>').join('');
  } else {
    // 诊断口径（2026-10-15 需求4）：区分「没跑」和「跑了没文字」——
    // 有码类（label/清单）治理过却零 token = 漏提，给一键补跑入口
    const needOcr = (kind === 'label' || kind === 'packing_list' ||
                     kind === 'unknown' || kind === 'product' || kind === 'packaging');
    right += needOcr && p.govern_state === 'done'
      ? '<div class="faint">这张治理过但没有 OCR 文本 —— 早期治理时可能没跑/没跑成。'+
        '点上方「重新识别」补跑本地 OCR（不花多模态额度）。</div>'
      : '<div class="faint">无 OCR 文本（画面上可能确实没有文字）。</div>';
  }
  right += '</div>';

  right += '<div class="dsec"><h4>大模型描述</h4>';
  right += p.vision_desc ? '<div class="muted">'+esc(p.vision_desc)+'</div>'
                        : '<div class="faint">无描述（未治理 / 未配多模态）。</div>';
  right += '</div>';

  // 标签结构化提取：治理时从标识卡上读出的品名/规格/材质等，可一键填充到产品
  let vmeta = {};
  try{ vmeta = (p.vision_meta && p.vision_meta!=='{}') ? (typeof p.vision_meta==='string'?JSON.parse(p.vision_meta):p.vision_meta) : {}; }catch(e){}
  const metaKeys = [['name','品名'],['spec','规格'],['brand','品牌'],['material','材质'],['unit','单位'],['category','类别']];
  const metaEntries = metaKeys.filter(([k])=>vmeta[k]);
  if(metaEntries.length){
    right += '<div class="dsec"><h4>标签提取的产品信息</h4>';
    right += '<div class="kv" style="display:grid;grid-template-columns:80px 1fr;gap:4px 8px;margin-bottom:8px">';
    metaEntries.forEach(([k,label])=>{
      right += '<span class="k" style="padding-top:2px">'+label+'</span><span>'+esc(vmeta[k])+'</span>';
    });
    right += '</div>';
    if(links.length){
      right += '<button class="btn sm" id="dwMetaApply">应用到产品「'+esc(links[0].code_norm)+'」</button>'+
        '<span class="faint" style="margin-left:6px">只填充空字段，已有值不覆盖</span>';
    }else{
      right += '<div class="faint">这张照片还没关联产品 —— 先关联，再把标签信息填过去。</div>';
    }
    right += '</div>';
  }

  // 同组其他照片：group_idx 相同 = 同一次连拍（标签特写+全景图等）
  const gps = p.group_photos || [];
  // 🔴 2026-10-18：这一块的**渲染**已并入上方「同组连拍 · 可能的全景图」
  //    （同一个问题不点两次），这里只保留数据：懒加载条件要用 gps.length，
  //    大图图注的文件名/时间也从它取。
  right += '</details>';   // /details.dw-more

  let html = '<div class="dw-cols"><div class="dw-left">'+left+'</div>'+
             '<div class="dw-right">'+right+'</div></div>';

  $('#dwFile').textContent = p.file;
  $('#dwBody').innerHTML = html;
  $('#drawer').classList.add('on');

  // 大图「先模糊后清晰」：缩略图（~20KB，几乎必定已缓存）先顶上，
  // 预览图到位再换。慢盘/大图上这一下是「立刻有画面」和「白等几秒」的区别。
  _dwImgProgressive(p);

  // 标记/取消无效（2026-10-15 需求1）：详情页就地操作，背后列表同源刷新
  const invBtn = $('#dwInvalid');
  if(invBtn) invBtn.onclick = async ()=>{
    const to = !p.is_invalid;
    try{
      await post('/api/photos/invalid', {photo_ids:[pid], invalid: to});
      p.is_invalid = to ? 1 : 0;
      _drawerCache.set(pid, p);
      toast(to ? '已标记为无效' : '已取消无效标记', 'ok');
      window.dispatchEvent(new Event('photos:changed'));
      await openDrawer(pid);          // 重绘按钮/角标状态
    }catch(e){ toast('操作失败：' + e.message, 'err'); }
  };

  // 本次忽略/恢复（2026-10-18 需求4）：新产品暂不入库、退出关联队列
  const igBtn = $('#dwIgnore');
  if(igBtn) igBtn.onclick = async ()=>{
    const to = !p.photo_ignored;
    try{
      await post('/api/photos/ignore', {photo_ids:[pid], ignored: to});
      p.photo_ignored = to ? 1 : 0;
      _drawerCache.set(pid, p);
      toast(to ? '已忽略：退出关联队列，可在「已忽略」档恢复'
               : '已恢复：重新进入关联队列', 'ok');
      window.dispatchEvent(new Event('photos:changed'));
      await openDrawer(pid);          // 重绘按钮/角标状态
    }catch(e){ toast('操作失败：' + e.message, 'err'); }
  };

  // 重新识别拆两档（2026-10-19）：同一套流程，只差 mode。
  //   ocr  —— 本地免费，强制重跑文字提取；full —— 完整链路花多模态额度。
  // 两个按钮互斥禁用：一个在跑时另一个也不能点（后台同一个照片并发重治
  // 会把 ocr_tokens 写乱）。
  const dwRegovRun = async (btn, mode)=>{
    const label = mode === 'ocr' ? 'OCR 识别' : '大模型识别';
    const other = $(mode === 'ocr' ? '#dwRegov' : '#dwRegovOcr');
    btn.disabled = true;
    if(other) other.disabled = true;
    btn.textContent = '识别中…';
    try{
      const r = await post('/api/photos/'+pid+'/regovern', {mode: mode});
      const bits = [];
      if((r.codes||[]).length) bits.push('读到 '+r.codes.length+' 个编码');
      if(r.tokens_n) bits.push('文字 '+r.tokens_n+' 条');
      if(r.links_added) bits.push('自动关联 '+r.links_added+' 条');
      if(r.hits_n > r.links_added) bits.push((r.hits_n - r.links_added)+' 条进待确认');
      toast(label+'完成'+(bits.length?'：'+bits.join('，'):''), 'ok');
      const fresh = await api('/api/photos/'+pid);
      _drawerCache.set(pid, fresh);
      await openDrawer(pid);
      window.dispatchEvent(new Event('photos:changed'));
    }catch(e){
      toast(label+'失败：'+e.message, 'err');
      btn.disabled = false;
      btn.textContent = label;
      if(other) other.disabled = false;
    }
  };
  const rgBtn = $('#dwRegov');
  if(rgBtn) rgBtn.onclick = ()=>dwRegovRun(rgBtn, 'full');
  const rgOcrBtn = $('#dwRegovOcr');
  if(rgOcrBtn) rgOcrBtn.onclick = ()=>dwRegovRun(rgOcrBtn, 'ocr');

  // 「同组连拍 · 可能的全景图」+「同编码的其他照片」：懒加载。
  // 2026-10-18 合并：条件从「有关联产品」放宽为「有同组照片 **或** 已关联产品」
  // （同组连拍与有没有关联无关）；两者皆无才不请求。
  // 抽屉被重绘后 $('#dwPano') 会换成新节点 —— 回调里先查再写，别写进旧 DOM。
  if((p.links || []).length || gps.length){
    api('/api/photos/' + pid + '/panoramas').then(async d=>{
      const box = $('#dwPano'), sec = $('#dwPanoSec');
      if(!box || !sec) return;                     // 抽屉已切到别的照片
      const items = d.items || [];
      const sibs = d.siblings || [];
      if(!items.length && !sibs.length){ sec.style.display = 'none'; return; }
      const firstCode = links.length ? links[0].code_norm : '';
      const codeIn = $('#dwPanoCode');
      if(codeIn && !codeIn.value && firstCode) codeIn.value = firstCode;
      const bar = $('#dwPanoBar');
      if(items.length && bar) bar.style.display = '';
      if(items.length){
        // 合并列表：同组连拍在前（后端已排好序），两类都显示文件名 + 拍摄时间
        box.innerHTML = items.map(s=>{
          const srcTag = s.source === 'group'
            ? '<span class="tag ok">同组连拍</span>'
            : '<span class="tag">可能的全景图</span>';
          const gap = fmtGap(diffSec(p.taken_at, s.taken_at));
          return '<div class="pano-item">'+
            '<input type="checkbox" class="dwGChk" value="'+esc(s.photo_id)+'"'+
              ' style="flex:0 0 auto" title="勾选后可一并关联">'+
            '<img loading="lazy" src="'+s.thumb+'" data-full="/img/'+esc(s.photo_id)+'" '+
              'data-cap="'+esc(s.file)+'" data-taken="'+esc(s.taken_at||'')+'" '+
              'title="'+esc(s.file)+'（点击看大图）">'+
            '<div class="pano-info">'+
              srcTag+
              '<span class="faint">'+esc(kindName(s.photo_kind))+'</span>'+
              ((s.used_by || 0) > 0
                ? '<span class="tag warn" title="整托盘常装多件货">已用于 '+s.used_by+' 个产品</span>' : '')+
              // 文件名 + 拍摄时间：判断「是不是同一件货」靠的就是这两个。
              // 2026-10-18 老板反馈「图片太小，文件名和时间看不清」：
              // 拆成两行（文件名一行可截断有 title，时间一行完整显示），
              // 缩略图也放大（见 app.css .pano-item img）。
              // class 带 gshot-t：cdp_ui1007 的「展示图的地方都要有时间到秒」
              // 断言扫的就是这个类，合并后仍然命中。
              '<div class="pano-file" style="width:100%" title="'+esc(s.file||'')+'">'+
                esc(s.file||'')+'</div>'+
              '<div class="pano-sub faint gshot-t" style="width:100%" '+
                'title="'+esc(s.taken_at||'无时间')+'">'+fmtTaken(s.taken_at)+
                (gap? ' · 距本张 '+gap : '')+'</div>'+
              // 推荐依据（2026-10-19 老板：「推荐不是很准」）：
              // 把「凭什么推这张」写在脸上 —— 同箱 N / 相隔几秒 / 连拍序号相邻。
              // 老板一眼能判该不该点「确认为同一产品」，不用去猜系统怎么算的。
              (s.reason
                ? '<div class="pano-why" style="width:100%" title="推荐依据：'+
                  esc(s.reason)+'">依据：'+esc(s.reason)+'</div>' : '')+
            '</div>'+
            '<button class="btn sm ghost" data-pano-link="'+esc(s.photo_id)+'"'+
              ' data-pano-code="'+esc(s.code||firstCode)+'">确认为同一产品</button>'+
          '</div>';
        }).join('');
      } else {
        box.innerHTML = '<div class="faint">没有同组连拍或邻近照片。</div>';
      }
      // 「不遗漏」出口（2026-10-18）：同组超过上限只展示前 8 张，
      //   其余的给一个「展开整组」—— 数据就在详情的 group_photos 里（全量），
      //   就地展开成只读网格，不打断当前上下文、不跳页。
      //   口径与后端一致：排除无效照。
      const gAll = gps.filter(g=>!g.is_invalid);
      const gShown = items.filter(s=>s.source==='group').length;
      const gRest = gAll.length - gShown;      // 当前照片本身不在 gAll 里
      const moreBox = $('#dwGroupMore');
      if(moreBox){
        moreBox.innerHTML = (gRest > 0)
          ? '<div class="row" style="gap:8px;align-items:center;margin-top:2px">'+
            '<span class="faint">本组共 '+(gAll.length+1)+' 张，还有 '+gRest+
            ' 张未显示（避免整组刷屏，只给前 8 张）</span>'+
            '<button class="btn sm ghost" id="dwGroupMoreBtn">展开整组</button></div>'
          : '';
      }
      // 同产品编码的其他照片：**大图正下方**（2026-10-19 老板需求1）。
      // 标准图标识（2026-10-21 老板反馈修正）：只给**真的被做成标准图的那张
      // 源照片**打徽标 —— 产品只有 1 张标准图时，原来按「产品有没有标准图」
      // 判断会把同编码所有照片全打上，误导。逐张比 src_photo_id；
      // 上传的标准图 src_photo_id 是哨兵值（_UPLOADED_），天然匹配不上任何照片。
      const sbox = $('#dwSibs');
      if(sbox && sibs.length){
        let stdSrcIds = new Set();
        try{
          const sd = await api('/api/standard-images?code='+
            encodeURIComponent(links.map(l=>l.code_norm)[0]||''));
          stdSrcIds = new Set((sd.items||[])
            .filter(s=>(s.origin||'crop')==='crop' && s.src_photo_id)
            .map(s=>s.src_photo_id));
        }catch(_e){ /* 标准图取不到不挡参考块 */ }
        // 2026-10-20 老板：这块要「小一点、往上放、只放最近的几个」——
        // 同编码可能有几十张（历史各批次），全铺开会把大图挤出首屏。
        // 口径：**按拍摄时间倒序取前 SIB_FIRST 张**，更早的折起来。
        // 排序在这层做（后端 siblings 不保证顺序，别依赖它的返回次序）。
        const SIB_FIRST = 8;
        const byTime = (a,b)=>String(b.taken_at||'').localeCompare(String(a.taken_at||''));
        const sibSorted = sibs.slice().sort(byTime);
        const head = sibSorted.slice(0, SIB_FIRST), rest = sibSorted.slice(SIB_FIRST);
        const sibCard = s => '<div class="dw-sib" data-sibpid="'+esc(s.photo_id)+'" '+
                'title="'+esc(s.file||'')+'">'+kindChip(s.photo_kind||'unknown','dw-sibkind')+
                (stdSrcIds.has(s.photo_id)? ' <span class="tag ok dw-sibstd" style="font-size:10px" '+
                  'title="这张照片已制作标准图，导出报告时采用">标准图</span>' : '')+
                '<img loading="lazy" src="'+s.thumb+'">'+
                '<div class="gshot-t" title="'+esc(s.taken_at||'无时间')+'">'+fmtTaken(s.taken_at)+'</div>'+
                // 文件名留一行（10px 截断）：卡片虽小，判断「是不是同一件货」
                // 还是常要扫一眼文件名；完整值在 title 里 hover 可见。
                '<div class="dw-sibf" title="'+esc(s.file||'')+'">'+esc(s.file||'')+'</div>'+
                '</div>';
        sbox.innerHTML =
          '<div class="faint" style="margin-bottom:4px">最近 '+head.length+'/'+sibs.length+' 张</div>'+
            '<div class="dw-sibgrid">'+head.map(sibCard).join('')+'</div>'+
            (rest.length
              ? '<details class="dw-sibmore"><summary>展开更早的 '+rest.length+' 张</summary>'+
                '<div class="dw-sibgrid" style="margin-top:6px">'+
                rest.map(sibCard).join('')+'</div></details>'
              : '');
        const sibSec = $('#dwSibsSec');
        if(sibSec) sibSec.style.display = '';
      }
      sec.style.display = '';
      $$('#dwPano .pano-item img').forEach(im=>{
        im.onclick = ()=>openViewer(im.dataset.full, im.dataset.cap, im.dataset.taken);
      });
      $$('#dwBody [data-sibpid]').forEach(el=>el.onclick = ()=>{
        const s = sibs.find(x=>x.photo_id===el.dataset.sibpid);
        if(s) openViewer(s.full, s.file, s.taken_at);
      });
      $$('#dwPano [data-pano-link]').forEach(btn=>{
        btn.onclick = async ()=>{
          btn.disabled = true;
          await doDrawerLink(btn.dataset.panoLink, btn.dataset.panoCode);
        };
      });
      // 展开整组：把 group_photos 里未展示的补渲染成只读网格（点开看大图）。
      // ⚠️ 只读、不做批量关联 —— 这段是「兜底可查」，不是推荐列表，
      //    再塞一套勾选框等于把截断的负担原样还回去。
      const moreBtn = $('#dwGroupMoreBtn');
      if(moreBtn) moreBtn.onclick = ()=>{
        const grid = $('#dwGroupAllGrid');
        if(!grid) return;
        const shownIds = new Set(items.map(s=>s.photo_id));
        const rest = gps.filter(g=>!g.is_invalid && !shownIds.has(g.id));
        grid.style.display = '';
        grid.innerHTML = '<div class="faint" style="margin-bottom:6px">本组其余 '+
          rest.length+' 张（只读，点开看大图；要关联的话它出现在推荐里再确认）</div>'+
          '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px">'+
          rest.map(g=>'<div class="shot-card" data-morepid="'+esc(g.id)+'" title="'+esc(g.file||'')+'">'+
            kindChip(g.photo_kind||'unknown')+
            '<img loading="lazy" src="'+g.thumb+'" style="width:100%;height:112px;object-fit:cover;border-radius:4px;cursor:pointer">'+
            '<div class="gshot-t" style="font-size:12px" title="'+esc(g.taken_at||'无时间')+'">'+
            fmtTaken(g.taken_at)+'</div>'+
            '<div class="faint" style="font-size:11px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" '+
            'title="'+esc(g.file||'')+'">'+esc(g.file||'')+'</div></div>').join('')+'</div>';
        moreBtn.parentElement.style.display = 'none';
        $$('#dwGroupAllGrid [data-morepid]').forEach(el=>el.onclick = ()=>{
          const g = gps.find(x=>x.id===el.dataset.morepid);
          if(g) openViewer(g.full || ('/img/'+g.id), g.file||'', g.taken_at);
        });
      };
      const pAll = $('#dwPanoAll'), pLink = $('#dwPanoLink');
      const sync = ()=>{
        const n = $$('#dwPano .dwGChk').filter(c=>c.checked).length;
        if(!pLink) return;
        pLink.disabled = !n;
        pLink.textContent = n ? ('关联选中（'+n+'）到产品') : '关联选中到产品';
      };
      if(pAll) pAll.onchange = ()=>{
        $$('#dwPano .dwGChk').forEach(c=>c.checked = pAll.checked);
        sync();
      };
      $$('#dwPano .dwGChk').forEach(c=>c.onchange = sync);
      if(pLink) pLink.onclick = async ()=>{
        const ids = $$('#dwPano .dwGChk').filter(c=>c.checked).map(c=>c.value);
        if(!ids.length) return toast('先勾选要关联的照片','err');
        const code = (($('#dwPanoCode')||{}).value || firstCode || '').trim();
        if(!code) return toast('输入产品编码，或用当前照片已关联的编码','err');
        try{
          const r = await post('/api/links',{photo_ids:ids, code:code, by:'web',
                                            evidence:'同组连拍/全景批量关联'});
          toast('已关联 '+r.linked+' 张照片到 '+code,'ok');
          // 批量动了好几张（可能含当前这张）的关联关系 —— 整包详情缓存作废，
          // 否则 openDrawer 复用旧数据，「已关联产品」不更新（2026-10-14 修）。
          _drawerCache.clear();
          openDrawer(pid); loadStats();
          // ② 关联后自动刷新背后的列表；⚠️ 别发 wizard:refresh（advance
          //    语义会把老板从③直接推到④，2026-10-14 实测）。
          window.dispatchEvent(new Event('photos:changed'));
        }catch(e){ toast('关联失败：'+e.message,'err'); }
      };
    }).catch(()=>{ const s = $('#dwPanoSec'); if(s) s.style.display = 'none'; });
  }

  // 照片分类：切换即保存（2026-10-15：模型判错时人工改判）
  // 2026-10-15 老板反馈「改了分类其他部分没同步刷新」：抽屉里不止下拉一处
  // 显示分类 —— 元数据行角标、关联区文案（isDoc）、标准图入口（scene/清单
  // 隐藏）、识别细节提示全跟着分类走。就地逐个补丁必漏，干脆整体重绘
  // （openDrawer 会保持滚动位置，_drawerCache 已更新所以读到新值）；
  // 提示改走全局 toast —— 内联「已保存」会随重绘一起没掉。
  const kindSel = $('#dwKind');
  if(kindSel) kindSel.onchange = async ()=>{
    try{
      await post('/api/photos/kind', {photo_ids:[pid], kind: kindSel.value});
      p.photo_kind = kindSel.value || 'unknown';
      p.kind_conf = null;               // 人工拍板，不再挂模型的置信度
      _drawerCache.set(pid, p);
      await openDrawer(pid);
      toast('已改判为「'+kindName(p.photo_kind)+'」', 'ok');
      // 列表/树的分类计数与角标跟着变（分类是筛选维度之一）
      window.dispatchEvent(new Event('photos:changed'));
      // 改判即重治（2026-10-15 需求1）：人工纠偏分类后，按新分类重跑
      // 读码链路 —— 分类判错导致编码没识别的图，改一个下拉框就救回来。
      // 异步跑（OCR/视觉要几秒），完成后回填缓存 + 重绘，编码/候选就位。
      post('/api/photos/'+pid+'/regovern', {}).then(async r=>{
        const bits = [];
        if((r.codes||[]).length) bits.push('读到 '+r.codes.length+' 个编码');
        if(r.links_added) bits.push('自动关联 '+r.links_added+' 条');
        if(r.hits_n > r.links_added) bits.push((r.hits_n - r.links_added)+' 条进待确认');
        toast('已按「'+kindName(r.kind)+'」重新识别'+(bits.length?'：'+bits.join('，'):''), 'ok');
        try{
          const fresh = await api('/api/photos/'+pid);
          _drawerCache.set(pid, fresh);
          if($('#drawer').classList.contains('on')) await openDrawer(pid);
        }catch(_e){ /* 缓存回填失败不影响主流程 */ }
        window.dispatchEvent(new Event('photos:changed'));
      }).catch(e=>{ toast('重新识别失败：'+e.message, 'err'); });
    }catch(e){ toast('保存失败：'+e.message, 'err'); }
  };

  // 用途分类：切换即保存
  const usageSel = $('#dwUsage');
  if(usageSel) usageSel.onchange = async ()=>{
    const msg = $('#dwUsageMsg');
    try{
      await patch('/api/photos/'+pid+'/usage', {usage: usageSel.value});
      p.photo_usage = usageSel.value || null;
      _drawerCache.set(pid, p);
      msg.textContent = '已保存';
      setTimeout(()=>{ if(msg) msg.textContent=''; }, 1500);
      // 监装细分只在监装照上有意义 —— 切成监装立刻显示，切走立刻隐藏
      const row = $('#dwSuptagRow');
      if(row) row.style.display = usageSel.value==='监装' ? '' : 'none';
      const aiRow = $('#dwSuptagAiRow');
      if(aiRow) aiRow.style.display = usageSel.value==='监装' ? '' : 'none';
    }catch(e){ msg.textContent = '保存失败：'+e.message; }
  };

  // 监装细分：切换即保存（POST，后端只认 7 个枚举值，空 = 清除）
  const suptagSel = $('#dwSuptag');
  if(suptagSel) suptagSel.onchange = async ()=>{
    const msg = $('#dwSuptagMsg');
    try{
      const r = await post('/api/photos/supervision-tag', {photo_ids:[pid], tag: suptagSel.value});
      p.supervision_tag = r.tag || null;
      p.sup_tag_confirmed = 1;          // 人工表态过了，重跑治理不再动它
      _drawerCache.set(pid, p);
      msg.textContent = '已保存';
      setTimeout(()=>{ if(msg) msg.textContent=''; }, 1500);
    }catch(e){ msg.textContent = '保存失败：'+e.message; }
  };

  // 采用模型建议：等于人工点了那个下拉框，之后这张就是「已确认」
  const aiBtn = $('#dwSuptagAccept');
  if(aiBtn) aiBtn.onclick = async ()=>{
    const msg = $('#dwSuptagMsg');
    aiBtn.disabled = true;
    try{
      const r = await post('/api/photos/supervision-tag/accept-ai', {photo_ids:[pid]});
      p.supervision_tag = p.sup_tag_ai;
      p.sup_tag_confirmed = 1;
      _drawerCache.set(pid, p);
      openDrawer(pid);                  // 重画：把「建议」那一行换成「已确认」
      const m2 = $('#dwSuptagMsg');
      if(m2){ m2.textContent = '已采用建议'; setTimeout(()=>m2.textContent='', 1500); }
    }catch(e){
      aiBtn.disabled = false;
      if(msg) msg.textContent = '采用失败：'+e.message;
    }
  };

  $('#dwImg').onclick = ()=>{ $('#maskImg').src = p.full; resetViewer(); $('#mask').classList.add('on'); };
  // 候选 / 同编码照片的点开（data-pano-* / data-sibpid）在上面异步块里绑。
  // 语义不变：点图 = 看大图，不换详情页（老板 10-02 要求）；要换详情用大图上的
  // 「打开详情」。全选 / 批量关联也已并入同一块（dwPanoAll / dwPanoLink）。
  const metaBtn = $('#dwMetaApply');
  if(metaBtn) metaBtn.onclick = async ()=>{
    const code = links.length? links[0].code_norm : '';
    if(!code) return toast('先关联产品','err');
    // 只填充产品当前为空的字段，不覆盖已有值
    try{
      const prod = await api('/api/products/'+encodeURIComponent(code));
      const patchData = {};
      metaKeys.forEach(([k])=>{
        if(vmeta[k] && !prod[k]) patchData[k] = vmeta[k];
      });
      if(!Object.keys(patchData).length) return toast('产品字段都已有值，无需填充','err');
      await patch('/api/products/'+encodeURIComponent(code), patchData);
      toast('已填充：'+Object.keys(patchData).map(k=>({name:'品名',spec:'规格',brand:'品牌',material:'材质',unit:'单位',category:'类别'}[k]||k)).join('、'),'ok');
      openDrawer(pid);
    }catch(e){ toast('填充失败：'+e.message,'err'); }
  };
  $$('#dwBody .un').forEach(u=>u.onclick=async()=>{
    try{ await del('/api/links',{code:u.dataset.un, photo_id:pid}); toast('已解除','ok');
      _drawerCache.delete(pid);          // 关联关系变了，缓存详情作废，重开必须重取
      openDrawer(pid); loadStats();
      // ⚠️ 同上：不发 wizard:refresh（advance 会把③推到④）
      window.dispatchEvent(new Event('photos:changed'));
    }
    catch(e){ toast('解除失败：'+e.message,'err'); }
  });
  // 关联输入框：只在「建议关联」区块渲染时存在（已关联的照片不渲染）
  const linkBtn = $('#dwLink');
  const codeInput = $('#dwCode');
  if(linkBtn) linkBtn.onclick = ()=>doDrawerLink(pid);
  if(codeInput) codeInput.onkeydown = e=>{ if(e.key==='Enter') doDrawerLink(pid); };
  // 编码联想（2026-10-19）：手输 14~16 位极易错，输后几位带出完整编码。
  //   dwCode：选中即关联（这个框的回车语义就是关联）；dwPanoCode：填入即可。
  if(codeInput) attachCodeSuggest(codeInput, c=>doDrawerLink(pid, c));
  const panoCodeIn = $('#dwPanoCode');
  if(panoCodeIn) attachCodeSuggest(panoCodeIn, null);
  const stdBtn = $('#dwStd');
  if(stdBtn) stdBtn.onclick = ()=>openStdEditor(pid, kind, links.length?links[0].code_norm:'');
  // 标准图列表：等它落定再还原滚动 —— 早一步还原会被当时的内容高度钳住
  // （列表是异步来的，之后内容长高，scrollTop 不会自己长回去）。
  if(stdAllowed && firstProd) await loadDwStdList(firstProd, pid);

  if($('#dwCands')){    // 已关联照片：建议关联区块整体不渲染，也别去请求候选
  try{
    const cs = await api('/api/photos/'+pid+'/candidates');
    const box = $('#dwCands');
    if(!cs.items.length){
      box.innerHTML = emptyHtml('🔎','没有候选编码','这张照片没读出可匹配的编码，可在上方手输编码关联','','sm');
    }
    else box.innerHTML = cs.items.map(c=>{
      const fuzzy = c.fuzzy ? ' title="识别可能不准，请核对" style="border:1px solid var(--warn)"' : '';
      const done = linkedSet.has(c.code) ? ' ✓' : '';
      return '<div class="linkrow"><span class="chip btn'+'" data-c="'+esc(c.code)+'"'+fuzzy+'>'+esc(c.code)+'</span>'+
        '<span class="muted">'+esc(c.name||'')+'</span>'+
        '<span class="faint">'+(c.why||'')+(c.fuzzy?' · 模糊需核对':'')+'</span></div>';
    }).join('') + '<div class="faint" style="margin-top:6px">点编码即关联；模糊候选请先核对再点。</div>';
    $$('#dwCands .chip').forEach(ch=>ch.onclick=()=>doDrawerLink(pid, ch.dataset.c));
  }catch(e){ $('#dwCands').innerHTML='<div class="faint">候选读取失败</div>'; }
  }
  // 滚动还原放在**最后**：标准图列表 / 候选都是异步插入的，早还原会被当时的
  // 内容高度钳住（内容后来长高，scrollTop 不会自己长回去）。
  if(_dwKeepScroll >= 0 && db){ db.scrollTop = _dwKeepScroll; _dwKeepScroll = -1; }
}

/* ── 编码联想（2026-10-19 老板需求：输入编码要能联想，提升输入效率）──
   抽屉两个输入框共用：dwCode（选中=直接关联）、dwPanoCode（选中=填入）。
   后端 /api/products/suggest 包含式匹配（现场记的是后几位/中间几位）。
   键盘：↑↓ 选择 / Enter 选中或原样提交 / Esc 关闭；点选同选中。
   ⚠️ 下拉用 fixed + 实时坐标（无定位祖先时会挂 body，列表跟着滚动跑偏）。
   ⚠️ 下拉节点**不能用固定 id**：两个输入框各挂一份联想，共用 id 时
   全局选择器会命中别人的下拉 —— 点了 dwCode 的下拉直接触发写库关联
   （CDP 实测踩过）。每实例持有自己的 box 引用，事件只绑 box 内部。 */
function attachCodeSuggest(input, onPick){
  let items = [], idx = -1, box = null, timer = null;

  const close = ()=>{ if(box){ box.remove(); box = null; } idx = -1; };
  const render = ()=>{
    close();
    if(!items.length) return;
    box = document.createElement('div');
    box.className = 'dw-suggest';
    box.style.cssText = 'position:fixed;z-index:1000;background:#fff;border:1px solid var(--line);'
      +'border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.12);max-height:220px;'
      +'overflow:auto;min-width:' + Math.max(220, input.offsetWidth) + 'px';
    const r = input.getBoundingClientRect();
    box.style.left = r.left + 'px';
    box.style.top = (r.bottom + 4) + 'px';
    box.innerHTML = items.map((p,i)=>
      '<div class="dw-sg" data-i="'+i+'" style="padding:6px 10px;cursor:pointer;'
        +(i===idx?'background:var(--line-2);':'')+'">'
        +'<span style="font-weight:600">'+esc(p.code_norm)+'</span>'
        +(p.name? ' <span class="faint" style="font-size:12px">'+esc(p.name)+'</span>':'')
      +'</div>').join('');
    document.body.appendChild(box);
    // 🔴 mousedown 必须 preventDefault（2026-10-19 老板实测「点了没反应」）：
    //    真实浏览器点击序列是 mousedown → blur → mouseup → click。
    //    input 的 blur 监听 150ms 后 close() 把 box 移除，**已脱离文档流的
    //    元素不再派发 click** —— 看着就是「点了没反应」。
    //    （CDP 用 el.click() 强制派发能过 = 假绿，必须真实鼠标事件才测得出来。）
    //    preventDefault 掉 mousedown 的默认行为 = 输入框不失焦，下拉存活。
    box.addEventListener('mousedown', e=>e.preventDefault());
    // ⚠️ 只绑 box 内部 —— 事件走的是闭包里的这个实例自己的 items/onPick
    box.querySelectorAll('.dw-sg').forEach(el=>el.onclick = ()=>{
      pick(items[+el.dataset.i]);
    });
  };
  const pick = (p)=>{
    if(!p) return;
    input.value = p.code_norm;
    close();
    if(onPick) onPick(p.code_norm);
    else input.focus();
  };
  input.addEventListener('input', ()=>{
    clearTimeout(timer);
    const q = input.value.trim();
    if(q.length < 2){ close(); return; }   // 一两位噪音太大，等两位再联想
    timer = setTimeout(async ()=>{
      try{
        const d = await api('/api/products/suggest?q='+encodeURIComponent(q));
        items = d.items || [];
        idx = items.length ? 0 : -1;
        render();
      }catch(e){ close(); }
    }, 200);
  });
  input.addEventListener('keydown', e=>{
    if(!box || !items.length) return;      // 无下拉时走各自原有 Enter 逻辑
    if(e.key === 'ArrowDown'){ idx = Math.min(items.length-1, idx+1); render(); e.preventDefault(); }
    else if(e.key === 'ArrowUp'){ idx = Math.max(0, idx-1); render(); e.preventDefault(); }
    else if(e.key === 'Enter'){ pick(items[idx]); e.preventDefault(); }
    else if(e.key === 'Escape'){ close(); }
  });
  input.addEventListener('blur', ()=>setTimeout(close, 150));  // 留时间给点选
}

async function doDrawerLink(pid, code){
  code = (code||'').trim() || ($('#dwCode') ? $('#dwCode').value.trim() : '');
  if(!code) return;
  try{
    await post('/api/links',{photo_id:pid, code:code, by:'web'});
    toast('已关联 '+code,'ok');
    const dc = $('#dwCode'); if(dc) dc.value='';   // 手输框只在「待关联」时渲染，必须判空
    _drawerCache.delete(pid);          // 关联关系变了，缓存详情作废，重开必须重取
    openDrawer(pid); loadStats();
    // ② 关联后自动刷新背后的列表（五档徽章与列表同源，数字自动一致）
    // ⚠️ 同上：不发 wizard:refresh（advance 会把③推到④）
    window.dispatchEvent(new Event('photos:changed'));
  }catch(e){ toast('关联失败：'+e.message,'err'); }
}
async function loadDwStdList(code, pid){
  const box = $('#dwStdList');
  if(!box) return;
  try{
    const d = await api('/api/standard-images?code='+encodeURIComponent(code));
    const items = d.items||[];
    if(!items.length){
      box.innerHTML = emptyHtml('🖼️','该产品还没有标准图','用「制作标准图」裁剪保存后，即成为当前生效版','','sm');
      return;
    }
    const last = items[items.length-1];
    box.innerHTML = '<div class="faint" style="margin-bottom:4px">标准图版本（最新为当前生效，导出时采用）：</div>'+
      items.map(s=>{
        const cur = s.id===last.id;
        return '<div class="stdrow">'+
          '<img src="/std-img/'+s.id+'" alt="">'+
          '<div class="inf">'+
            '<span class="tag '+(cur?'ok':'')+'">'+(cur?'当前生效':'历史')+'</span>'+
            (s.src_photo_id===pid? ' <span class="tag">本图</span>':'')+
            ' '+kindChip(s.kind)+
            ' <span class="faint">'+(s.width||'?')+'×'+(s.height||'?')+' · '+esc((s.created_at||'').slice(0,10))+'</span>'+
          '</div>'+
          '<span class="un" data-std-del="'+esc(s.id)+'" title="删除该版本">删除</span>'+
        '</div>';
      }).join('');
    $$('#dwStdList [data-std-del]').forEach(x=>x.onclick=async()=>{
      if(!confirm('删除这条标准图版本？（只删标准图资产，不动原照片）')) return;
      try{
        await api('/api/standard-images/'+x.dataset.stdDel,{method:'DELETE'});
        toast('已删除','ok'); loadDwStdList(code, pid);
      }catch(e){ toast('删除失败：'+e.message,'err'); }
    });
  }catch(e){
    box.innerHTML = '<span class="faint">标准图读取失败</span>';
  }
}
$('#dwClose').onclick = ()=>$('#drawer').classList.remove('on');

/* ←/→ 在相邻照片间切换（按钮 + 方向键都走这里）
   ⚠️ 这段在机械拆分时丢过一次：HTML 里的按钮还在，但没人绑 onclick，
      页面「看着能用、点了没反应」。改动后必须跑 checks/cdp_features 的第 7 项。 */
function drawerGo(d){
  if(_drawerList.length < 2) return;
  const i = _drawerIdx + d;
  if(i < 0 || i >= _drawerList.length) return;
  openDrawer(_drawerList[i]);
}
$('#dwPrev').onclick = e=>{ e.stopPropagation(); drawerGo(-1); };
$('#dwNext').onclick = e=>{ e.stopPropagation(); drawerGo(1); };
document.addEventListener('keydown', e=>{
  if(!$('#drawer').classList.contains('on')) return;
  const t = document.activeElement && document.activeElement.tagName;
  if(t === 'INPUT' || t === 'TEXTAREA') return;   // 别抢输入框的方向键
  if(e.key === 'ArrowLeft'){ e.preventDefault(); drawerGo(-1); }
  else if(e.key === 'ArrowRight'){ e.preventDefault(); drawerGo(1); }
});

/* Esc 逐层关：大图 → 标准图编辑器 → 照片详情，**关掉一层就算消费掉这次 Esc**。
   原来是一把全关（三个一起 remove），连带把下面开着的层也一起关了。 */
onEscape(()=>{
  if($('#mask').classList.contains('on')){
    $('#mask').classList.remove('on'); resetViewer(); return true;
  }
  if($('#stdEd').classList.contains('on')){ $('#stdEd').classList.remove('on'); return true; }
  if($('#drawer').classList.contains('on')){ $('#drawer').classList.remove('on'); return true; }
}, 50);   // prio 50：比产品/批次抽屉(10)高，Esc 先关照片详情这一层

/* 大图 → 详情：关掉遮罩再开抽屉（两个浮层不叠着开） */
$('#maskToDetail').onclick = ()=>{
  if(!_viewerPid) return;
  $('#mask').classList.remove('on');
  resetViewer();
  if(_drawerList.includes(_viewerPid)){
    openDrawer(_viewerPid);
  }else{
    _drawerList.splice(_drawerIdx+1, 0, _viewerPid);
    openDrawer(_viewerPid);
  }
};

export { _drawerCache, loadDwStdList, _drawerList, openDrawer, doDrawerLink, _drawerIdx, drawerGo, openViewer };

export function setDrawerList(arr){ _drawerList = arr; }
export function getDrawerList(){ return _drawerList; }
