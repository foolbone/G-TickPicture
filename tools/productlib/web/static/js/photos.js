// photos.js —— 由 index.html 内联脚本拆分而来，逻辑未改
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS, fmtTaken, fmtGap, diffSec, getCid } from './core.js';
import { openModal } from './modal.js';
import { attachDirPicker } from './dirpicker.js';
import { openDrawer, setDrawerList } from './drawer.js';
import { loadStats } from './home.js';
import { loadPhotoTree } from './phototree.js';
import { selOn, selHas, selToggle, selSetMode, selBindBar,
         selSetIds, selReset, selIds, selSize, selClear, selUpdBar,
         selAddIds } from './selbatch.js';
// 不导入 batches.js —— 批次刷新由 batches.js 自行注册 onTab('batches') 完成

/* ── 照片 ── */
/** 一张照片卡片。prevTaken 传入时多显示「与上一张间隔 +3s」——
 *  同组连拍最该看的就是这个数（0~2s = 真的连拍，2min = 中间停过）。
 *  ⚠️ 「待确认 / 新产品」角标**不在这里拼** —— 那两个集合要全库模糊匹配，
 *  冷缓存 6 秒级；由 applyFlagBadges() 在渲染后异步补，首屏不等它。 */
function shotCard(p, showLink, stdSet, prevTaken){
  const kind = p.photo_kind || 'unknown';
  const st = p.govern_state==='done' ? 'ok' : (p.govern_state==='failed'?'err':'');
  const flagHtml = '';
  let codes = [];
  try { codes = (p.vision_codes && p.vision_codes!=='[]') ? JSON.parse(p.vision_codes||'[]') : []; } catch(e){}
  const codeLine = codes.length
    ? '<div class="codes">编码：'+codes.slice(0,3).map(c=>'<b>'+esc(c)+'</b>').join(' ') +
      (codes.length>3?(' +'+(codes.length-3)):'')+'</div>'
    : '';
  const tail = (p.govern_state!=='done')
    ? ' · <span class="tag '+st+'">'+esc(p.govern_state)+'</span>' : '';
  const gap = prevTaken ? fmtGap(diffSec(prevTaken, p.taken_at)) : '';
  const metaLine = fmtTaken(p.taken_at)
      + (gap? (' · '+gap) : '')
      + ' · '+p.size_mb+'MB'+(p.nlink?' · 关联 '+p.nlink:'')+tail;
  // 无效照片（2026-10-12）：角标 + 卡片降透明 —— 一眼看出「这批不在工作队列里」
  const invalid = !!p.is_invalid;
  // 已关联/待关联角标（2026-10-19 老板需求「图片上标识已关联和待关联」）：
  //   已关联 = 有 links（nlink>0）；待关联 = 产品图（label/product，
  //   与 _UNLINKED_SQL 白名单同口径）且无 links。非产品照不标（不关它的事）。
  const isLinkable = (kind==='label' || kind==='product');
  const linkBadge = (p.nlink > 0)
    ? '<span class="badge linkb" title="已关联 '+p.nlink+' 个产品编码">已关联</span>'
    : (isLinkable
        ? '<span class="badge todob" title="产品图但还没关联编码 —— 待关联队列">待关联</span>'
        : '');
  return '<div class="shot'+(invalid?' inval':'')+'" data-id="'+p.id+'">'+
    '<img loading="lazy" src="'+p.thumb+'" alt="">'+
    kindBadge(kind)+
    (invalid? '<span class="badge invalb" title="已标记无效：默认不出现在列表/候选/选图等工作队列">无效</span>':'')+
    (stdSet && stdSet.has(p.id) ? '<span class="badge stdb" title="已用此图制作标准图，导出时优先">标</span>':'')+
    linkBadge+
    flagHtml+
    (codeLine || '')+
    // 紧凑模式下 hover 才浮出：文件名 / 时间 / 大小
    '<div class="hinfo"><b>'+esc(p.file)+'</b><i>'+metaLine+'</i></div>'+
    '<div class="meta" title="'+esc(p.file)+'">'+esc(p.file)+'</div>'+
    '<div class="meta faint">'+metaLine+'</div></div>';
}
function bindShots(sel){
  const cards = $$(sel+' .shot');
  // 抽屉左右切换要依据「当前网格的顺序」—— 记下序列，切换时不重新请求整个列表
  setDrawerList(cards.map(c=>c.dataset.id));
  cards.forEach(card=>{
    if(selOn()){
      // 批量选择模式（2026-10-12）：点卡片 = 勾选/取消，不进详情抽屉
      card.classList.toggle('sel-on', selHas(card.dataset.id));
      card.onclick = ()=>{
        selToggle(card.dataset.id);       // 内部会更新当前生效的操作条计数
        card.classList.toggle('sel-on', selHas(card.dataset.id));
      };
      return;
    }
    card.onclick = ()=>openDrawer(card.dataset.id);
  });
}

/* ── 批量选择 & 无效照片标记（2026-10-12 老板需求）──
   选择模式只在本页生效：进入后点卡片即勾选，底部操作条做批量动作。
   选中集合跨「加载更多」保留（以 photo id 为准，与 DOM 无关）。
   实现抽到 selbatch.js（柜作业③复用同一份，2026-10-14）。 */
const SEL_IDS = {btn:'#selBtn', bar:'#selBar', n:'#selN', invalid:'#selInvalid',
                 valid:'#selValid', all:'#selAll', exit:'#selExit', tip:'#selTip',
                 clear:'#selClear', ignore:'#selIgnore', unignore:'#selUnignore',
                 boxSel:'#shots', onMode: ()=>bindShots('#shots')};
selSetIds(SEL_IDS);
// 批量改判的分类选项：与抽屉下拉同一份 KIND_LABELS（core.js 一处定义）
$('#selKind').innerHTML = '<option value="">改判分类…</option>' +
  Object.keys(KIND_LABELS).map(k=>'<option value="'+esc(k)+'">'+
    esc(KIND_LABELS[k])+'</option>').join('');
function selEnter(){ selSetMode(true, SEL_IDS, _afterInvalid); }
// ⚠️ 进本页选择模式时先把「当前生效的操作条」切回照片库这份 ——
// selbatch 的勾选状态是跨页单例，不切的话在③勾完回照片页会去更新③的计数器。
$('#selBtn').onclick = ()=>{
  selSetIds(SEL_IDS);
  selSetMode(!selOn(), SEL_IDS, _afterInvalid);
};
function _afterInvalid(){
  loadCurrent(true);          // 列表/徽章重算（默认排除无效）
  loadStats();
  refreshPhotoTree();         // 树上的用途/分类计数跟着变
  // ⚠️ 别发 wizard:refresh —— 它带 advance 语义（当前步完成就跳下一步），
  //    会在后台悄悄把③推到④。③可见时 photos:changed 的监听器会刷网格/
  //    待办/进度摘要；不可见时切回柜页的 loadProgress(false) 自愈。
  window.dispatchEvent(new Event('photos:changed'));
}
// 批量改判分类（2026-10-15）：勾一批 → 选分类 → 应用。与「标记无效」共用
// 同一个勾选集合（selbatch）；改完只刷新列表，不退出选择模式。
$('#selKindDo').onclick = async ()=>{
  const k = $('#selKind').value;
  if(!k) return toast('先选要改成哪个分类', 'err');
  if(!selSize()) return toast('先勾选照片', 'err');
  try{
    const r = await post('/api/photos/kind', {photo_ids: selIds(), kind: k});
    toast('已把 ' + r.updated + ' 张改判为「' + kindName(k) + '」', 'ok');
    $('#selKind').value = '';
    selClear(); selUpdBar(SEL_IDS);
    _afterInvalid();          // 列表/徽章/树计数统一刷新
  }catch(e){ toast('改判失败：' + e.message, 'err'); }
};

