// core.js —— 由 index.html 内联脚本拆分而来，逻辑未改
// 分类文案（2026-10-17 老板分类表：预检段 0201–0205）。
// ⚠️ 键序 = 0201→0205 编号序（下拉按 Object.keys 顺序枚举）；UI 文案**不带编号**
//   （老板原话：编号只是为了显示顺序）。scene 是监装照在 photo_kind 上的占位
//   （细分在监装下拉，见 drawer.js SUPTAGS），编号体系外，收尾。
const KIND_LABELS = {label:'产品·有编码', product:'产品·无编码',
                     packaging:'包装', packing_list:'清单',
                     unknown:'其他预检', scene:'场景（监装照）'};
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));

function toast(msg, kind){
  const d = document.createElement('div');
  d.textContent = msg;
  if(kind) d.className = kind;
  $('#toast').appendChild(d);
  setTimeout(()=>d.remove(), kind==='err'?6000:3200);
}
async function api(path, opt){
  const r = await fetch(path, opt);
  const t = await r.text();
  let j; try{ j = JSON.parse(t); }catch(e){ j = {detail:t}; }
  if(!r.ok){ throw new Error(j.detail || ('HTTP '+r.status)); }
  return j;
}
const post   = (p,b) => api(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});
const patch  = (p,b) => api(p,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});

/* 统一空态：图标 + 一句话 + 下一步动作按钮（避免各处灰字风格不一） */
function emptyHtml(icon, title, sub, actionHtml, cls){
  return '<div class="empty'+(cls? ' '+cls : '')+'"><div class="ec">'+icon+'</div>'
    + '<div class="et">'+esc(title)+'</div>'
    + (sub? '<div class="es">'+esc(sub)+'</div>' : '')
    + (actionHtml? '<div class="eb">'+actionHtml+'</div>' : '')
    + '</div>';
}
const del    = (p,b) => api(p,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});
const esc    = s => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* ── 拍照时间：一处格式化，全站图片卡片共用（10-05 老板要求「同组连拍照片上显示
   拍照时间，其他地方只要展示图片的地方都要显示」）。
   两条口径（别各写一份，slice(0,16) 那种到分钟就收工的写法必须全站清掉）：
     1) **必须到秒** —— 现场连拍常常 0~2 秒一张，只到分钟等于没显示；
     2) 缺时间显示「时间未知」而不是留空 —— 留空会被读成"没这信息"，
        看的人会怀疑数据丢了。 */
export function fmtTaken(taken, opt){
  const o = opt || {};
  const s = String(taken==null?'':taken).trim();
  if(!s) return o.blank || '时间未知';
  const m = s.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
  if(!m) return s.replace('T', ' ');
  const d = m[1]+'-'+m[2]+'-'+m[3], t = m[4]+':'+m[5]+':'+(m[6]||'00');
  if(o.date)   return d;
  if(o.full)   return d+' '+t;
  if(o.clock)  return t;            // 同一屏里日期已经写在别处时用
  return m[2]+'-'+m[3]+' '+t;
}
/* 相邻两张的间隔（秒）—— 同组连拍最该看的一个数：3 秒 = 真的连拍，
   2 分钟 = 其实停过一次。返回 '' 表示算不出（缺时间）。 */
export function fmtGap(sec){
  if(sec==null || !isFinite(sec)) return '';
  const s = Math.max(0, Math.round(sec));
  if(s < 60) return '+'+s+'s';
  const m = Math.floor(s/60);
  if(m < 60)    return '+'+m+'m'+(s%60? (s%60)+'s' : '');
  const h = Math.floor(m/60);
  return '+'+h+'h'+(m%60? (m%60)+'m' : '');
}
/* 时长（秒）→ 人话。作业耗时用：跨天出「2天3小时」，不到 1 分钟出秒。
   与 fmtGap 的分工：fmtGap 是「相邻两张的间隔」带 + 号，fmtDur 是
   「一整段作业的时长」不带号。 */
export function fmtDur(sec){
  if(sec==null || !isFinite(sec)) return '';
  const s = Math.max(0, Math.round(sec));
  if(s < 60) return s+'秒';
  const m = Math.floor(s/60);
  if(m < 60)    return m+'分'+(s%60? (s%60)+'秒' : '');
  const h = Math.floor(m/60);
  if(h < 24)    return h+'小时'+(m%60? (m%60)+'分' : '');
  const d = Math.floor(h/24);
  return d+'天'+(h%24? (h%24)+'小时' : '');
}
/* 柜作业时长（后端 work 汇总）→ 起止区间，如「09-15 20:40 ~ 09-29 19:24」。
   两端共用同一份口径，别在页面里各写一遍。 */