// 全选当前搜索条件下的全部数据（2026-10-15 需求1）：跨页、含未加载的。
// 口径 = 树/下拉筛选 + 当前档（flag），与列表同一套参数。
$('#selAllFiltered').onclick = async ()=>{
  const qs = new URLSearchParams(Object.assign({}, _tabBaseQs(),
    {flag: _tabs.tab, limit: 5000, offset: 0}));
  if(_tabs.tab === 'invalid') qs.set('invalid', 'only');
  if(_tabs.tab === 'ignored') qs.set('ignored', 'only');
  busy(true);
  let d;
  try{ d = await api('/api/photos?' + qs); }
  catch(e){ busy(false); return toast('读取失败：' + e.message, 'err'); }
  busy(false);
  const ids = (d.items || []).map(x=>x.id);
  if(!ids.length) return toast('当前筛选条件下没有照片', 'err');
  selAddIds(ids);
  toast('已选中当前筛选结果 ' + ids.length + ' 张（含未加载的页）', 'ok');
};

/* ── 「待确认 / 新产品」角标：渲染后异步补 ──────────────────────
   🔴 为什么单独一次请求而不是 /api/photos?mark=1：
   那两个集合要全库模糊匹配 + OCR 聚合，实测冷缓存 **6.6 秒**（2738 张照片），
   挂在列表主查询上会把照片页首屏从 0.3s 拖成 6.6s —— 而且「先看到照片、
   再看到角标」本来就比等 6 秒更合理。角标没到之前**不显示**（不是显示 0）。
   第二次起后端缓存命中（60s TTL），实测 0.3s。 */
const FLAG_TIP = {
  cand: '读出了像产品库里某个编码，但还没关联 —— 需要你判断要不要关联',
  newprod: '读出的编码产品库里没有 —— 需要你确认是不是新产品并入库',
};
let _flagTimer = null;
function _flagIdle(fn){
  // 让路给首屏与用户交互：角标那两个集合冷缓存要全库扫十几秒（纯 Python，
  // 抢 GIL），跟用户点击抢同一个进程会让「点开一张照片」明显变慢。
  // 所以等浏览器空闲再发；第一次没算完不显示，2 秒后再补一次。
  if(typeof requestIdleCallback === 'function') requestIdleCallback(fn, {timeout:2500});
  else setTimeout(fn, 1200);
}
export async function applyFlagBadges(sel){
  const box = $(sel);
  if(!box) return;
  _flagIdle(async ()=>{
    // ⚠️ 用 box.querySelectorAll 而不是 $$：core.js 的 $$ 只收选择器、不收 root，
    //    全局查会在「分组」视图里把组内展开的照片也算进来（角标贴错卡片）。
    const cards = Array.from(box.querySelectorAll('.shot'));
    const ids = cards.map(c=>c.dataset.id).filter(Boolean);
    if(!ids.length) return;
    let d;
    try{ d = await api('/api/photo-flags?ids=' + ids.join(',')); }
    catch(e){ return; }               // 角标失败就不画，绝不影响照片本身
    const tags = Object.entries(d || {});
    if(!tags.length){
      // 冷缓存下后端还在算 → 稍后再试一次；两次都没拿到就放弃（不显示 ≠ 没有）
      clearTimeout(_flagTimer);
      _flagTimer = setTimeout(()=>applyFlagBadges(sel), 2500);
      return;
    }
    for(const [pid, tl] of tags){
      const card = cards.find(c=>c.dataset.id === pid);
      if(!card || card.querySelector('.fbadge')) continue;
      const html = (tl || []).filter(t=>FLAG_TIP[t])
        .map(t=>'<span class="fbadge '+(t==='cand'?'cand':'newp')+'" title="'
                + esc(FLAG_TIP[t]) + '">' + (t==='cand'?'待确认':'新产品') + '</span>').join('');
      if(html) card.insertAdjacentHTML('beforeend', html);
    }
  });
}
$('#mask .close').onclick = ()=>{ $('#mask').classList.remove('on'); resetViewer(); };
$('#mask').onclick = e=>{ if(e.target.id==='mask'){ $('#mask').classList.remove('on'); resetViewer(); } };

/* ── 照片查看器：旋转 / 缩放 / 平移 ──
   平移（2026-10-15 老板需求）：放大后要能拖着看各个位置的细节 ——
   只看缩放不给平移，等于放大只能看见中间一块。
   🔴 transform 顺序必须是 translate → rotate → scale：translate 写在最前面
   位移量才是**屏幕像素**（拖拽几像素就走几像素）；写在 scale 之后会被
   缩放倍数放大，拖一下就飞出屏幕。 */
let _vAngle = 0, _vScale = 1, _vTx = 0, _vTy = 0;
const _V_SCALES = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4];
function _applyViewer(){
  const img = $('#maskImg');
  if(img) img.style.transform =
    'translate('+_vTx+'px,'+_vTy+'px) rotate('+_vAngle+'deg) scale('+_vScale+')';
  const info = $('#maskInfo');
  if(info) info.textContent = _vAngle+'° · '+Math.round(_vScale*100)+'%'
    + (_vScale>1 ? ' · 拖动查看细节' : '');
}
function resetViewer(){ _vAngle=0; _vScale=1; _vTx=0; _vTy=0; _applyViewer(); }
/* 位移钳制：不让图被拖出屏幕（留一点边，免得拖到看不见图）。
   旋转 90/270° 时宽高互换 —— 按角度取有效宽高。 */
function _vClamp(){
  const img = $('#maskImg');
  if(!img) return;
  // ⚠️ offsetWidth 在图片尚未完成布局时会是 0 —— 那时钳制会把两个方向都
  //    钳成 0，表现为「放大了却拖不动」（2026-10-15 CDP 实测抓到）。
  //    回退：用当前渲染矩形反推未缩放尺寸（rect 含 transform，除以 scale）。
  const r = img.getBoundingClientRect();
  const w = img.offsetWidth || (r.width ? r.width / _vScale : 0);
  const h = img.offsetHeight || (r.height ? r.height / _vScale : 0);
  const swap = (_vAngle % 180) !== 0;
  const ew = (swap ? h : w) * _vScale, eh = (swap ? w : h) * _vScale;
  // 兜底：尺寸算不出来时（图还没完成布局）按窗口比例给个宽裕的量 ——
  //    宁可多拖一点（拖偏了点「重置」就行），也不能出现「放大了却拖不动」。
  const mx = Math.max(Math.round(window.innerWidth * 0.4),
                      Math.round((ew - window.innerWidth) / 2 + 60));
  const my = Math.max(Math.round(window.innerHeight * 0.4),
                      Math.round((eh - window.innerHeight) / 2 + 60));
  if(_vTx > mx) _vTx = mx; if(_vTx < -mx) _vTx = -mx;
  if(_vTy > my) _vTy = my; if(_vTy < -my) _vTy = -my;
}
function _vStepScale(dir){
  let i = _V_SCALES.indexOf(_vScale);
  if(i<0) i = _V_SCALES.indexOf(1);
  i = Math.max(0, Math.min(_V_SCALES.length-1, i+dir));
  _vScale = _V_SCALES[i];
  _vClamp(); _applyViewer();
}
$('#maskRotL').onclick  = ()=>{ _vAngle=(_vAngle-90+360)%360; _vClamp(); _applyViewer(); };
$('#maskRotR').onclick  = ()=>{ _vAngle=(_vAngle+90)%360; _vClamp(); _applyViewer(); };
$('#maskZoomIn').onclick= ()=>_vStepScale(1);
$('#maskZoomOut').onclick=()=>_vStepScale(-1);
$('#maskReset').onclick = resetViewer;
$('#maskImg').addEventListener('wheel', e=>{
  if(!$('#mask').classList.contains('on')) return;
  e.preventDefault();
  _vStepScale(e.deltaY<0 ? 1 : -1);
}, {passive:false});

/* 拖动平移：只处理鼠标左键/触摸单指；松手后光标恢复 grab。
   用 pointer 事件 —— 一套代码覆盖鼠标 + 触屏，且支持指针捕获（拖出图外
   也不断）。touch-action:none 在 CSS 里关掉浏览器的默认手势。 */
(()=>{
  const img = $('#maskImg');
  if(!img) return;
  let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
  img.addEventListener('pointerdown', e=>{
    if(!$('#mask').classList.contains('on')) return;
    if(e.pointerType === 'mouse' && e.button !== 0) return;
    dragging = true; sx = e.clientX; sy = e.clientY; ox = _vTx; oy = _vTy;
    img.classList.add('dragging');
    try{ img.setPointerCapture(e.pointerId); }catch(_){}
    e.preventDefault();
  });
  img.addEventListener('pointermove', e=>{
    if(!dragging) return;
    _vTx = ox + (e.clientX - sx);
    _vTy = oy + (e.clientY - sy);
    _vClamp(); _applyViewer();
  });
  const end = e=>{
    if(!dragging) return;
    dragging = false;
    img.classList.remove('dragging');
    try{ img.releasePointerCapture(e.pointerId); }catch(_){}
  };
  img.addEventListener('pointerup', end);
  img.addEventListener('pointercancel', end);
  // 方向键微调（看细节时比拖更稳）
  document.addEventListener('keydown', e=>{
    if(!$('#mask').classList.contains('on')) return;
    const step = e.shiftKey ? 120 : 40;
    if(e.key === 'ArrowLeft'){ _vTx += step; }
    else if(e.key === 'ArrowRight'){ _vTx -= step; }
    else if(e.key === 'ArrowUp'){ _vTy += step; }
    else if(e.key === 'ArrowDown'){ _vTy -= step; }
    else return;
    e.preventDefault(); _vClamp(); _applyViewer();
  });
})();

/* 页码分页（2026-10-20 老板：不要「加载更多」，普通翻页、一屏一页）。
   照片库三个视图（全部 loadShots / 分组 loadGroups / 五档 loadPhotoTabs）
   共用这一份页码与页大小；切视图时重置（见 setShotView）。 */
let fPage = 1;
let fSize = 0;
let _fitTries = 0;       // 首屏「按稳定布局重算一屏几张」允许最多 2 次（布局要两拍才稳）
let _sized = false;      // 兼容旧标记（切视图时重置）
const GROUP_SIZE = 30;   // 分组视图每页「组数」（组卡片比照片卡高，单独定）
let _curView = 'full';   // compact / full / group
/* 🔴 请求序列守卫：连续触发两次加载（如「标记无效」和切筛选各发一次）时，
   两个响应都在飞 —— 后发的先到、先发的后到，旧响应会把新结果盖掉
   （2026-10-14 实测：标记无效后列表卡在旧状态）。谁新谁赢，旧的丢弃。 */
let _loadSeq = 0;

async function loadShots(reset){
  const seq = ++_loadSeq;
  if(reset) fPage = 1;
  if(!fSize) fSize = measureSize($('#shots')) || 24;
  const qs = new URLSearchParams({
    state:$('#fState').value, kind:_kindQs(),
    batch:$('#fBatch').value, usage:_usageQs(),
    invalid:$('#fInvalid').value,
    unlinked:$('#fUnlinked').checked?1:0,
    todo:(($('#fCand') && $('#fCand').value) || ''),
    q:$('#fQ').value.trim(),
    container_id:(($('#fContainer') && $('#fContainer').value) || ''),
    sort:_sortVal(),
    limit:fSize, offset:(fPage-1)*fSize});
  const d = await api('/api/photos?'+qs);
  if(seq !== _loadSeq) return;    // 已有更新的请求，这份旧响应丢弃
  $('#fTotal').textContent = '共 '+d.total+' 张';
  const box = $('#shots');
  box.innerHTML = d.items.map(p=>shotCard(p)).join('');   // 页码分页：替换不累积
  $('#shotsEmpty').style.display = d.total? 'none':'block';
  renderPagerInto('#moreBtn', d.total, ()=>loadShots(false));
  // 首屏校准：第一次量的时候卡片还没渲染（布局也没稳），用的是兜底高度 →
  // 拿回来的张数会多出一行、把页码挤出视口。这里按**真实卡片高度**再量一次，
  // 变了就重取这一页（只做一次，不来回抖）。
  // 首屏校准：第一次量的时候布局还没稳（顶栏/工具条刚渲染完，top 会漂），
  // 算出来偏少就只铺 1 行。这里按**稳定后的布局**再量一次，算出来更多就重取
  // 这一页（只做一次；只在变多时重取，避免来回抖）。
  if(_fitTries < 2){
    _fitTries++;
    const n = measureSize(box);
    if(n > 0 && n > fSize){
      fSize = n; fPage = 1;
      return loadShots(false);
    }
  }
  bindShots('#shots');
  applyFlagBadges('#shots');
}