export function workRange(w){
  if(!w || !w.from || !w.to) return '';
  // 🔴 跨年必须带年份：只显示 MM-DD 会把「2021-08-31 → 2026-10-13」读成
  //    同一年的 8 月到 10 月（真实库那柜跨 5 年，验收时才发现）。
  const y1 = String(w.from).slice(0,4), y2 = String(w.to).slice(0,4);
  const o = (y1 !== y2) ? {date:true} : null;
  return fmtTaken(w.from, o)+' ~ '+fmtTaken(w.to, o);
}
/* 柜作业时长（后端 work 汇总）→ 时长文案。
   🔴 零散数据（后端 scattered：含跨度异常的段）只给段数不给时长 ——
      「历史图片」那种兜底柜能算出 44855 小时，宁可少说也不能把数据
      问题说成作业强度。 */
export function workDur(w){
  if(!w) return '';
  if(w.scattered) return w.segments+' 段（数据零散，不计时长）';
  const d = fmtDur(w.active_sec);
  return d ? '净作业 '+d : '时长未知';
}
/* 两个 ISO 串之间的秒差（任一为空 → NaN，交给调用方决定显示什么） */
export function diffSec(a, b){
  const ta = Date.parse(String(a||'').replace(' ', 'T'));
  const tb = Date.parse(String(b||'').replace(' ', 'T'));
  return (isFinite(ta) && isFinite(tb)) ? (tb - ta)/1000 : NaN;
}

/* 分类：一处定义颜色与中文名，全站共用（KIND_LABELS 见「标准图编辑器」段） */
function kindCls(kind){ return 'k-' + (KIND_LABELS[kind] ? kind : 'unknown'); }
function kindName(kind){ return KIND_LABELS[kind] || (kind || '未分类'); }
function kindChip(kind, cls){
  return '<span class="tag ' + kindCls(kind) + (cls? ' '+cls : '') + '">' + esc(kindName(kind)) + '</span>';
}
function kindBadge(kind, cls){
  return '<span class="badge ' + kindCls(kind) + (cls? ' '+cls : '') + '" title="分类：'
    + esc(kindName(kind)) + '">' + esc(kindName(kind)) + '</span>';
}

/* ── tab ── */
// 各页面模块自己注册「切到我这页要跑什么」，core 不反向依赖它们
const TAB_LOADERS = {};
export function onTab(t, fn){ (TAB_LOADERS[t] = TAB_LOADERS[t] || []).push(fn); }
$$('nav button').forEach(b=>b.onclick=()=>go(b.dataset.tab));
$$('[data-go]').forEach(a=>a.onclick=e=>{e.preventDefault();go(a.dataset.go)});
export function go(t){
  $$('nav button').forEach(b=>b.classList.toggle('on', b.dataset.tab===t));
  $$('section').forEach(s=>s.classList.toggle('on', s.id==='tab-'+t));
  window.scrollTo(0,0);
  // 2026-10-18 老板需求：刷新后保持当前页面（此前刷新必回首页）
  try{ localStorage.setItem('plTab', t); }catch(e){}
  (TAB_LOADERS[t] || []).forEach(fn=>{ try{ fn(); }catch(e){ console.error(e); } });
}
// 调试/自动化用：模块作用域外的脚本（控制台、e2e）也能切页 / 进柜作业
// ⚠️ 柜作业并进柜页后不再是 tab，脚本里的 go('wizard') 全部失效，
//    要走 enterWizard（它会切到柜页再切到作业视图）。
if(typeof window!=='undefined'){ window.go = go; window.enterWizard = enterWizard; }

/* ── 柜作业视图切换（2026-10-08）──────────────────────────────
   「柜作业」已经并进柜页（#tab-containers 里的 #ctWizView），
   柜列表和作业流是同一页里的两个视图。

   🔴 这两个函数**必须放 core.js**，不能放 containers.js / wizard.js：
     wizard.js 已经 import 了 containers.js（loadContainerOptions /
     openContainerModal），containers.js 再反向 import wizard.js 就是
     **ESM 循环依赖** —— 运行期拿到 undefined，而静态检查（esm_syntax /
     esm_graph / web_contract）全是绿的，只有真点按钮才炸。
     放 core.js 两边都能用，环自然断开。 */