/* ── 分组视图：同货品连拍聚成一组卡片，点开看整组 ── */
function groupCard(g){
  const kindsHtml = Object.entries(g.kinds||{}).map(([k,n])=>
    '<span class="chip k-'+k+'">'+kindName(k)+(n>1?'×'+n:'')+'</span>').join('');
  const codesHtml = (g.codes||[]).slice(0,4).map(c=>
    '<span class="code">'+esc(c)+'</span>').join('')
    + ((g.codes||[]).length>4?'<span class="faint">+'+(g.codes.length-4)+'</span>':'');
  const linkedHtml = (g.linked_codes||[]).slice(0,3).map(c=>
    '<span class="linked">已关联 '+esc(c)+'</span>').join('');
  const t1 = g.taken_from, t2 = g.taken_to;
  const f1 = t1? fmtTaken(t1) : '', f2 = t2? fmtTaken(t2) : '';
  // 跨多久 = 这一组连拍了多长时间（组就是按时间聚的，跨度是它的直接体现）
  const span = (t1 && t2) ? fmtGap(diffSec(t1, t2)).replace(/^\+/, '') : '';
  const timeRange = (f1 && f2) ? (f1===f2 ? f1 : f1+' ~ '+f2+(span? '（跨 '+span+'）' : ''))
                                : (f1||f2);
  // 组内照片（展开后显示）—— 复用 shotCard，但点击要阻止冒泡避免收起组
  const shotsHtml = g.photos.map((p,i)=>
    shotCard(p, null, null, i? g.photos[i-1].taken_at : null)).join('');
  return '<div class="gcard" data-key="'+esc(g.key)+'">'+
    '<div class="ghead">'+
      '<img class="gcover" loading="lazy" src="'+g.cover_thumb+'" alt="">'+
      '<div class="ginfo">'+
        '<div class="gtitle"><span class="gcount">'+g.count+' 张</span>'+
          '<span class="gtime">'+esc(timeRange)+'</span></div>'+
        '<div class="gsum">'+kindsHtml+codesHtml+linkedHtml+'</div>'+
      '</div>'+
      '<span class="garrow">›</span>'+
    '</div>'+
    '<div class="gbody"><div class="gshots">'+shotsHtml+'</div></div>'+
  '</div>';
}

async function loadGroups(reset){
  const seq = ++_loadSeq;
  if(reset) fPage = 1;
  const qs = new URLSearchParams({
    state:$('#fState').value, kind:_kindQs(),
    batch:$('#fBatch').value, usage:_usageQs(),
    invalid:$('#fInvalid').value,
    unlinked:$('#fUnlinked').checked?1:0,
    todo:(($('#fCand') && $('#fCand').value) || ''),
    q:$('#fQ').value.trim(),
    container_id:(($('#fContainer') && $('#fContainer').value) || ''),
    sort:_sortVal(),
    limit:GROUP_SIZE, offset:(fPage-1)*GROUP_SIZE});
  const d = await api('/api/photos/groups?'+qs);
  if(seq !== _loadSeq) return;    // 已有更新的请求，这份旧响应丢弃
  $('#fTotal').textContent = '共 '+d.total+' 组';
  const box = $('#shots');
  box.innerHTML = d.items.map(groupCard).join('');   // 页码分页：替换不累积
  $('#shotsEmpty').style.display = d.total? 'none':'block';
  renderPagerInto('#moreBtn', d.total, ()=>loadGroups(false), GROUP_SIZE);
  // 组卡片点击展开/收起；组内照片点击走 openDrawer（阻止冒泡）
  $$('#shots .gcard').forEach(card=>{
    card.onclick = e=>{
      // 点到照片卡 → 不收起组
      if(e.target.closest('.shot')) return;
      card.classList.toggle('open');
      if(card.classList.contains('open')) bindShots('#shots');
    };
  });
  bindShots('#shots');
}

/* ── 五档分组选项卡（10-07 老板第二轮：待确认关联 / 新产品确认 也要能分组看）──
   五档：全部 / 已关联 / 待关联 / 待确认关联 / 新产品确认。

   为什么改成选项卡而不是上下两段：
     ① 五个集合**互相重叠**（待确认、新产品都是「待关联」的子集，一张照片
        可以同时属于三档），上下分段必须两两互斥 —— 做不到就只能重复渲染照片；
     ② 分段会把照片区竖向撑开，而照片区正是要留大的那块（第一轮反馈）。

   ⚠️ 每档的徽章数字取自后端 COUNT（/api/photos/linkstate），**不是已取到的条数** ——
   「还没查完」不许渲染成「共 N 张」的结论态（铁律 17）。
  ⚠️ 「待确认关联」「新产品确认」都是**待关联**的子集，所以它们的和 ≤ 待关联，
  加起来不等于「全部」是正常的。
  🔴 2026-10-17 老板规则（重要）：「只有产品需要关联」—— 只有产品图片
  （0201 有编码 / 0202 无编码）进待关联；包装/清单/其他预检/场景/未识别
  一律不进（后端白名单 LINKABLE_KINDS，与徽章/列表/工作台同源）。 */
export const PHOTO_TABS = [
  {key: '',        label: '全部'},
  {key: 'linked',  label: '已关联'},
  {key: 'unlinked',label: '待关联',
   hint: '产品图片（有编码/无编码）还没关联到任何产品；包装/清单/场景等非产品照不进此列'},
  {key: 'ignored', label: '已忽略',
   hint: '本次忽略的照片 —— 新产品暂不入库、退出关联队列；可在这里恢复，或等后续柜清单导入自动关联'},
  {key: 'invalid', label: '无效图片',
   hint: '已标记无效的照片 —— 默认退出各工作队列，可在这里查看与撤销'},
];
const LK_PAGE = 60;
/* 柜作业③专用四档（2026-10-15 需求5）：全部/已关联/待关联/无效图片。
   待确认关联/新产品确认的工作台在审核页与照片库页仍保留 —— ③的口径是
   「这柜的照片都在什么状态」，无效档是清单/包装清理与重复图确认的落脚点。 */
export const PHOTO_TABS_WIZ = [
  {key: '',        label: '全部'},
  {key: 'linked',  label: '已关联'},
  {key: 'unlinked',label: '待关联',
   hint: '产品图片（有编码/无编码）还没关联到任何产品；包装/清单/场景等非产品照不进此列'},
  {key: 'ignored', label: '已忽略',
   hint: '本次忽略的照片 —— 新产品暂不入库、退出关联队列；可在这里恢复'},
  {key: 'invalid', label: '无效图片',
   hint: '已标记无效的照片 —— 默认退出各工作队列，可在这里查看与撤销'},
];
export function tabsInit(){
  return {tab: '', off: 0, html: '', n: 0, total: 0, counts: null};
}
function tabBarHtml(active, counts, tabs){
  return (tabs || PHOTO_TABS).map(t=>{
    const k = t.key || 'all';
    const n = counts ? counts[k] : null;
    return '<button data-ptab="'+t.key+'" title="'+esc(t.hint || (t.label+'（本筛选范围内）'))+'"'+
      (t.key===active?' class="on"':'')+'>'+esc(t.label)+
      (n == null ? '<span class="n" data-zero="1">—</span>'
                 : ' <span class="n"'+(n?'':' data-zero="1"')+'>'+n+'</span>')+
      '</button>';
  }).join('');
}

/** 五档选项卡通用实现（照片页与向导③共用一份）。
 *  [o] {bar:选项卡容器选择器, box:照片网格选择器, more:加载更多按钮选择器,
 *       st:状态对象, baseQs:公共筛选, reset:是否重建, onCounts:计数回调}
 *  换柜 / 改筛选 → reset:true（徽章与列表一起重算，不留旧数字）。 */
/** 一屏能放几张（视口自适应）：列数 × 行数。
 *  卡片高度从真实 DOM 量（主题/缩放下 CSS 常量会漂），量不到用 170 估。 */
function measureSize(box){
  if(!box || !box.clientWidth) return 0;
  const gap = 10;                                   // 与 .shots 的 gap 一致
  const card = box.querySelector('.shot, .gcard');
  const cardH = card ? card.getBoundingClientRect().height : 221;
  if(!cardH) return 0;
  // 可用高度 = 视口 - 网格顶边 - 底部预留。
  // 🔴 预留必须给足：实测网格顶边在布局稳定后会从 376 漂到 413，而页码行
  //    占 38px —— 按「刚好卡住」算会在渲染完成后溢出 20 多 px 出滚动条。
  //    120 = 页码行 38 + 上方漂移 37 + 余量，宁可少放一行也不让页面能滚。
  // 底部预留：只留页码行（24）+ margin（14）+ 余量（6）≈ 44，尽量铺满。
  // ⚠️ 别再按容器分档：顶部压缩后柜作业③与照片库的可用高度已经同一量级，
  //    分档会让③少一行（实测 120 → 3 行 15 张，44 → 4 行 20 张铺满）。
  const reserve = 44;
  const availH = Math.max(120, window.innerHeight - box.getBoundingClientRect().top - reserve);
  // 列数按网格的最小列宽（CSS minmax 下限）算 —— 不能用卡片实际宽度反推：
  // 卡片被 1fr 拉伸，列越少卡片越宽，反推会越算越少。
  // 柜作业③ `.wshots .grid` 改成了 minmax(190px)（2026-10-20 效果图：5 列规整方卡）；
  // 照片库 `.shot-grid` 仍是 minmax(150px)。
  const minCardW = (box.id === 'wizShots') ? 190 : 150;
  const cols = Math.max(1, Math.floor((box.clientWidth + gap) / (minCardW + gap)));
  const rows = Math.max(1, Math.floor((availH + gap) / (cardH + gap)));
  return cols * rows;
}

/** 页码控件 HTML（2026-10-20 老板：不要「加载更多」，普通翻页，一屏一页）。
 *  st.page 1 起，st.size 每页张数，st.total 总张数。 */
function pagerHtml(st){
  const total = st.total || 0, size = st.size || 60;
  const pages = Math.max(1, Math.ceil(total / size));
  if(pages <= 1) return '<span class="faint">共 '+total+' 张</span>';
  const cur = Math.min(Math.max(1, st.page || 1), pages);
  // 页码窗口：当前页尽量居中，最多 7 个，两端出省略号
  let lo = Math.max(1, cur - 3), hi = Math.min(pages, lo + 6);
  lo = Math.max(1, hi - 6);
  const pgBtn = (n, on)=>'<button class="pgb'+(on?' on':'')+'" data-pg="'+n+'">'+n+'</button>';
  let h = '<span class="faint">共 '+total+' 张</span>'+
    '<button class="pgb'+(cur<=1?' off':'')+'" data-pg="'+(cur-1)+'"'
      +(cur<=1?' disabled':'')+'>上一页</button>';
  if(lo > 1) h += pgBtn(1) + (lo > 2 ? '<span class="faint">…</span>' : '');
  for(let i=lo;i<=hi;i++) h += pgBtn(i, i === cur);
  if(hi < pages) h += (hi < pages-1 ? '<span class="faint">…</span>' : '') + pgBtn(pages);
  h += '<button class="pgb'+(cur>=pages?' off':'')+'" data-pg="'+(cur+1)+'"'
      +(cur>=pages?' disabled':'')+'>下一页</button>';
  return h;
}

/** 网格一行有几列（与 measureSize 同一套宽度口径）。 */
function measureCols(box){
  if(!box || !box.clientWidth) return 1;
  return Math.max(1, Math.floor((box.clientWidth + 10) / 160));
}

/** 把页码控件画进容器（照片库三个视图共用一份实现）。
 *  [size] 每页条数，不传就用 fSize。onGo() 由调用方重新加载当前页。 */
function renderPagerInto(sel, total, onGo, size){
  const mb = $(sel);
  if(!mb) return;
  const sz = size || fSize || 24;
  try{
    mb.style.display = '';
    mb.innerHTML = pagerHtml({page: fPage, size: sz, total: total});
  }catch(e){
    // async 里的异常是静默的（rejected promise 不触发 exceptionThrown），
    // 这里必须自己喊出来，否则分页会"莫名其妙不渲染"
    console.error('[pager] 渲染失败', e, {size: sz, total: total, page: fPage});
    return;
  }
  $$('[data-pg]', mb).forEach(b=>{
    b.onclick = ()=>{
      const p = parseInt(b.dataset.pg, 10);
      if(!p || p === fPage) return;
      fPage = p;
      onGo();
      // 翻页后回顶：否则新一页从中间开始，看着像没换
      try{ $('#shots').scrollIntoView({block:'start'}); }catch(e){}
    };
  });
}