export function showWizView(on){
  const w = $('#ctWizView'), l = $('#ctListView');
  if(w) w.style.display = on? '':'none';
  if(l) l.style.display = on? 'none':'';
}
export function inWizView(){
  const w = $('#ctWizView');
  return !!w && w.style.display !== 'none';
}
/** 进入某个柜的柜作业。cid 为空 = 沿用当前柜；step 为空 = 自动落到第一个未完成的步骤。 */
export function enterWizard(cid, step){
  go('containers');
  showWizView(true);
  window.dispatchEvent(new CustomEvent('wizard:goto',
    { detail:{ cid: cid || '', step: step || '' } }));
}

/* ── 审核页子标签：一次只看一段，徽章常显三段待办 ── */
function revTab(key){
  $$('#revTabs .rt').forEach(el=>el.classList.toggle('on', el.dataset.rt===key));
  ['wb','dc','mg'].forEach(k=>{
    const w = $('#rt-'+k);
    if(w) w.style.display = (k===key)? '':'none';
  });
  // 与主 tab 同款：刷新保持（2026-10-18）
  try{ localStorage.setItem('plRevTab', key); }catch(e){}
}
$$('#revTabs .rt').forEach(el=>el.onclick=()=>revTab(el.dataset.rt));
function setRevCount(id, n){
  const el = $(id);
  if(el){ el.textContent = n; el.className = 'n' + (n>0? ' hot':''); }
}

/* Esc 关闭钩子：各层自己注册「我怎么关」，避免 drawer 反向依赖 batches 成环。
   ⚠️ 两条规矩（10-04）：
     1) **逆序执行** —— 后注册的通常是更上层的浮层，先关它；
     2) 处理器 **return true 表示「这次 Esc 我消费了」**，后面的层不再关。
   没有这两条时一次 Esc 会把照片详情和它下面的产品抽屉一起关掉 ——
   老板在抽屉里看照片按一下 Esc，产品详情也没了，得重新点开。 */
const ESC_HANDLERS = [];
/* prio 越大越先关（= 越上层的浮层）。⚠️ 别指望注册顺序：photos.js 与
   drawer.js 互相 import，模块真正执行的先后跟 main.js 里的 import 写法不是
   一回事 —— 实测 drawer 的钩子会排在 products 前面，光靠「逆序执行」会把
   产品抽屉先关掉、照片详情留在屏幕上。所以上层浮层必须显式给高 prio。 */
export function onEscape(fn, prio=10){ ESC_HANDLERS.push({fn, prio}); }
document.addEventListener('keydown', e=>{
  if(e.key !== 'Escape') return;
  const layers = [...ESC_HANDLERS].sort((a, b)=> b.prio - a.prio);
  for(const h of layers){
    try{ if(h.fn() === true) break; }catch(err){ console.error(err); }
  }
});

/* 导入 / 长任务进度覆盖层（通用，从 photos 段提到 core） */
function busy(on, title, detail){
  $('#busy').classList.toggle('on', !!on);
  if(title) $('#busyT').textContent = title;
  if(detail!==undefined) $('#busyD').textContent = detail||'';
}

// go / onTab 已在定义处 export，这里导出其余工具
// go / onTab / onEscape 已在定义处 export（重复列进下面的列表会报 Duplicate export）
// ⚠️ fmtTaken / fmtGap / diffSec 用的是 `export function` 就地导出，
//    不要再写进这个导出块 —— 同一名字导出会直接 SyntaxError（整个页面白屏）。

/* ── 全局柜锚点：全站唯一真相源（2026-10-06 v5）──
   所有写类柜下拉（导入 / 清单 / 报告选柜）都以锚点为唯一值；
   资产页的柜筛选是另一回事（本地筛选，不广播）。
   状态只落 localStorage['plCid']，不各页各记一份。 */
let _cid = (()=>{ try{ return localStorage.getItem('plCid') || ''; }catch(e){ return ''; } })();
const _cidListeners = new Set();
export function getCid(){ return _cid; }
export function setCid(id){
  _cid = id || '';
  try{ if(_cid) localStorage.setItem('plCid', _cid); else localStorage.removeItem('plCid'); }catch(e){}
  _cidListeners.forEach(fn=>{ try{ fn(_cid); }catch(e){ console.error(e); } });
}
export function onCidChange(fn){
  _cidListeners.add(fn);
  return ()=> _cidListeners.delete(fn);
}

// ⚠️ enterWizard / showWizView / inWizView 用的是**定义处 export**，
//    别再写进下面这个列表 —— 两处都写 = Duplicate export，
//    整个模块图挂掉、全站白屏，而 esm_syntax 之外的检查抓不到。
export { $, $$, toast, api, post, patch, del, esc, emptyHtml, busy,
         kindCls, kindName, kindChip, kindBadge, KIND_LABELS, revTab, setRevCount };