export async function loadPhotoTabs(o){
  const box = $(o.box);
  if(!box) return;
  const st = o.st;
  // 同一状态对象内的请求序列守卫（原理同 _loadSeq，但五档选项卡被照片页与
  // 向导③各持一份 st，必须按 st 分开计数，不能共用模块级变量）。
  st._seq = (st._seq || 0) + 1;
  const seq = st._seq;
  // 首次调用或 reset（换柜 / 改筛选）→ 回第 1 页重建；翻页 reset=false → 只换页。
  // ⚠️ 页码分页（2026-10-20）：不再累积 HTML，每次只渲染当前页。
  if(o.reset || st._inited !== true){
    st.page = 1; st.html = ''; st.n = 0; st.total = 0; st._inited = true;
  }
  // 每页张数：首次量视口；量不到（首屏还没卡片）用 60 兜底，取回后再校准。
  if(!st.size) st.size = measureSize(box) || 60;
  // ① 徽章：**不阻塞网格**（2026-10-17：linkstate 冷算要扫全库候选，
  //    曾让首屏白等 4 秒才看到照片）。先渲染「—」，计数回来只重排选项卡。
  try{
    // ⚠️ 把**当前筛选上下文整体**带给 linkstate（2026-10-14）：树选了
    //    用途/分类后徽章与「共 N 张」必须跟着收窄，只传柜/批就是数字撒谎。
    const bq = o.baseQs || {};
    const q = new URLSearchParams({
      container_id: bq.container_id || '', batch: bq.batch || '',
      state: bq.state || '', kind: bq.kind || '', usage: bq.usage || '',
      q: bq.q || '', unlinked: bq.unlinked || 0,
      invalid: bq.invalid || 'hide', pending: bq.pending || 0,
      todo: bq.todo || ''});
    st.counts = null;
    renderTabBar(o);
    var pCounts = api('/api/photos/linkstate?' + q).then(d => {
      if(seq !== st._seq) return null;    // 已有更新的请求，旧响应丢弃
      st.counts = d;
      renderTabBar(o);
      return d;
    }).catch(() => null);
  }catch(e){ st.counts = null; var pCounts = Promise.resolve(null); }
  // ② 当前档的照片（与徽章并行，不等它）
  //    页码分页：只取当前页 —— offset 由页码算，不再累加。
  const qs = new URLSearchParams(Object.assign({}, o.baseQs,
    {flag: st.tab, mark: 1, limit: st.size, offset: (st.page - 1) * st.size}));
  // 无效图片档：把「排除无效」翻成「只看无效」—— 列表与徽章同一口径
  if(st.tab === 'invalid') qs.set('invalid', 'only');
  // 已忽略档（2026-10-18）：同款三态翻转
  if(st.tab === 'ignored') qs.set('ignored', 'only');
  if(o.reset) box.innerHTML = '<span class="faint">读取中…</span>';
  let d;
  try{ d = await api('/api/photos?' + qs); }
  catch(e){ if(seq !== st._seq) return;
    box.innerHTML = '<span class="faint">读取失败：'+esc(e.message)+'</span>';
            if(o.onCounts) o.onCounts(st.counts, st); return; }
  if(seq !== st._seq) return;   // 已有更新的请求，这份旧响应丢弃
  const items = d.items || [];
  st.html = items.map(p=>shotCard(p)).join('');   // 页码分页：替换，不累积
  st.n = items.length;
  st.total = d.total || 0;
  // 末页越界（照片被删/标无效后末页空了）→ 退到最后一页，别让用户停在空白
  const maxPage = Math.max(1, Math.ceil(st.total / st.size));
  if(st.page > maxPage){
    st.page = maxPage;
    return loadPhotoTabs(Object.assign({}, o, {reset:false}));
  }
  // 列表已成功（走到这里就是取到了）→ 空就是空，
  // 别再拿「徽章还没回」显示「读取中…」（2026-10-17 徽章异步化）
  box.innerHTML = st.html || '<span class="faint">这一档没有照片</span>';
  bindShots(o.box);
  applyFlagBadges(o.box);
  renderPager(o, st);
  // 🔴 首屏校准：第一次量的时候布局还没稳（顶栏/工具条/选项卡刚渲染完，
  //    gridTop 会从 440 一路漂到 303），算出来偏少就只铺两行。
  //    渲染完按**稳定后的布局**再量一次，更多就重取这一页（只在变多时，避免抖动）。
  // 🔴 必须**双向**校准（n !== st.size 就重取）：只在"变多时重取"的话，
  //    首次量不到（容器还没布局）落到兜底 60 就再也不会被修正 —— 实测一页
  //    塞 60 张、靠容器内部滚动，docSh 看着没超其实要滚很久。
  if((st._fit || 0) < 3){
    st._fit = (st._fit || 0) + 1;
    const n = measureSize(box);
    if(n > 0 && n !== st.size){
      st.size = n;
      st.page = 1;
      return loadPhotoTabs(o);
    }
  }
  // 徽章可能还没回（冷算兜底）—— 等它到了再报计数，「共 N 张」不撒谎；
  // seq 不匹配说明已有更新的请求，这份旧响应连计数都不许覆盖。
  const counts = await pCounts;
  if(seq !== st._seq) return;
  st.counts = counts;
  renderTabBar(o);
  // ⚠️ onCounts 放在**最后**：它要报「已显示 n / total 张」，n 与 total 得是
  //    当前档的真实值。放在取照片之前会永远显示「已显示 0 / 0 张」。
  if(o.onCounts) o.onCounts(st.counts, st);
}
/** 把页码控件画进 o.more 容器（复用原「加载更多」按钮的位置）。 */
function renderPager(o, st){
  const mb = o.more ? $(o.more) : null;
  if(!mb) return;
  // ⚠️ 必须包 try：调用方是 async 函数，这里抛错会变成 rejected promise，
  //    CDP 的 Runtime.exceptionThrown 抓不到（表现就是「页码莫名其妙不渲染」）。
  try{
    mb.style.display = '';
    mb.innerHTML = pagerHtml(st);
  }catch(e){
    window.__pgErr = String(e);
    console.error('[pager] 渲染失败', e, {size: st.size, total: st.total, page: st.page});
    return;
  }
  $$('[data-pg]', mb).forEach(b=>{
    b.onclick = ()=>{
      const p = parseInt(b.dataset.pg, 10);
      if(!p || p === st.page) return;
      st.page = p;
      loadPhotoTabs(Object.assign({}, o, {reset:false}));
      // 翻页后回顶：否则新一页从中间开始，看着像没换
      try{ const bx = $(o.box); if(bx) bx.scrollIntoView({block:'start'}); }catch(e){}
    };
  });
}

function renderTabBar(o){
  const bar = o.bar ? $(o.bar) : null;
  if(!bar) return;
  bar.innerHTML = tabBarHtml(o.st.tab, o.st.counts, o.tabs);
  $$('[data-ptab]', bar).forEach(b=>b.onclick=()=>{
    const k = b.dataset.ptab;
    if(o.st.tab === k) return;
    // ⚠️ total 也要清：它存的是**上一档**的总数，不清就会在切档瞬间
    //    让「已显示 n / total 张」报出上一档的数字。
    o.st.tab = k; o.st.page = 1; o.st.html = ''; o.st.n = 0; o.st.total = 0;
    loadPhotoTabs(Object.assign({}, o, {reset:false}));
  });
}

let _tabs = tabsInit();
/* 五档视图的公共筛选参数（换柜/改筛选/刷新都从这取，别各写一份）。 */
function _tabBaseQs(){
  return {
    state:$('#fState').value, kind:_kindQs(),
    batch:$('#fBatch').value, usage:_usageQs(),
    invalid:$('#fInvalid').value,
    unlinked:$('#fUnlinked').checked?1:0,
    todo:(($('#fCand') && $('#fCand').value) || ''),
    q:$('#fQ').value.trim(),
    container_id:(($('#fContainer') && $('#fContainer').value) || ''),
    sort:_sortVal()};
}
function loadTabView(reset){
  return loadPhotoTabs({
    bar: '#shotTabs', box: '#shots', more: '#moreBtn',
    st: _tabs, baseQs: _tabBaseQs(), reset: reset,
    onCounts: (c)=>{
      const t = $('#fTotal');
      if(t && c) t.textContent = '共 '+c.all+' 张';
      const se = $('#shotsEmpty');
      if(se) se.style.display = (c && c.all) ? 'none' : 'block';
    }});
}

/* 统一加载入口：按当前视图分发。
   🔴 必须 return 各视图的 Promise：调用方 `await loadCurrent(true)` 要等
   加载真正完成（如 photos:changed 监听器要在渲染完再补翻页、还原滚动）。
   fire-and-forget 会让 await 下一个微任务就返回 —— refill 循环读到清零
   中的 st，条件不成立直接跳过，用户看到列表缩回首屏（2026-10-14 实测）。 */
function loadCurrent(reset){
  if(_curView==='link') return loadTabView(reset);
  else if(_curView==='group') return loadGroups(reset);
  else return loadShots(reset);
}

$('#fSearch').onclick = ()=>loadCurrent(true);
// ⚠️ 不再给 #moreBtn 绑「加载更多」：它是页码容器，onclick 由 renderPagerInto
//    逐页重新绑（旧那句 fOffset += 60 在页码分页下会把页码和偏移彻底走散）。

/* 网格视图：紧凑 / 详情 / 分组 —— 选择记在本地 */
// 关联视图（link）里 #shots 装的是两段（每段自带 .grid），容器本身不能是网格
const _VIEWS = ['compact', 'full', 'group', 'link'];
function _normView(v){ return _VIEWS.indexOf(v) >= 0 ? v : 'full'; }
function _applyViewClass(v){
  document.body.classList.toggle('v-compact', v==='compact');
  const box = $('#shots');
  // ⚠️ link 视图**也要** grid：选项卡只切内容、不套额外容器，卡片直接躺在
  //    #shots 里（上一版是两段各带一个内层 .grid）。少了这个 class 卡片会
  //    退化成块级单列大图 —— 照片区一下变成「一条一条」，正是要避免的。
  box.classList.toggle('grid', v!=='group');
  box.classList.toggle('glist', v==='group');
  const tabs = $('#shotTabs');
  if(tabs) tabs.style.display = (v==='link') ? '' : 'none';
}
function setShotView(v){
  v = _normView(v);
  _curView = v;
  _applyViewClass(v);
  $$('#shotView button').forEach(b=>b.classList.toggle('on', b.dataset.v===v));
  try{ localStorage.setItem('shotView', v); }catch(e){}
  fPage = 1; fSize = 0; _fitTries = 0; _sized = false;   // 切视图重算「一屏几张」，页码回第 1 页
  loadCurrent(true);
}
$$('#shotView button').forEach(b=>b.onclick=()=>setShotView(b.dataset.v));
try{ _curView = _normView(localStorage.getItem('shotView')); }
catch(e){ _curView='full'; }
// 初始化时不触发 load（onTab 会触发），只设 UI 状态
(function initView(){
  _applyViewClass(_curView);
  $$('#shotView button').forEach(b=>b.classList.toggle('on', b.dataset.v===_curView));
})();
/* ── 左侧树形筛选：先用途后分类（2026-10-14 老板需求）──
   树是「看见全集 + 快速点」的入口，筛选状态的真源仍是工具栏下拉
   （loadShots/loadGroups/loadTabView 都读它们）—— 不另养一份筛选逻辑，
   点点树 = 改下拉的值 + 重载。计数走 /api/photos/facets，与列表同源。 */
// 左侧树多选集合（2026-10-19 老板需求「按分类支持多选」）——
// 树是新的筛选真源之一：查询参数优先取树的集合（逗号分隔 → 后端 IN），
// 空时回退工具栏下拉（单选快捷）。下拉 onchange 会清空对应树集合
// （下拉是单选语义，选了就覆盖多选）。
const _treeVal = {usages:[], kinds:[], pending:false};
function _treeCtx(){
  return {
    container_id: ($('#fContainer') && $('#fContainer').value) || '',
    batch: $('#fBatch').value, state: $('#fState').value,
    q: $('#fQ').value.trim(), unlinked: $('#fUnlinked').checked ? 1 : 0,
    invalid: $('#fInvalid').value,
    todo:(($('#fCand') && $('#fCand').value) || '')};
}
/** kind/usage 查询值：树多选集合优先，空则回退下拉单选。 */
function _kindQs(){ return _treeVal.kinds.length ? _treeVal.kinds.join(',') : $('#fKind').value; }
function _usageQs(){ return _treeVal.usages.length ? _treeVal.usages.join(',') : $('#fUsage').value; }
function refreshPhotoTree(){
  return loadPhotoTree({
    bar:'#phTree', ctx:_treeCtx, value:_treeVal, showPending:false,
    onChange:(v)=>{
      _treeVal.usages = v.usages || [];
      _treeVal.kinds = v.kinds || [];
      _treeVal.pending = v.pending;
      loadCurrent(true);
      refreshPhotoTree();     // 交叉筛选：另一维的计数跟着收窄
    }});
}

$('#fState').onchange = $('#fKind').onchange = $('#fUsage').onchange = $('#fUnlinked').onchange
                      = $('#fBatch').onchange = $('#fInvalid').onchange = $('#fCand').onchange = ()=>{
  // 下拉是单选语义：选了它，树的多选集合作废（避免两个真源打架）
  if(this && this.id === 'fKind') _treeVal.kinds = [];
  if(this && this.id === 'fUsage') _treeVal.usages = [];
  loadCurrent(true); refreshPhotoTree();
};
// 排序（2026-10-19 老板需求「显示当前排序规则，增加更多排序方式」）：
//   下拉切换即重载；当前规则常显在工具栏右侧（fSortNote）。
const _SORT_LABELS = {time:'按拍摄时间', code:'按编码', state:'按治理状态'};
function _sortVal(){ const e = $('#fSort'); return (e && e.value) || 'time'; }
function _showSortNote(){
  const n = $('#fSortNote');
  if(n) n.textContent = '排序：' + (_SORT_LABELS[_sortVal()] || '按拍摄时间');
}
if($('#fSort')){
  $('#fSort').onchange = ()=>{ _showSortNote(); loadCurrent(true); };
  _showSortNote();
}

/* ② 关联确认后自动刷新（2026-10-13 老板反馈）：
   抽屉里确认关联 / 解除关联后广播 photos:changed —— 这里重拉当前视图，
   五档徽章与列表同源（photo_where_sql 一份 WHERE），数字自动一致。
   ⚠️ 不能让 photos.js 反过来 import drawer.js（已是 drawer→photos 单向）。

   2026-10-14 老板追加：刷新必须**保持用户当前位置** ——
   ① 不弹回顶部：整体重渲染后 scrollY 归零，先记后还；
   ② 不缩回第一页：reset 会把 offset 清 0，「加载更多」翻过的页数要补回来
      （待确认档关联掉一张后总数会变，补到原来的页数或没有更多为止）。
   ⚠️ 只在照片库页可见时才刷：在柜作业③里关联时那边自己会刷，这里再拉一轮
      全库列表纯属浪费（还可能跟③的请求抢 GIL）。 */
window.addEventListener('photos:changed', async ()=>{
  const pg = $('#tab-batches');
  if(pg && !pg.classList.contains('on')) return;
  const y = window.scrollY;
  // 🔴 页码分页（2026-10-20 需求10）：只重载**当前页**，页码不动。
  //    原来记 fOffset 再 while 循环反复追加回原偏移 —— 那是「加载更多」时代的
  //    写法，页码分页下会请求几十次，还把页码走散、跳回第 1 页。
  await loadCurrent(false);        // reset=false：不重置 fPage
  window.scrollTo(0, y);
  refreshPhotoTree();      // 标记无效/关联会动用途分类计数，树跟着刷新
});

async function loadKinds(){
  const d = await api('/api/fields');
  const sel = $('#fKind');
  if(sel.options.length<=1){
    for(const k in d.kinds) sel.add(new Option(k+' — '+d.kinds[k], k));
    // 未识别（NULL）：树上点「未分类」时真源下拉必须有这个值，
    // 否则筛选丢失、列表跟树对不上（2026-10-15）
    sel.add(new Option('_unset — 未分类（未识别）', '_unset'));
  }
}

/* ── 导入照片（统一模态 —— 资产页按钮与向导③共用同一份实现）──
   一个入口搞定两种格式：填目录走 /import-auto（自动探测标准采集格式），
   或直接多选文件上传。柜**只读展示**（取自全局锚点），无柜不导 ——
   顺序仍然是「先柜后目录」（柜是流程第一步）。 */
export function openImportPhotosModal(cid){
  const useCid = cid || getCid();
  openModal({
    title: '导入照片',
    width: 580,
    bodyHtml:
      '<p class="faint">将导入到<b>当前所选柜</b>（在「柜作业」右上角切换柜）。'+
      '支持标准采集格式 <code>.../预检/{箱号}/照片.jpg</code>；'+
      '<b>柜号以这里选的柜为准</b>，目录名不影响归属，程序不会自动建柜。</p>'+
      '<label>目录（大批量用这个）</label>'+
      '<div class="row" style="flex-wrap:nowrap">'+
        '<input type="text" id="phFolder" placeholder="本机照片目录，如 D:/预检图片" style="flex:1">'+
        '<button class="btn ghost sm" id="phPickDir">选择目录</button>'+
      '</div>'+
      '<label>或直接上传文件（可多选）</label>'+
      '<input type="file" id="phFiles" multiple accept="image/*">',
    okText: '导入',
    onOk: async (vals, el)=>{
      if(!useCid) return '请先选择柜（到「柜」页进一个柜作业，或在本页的柜选择器里选）';
      const folderEl = el.querySelector('#phFolder');
      const folder = (folderEl && folderEl.value ? folderEl.value.trim() : '');
      const files = el.querySelector('#phFiles').files;
      if(!folder && (!files || !files.length)) return '请填目录，或选择要上传的文件';
      busy(true, '正在导入照片…', folder || (files.length + ' 个文件'));
      try{
        if(folder){
          const r = await post('/api/photos/import-auto', {folder, container_id: useCid});
          busy(false);
          // 成功/失败的结果必须说清楚（含「目录名与柜号不一致」的点名）
          if(r.mode === 'standard'){
            const where = r.container_no ? ('已挂到柜【' + r.container_no + '】') : '';
            const mis = (r.dir_mismatch || []).length
              ? ('。注意：照片目录名 ' + r.dir_mismatch.join('、') +
                 ' 与所选柜号不同，柜号以你选的那个为准') : '';
            toast('标准采集格式：新增 ' + r.added + ' 张，跳过 ' + r.skipped + '。' + where + mis, 'ok');
          }else if(r.all_duplicate){
            toast('全部 ' + r.skipped + ' 张照片均已存在，未创建新批次', 'warn');
          }else{
            toast('导入完成：新增 ' + r.added + ' 张，重复跳过 ' + r.skipped, 'ok');
          }
        }else{
          const fd = new FormData();
          for(const f of files) fd.append('files', f);
          fd.append('container_id', useCid);
          const r = await api('/api/photos/upload', {method:'POST', body: fd});
          busy(false);
          toast('上传完成：落盘 ' + r.saved + '，新增 ' + r.added + '，重复跳过 ' + r.skipped, 'ok');
        }
        loadStats(); loadCurrent(true);
        window.dispatchEvent(new Event('wizard:refresh'));
        return true;
      }catch(e){ busy(false); return '导入失败：' + e.message; }
    }
  });
  // 目录选择器要挂在**刚建好的**模态里（attachDirPicker 要求元素已在 DOM 中）
  if($('#phFolder')) attachDirPicker('phFolder', 'phPickDir');
}
$('#fImport').onclick = ()=>openImportPhotosModal();

/* 顶部说明折叠（2026-10-21 老板布局调整：标题行整块删了，说明按钮一并移除；
   保留绑定加 null 保护，避免 DOM 不存在时报错）。 */
if($('#fIntroToggle')) $('#fIntroToggle').onclick = ()=>{
  const box = $('#fIntro'), btn = $('#fIntroToggle');
  const open = box.style.display !== 'none';
  box.style.display = open? 'none' : '';
  btn.textContent = open? '说明 ▾' : '收起 ▴';
  btn.setAttribute('aria-expanded', open? 'false' : 'true');
};

/* ── 按柜筛选（P5 资产化）：照片是资产，要能以柜为主视角翻 ──
   ⚠️ 这是**筛选**，不是锚点 —— 不参与 setCid 广播（锚点只有一个）。 */
async function loadContainerFilter(){
  const sel = $('#fContainer');
  if(!sel) return;
  let items = [];
  try{ items = (await api('/api/containers')).items || []; }catch(e){ return; }
  const cur = sel.value;
  sel.innerHTML = '<option value="">全部柜</option>' +
    items.filter(c=>c.container_no !== '_UNCATEGORIZED')
      .map(c=>'<option value="'+esc(c.id)+'">'+esc(c.container_no)+'</option>').join('');
  if(cur && [].some.call(sel.options, o=>o.value === cur)) sel.value = cur;
}
$('#fContainer').onchange = ()=>loadCurrent(true);
// 「只看当前柜」按钮已删（2026-10-11）：顶部全局选择器没了，按钮失去意义。

// ⚠️ loadPhotoTabs / tabsInit / PHOTO_TABS 在定义处就 `export` 了，别再往这里列 ——
//    列一次是 Duplicate export（node --check 直接报错，浏览器整模块挂掉）。
export { busy, setShotView, shotCard, loadShots, loadGroups, loadCurrent,
         loadKinds, bindShots, resetViewer, pagerHtml };

onTab('batches', loadKinds);
onTab('batches', loadContainerFilter);
onTab('batches', ()=>loadCurrent(true));
onTab('batches', refreshPhotoTree);   // 左侧树（用途/分类计数）随页面加载
// 注意：loadBatches 的 onTab 注册在 batches.js 自己身上（此处若再注册会重复拉取，
// 且会形成 batches <-> photos 的循环依赖）
