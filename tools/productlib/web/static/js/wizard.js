// wizard.js —— 柜作业（原「作业向导」，2026-10-08 并进柜页）
//
// 沿「①建柜 → ②导清单 → ③照片 → ④选图 → ⑤生成报告」走完一柜的全部写动作。
// 状态**派生自后端** /api/containers/{cid}/progress（不落 localStorage 记账），
// 关掉浏览器回来还是那一步。④选图是唯一的客户端步骤（后端无对应），可跳过。
//
// 每张卡片统一五段：说明 → 本步状态 → **结果详情** → 主操作 → 反向链接。
// 写动作落点：建柜 /products 导入 / 照片导入 三处模态与资产页共用同一份实现；
// 治理面板是**从照片库整块搬进来的**（#govPanel，batches.js 同一份 handler，不是复制）。
import { $, $$, api, post, patch, esc, toast, busy, go, onTab, onEscape,
         getCid, setCid, onCidChange, KIND_LABELS, kindName,
         showWizView, inWizView } from './core.js';
// ④选图的「看大图」复用照片页那个查看器（同一份实现，别各写一套）。
// ⚠️ 不会成环：没有任何模块 import wizard.js，drawer.js 也已被 photos.js 等多个模块引用。
import { openViewer } from './drawer.js';
import { openModal } from './modal.js';
import { loadContainerOptions, openContainerModal, loadContainers } from './containers.js';
import { openImportChecklistModal } from './products.js';
import { openImportPhotosModal, shotCard, bindShots,
         loadPhotoTabs, tabsInit, PHOTO_TABS_WIZ, pagerHtml } from './photos.js';
import { loadPhotoTree } from './phototree.js';
import { selReset, selSetMode, selBindBar, selSetIds, selAddIds,
         selOn, selIds, selSize, selClear, selUpdBar } from './selbatch.js';
import { loadBatches, loadGovernInfo } from './batches.js';

const STEPS = ['container', 'checklist', 'photos', 'picks', 'report'];
const META = {
  container: { n: '①', name: '建柜',
    desc: '柜号是全流程主线。下面的柜信息会进报告的 General Information —— 缺项标橙，改完点保存。' },
  checklist: { n: '②', name: '导入清单',
    desc: '把货品清单（Excel）导入到本柜，并在这里查看 / 修改清单内容（品名·规格·Loading·核对）。' },
  photos:    { n: '③', name: '照片',
    desc: '' },
  picks:     { n: '④', name: '选图',
    desc: '为报告挑用图：每件货的核对照（Quantity check），以及监装照片（柜况④每类一张、卡车⑦多选）。都不选也能出报告 —— 那时按编码/最新照片自动取。' },
  report:    { n: '⑤', name: '生成报告',
    desc: '按柜出装柜报告（Packing list + Quantity check + 柜况 / 卡车照片）。' },
};

/* ── 状态 ── */
let _prog = null;
let _loadErr = '';
let _active = 'container';
let _detail = null;
let _reports = null;
let _genResultHtml = '';
let _wCodes = [];                 // ④ 编码池
let _wPicks = {};                 // ④ code_norm -> [photo_id,...]
let _lastRp = null;               // ④ 最近一次检索结果（局部重绘用）
let _anchorWarn = '';             // 脏柜锚点的持久提示（自愈后仍要看得到）
let _lpFor = '';                  // ④ 已为哪个柜自动载过编码+检索过（避免每次进都重跑）
let _clBatch = '', _clRows = [], _clPage = 0, _clFor = '';
const CL_PAGE_MAX = 50;
/** 清单每页行数：按视口高度算，保证「表格 + 页码」一屏装下（老板要「不要往下滚」）。
 *  一页 50 行时表格比视口还高，页码被挤到下面，看着像没有翻页。 */
function clPageSize(){
  // 实测 17 行时页面还超 87px（一屏 900），按每行 34px 反推再留余量 → 约 12 行
  const avail = window.innerHeight - 450;   // 导航+步骤条+工具栏+表头+页码+边距
  return Math.max(6, Math.min(CL_PAGE_MAX, Math.floor(avail / 34)));
}
let _metaDraft = null;            // ① 柜信息已保存值快照（判「有没有未保存改动」）

/* ── 治理抽屉开关（2026-10-21 老板报「旧版照片治理的抽屉，打开了关闭不了」）──
   根因：抽屉是 position:fixed 右侧 560px、z-index 70，**它自己把唯一的关闭
   入口盖住了** —— 开关按钮 #wGovToggle 在向导卡片标题行最右（.wstat-inline
   的 margin-left:auto 把它推到卡片右缘），正好落在抽屉覆盖区下面；抽屉内
   又没有 × 按钮、没有 Esc、没有点外面关闭。于是「打开」后没有任何一条能
   走到关闭的路径。
   ⚠️ 之前 cdp_old_wizard.py 的 8a/8b/8c 用**程序化 t.click()**，绕过命中
      测试 —— 按钮被浮层盖住时照样触发 handler，所以这个缺陷一直测不出来。
   现在补齐三条关闭路径（与 batches.js 批次抽屉同一套范式）：
     ① 抽屉内顶栏的「✕ 关闭」按钮（#gGovClose，见 index.html）
     ② Esc（onEscape 消费这次按键）
     ③ 点抽屉外关闭（document mousedown 落在 #wizGovWrap 之外）
   ③ 为什么不用全屏遮罩：遮罩 z-index 只能落在 55~69 区间才不压住批次
      抽屉（#bDrawer 60 / #bMask 55），但那区间又低于治理抽屉自己(70)，
      遮罩会盖在**治理面板内呼出的批次抽屉**上面（照片批次按钮就在治理
      面板里）—— 层级打架。mousedown 判「点在面板外」不引入任何新层。
   ⚠️ 抽屉状态记在 _govOpen 里：bindStep 每次重绘都会跑，若只用
      style.display 表达状态，重绘时无法区分「用户开的」和「默认收的」。*/
let _govOpen = false;

function govDrawerIsOpen(){
  const gw = $('#wizGovWrap');
  return !!(gw && gw.style.display !== 'none');
}
function openGovDrawer(){
  const gw = $('#wizGovWrap');
  if(!gw) return;
  _govOpen = true;
  gw.style.display = 'flex';
  // 抽屉内是同一份实现：展开时顺手把折叠体也展开，省一次点击
  const gb = document.querySelector('#govPanel .foldbody');
  if(gb) gb.style.display = '';
}
function closeGovDrawer(){
  const gw = $('#wizGovWrap');
  if(!gw) return;
  _govOpen = false;
  gw.style.display = 'none';
}


/* ④ 采用标记按柜存 —— 与报告中心同一口径，刷新 / 切步骤不丢 */
const PICKS_KEY = cid => 'wizPicks:' + cid;
function pickCount(){
  return Object.values(_wPicks).reduce((a, v)=>a + (Array.isArray(v) ? v.length : 0), 0);
}
function savePicks(){
  try{ localStorage.setItem(PICKS_KEY(getCid()), JSON.stringify(_wPicks)); }catch(e){}
}
function loadPicks(){
  for(const k of Object.keys(_wPicks)) delete _wPicks[k];
  let raw = null;
  try{ raw = localStorage.getItem(PICKS_KEY(getCid())); }catch(e){}
  if(raw){ try{ Object.assign(_wPicks, JSON.parse(raw) || {}); }catch(e){} }
}

/* ④ 监装照片（报告④柜况每类可多张 / ⑦卡车多选）。与编码采用分开存 ——
   两类决定互相独立，而且必须能区分「没动过」（= 后端自动取，不传
   trucks/conds 键）和「选了又全取消」（= ⑦ 明确留空）。所以落盘的是
   一个独立 key：key 存在 = 人工动过监装照。
   2026-10-18 老板规则：柜况细类**不限一张**，_wConds[tag] = [photo_id,...]；
   旧数据（单 photo_id）loadSup 时归一成 list。 */
let _supGroups = null;            // /supervision-photos 的分组缓存（渲染用）
let _wTrucks = [];                // ⑦ 选中的 photo_id（按点选顺序）
let _wConds = {};                 // ④ tag -> [photo_id,...]（每类可多张）
const SUP_KEY = cid => 'wizPicksSup:' + cid;
function supTouched(){
  try{ return !!localStorage.getItem(SUP_KEY(getCid())); }catch(e){ return false; }
}
function saveSup(){
  try{ localStorage.setItem(SUP_KEY(getCid()),
    JSON.stringify({ trucks: _wTrucks, conds: _wConds })); }catch(e){}
}
function loadSup(){
  _wTrucks = []; _wConds = {};
  let raw = null;
  try{ raw = localStorage.getItem(SUP_KEY(getCid())); }catch(e){}
  if(raw){ try{ const d = JSON.parse(raw) || {};
    if(Array.isArray(d.trucks)) _wTrucks = d.trucks.map(String);
    if(d.conds && typeof d.conds === 'object'){
      for(const k of Object.keys(d.conds)){
        const v = d.conds[k];
        _wConds[k] = Array.isArray(v) ? v.map(String) : (v ? [String(v)] : []);
      }
    }
  }catch(e){} }
}
function resetSup(){
  _wTrucks = []; _wConds = {};
  try{ localStorage.removeItem(SUP_KEY(getCid())); }catch(e){}
}
function condCount(){             // ④ 已选图片总数（多选后按张数计）
  return Object.values(_wConds).reduce((a, v)=>a + (Array.isArray(v) ? v.length : 0), 0);
}

/* ── 每步状态：把后端 5 个 steps 重新映射到 UI 的 5 步 ── */
function stepState(key){
  if(!_prog) return { done:false, summary:'—' };
  const P = _prog.steps, cid = getCid();
  if(!cid && key !== 'container') return { done:false, summary:'未选柜', blocked:true };
  if(key === 'container') return { done:P.container.done, summary:P.container.summary };
  if(key === 'checklist') return { done:P.checklist.done, summary:P.checklist.summary };
  if(key === 'photos'){
    const ph = P.photos, gv = P.govern;
    return { done: ph.done && gv.done,
             summary: ph.total ? (ph.total + ' 张 · 治理 ' + gv.done_cnt + '/' + gv.total) : '未导入' };
  }
  if(key === 'picks'){
    if(P.checklist.row_total === 0) return { done:false, summary:'先完成②', blocked:true };
    const n = pickCount() + _wTrucks.length + condCount();
    return { done: n > 0, summary: n ? ('已选 ' + n + ' 张') : '未选（可跳过）' };
  }
  if(key === 'report') return { done:P.report.done, summary:P.report.summary };
  return { done:false, summary:'—' };
}
function defaultActive(){
  if(!_prog) return 'container';
  for(const k of STEPS){ if(!stepState(k).done) return k; }
  return 'report';
}
function nextStepKey(k){ const i = STEPS.indexOf(k); return STEPS[Math.min(i + 1, STEPS.length - 1)]; }

async function loadProgress(advance){
  const cid = getCid();
  if(!cid){ _prog = null; _detail = null; _loadErr = ''; render(); return; }
  _loadErr = '';
  try{
    _prog = await api('/api/containers/' + cid + '/progress');
  }catch(e){
    // 🔴 404 = 后端没这个端点 —— 十有八九是**服务进程是旧的**（路由在进程启动时
    //    加载、静态文件每请求现读，于是「界面是新的、接口 404」）。别只甩 Not Found。
    // 🔴 400 + 「柜不存在」= **锚点脏了**：localStorage['plCid'] 按 origin 存、
    //    跨库共用，换机器/换库后还指着旧库的柜（老板 10-07 用绿色包在全新环境
    //    撞到，整页 500）。这种就地把锚点清掉并落到第一个柜，别只弹一句报错。
    const raw = (e && e.message) ? e.message : String(e);
    _prog = null;
    if(/柜不存在/.test(raw)){
      setCid('');
      const items = await loadContainerOptions().catch(()=>[]);
      if(items && items.length){
        _anchorWarn = '上次选的柜在这个库里没有（换机器或换库后，浏览器里还留着旧柜号「'
                    + cid + '」），已经帮你切到「' + (items[0].container_no || '（未分柜）')
                    + '」。若那柜的货确实要继续做，把老版本的 data\\ 整个拷到这个版本目录即可。';
      }else{
        _anchorWarn = '上次选的柜在这个库里没有（换机器或换库后，浏览器里还留着旧柜号「'
                    + cid + '」），而当前这个柜库还没有柜 —— 先到「柜」页新建一个；'
                    + '若那柜的货确实要继续做，把老版本的 data\\ 整个拷到这个版本目录即可。';
      }
      toast(_anchorWarn, 'warn');
      loadProgress(false);
      return;
    }
    _loadErr = /not found|404/i.test(raw)
      ? ('后端没有这个接口（' + raw + '）。多半是服务进程还是旧的 —— ' +
         '路由在进程启动时加载、页面是每次现读的，所以会「界面是新的、接口 404」。' +
         '重启产品库服务即可。')
      : ('读取向导进度失败：' + raw);
    toast(_loadErr, 'err');
  }
  // 柜详情（①②③④ 的结果详情都从它出）—— 单独 try：详情挂了不连累进度
  try{ _detail = await api('/api/containers/' + cid); }
  catch(e){ _detail = null; }
  // 自动跳步只在**这一步真的完成**时发生。
  // ⚠️ v6 把「导入照片」与「跑治理」并成一步后，不能再"导完就跳"——
  //    治理还没跑呢，跳到④等于把老板从治理面板上带走（实测 Photos 已入库
  //    但界面停在④，看不到自己刚导的照片）。
  if(advance && _prog && stepState(_active).done) _active = nextStepKey(_active);
  else if(!_active || !_prog || !_prog.steps[_active]) _active = defaultActive();
  render();
}

function render(){
  const pct = $('#wizPct');
  if(pct) pct.textContent = _prog ? ('就绪 ' + _prog.ready_pct + '%') : '未选柜';
  renderBar();
  renderAnchorWarn();
  renderBody();
}

/* ── 脏柜锚点的持久提示（2026-10-07 绿色包在全新环境崩的那一页）──
   为什么不能只靠 toast：自愈会把锚点清空 → 递归 loadProgress → 提示被清掉，
   而 toast 几秒就没了 —— 用户看到的只会是「还没有选柜」，压根不知道
   「刚才那个柜号为什么不见了」。所以这里挂一条**可关闭的常驻条**。
   铁律 16：提示要具体到可操作（说清原因 + 下一步）。 */
function renderAnchorWarn(){
  const box = $('#wizWarn');
  if(!box) return;
  if(!_anchorWarn){ box.style.display = 'none'; box.innerHTML = ''; return; }
  box.style.display = '';
  box.innerHTML = '<span class="wi">⚠</span><span>' + esc(_anchorWarn) + '</span>' +
    '<button class="btn ghost sm" id="wizWarnX">知道了</button>';
  const x = $('#wizWarnX');
  if(x) x.onclick = ()=>{ _anchorWarn = ''; renderAnchorWarn(); };
}

/* ── 步骤条 ── */
function renderBar(){
  const bar = $('#wizBar');
  if(!bar) return;
  bar.innerHTML = STEPS.map((key, i)=>{
    const m = META[key], s = stepState(key);
    const state = s.blocked ? 'blocked' : (s.done ? 'done' : (_active === key ? 'current' : 'todo'));
    return '<div class="wstep ' + state + (_active === key ? ' cur' : '') + '" data-step="' + key + '">' +
        '<span class="wn">' + m.n + '</span>' +
        '<span class="wt">' + esc(m.name) + '</span>' +
        '<span class="ws">' + esc(s.summary) + '</span>' +
      '</div>' + (i < STEPS.length - 1 ? '<div class="wsep"></div>' : '');
  }).join('');
  $$('#wizBar .wstep').forEach(el=>el.onclick = ()=>{
    if(el.dataset.step === _active) return;
    if(!confirmLeave()) return;          // 有未保存改动 → 拦一下
    _active = el.dataset.step;
    render();
  });
  // 采用/清空都会走 renderBar —— 顺手刷新统计条里「已采用」那一格
  _updPickStat();
}

function renderBody(){
  const body = $('#wizBody');
  if(!body) return;
  const cid = getCid();

  if(!cid){
    body.innerHTML =
      '<div class="empty">' +
        '<div class="ec">🚢</div>' +
        '<div class="et">还没有选柜</div>' +
        '<div class="es">先建一个柜（或选一个已有柜），全流程都挂在它下面</div>' +
        '<div class="eb"><button class="btn sm" id="wizNew">＋ 新建柜</button>' +
        '<button class="btn ghost sm" id="wizPick">选择已有柜</button></div>' +
      '</div>';
    const nb = $('#wizNew'); if(nb) nb.onclick = openContainerModal;
    const pb = $('#wizPick'); if(pb) pb.onclick = ()=>{ const s = $('#wizCid'); if(s) s.focus(); };
    return;
  }
  if(!_prog){
    // ⚠️「还没查完」不等于「没问题」—— 读失败渲染成错误态 + 重试，不停在「读取中」
    body.innerHTML = _loadErr
      ? '<div class="wcard" style="border-color:var(--err)">' +
          '<div class="wcard-h"><b>读不到向导进度</b></div>' +
          '<div class="faint">' + esc(_loadErr) + '</div>' +
          '<div class="wactions" style="margin-top:12px">' +
            '<button class="btn sm" id="wRetry">重试</button>' +
            '<button class="btn ghost sm" id="wSwitchC">换个柜</button></div>' +
        '</div>'
      : '<div class="faint">读取中…</div>';
    const rb = $('#wRetry'); if(rb) rb.onclick = ()=>loadProgress(false);
    const sb = $('#wSwitchC'); if(sb) sb.onclick = ()=>{ const s = $('#wizCid'); if(s) s.focus(); };
    return;
  }
  body.innerHTML = stepCard(_active);
  bindStep(_active);
}

/* ── 离开拦截：有未保存的柜信息 / 清单改动就别让人悄悄跑掉 ── */
function metaDirty(){
  if(!_metaDraft) return 0;
  let n = 0;
  $$('#wDetail [data-mf]').forEach(el=>{
    if((el.value || '') !== String(_metaDraft[el.dataset.mf] || '')) n++;
  });
  return n;
}
function clDirty(){
  let n = 0;
  $$('#wizClBody [data-cl]').forEach(el=>{
    const r = _clRows[+el.dataset.i];
    if(!r) return;
    const cur = r[el.dataset.cl];
    if((el.value || '') !== String(cur == null ? '' : cur)) n++;
  });
  return n;
}
function anyDirty(){ return metaDirty() + clDirty(); }
function confirmLeave(){
  if(!anyDirty()) return true;
  const what = [];
  if(metaDirty()) what.push('柜信息 ' + metaDirty() + ' 处');
  if(clDirty()) what.push('清单 ' + clDirty() + ' 处');
  return window.confirm('有未保存的修改（' + what.join('、') + '）。\n\n离开将丢失这些修改，确定吗？');
}

/* ── 卡片 ── */
function blockedBtn(reason){
  return '<button class="btn" disabled title="' + esc(reason) + '">' + esc(reason) + '</button>';
}
function statusHtml(key){
  const P = _prog.steps;
  if(key === 'container'){
    const miss = (P.container.meta_missing || []);
    if(miss.length){
      const L = { seal_no:'封条号', inspector:'Inspector', client_name:'客户', location:'Location' };
      return '<span class="tag warn">缺：' + miss.map(m=>L[m] || m).join('、') + '</span>';
    }
    return '<span class="tag ok">柜信息完整</span>';
  }
  if(key === 'checklist')
    return '<span class="tag">清单行 ' + P.checklist.row_total + '</span>' +
      (P.checklist.row_unchecked ? '<span class="tag warn">未核对 ' + P.checklist.row_unchecked + '</span>'
                                 : '<span class="tag ok">已核对</span>') +
      '<span class="faint">清单批次 ' + P.checklist.batches + '</span>';
  if(key === 'photos'){
    const gv = P.govern;
    return '<span class="tag">照片 ' + P.photos.total + ' 张</span>' +
      '<span class="faint">批次 ' + P.photos.batches + ' · 监装 ' + P.photos.supervision + '</span>' +
      '<span class="tag ' + (gv.done ? 'ok' : '') + '">已治理 ' + gv.done_cnt + '/' + gv.total + '</span>' +
      (gv.pending ? '<span class="tag warn">待治理 ' + gv.pending + '</span>' : '') +
      (gv.failed  ? '<span class="tag err">失败 ' + gv.failed + '</span>' : '') +
      '<span class="faint">已关联 ' + gv.linked + '</span>';
  }
  if(key === 'picks'){
    const n = pickCount();
    const s = (P.picks && P.picks.stats) || null;
    // 命中/缺口用后端柜级统计（与列表同源），别在本地另算
    const hit = s && s.codes_total
      ? '<span class="tag ' + (s.missing ? 'warn' : 'ok') + '">命中 ' + s.with_photo +
        '/' + s.codes_total + '（' + s.hit_rate + '%）· 缺口 ' + s.missing + '</span>' +
        '<span class="faint">本柜照片 ' + s.photo_total + ' 张 · 已关联 ' +
        s.photo_linked + ' · 标准图 ' + s.std_photos + '</span>'
      : '';
    return (n ? '<span class="tag ok">已选 ' + n + ' 张</span>'
              : '<span class="faint">未选 —— 可跳过，报告会按编码自动取图</span>') + hit;
  }
  if(key === 'report') return '<span class="tag">' + P.report.summary + '</span>';
  return '';
}

function stepCard(key){
  const m = META[key];
  const cid = getCid();
  const status = statusHtml(key);
  let actions = '', extra = '';
  if(key === 'container'){
    // 2026-10-21 老板：步骤卡片底部的「＋ 新建柜 / 切换柜 / 最近柜」全部去掉 ——
    // 新建柜走柜列表页入口，切换柜走右上角 wizCid 下拉，这里重复占一行。
    actions = '';
    extra = '';
  } else if(key === 'checklist'){
    actions = '<button class="btn" id="wImpCl">选择 Excel 导入</button>' +
      '<button class="btn ghost sm" id="wTmpl">下载模板</button>';
    extra = '<div class="revlink"><a href="#" id="wToProducts">查看资产 → 产品库</a></div>';
  } else if(key === 'photos'){
    // ③的「＋ 导入照片」已在标题行 stepBtns 里，这里必须留空 ——
    // 留着会在内容区上方再画一个重复按钮（多占一行，还两个同名 id）。
    actions = '';
  } else if(key === 'picks'){
    const blocked = _prog.steps.checklist.row_total === 0;
    actions = blocked ? blockedBtn('先完成②导入清单')
                      : '<button class="btn" id="wLookup2">开始检索</button>';
    extra = '<div class="revlink"><a href="#" id="wToProducts2">查看资产 → 产品库</a></div>';
  } else if(key === 'report'){
    const ok = _prog.steps.checklist.row_total > 0 && _prog.steps.photos.total > 0;
    actions = ok ? '<button class="btn" id="wGen">生成 docx</button>' : blockedBtn(_genReason());
    extra = '<div class="revlink"><a href="#" id="wToReport">查看资产 → 报告档案</a></div>';
  }
  /* ① 建柜 → ⑤ 报告 各步自己的操作钮（2026-10-20 老板：全部挪到标题行末尾，
     原来占独立一行 .wactions/.revlink，白吃掉 40~50px）。 */
  let stepBtns = '';
  if(key === 'photos'){
    // 按效果图只留这两个 —— 「查看资产 → 照片库」链接是多出来的，去掉
    stepBtns = '<button class="btn ghost sm" id="wGovToggle" ' +
        'title="照片治理（分类 → 读码 → 关联），点开右侧抽屉">照片治理</button>' +
      '<button class="btn sm" id="wImpPh">＋ 导入照片</button>';
  } else if(key === 'checklist'){
    stepBtns = '<a class="btn ghost sm" id="wToProducts" href="#">查看资产 → 产品库</a>';
  } else if(key === 'report'){
    stepBtns = '<a class="btn ghost sm" id="wToReport" href="#">查看资产 → 报告档案</a>';
  } else if(key === 'picks'){
    stepBtns = '<a class="btn ghost sm" id="wToProducts2" href="#">查看资产 → 产品库</a>';
  }
  return '<div class="wcard">' +
    // 2026-10-20 老板：说明、统计、步骤操作钮全部并进标题行 —— 原来各自占一整行，
    // 加起来吃掉 100 多 px，照片区就少一两行。
    '<div class="wcard-h"><span class="wnum">' + m.n + '</span><b>' + esc(m.name) + '</b>' +
      (stepState(key).done ? '<span class="tag ok">已完成</span>' : '<span class="tag">待办</span>') +
      // 步骤说明文案已去掉（2026-10-20 老板：按效果图精简，多余文案别占行）
      '<span class="wstat-inline">' + status + '</span>' +
      '<span class="wbtns">' + stepBtns + '</span>' +
    '</div>' +
    '<div class="wdetail" id="wDetail">' + detailHtml(key) + '</div>' +
    // ⚠️ actions 还有实质按钮（②导入清单 / ⑤生成 docx / ①新建柜），不能删；
    //    只把「查看资产」链接挪进了标题行（stepBtns）。
    (actions ? '<div class="wactions">' + actions + '</div>' : '') +
  '</div>';
}

function _genReason(){
  const c = _prog.steps.checklist.row_total, p = _prog.steps.photos.total;
  if(c === 0 && p === 0) return '先完成②导入清单、③导入照片';
  if(c === 0) return '先完成②导入清单（报告要有 Packing list）';
  if(p === 0) return '先完成③导入照片（报告⑥要有图）';
  return '还不能生成';
}

/* ══════════════════════════════════════════════════════════════════
   结果详情：每步显示这一步做出了什么
   数据只用两处口径 —— container_detail（与柜详情页同源）
   + /api/report/loading-list（与报告档案同源），不新造数字
   ══════════════════════════════════════════════════════════════════ */
function _v(v){
  return (v === null || v === undefined || String(v).trim() === '')
    ? '<span class="faint wdmiss">未填</span>' : esc(v);
}
function fmtSize(b){ return b >= 1048576 ? (b/1048576).toFixed(1)+' MB'
                                         : Math.max(1, Math.round(b/1024))+' KB'; }

function detailHtml(key){
  if(!_detail && key !== 'report') return '<div class="faint">读取详情…</div>';
  if(key === 'container') return detailContainer();
  if(key === 'checklist') return detailChecklist();
  if(key === 'photos')    return detailPhotos();
  if(key === 'picks')     return detailPicks();
  if(key === 'report')    return detailReport();
  return '';
}

/* ── ① 柜信息（可编辑：改完点保存，与产品库字段编辑同一套规矩）── */
const META_FIELDS = [
  ['seal_no','封条号'], ['client_name','客户'], ['inspector','Inspector'],
  ['location','Location'], ['product_name','Product'],
  ['arrival_at','到达日期（Arrival time）'], ['departure_at','完成日期（Departure time）'],
];
function detailContainer(){
  const d = _detail;
  _metaDraft = {};
  META_FIELDS.forEach(([k])=>{ _metaDraft[k] = d[k] || ''; });
  _metaDraft['remark'] = d.remark || '';
  const cell = ([k, lb])=>'<label>' + lb +
    '<input type="text" data-mf="' + k + '" value="' + esc(d[k] || '') +
    '" placeholder="未填（会进报告 General Information）" class="' +
    ((d[k] || '').trim() ? '' : 'miss') + '"></label>';
  return '<div class="wdh">柜信息<span class="faint">（柜号是身份标识，不可改）</span></div>' +
    '<div class="wmeta">' +
      '<label>柜号<input type="text" value="' + esc(d.container_no || '') + '" readonly></label>' +
      META_FIELDS.map(cell).join('') +
      '<label style="grid-column:1/-1">备注（REMARKS）' +
        '<textarea data-mf="remark" rows="2" placeholder="可后补">' + esc(d.remark || '') + '</textarea></label>' +
      '<div class="wmeta-act">' +
        '<button class="btn sm" id="wMetaSave" disabled>保存修改</button>' +
        '<button class="btn ghost sm" id="wMetaReset" disabled>还原</button>' +
        '<span class="wdirty" id="wMetaMsg"></span>' +
      '</div>' +
    '</div>';
}
function metaSync(){
  const n = metaDirty();
  const s = $('#wMetaSave'), r = $('#wMetaReset'), m = $('#wMetaMsg');
  if(s) s.disabled = !n;
  if(r) r.disabled = !n;
  if(m) m.textContent = n ? ('有 ' + n + ' 处未保存') : '';
  $$('#wDetail [data-mf]').forEach(el=>{
    const same = (el.value || '') === String(_metaDraft[el.dataset.mf] || '');
    el.classList.toggle('dirty', !same);
    el.classList.toggle('miss', !String(el.value || '').trim());
  });
}
async function saveMeta(){
  const cid = getCid();
  if(!cid) return;
  const payload = {};
  $$('#wDetail [data-mf]').forEach(el=>{
    const k = el.dataset.mf, v = (el.value || '').trim();
    if(v !== String(_metaDraft[k] || '')) payload[k] = v || null;   // 空串 = 清空
  });
  if(!Object.keys(payload).length) return;
  try{
    await api('/api/containers/' + cid, { method:'PUT',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    toast('柜信息已保存', 'ok');
    loadProgress(false);
  }catch(e){ toast('保存失败：' + e.message, 'err'); }
}

/* ── ② 清单内容（可查看 + 可编辑；品名/规格写产品库，行核对写快照）── */
async function loadChecklistRows(cid){
  const bs = (_detail ? _detail.batches : []).filter(b => b.kind === 'checklist');
  if(!bs.length){ _clRows = []; _clBatch = ''; _clFor = ''; return; }
  if(!_clBatch || !bs.some(b => b.id === _clBatch)){
    // ⚠️ 默认必须挑**行数最多**的那批，不能挑「最后一个」——
    //    同柜重导会留下一个 0 行的空批次（replace 语义），挑它表格就是空的，
    //    看起来像「清单没导进来」（实测踩过：1003 行的柜默认显示 0 行）。
    const best = bs.reduce((a, b)=> ((b.rows || 0) > (a.rows || 0) ? b : a), bs[0]);
    _clBatch = (best.rows || 0) > 0 ? best.id : bs[bs.length - 1].id;
  }
  if(_clFor === cid + '|' + _clBatch) return;      // 已拉过，别重复拉（1000+ 行不便宜）
  try{
    const d = await api('/api/containers/' + cid + '/checklist?batch=' + encodeURIComponent(_clBatch));
    _clRows = d.items || [];
    _clPage = 0;
    _clFor = cid + '|' + _clBatch;
  }catch(e){ _clRows = []; }
}
function detailChecklist(){
  const d = _detail;
  const bs = (d.batches || []).filter(b => b.kind === 'checklist');
  if(!bs.length) return '<div class="faint">这个柜还没有清单批次 —— 在上面点「选择 Excel 导入」。</div>';
  const total = _clRows.length;
  const PS = clPageSize();          // 每页行数按视口算，保证表格+页码一屏装下
  const pages = Math.max(1, Math.ceil(total / PS));
  if(_clPage > pages - 1) _clPage = pages - 1;
  const slice = _clRows.slice(_clPage * PS, _clPage * PS + PS);
  return '<div class="wclbar">' +
      '<select id="wClBatch" title="同柜多次导入会形成多个批次">' +
        bs.map(b=>'<option value="' + esc(b.id) + '"' + (b.id === _clBatch ? ' selected' : '') + '>' +
          esc(b.name || b.id) + '（' + (b.rows || 0) + ' 行）</option>').join('') + '</select>' +
      '<span class="faint">全柜 ' + (d.row_total || 0) + ' 行 · 未核对 ' + (d.row_unchecked || 0) + '</span>' +
      '<span class="spacer"></span>' +
      '<button class="btn sm" id="wClSave" disabled>保存修改</button>' +
      '<button class="btn ghost sm" id="wClReset" disabled>还原</button>' +
      '<span class="wdirty" id="wClMsg"></span>' +
    '</div>' +
    (total
      ? '<div class="wclwrap"><table><thead><tr>' +
          '<th style="width:40px">#</th><th style="width:160px">编码</th><th>品名</th>' +
          '<th style="width:140px">规格</th><th style="width:100px">箱号</th>' +
          '<th style="width:70px">Order</th><th style="width:86px">Loading</th>' +
          '<th style="width:92px">核对</th>' +
        '</tr></thead><tbody id="wizClBody">' +
        slice.map((r, ri)=>{
          const i = _clPage * PS + ri;
          const chk = (r.check_result != null && r.check_result !== '') ? r.check_result : '';
          const inp = (f, val, ph)=>'<input data-cl="' + f + '" data-i="' + i +
            '" value="' + esc(val || '') + '" placeholder="' + ph + '">';
          return '<tr>' +
            '<td class="ro faint">' + (r.seq || '') + '</td>' +
            '<td class="ro" title="' + esc(r.code) + '">' + esc(r.code) + '</td>' +
            '<td>' + inp('name', r.name, '未填写') + '</td>' +
            '<td>' + inp('spec', r.spec, '—') + '</td>' +
            '<td class="ro faint">' + esc(r.package_no || '—') + '</td>' +
            '<td class="ro faint">' + esc(r.order_qty || '') + '</td>' +
            '<td>' + inp('loading_qty', r.loading_qty, '—') + '</td>' +
            '<td>' + inp('check_result', chk, '未核对') + '</td>' +
          '</tr>';
        }).join('') + '</tbody></table></div>' +
        '<div class="wclpager">' +
          '<button id="wClPrev"' + (_clPage <= 0 ? ' disabled' : '') + '>‹ 上一页</button>' +
          '<span>第 ' + (_clPage + 1) + ' / ' + pages + ' 页 · 本批 ' + total + ' 行</span>' +
          '<button id="wClNext"' + (_clPage >= pages - 1 ? ' disabled' : '') + '>下一页 ›</button>' +
        '</div>'
      : '<div class="faint">这个批次没有行快照（旧清单导入，重导一次即可生成）。</div>') +
    '<div class="wclnote">品名 / 规格保存后写入<b>产品库</b>的产品主记录 —— 和「产品库」页改的是同一份；' +
    'Loading / 核对保存后写入本批次的<b>人工核对结论</b>（留空 = 未核对，报告沿用清单预填值，不会替你猜 PASS）。</div>';
}
function clSync(){
  const n = clDirty();
  const s = $('#wClSave'), r = $('#wClReset'), m = $('#wClMsg');
  if(s) s.disabled = !n;
  if(r) r.disabled = !n;
  if(m) m.textContent = n ? ('有 ' + n + ' 处未保存') : '';
  $$('#wizClBody [data-cl]').forEach(el=>{
    const row = _clRows[+el.dataset.i];
    const cur = row ? row[el.dataset.cl] : '';
    el.classList.toggle('dirty', (el.value || '') !== String(cur == null ? '' : cur));
  });
}
async function saveChecklist(){
  const prods = {}, rowChg = [];
  $$('#wizClBody [data-cl]').forEach(el=>{
    const r = _clRows[+el.dataset.i];
    if(!r) return;
    const f = el.dataset.cl, v = el.value || '';
    if(v === String(r[f] == null ? '' : r[f])) return;
    if(f === 'name' || f === 'spec'){
      const cn = r.code_norm || r.code;
      if(!cn) return;
      (prods[cn] = prods[cn] || {})[f] = v.trim();     // → 产品库（唯一真源）
    }else{
      // 行级：端点一次写 loading_qty + check_result，所以两个字段一起带
      let t = rowChg.find(x => x.seq === r.seq);
      if(!t){
        t = { batch_id:r.batch_id, seq:r.seq,
              check_result:(r.check_result || ''), loading_qty:(r.loading_qty || '') };
        rowChg.push(t);
      }
      if(f === 'loading_qty') t.loading_qty = v.trim(); else t.check_result = v.trim();
    }
  });
  const np = Object.keys(prods).length;
  if(!np && !rowChg.length) return;
  try{
    for(const cn in prods) await patch('/api/products/' + encodeURIComponent(cn), prods[cn]);
    for(const t of rowChg){
      await post('/api/checklist/rows/check', { batch_id:t.batch_id, seq:t.seq,
        check_result:t.check_result, loading_qty:t.loading_qty, by:'web' });
    }
    toast('已保存：' + np + ' 个产品字段 / ' + rowChg.length + ' 行核对', 'ok');
    loadProgress(false);
  }catch(e){ toast('保存失败：' + e.message, 'err'); }
}

/* ── ③ 照片浏览：按治理状态 / 分类 / 编码等筛，且能一路加载完 ──
   原来只给「最近 24 张」且**不能筛** —— 1000 多张的柜等于只看了个开头，
   治理到哪、某张照片什么分类、某个编码有没有图，全都查不到。

   2026-10-14 老板需求两条，都落在这一步：
   ① 左侧树形筛选（先用途后分类，带计数）—— 照片库同款实现（phototree.js）；
   ② 监装细分待办**合并进树里**（「监装待确认 → 待确认细分」入口），不再
      单独占一块、不再一行一张图；选中后本步网格直接出待办照片，卡片上
      带细分下拉 / 采用建议 / 标为监装，网格一排多张。同一屏还给批量
      标记无效（与照片库共用 selbatch.js）。 */
const SH_PAGE = 60;
let _shOffset = 0, _shTotal = 0;
let _wTabs = tabsInit();      // ③ 五档分组选项卡的翻页/计数状态
// ③ 左侧树选中态（2026-10-19 多选：usages/kinds 集合，逗号分隔进查询）
let _wTree = {usages:[], kinds:[], pending:false};
const W_SEL_IDS = {btn:'#wSelBtn', bar:'#wSelBar', n:'#wSelN',
                   invalid:'#wSelInvalid', valid:'#wSelValid', all:'#wSelAll',
                   clear:'#wSelClear',
                   ignore:'#wSelIgnore', unignore:'#wSelUnignore',
                   exit:'#wSelExit', boxSel:'#wizShots',
                   onMode: ()=>bindShots('#wizShots')};
/* 工具条小图标（2026-10-15）：一排同样的 ghost 文字按钮分不出「筛选」和
   「工具」—— 现在筛选带放大镜、工具各带专用图形，扫一眼就知道点它是
   缩小范围还是对结果做事。13px stroke 风格与全站轻量图标一致。 */
const W_ICO = {
  q:  '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="7" cy="7" r="4.2"/><path d="M10.2 10.2 14 14"/></svg>',
  box:'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1.8 14 5v6L8 14.2 2 11V5z"/><path d="M2 5l6 3.2L14 5M8 8.2v6"/></svg>',
  clean:'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><path d="M8 2v2.6M8 11.4V14M2 8h2.6M11.4 8H14M4.3 4.3l1.8 1.8M9.9 9.9l1.8 1.8M11.7 4.3l-1.8 1.8M6.1 9.9l-1.8 1.8"/></svg>',
  dup:'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="5.6" y="5.6" width="8" height="8" rx="1.6"/><path d="M10.4 5.6v-1a2 2 0 0 0-2-2h-5a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h1"/></svg>',
  more:'<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 6.5 8 10l3.5-3.5"/></svg>'
};
function detailPhotos(){
  const kindOpts = Object.keys(KIND_LABELS)
    .map(k=>'<option value="'+esc(k)+'">'+esc(KIND_LABELS[k])+'</option>').join('');
  return '<div class="wdh" style="margin-top:2px">本柜照片' +
      '<span class="faint" id="wShotsTotal"></span>' +
      '<span class="spacer"></span>' +
      // 待确认视图才出现的一行操作：批量采用建议（细分待办专用）。
      // 🔴 「批量选择」原先也在这条里（只在待确认视图显示）—— 四档化后
      //    老板在正常视图根本找不到批量入口（2026-10-15 反馈），挪进
      //    常驻工具条，任何档位都能进批量勾选。
      '<span id="wSupBar" style="display:none;gap:6px;align-items:center">' +
        '<button class="btn ghost sm" id="wSupPendAll" disabled' +
          ' title="把还挂着 AI 建议且没确认的监装照，批量采用建议值">全部采用建议</button>' +
      '</span>' +
    '</div>' +
    '<div class="prow">' +
      '<div class="ptree" id="wPhTree"></div>' +
      '<div class="pmain">' +
      // ── 工具条分区（2026-10-15 老板反馈：10 个控件挤一行）──
      // ① 查询区：缩小范围的控件（状态 / 关键词 / 待关联 / 待办 + 查询/重置）；
      // ② 工具区：对结果做事的按钮（按箱号分组 / 批量选择 / 更多▾）；
      // ③ 低频工具（清理、重复图片）收进「更多 ▾」—— 干完一次就走的
      //    工具不该常驻占地；下拉点外面自动关（document 监听见文件末尾）。
      '<div class="wclbar">' +
        '<span class="tgrp">' +
          '<select id="wShState" title="按治理状态筛">' +
            '<option value="">全部治理状态</option><option value="pending">待治理</option>' +
            '<option value="done">已治理</option><option value="skipped">已跳过</option>' +
            '<option value="failed">失败</option></select>' +
          '<input type="text" id="wShQ" placeholder="搜编码 / 文件名 / 描述" style="min-width:200px" ' +
            'title="同时搜：文件名、大模型描述、大模型读出的编码、已关联的产品编码">' +
          '<label class="faint"><input type="checkbox" id="wShUnlinked"> 只看待关联</label>' +
          // 关联待办进查询条件（2026-10-15 老板需求）：③四档化后待确认关联
          // 在这里筛 —— 与树/状态/关键词自由组合
          '<select id="wShCand" title="关联待办：照片里读出了编码、等人工确认的那部分">' +
            '<option value="">全部待办</option>' +
            '<option value="cand">待确认关联</option>' +
            '<option value="newprod">新产品确认</option></select>' +
          '<button class="btn sm" id="wShSearch">'+W_ICO.q+'查询</button>' +
          '<button class="btn ghost sm" id="wShReset">重置</button>' +
        '</span>' +
        '<span class="spacer"></span>' +
        '<span class="tgrp tgrp-tool">' +
          '<button class="btn ghost sm tool" id="wShCarton"' +
            ' title="按箱号聚合展示照片（再点一次恢复四档列表）">'+W_ICO.box+'按箱号分组</button>' +
          '<button class="btn sm" id="wSelBtn"' +
            ' title="批量选择：勾选后可批量标记无效 / 改判分类">批量选择</button>' +
          '<span class="tdrop" id="wMoreDrop">' +
            '<button class="btn ghost sm tool" id="wMoreBtn"' +
              ' title="低频工具：清单/包装清理、重复图片检测">更多'+W_ICO.more+'</button>' +
            '<span class="tdrop-m">' +
              '<button class="titem" id="wCleanInvalid"' +
                ' title="识别没关联过的清单/包装照，确认后批量标为无效">'+W_ICO.clean+'清单/包装清理</button>' +
              '<button class="titem" id="wDupBtn"' +
                ' title="自动找出拍重了的相似照片，确认后只留一张">'+W_ICO.dup+'重复图片</button>' +
            '</span>' +
          '</span>' +
        '</span>' +
        // 分类/用途改到左侧树（2026-10-14）；下拉保留为筛选状态真源，隐藏
        // ⚠️ '_unset'（未识别）必须有自己的 option：树上点「未分类」时
        //    真源下拉没有这个值 = 筛选丢失，列表跟树对不上（2026-10-15）
        '<select id="wShKind" style="display:none"><option value="">全部分类</option>' + kindOpts +
          '<option value="_unset">未分类</option></select>' +
        '<select id="wShUsage" style="display:none">' +
          '<option value="">全部用途</option><option value="预检">预检</option>' +
          '<option value="监装">监装</option><option value="_unset">未分类</option></select>' +
      '</div>' +
      // 五档分组选项卡（10-07 第二轮）：全部 / 已关联 / 待关联 / 待确认关联 / 新产品确认。
      // 常驻、不藏在复选框后面 —— 这两档是**要去干活**的入口（确认关联 / 确认新产品），
      // 藏起来等于没有。徽章数字是后端 COUNT，与下面列表条数同一份 WHERE。
      '<div class="ptabs" id="wShTabs"></div>' +
      '<div class="wshots"><div class="grid" id="wizShots"></div></div>' +
      '<div class="row" style="margin-top:8px">' +
        '<div class="pager-row" id="wShMore" style="display:none"></div>' +
        '<span class="faint" id="wShotsShown"></span>' +
      '</div>' +
      // 批量选择操作条（与照片库同一份实现 selbatch.js）
      '<div class="selbar" id="wSelBar" style="display:none">' +
        '<span class="faint">已选 <b id="wSelN">0</b> 张</span>' +
        '<button class="btn sm" id="wSelInvalid">标记无效</button>' +
        '<button class="btn sm ghost" id="wSelValid">取消无效</button>' +
        // 本次忽略（2026-10-18）：新产品暂不入库、退出关联队列，可恢复
        '<button class="btn sm" id="wSelIgnore">本次忽略</button>' +
        '<button class="btn sm ghost" id="wSelUnignore">恢复忽略</button>' +
        // 批量改判分类（2026-10-15，与照片库选择条同款）：模型识别不一定准，
        // ③ 是几百张照片的主战场 —— 改判入口不能只在照片库有，勾一批 → 选
        // 分类 → 应用（POST /api/photos/kind，只写标记不动文件）。
        '<select id="wSelKind" title="把勾选的照片改判为这个分类">' +
          '<option value="">改判分类…</option></select>' +
        '<button class="btn sm ghost" id="wSelKindDo">应用分类</button>' +
        '<button class="btn sm ghost" id="wSelAll">全选本页</button>' +
        '<button class="btn sm ghost" id="wSelAllFiltered"' +
          ' title="按当前筛选条件选中全部照片（跨页，含未加载的）">全选筛选结果</button>' +
        // 清除已选（2026-10-15）：清空勾选但留在选择模式（与「退出选择」不同）
        '<button class="btn sm ghost" id="wSelClear"' +
          ' title="清空已勾选的照片（仍在选择模式，可继续勾）">清除已选</button>' +
        '<button class="btn sm ghost" id="wSelExit">退出选择</button>' +
        '<span class="faint">无效照片默认退出各工作队列，可随时撤销</span>' +
      '</div>' +
      '</div>' +
    '</div>';
}
async function loadWizardPhotos(cid, reset){
  const box = $('#wizShots');
  if(!box) return;
  await loadPhotoTabs({
    bar: '#wShTabs', box: '#wizShots', more: '#wShMore',
    tabs: PHOTO_TABS_WIZ,               // ③ 四档（2026-10-15 需求5）：含无效图片档
    st: _wTabs, baseQs: _wBaseQs(cid), reset: reset,
    onCounts: (c, st)=>{
      const tot = $('#wShotsTotal');
      if(tot) tot.textContent = (c ? ('共 ' + c.all + ' 张') : '');
      const shown = $('#wShotsShown');
      // 说清是**当前档**的数字：徽章上的 1060 是全柜，下面的 56 才是这一档，
      // 两个数摆在一起不点名就会被人当成不一致（铁律 23）。
      if(shown) shown.textContent = (c && st.total)
        ? ('当前档「' + (st.tab || '全部') + '」已显示 ' + st.n + ' / ' + st.total + ' 张')
        : '';
      // 待确认视图：卡片渲染完再补细分操作（下拉/采用建议/标为监装）
      if(_wTree.pending) _decoratePendingCards();
    }  });
}

/* ── ③ 左侧树（用途 → 分类 + 监装待确认，2026-10-14）── */
function _wTreeCtx(){
  const val = id => { const e = $('#'+id); return e ? (e.value || '') : ''; };
  return {
    container_id: getCid() || '',
    batch: '', state: val('wShState'), q: val('wShQ').trim(),
    unlinked: ($('#wShUnlinked') && $('#wShUnlinked').checked) ? 1 : 0,
    invalid: 'hide',
    todo: val('wShCand')};
}
function refreshWizardTree(){
  return loadPhotoTree({
    bar:'#wPhTree', ctx:_wTreeCtx, value:_wTree, showPending:true,
    pendingN: (_supPend && _supPend.items) ? _supPend.items.length : null,
    onChange:(v)=>{
      _wTree.usages = v.usages || [];
      _wTree.kinds = v.kinds || [];
      _wTree.pending = v.pending;
      const grid = $('#wizShots');
      if(grid) grid.classList.toggle('pending', !!v.pending);
      _showSupBar(v.pending);
      loadWizardPhotos(getCid(), true);
      refreshWizardTree();                 // 交叉筛选：另一维计数跟着收窄
    }});
}
/** 待确认视图才有的一行操作（批量采用建议 + 批量选择）。 */
function _showSupBar(on){
  const bar = $('#wSupBar');
  if(bar) bar.style.display = on ? 'inline-flex' : 'none';
}

/* ── 清单/包装照清理（2026-10-15 需求2）：系统识别 + 用户确认批量无效 ──
   老板口径：清单/包装照用户都当无效图。系统按分类把没关联过的这两类
   找出来，人确认后一键标无效 —— 只写标记不删文件，无效图片档可撤销。
   ⚠️ 函数声明 + 进③渲染后再绑 onclick —— ③的 DOM 是进视图才有的，
   模块加载时绑 = null.onclick，整个 wizard.js 初始化都会被打断。 */
async function _openCleanInvalid(){
  const cid = getCid();
  if(!cid) return toast('先在右上角选择柜', 'err');
  busy(true);
  let d;
  try{ d = await api('/api/photos/auto-invalid?container_id=' + cid); }
  catch(e){ busy(false); return toast('读取失败：' + e.message, 'err'); }
  busy(false);
  if(!d.total) return toast('没有识别到待清理的清单/包装照', 'ok');
  const prevN = (d.preview || []).length;
  const cells = (d.preview || []).map(p=>
    '<div class="dupcell"><img loading="lazy" src="'+p.thumb+'" title="'+esc(p.file)+'">'+
    '<span class="tag">'+esc(kindName(p.photo_kind))+'</span></div>').join('');
  openModal({
    title: '清理清单/包装照',
    width: 760,
    bodyHtml:
      '<p>识别到 <b>'+d.total+'</b> 张没关联过的<b>清单 / 包装</b>照'+
      (d.linked_n ? '（另有 '+d.linked_n+' 张已关联过，不在名单）' : '')+
      '。确认后批量标记为<b>无效</b> —— 只做标记不删文件，'+
      '在「无效图片」档可随时撤销。</p>'+
      '<div class="dupgrid">'+cells+'</div>'+
      (d.total > prevN ? '<p class="faint">仅预览前 '+prevN+
        ' 张，确认时全部 '+d.total+' 张一并标记。</p>' : ''),
    okText: '全部标为无效（'+d.total+' 张）',
    danger: true,
    onOk: async ()=>{
      let n = 0;
      for(let i = 0; i < d.ids.length; i += 400){   // 端点一次限 500
        const r = await post('/api/photos/invalid',
          {photo_ids: d.ids.slice(i, i + 400), invalid: true});
        n += r.updated || 0;
      }
      toast('已把 ' + n + ' 张标为无效', 'ok');
      window.dispatchEvent(new Event('photos:changed'));
    },
  });
}

/* ── 相似重复图片（2026-10-15 需求3）：dHash 指纹近邻 + 人工确认 ──
   每组建议保留一张（已关联优先），勾选其余张批量标无效。 */
async function _openDupModal(){
  const cid = getCid();
  if(!cid) return toast('先在右上角选择柜', 'err');
  busy(true);
  let d;
  try{ d = await api('/api/photos/dups?container_id=' + cid); }
  catch(e){ busy(false); return toast('读取失败：' + e.message, 'err'); }
  busy(false);
  if(!(d.groups || []).length){
    return toast(d.remaining
      ? '相似指纹还在计算（剩 ' + d.remaining + ' 张），请稍后再点一次'
      : '没发现相似的重复照片', 'ok');
  }
  const rows = (d.groups || []).map(g=>
    '<div class="duprow">'+
      '<div class="dupcell keep"><img loading="lazy" src="'+g.keep.thumb+'" '+
        'title="'+esc(g.keep.file)+'">'+
        '<span class="tag ok">建议保留'+(g.keep.linked ? ' · 已关联' : '')+'</span></div>'+
      g.others.map(o=>
        '<div class="dupcell"><label style="display:flex;align-items:center;gap:4px">'+
        '<input type="checkbox" checked data-dup-id="'+o.id+'">'+
        '<img loading="lazy" src="'+o.thumb+'" title="'+esc(o.file)+'"></label>'+
        '<span class="tag">'+esc(kindName(o.photo_kind) || '未分类')+'</span></div>').join('')+
    '</div>').join('');
  openModal({
    title: '重复图片（' + d.total_groups + ' 组）',
    width: 860,
    bodyHtml:
      '<p>每组左边是<b>建议保留</b>的一张（已关联的优先），'+
      '勾选的重复张将标记为<b>无效</b>（不删文件，可撤销）。</p>'+
      '<div class="duplist">'+rows+'</div>'+
      (d.remaining ? '<p class="faint">⚠️ 还有 ' + d.remaining +
        ' 张指纹未算完，稍后再点一次能找出更多。</p>' : '') +
      (d.total_groups > (d.groups || []).length ? '<p class="faint">仅显示前 ' +
        d.groups.length + ' 组。</p>' : ''),
    okText: '把勾选的标为无效',
    danger: true,
    onOk: async ()=>{
      const picked = [...document.querySelectorAll('input[data-dup-id]:checked')]
        .map(x => x.dataset.dupId);
      if(!picked.length) return '请先勾选要标无效的重复照片';
      let n = 0;
      for(let i = 0; i < picked.length; i += 400){
        const r = await post('/api/photos/invalid',
          {photo_ids: picked.slice(i, i + 400), invalid: true});
        n += r.updated || 0;
      }
      toast('已把 ' + n + ' 张重复照片标为无效', 'ok');
      window.dispatchEvent(new Event('photos:changed'));
    },
  });
}

/* ── ③ 按箱号分组展示（2026-10-14 老板需求）──
   箱号是采集时的物理归属（预检/{箱号}/照片.jpg），按它聚合 = 按「这箱货」
   看证据。交互复用照片库分组视图的卡片（.gcard：点组头展开、组内点照片
   进抽屉），开关与五档选项卡互斥显示。
   🔴 与五档共用一套筛选 baseQs（树/工具栏怎么筛，箱号分组就怎么算），
      pending（树上待确认细分）也照常生效。 */
let _wCarton = {on: false, page: 1, n: 0, total: 0, html: ''};
const CARTON_PAGE = 20;   // 箱号组视图每页组数（组卡片比照片卡高）
function _wBaseQs(cid){
  const val = id => { const e = $('#'+id); return e ? (e.value || '') : ''; };
  return {
    container_id: cid,
    // 树多选集合优先（逗号分隔 → 后端 IN），空则回退隐藏下拉
    state: val('wShState'),
    // 结构防御：取不到数组就当没选（宁可退化成下拉口径，也别抛异常把
    // 整个列表加载打断 —— 2026-10-19 的坑就是这么静默发生的）
    kind: (_wTree.kinds || []).length ? _wTree.kinds.join(',') : val('wShKind'),
    usage: (_wTree.usages || []).length ? _wTree.usages.join(',') : val('wShUsage'),
    q: val('wShQ').trim(),
    unlinked: ($('#wShUnlinked') && $('#wShUnlinked').checked) ? 1 : 0,
    todo: val('wShCand'),
    invalid: 'hide',
    pending: _wTree.pending ? 1 : 0};
}
/* 统一的③列表重载入口：箱号模式翻组，五档模式翻页（两者状态独立）。 */
function _wReload(cid, reset){
  if(_wCarton.on) return loadCartonGroups(cid, reset);
  return loadWizardPhotos(cid, reset);
}
async function loadCartonGroups(cid, reset){
  const box = $('#wizShots');
  if(!box || !cid) return;
  if(reset){
    _wCarton.page = 1; _wCarton.n = 0; _wCarton.total = 0; _wCarton.html = '';
    box.innerHTML = '<span class="faint">读取中…</span>';
  }
  const qs = new URLSearchParams(Object.assign({}, _wBaseQs(cid),
    {limit: CARTON_PAGE, offset: (_wCarton.page - 1) * CARTON_PAGE}));
  let d;
  try{ d = await api('/api/photos/carton-groups?' + qs); }
  catch(e){ box.innerHTML = '<span class="faint">箱号分组读取失败：' + esc(e.message) + '</span>'; return; }
  const items = d.items || [];
  _wCarton.html = items.map(cartonCardHtml).join('');   // 页码分页：替换不累积
  _wCarton.n = items.length;
  _wCarton.total = d.total || 0;
  box.innerHTML = _wCarton.html ||
    '<span class="faint">没有符合条件的照片</span>';
  // 组头点击展开/收起；组内照片点击走抽屉（阻止冒泡，同照片库分组视图）
  $$('#wizShots .gcard').forEach(card=>{
    card.onclick = e=>{
      if(e.target.closest('.shot')) return;
      card.classList.toggle('open');
      if(card.classList.contains('open')) bindShots('#wizShots');
    };
  });
  bindShots('#wizShots');
  // 箱号组视图页码（2026-10-20 老板：不要「加载更多」，普通翻页）
  const mb = $('#wShMore');
  if(mb){
    mb.style.display = '';
    mb.innerHTML = pagerHtml({page: _wCarton.page, size: CARTON_PAGE,
                              total: _wCarton.total});
    $$('[data-pg]', mb).forEach(b=>{
      b.onclick = ()=>{
        const p = parseInt(b.dataset.pg, 10);
        if(!p || p === _wCarton.page) return;
        _wCarton.page = p;
        loadCartonGroups(cid, false);
        try{ box.scrollIntoView({block:'start'}); }catch(e){}
      };
    });
  }
  const shown = $('#wShotsShown');
  if(shown) shown.textContent = _wCarton.total
    ? ('共 ' + _wCarton.total + ' 个箱号 · 已显示 ' + _wCarton.n + ' 组') : '';
}
function cartonCardHtml(g){
  const kindsHtml = Object.entries(g.kinds||{}).map(([k,n])=>
    '<span class="chip k-'+k+'">'+kindName(k)+(n>1?'×'+n:'')+'</span>').join('');
  const codesHtml = (g.codes||[]).slice(0,4).map(c=>
    '<span class="code">'+esc(c)+'</span>').join('')
    + ((g.codes||[]).length>4?'<span class="faint">+'+(g.codes.length-4)+'</span>':'');
  const linkedHtml = (g.linked_codes||[]).slice(0,3).map(c=>
    '<span class="linked">已关联 '+esc(c)+'</span>').join('');
  const name = g.carton_no || '未标注箱号';
  return '<div class="gcard" data-carton="'+esc(name)+'">'+
    '<div class="ghead">'+
      '<img class="gcover" loading="lazy" src="'+g.cover_thumb+'" alt="">'+
      '<div class="ginfo">'+
        '<div class="gtitle"><span class="gcount">'+g.count+' 张</span>'+
          '<span class="gtime">'+esc(name)+'</span></div>'+
        '<div class="gsum">'+kindsHtml+codesHtml+linkedHtml+'</div>'+
      '</div>'+
      '<span class="garrow">›</span>'+
    '</div>'+
    '<div class="gbody"><div class="gshots">'+
      (g.photos||[]).map(p=>shotCard(p)).join('')+'</div></div>'+
  '</div>';
}

/* ── ③ 监装照片 · 细分确认 ──
   待办 = (用途=监装 且 细分没人工确认) 或 (用途未标 但 模型给了细分建议)。
   tag→中文名由后端下发（pending.labels），前端不抄第二份。
   动作全部走既有端点：标用途 PATCH /api/photos/{id}/usage；
   确认细分 POST /api/photos/supervision-tag；采用建议 …/accept-ai。 */
let _supPend = null;
async function loadSupPending(cid){
  if(!cid){ _supPend = null; _refreshSupUI(); return; }
  try{ _supPend = await api('/api/containers/' + cid + '/supervision-pending'); }
  catch(e){ _supPend = null; _refreshSupUI('读取待确认失败：' + e.message); return; }
  _refreshSupUI();
}
function _suptagOptions(labels, cur){
  return '<option value="">未标注</option>' +
    Object.keys(labels).map(k=>'<option value="' + k + '"' +
      (cur === k ? ' selected' : '') + '>' + esc(labels[k]) + '</option>').join('');
}
/* 待办界面刷新（2026-10-14 起没有独立区块了，合并进左侧树 + 网格卡片）：
   ① 树上「待确认细分」的计数；
   ② 待确认视图里给网格卡片补操作行；
   ③ 顶部「全部采用建议」按钮状态。 */
function _refreshSupUI(errText){
  const items = (_supPend && _supPend.items) || [];
  _showSupBar(_wTree.pending);
  const allBtn = $('#wSupPendAll');
  if(allBtn){
    const n = items.filter(x => x.usage === '监装' && x.ai_tag).length;
    allBtn.disabled = !n;
    allBtn.textContent = n ? ('全部采用建议（' + n + '）') : '全部采用建议';
    // 批量采用建议：只动「监装 + 有建议」的，覆盖前确认
    allBtn.onclick = async ()=>{
      const ids = items.filter(x => x.usage === '监装' && x.ai_tag).map(x=>x.photo_id);
      if(!ids.length) return;
      if(!window.confirm('把 ' + ids.length + ' 张监装照全部采用模型建议的细分？')) return;
      allBtn.disabled = true;
      try{
        await post('/api/photos/supervision-tag/accept-ai', {photo_ids: ids});
        toast('已批量采用 ' + ids.length + ' 张建议', 'ok');
        _supReload();
      }catch(e){ allBtn.disabled = false; toast('批量采用失败：' + e.message, 'err'); }
    };
  }
  refreshWizardTree();
  if(_wTree.pending) _decoratePendingCards();
  if(errText) toast(errText, 'err');
}

/** 待确认视图：给网格里的待办卡片补一行操作（细分下拉 / 采用建议 / 标为监装）。
    待办数据来自 _supPend（与后端 supervision_pending_of 同一个集合），
    前端不重算第二份。 */
function _decoratePendingCards(){
  const items = (_supPend && _supPend.items) || [];
  const labels = (_supPend && _supPend.labels) || {};
  const grid = $('#wizShots');
  if(!grid) return;
  $$('#wizShots .shot').forEach(card=>{
    if(card.querySelector('.supact')) return;          // 已补过，别重复叠加
    const it = items.find(x=>String(x.photo_id) === card.dataset.id);
    if(!it) return;
    const conf = (it.ai_conf != null) ? Math.round(it.ai_conf * 100) : 0;
    const aiBit = it.ai_tag
      ? '<span class="tag acc" title="' + esc(it.ai_reason || '') + '">建议 ' +
        esc(labels[it.ai_tag] || it.ai_tag) + ' · ' + conf + '%</span>'
      : '<span class="faint">无建议</span>';
    const useBit = it.usage === '监装' ? ''
      : '<button class="btn ghost sm" data-supuse="' + it.photo_id + '"' +
        ' title="先标用途，才能确认细分（细分只对监装照有意义）">标为监装</button>';
    const row = document.createElement('div');
    row.className = 'supact';
    row.innerHTML =
      '<div class="row" style="gap:4px;flex-wrap:wrap">' + aiBit + useBit + '</div>' +
      '<div class="row" style="gap:4px;margin-top:2px">' +
        '<select data-suptag="' + it.photo_id + '" style="flex:1;min-width:0">' +
          _suptagOptions(labels, it.tag) + '</select>' +
        '<button class="btn sm" data-supacc="' + it.photo_id + '"' +
          ((it.usage === '监装' && it.ai_tag) ? '' : ' disabled') +
          ' title="采用模型建议的那一格">采用</button>' +
      '</div>';
    card.appendChild(row);
  });
  _bindSupAct(grid);
}
function _bindSupAct(root){
  root.querySelectorAll('[data-supuse]').forEach(b=>b.onclick = async ()=>{
    b.disabled = true;
    try{
      await patch('/api/photos/' + b.dataset.supuse + '/usage', {usage:'监装'});
      toast('已标为监装照 —— 现在可以确认细分了', 'ok');
      _supReload();          // 重拉待办 + 待办视图的网格重筛
    }catch(e){ b.disabled = false; toast('标用途失败：' + e.message, 'err'); }
  });
  root.querySelectorAll('[data-suptag]').forEach(sel=>sel.onchange = async ()=>{
    try{
      await post('/api/photos/supervision-tag',
        {photo_ids:[sel.dataset.suptag], tag: sel.value});
      toast('细分已确认', 'ok');
      _supReload();
    }catch(e){ toast('确认失败：' + e.message, 'err'); }
  });
  root.querySelectorAll('[data-supacc]').forEach(b=>b.onclick = async ()=>{
    const it = ((_supPend && _supPend.items) || [])
      .find(x=>String(x.photo_id) === b.dataset.supacc);
    const lab = (it && it.ai_tag && _supPend.labels) ? _supPend.labels[it.ai_tag] : '';
    b.disabled = true;
    try{
      await post('/api/photos/supervision-tag/accept-ai',
        {photo_ids:[b.dataset.supacc]});
      toast('已采用建议：' + (lab || (it && it.ai_tag) || ''), 'ok');
      _supReload();
    }catch(e){ b.disabled = false; toast('采用失败：' + e.message, 'err'); }
  });
}
/** 待办动作后统一刷新：先重拉待办数据（计数/卡片装饰），再重筛网格 ——
    只刷数据不重筛的话，确认过的那张还挂在待办视图里（2026-10-14 修）。 */
async function _supReload(){
  await loadSupPending(getCid());
  if(_wTree.pending) loadWizardPhotos(getCid(), true);
}

/* ── ④ 选图（原⑤的取材，独立成步）── */

/* 柜级统计条：本柜**全量**，进④就有，不必先点检索。
   🔴 数字全部由后端 `/api/containers/{cid}/progress` 的 steps.picks.stats 下发，
   与下面检索列表的「命中」同源 —— 前端只负责显示，**绝不在本地另算一套**
   （算两套必然漂移：铁律 23）。
   「已采用」是唯一的客户端状态（采用结果存在 localStorage），所以单独一格，
   且必须在采用/清空后跟着变。 */
function _picksStats(){
  return (_prog && _prog.steps && _prog.steps.picks && _prog.steps.picks.stats) || null;
}
function _statCell(n, label, cls){
  return '<span class="wpstat-c' + (cls ? ' ' + cls : '') + '"><b>' + n + '</b><em>' +
    esc(label) + '</em></span>';
}
function picksStatsHtml(){
  const s = _picksStats();
  if(!s || !s.codes_total)
    return '<div class="wpstat"><div class="faint">这个柜还没有清单编码 —— 先到②导入清单。</div></div>';
  const cc = Object.keys(_wPicks).length;
  /* 老板 10-11：统计条只常显关键指标（清单编码 / 命中 / 缺口 / 占比 / 已采用），
     其余（产品库已有 / 本柜照片 / 已关联命中 / 标准图）默认收起，展开才显示 ——
     一眼要看的是「缺口还剩多少」，不是全部数字。 */
  return '<div class="wpstat">' +
    '<div class="wpstat-row">' +
      _statCell(s.codes_total, '清单编码（种）') +
      _statCell(s.with_photo, '有照片·命中（种）', 'ok') +
      _statCell(s.missing, '缺口（种）', s.missing ? 'warn' : 'ok') +
      '<span class="wpstat-rate">命中占比 <b>' + s.hit_rate + '%</b></span>' +
      '<span class="wpstat-c" id="wPickStatAdopt">' + _adoptCellHtml(cc) + '</span>' +
      '<span class="spacer"></span>' +
      '<button class="btn ghost sm" id="wStatMoreBtn" title="展开次要指标">其他指标 ▾</button>' +
    '</div>' +
    '<div class="wpstat-bar" title="命中 ' + s.with_photo + ' / 清单 ' + s.codes_total + '">' +
      '<i style="width:' + s.hit_rate + '%"></i></div>' +
    '<div class="wpstat-row" id="wStatMore" style="display:none">' +
      _statCell(s.in_lib, '产品库已有（种）') +
      _statCell(s.photo_total, '本柜照片（张）') +
      _statCell(s.photo_linked, '其中已关联·命中（张）', 'ok') +
      _statCell(s.std_photos, '其中标准图（张）', 'std') +
      '<span class="faint">本柜全量口径；下面列表是本次检索的范围，两者可能不同。</span>' +
    '</div>' +
  '</div>';
}
/* 统计条「其他指标」展开/收起 —— 重绘后状态由按钮文字恢复，不另存状态。 */
function bindStatsToggle(){
  const btn = $('#wStatMoreBtn'), box = $('#wStatMore');
  if(!btn || !box) return;
  const open = box.style.display !== 'none';
  btn.textContent = open ? '其他指标 ▴' : '其他指标 ▾';
  btn.onclick = ()=>{
    const nowOpen = box.style.display !== 'none';
    box.style.display = nowOpen ? 'none' : '';
    btn.textContent = nowOpen ? '其他指标 ▾' : '其他指标 ▴';
  };
}
function _adoptCellHtml(cc){
  const n = pickCount();
  return '<b' + (n ? ' class="ok"' : '') + '>' + cc + '</b><em>已采用（' + n + ' 张）</em>';
}
/* 采用/清空后刷新「已采用」那一格 —— 统计条其余数字是柜级全量，不受采用影响。 */
function _updPickStat(){
  const el = $('#wPickStatAdopt');
  if(el) el.innerHTML = _adoptCellHtml(Object.keys(_wPicks).length);
}
/* ④ 当前选项卡：'pre' 预检照片（编码核对照） | 'sup' 监装照片。
   老板 10-11：两类照片混在一页里不清晰，分两个选项卡。
   状态存 localStorage（按柜）—— 刷新后停在上次看的那个卡。 */
let _wPickTab = 'pre';
function _pickTabKey(){
  try{ return localStorage.getItem('wizPickTab:' + getCid()) || 'pre'; }catch(e){ return 'pre'; }
}
function _setPickTab(t){
  _wPickTab = t === 'sup' ? 'sup' : 'pre';
  try{ localStorage.setItem('wizPickTab:' + getCid(), _wPickTab); }catch(e){}
  renderPickTabs();
}
function detailPicks(){
  _wPickTab = _pickTabKey();
  const blocked = _prog.steps.checklist.row_total === 0;
  /* 编码池全自动：进④自动载清单编码并检索（bindStep 里做），不再给
     「载入该柜清单编码 / 解析文本」两个手动按钮（老板 10-11 去掉）。 */
  return '<div class="wdh">给报告挑用图<span class="faint">一个编码可多张；不选则按编码自动取一张</span></div>' +
    '<div class="seg" id="wPickTabs" style="margin-bottom:10px">' +
      '<button data-wpt="pre">预检照片（编码核对）</button>' +
      '<button data-wpt="sup">监装照片（柜况④/卡车⑦）</button>' +
    '</div>' +
    '<div id="wPickPre">' +
      picksStatsHtml() +
      '<div class="row" style="margin-top:8px">' +
        '<span class="faint" id="wPickTip"></span>' +
        (blocked ? '<span class="tag warn">先完成②导入清单，才能挑核对照</span>' : '') +
      '</div>' +
      '<div id="wCaiResult" class="wgen-result"></div>' +
    '</div>' +
    '<div id="wPickSup" style="display:none">' +
      /* 监装照片：老板 10-11 反馈「选图时没看到监装的照片」——④柜况/⑦卡车
         以前全在报告里自动取，界面上根本看不见。现在给全量候选：柜况每类
         点一张（第一张标「自动」= 不点也是它），卡车点选进⑦。 */
      '<div class="wdh" style="margin-top:4px">监装照片' +
        '<span class="faint">柜况④每类可挑多张 · 卡车⑦点选进报告；不动 = 自动取</span>' +
        '<span class="spacer"></span>' +
        '<button class="btn ghost sm" id="wSupReset"' + (supTouched() ? '' : ' disabled') +
        ' title="清掉人工指定，报告④⑦回到自动取图">恢复自动</button></div>' +
      '<div id="wSupBox"><div class="faint">读取监装照片…</div></div>' +
    '</div>';
}
/* 选项卡切换：预检/监装两块 DOM 都常驻（切的是 display，不重渲染）——
   采用标记、滚动位置都不丢。切到「监装」时顺手重拉一次候选（③里
   可能刚确认过细分，候选分组会变）。 */
function renderPickTabs(){
  const seg = $('#wPickTabs');
  if(!seg) return;
  seg.querySelectorAll('[data-wpt]').forEach(b=>{
    b.classList.toggle('on', b.dataset.wpt === _wPickTab);
    b.style.background = b.dataset.wpt === _wPickTab ? 'var(--brand-soft)' : '';
    b.style.color = b.dataset.wpt === _wPickTab ? 'var(--brand)' : '';
    b.style.fontWeight = b.dataset.wpt === _wPickTab ? '600' : '';
  });
  const pre = $('#wPickPre'), sup = $('#wPickSup');
  if(pre) pre.style.display = _wPickTab === 'pre' ? '' : 'none';
  if(sup) sup.style.display = _wPickTab === 'sup' ? '' : 'none';
  if(_wPickTab === 'sup' && getCid()) loadSupPhotos(getCid());
}
function bindPickTabs(){
  const seg = $('#wPickTabs');
  if(!seg) return;
  seg.querySelectorAll('[data-wpt]').forEach(b=>{
    b.onclick = ()=>_setPickTab(b.dataset.wpt);
  });
}
/* ── ④ 的监装照片区块：候选来自后端分组（柜况4类+卡车3类，组内最新在前）──
   🔴 分组口径（哪些 tag 是柜况、哪些进⑦、tag 中文名）由后端下发，前端
   不抄第二份 —— 抄两份必然漂移（铁律 23 的 JS 版）。 */
async function loadSupPhotos(cid){
  if(!cid){ _supGroups = null; renderSup(); return; }
  try{
    _supGroups = await api('/api/containers/' + cid + '/supervision-photos');
  }catch(e){
    _supGroups = null;
    renderSup('读取监装照片失败：' + e.message);
    return;
  }
  renderSup();
}
function _supShot(p, kind, tag, label){
  const picked = kind === 'cond'
    ? (_wConds[tag] || []).includes(String(p.photo_id))
    : _wTrucks.includes(String(p.photo_id));
  // cond 组第一张 = taken_at 最新的 = 后端不点时的自动值 → 标「自动」
  const mark = picked ? '<span class="rec mine">✓' + (kind === 'cond' ? '④' : '⑦') + '</span>'
                      : (p.auto ? '<span class="rec">自动</span>' : '');
  return '<div class="wcai-shot' + (picked ? ' pick' : '') + '" data-sup="' + p.photo_id +
    '" data-kind="' + kind + '" data-tag="' + esc(tag) +
    '" title="' + (kind === 'cond' ? '加入/移出报告④「' + label + '」（可多张）' : '加入/移出报告⑦') + '">' +
    '<img loading="lazy" src="/thumb/' + p.photo_id + '">' +
    '<span class="wcai-zoom" data-supzoom="' + p.photo_id +
    '" data-cap="' + esc(label) + '" data-taken="' + esc(p.taken_at || '') +
    '" title="看大图（点图片本身 = 选定）">⤢</span>' +
    mark + '</div>';
}
function renderSup(errText){
  const box = $('#wSupBox');
  if(!box) return;
  const rs = $('#wSupReset');
  if(rs) rs.disabled = !supTouched();
  if(errText){ box.innerHTML = '<span class="tag err">' + esc(errText) + '</span>'; return; }
  if(!_supGroups){ box.innerHTML = '<div class="faint">读取监装照片…</div>'; return; }
  if(!_supGroups.total){
    box.innerHTML = '<div class="faint">本柜还没有已确认细分的监装照片。' +
      '到<b>③照片</b>的「监装照片 · 细分确认」里给监装照打细分（或采用模型建议），' +
      '确认完这里就能按柜况④/卡车⑦挑图。</div>';
    return;
  }
  box.innerHTML = _supGroups.groups.filter(g => g.items.length).map(g =>
    '<div class="wcai-item"><b class="code">' + esc(g.label) + '</b> · ' +
    (g.kind === 'cond' ? '报告④（每类可多张）' : '报告⑦') +
    ' · ' + g.items.length + ' 张' +
    '<div class="wcai-shots">' + g.items.map((p, i) =>
      _supShot({ photo_id: p.photo_id, taken_at: p.taken_at,
                 auto: g.kind === 'cond' && i === 0 }, g.kind, g.tag, g.label)
    ).join('') + '</div></div>').join('');
  box.querySelectorAll('[data-sup]').forEach(el=>el.onclick = ()=>{
    const pid = String(el.dataset.sup), kind = el.dataset.kind, tag = el.dataset.tag;
    if(kind === 'cond'){
      const arr = _wConds[tag] || [];
      const i = arr.indexOf(pid);
      if(i >= 0) arr.splice(i, 1); else arr.push(pid);   // 多选 toggle
      _wConds[tag] = arr;
    }else{
      const i = _wTrucks.indexOf(pid);
      if(i >= 0) _wTrucks.splice(i, 1); else _wTrucks.push(pid);
    }
    saveSup(); renderSup(); renderBar();   // 步骤条「已选 N 张」跟着变
  });
  // 看大图：复用照片页查看器；必须 stopPropagation（角标在缩略图内部）
  box.querySelectorAll('[data-supzoom]').forEach(el=>el.onclick = (e)=>{
    e.stopPropagation();
    openViewer('/img/' + el.dataset.supzoom, el.dataset.cap, el.dataset.taken);
  });
}
function bindSupReset(){
  const rs = $('#wSupReset');
  if(rs) rs.onclick = ()=>{
    if(supTouched() && !window.confirm('清掉监装照片的人工指定？\n\n报告④回到每类最新一张（多选清空），⑦回到全部监装照。')) return;
    resetSup(); renderSup(); renderBar();
    toast('监装照片已恢复自动取图', 'ok');
  };
}
async function wLoadCodes(cid, quiet){
  try{
    const d = await api('/api/containers/' + cid + '/checklist');
    const rows = d.items || [];
    if(!rows.length){
      if(!quiet) toast('这个柜还没有清单行快照（先到②导入清单）', 'err');
      _wCodes = [];
      return 0;
    }
    const seen = new Set(); _wCodes = [];
    for(const r of rows){ if(r.code_norm && !seen.has(r.code_norm)){ seen.add(r.code_norm); _wCodes.push(r.code_norm); } }
    if(!quiet) toast('已载入 ' + _wCodes.length + ' 个编码', 'ok');
    return _wCodes.length;
  }catch(e){ if(!quiet) toast('载入失败：' + e.message, 'err'); return 0; }
}
/* ④选图的自动策略。可选清单由**后端下发**（/api/report/lookup 的 strategies），
   前端不再自己抄一份 —— 抄两份必然漂移。默认 balanced = 原行为。 */
let _wStrategy = 'balanced';
let _wStrategies = [];
function _strategyOptions(){
  const list = (_wStrategies && _wStrategies.length)
    ? _wStrategies
    : [{ key:'balanced', label:'均衡（标准图 / 最新 / 高清 综合打分）' }];
  return list.map(s => '<option value="'+esc(s.key)+'"' +
    (s.key === _wStrategy ? ' selected' : '') + '>' + esc(s.label) + '</option>').join('');
}

async function wLookup(cid, quiet){
  if(!_wCodes.length) return toast('还没有清单编码 —— 先到②导入清单', 'err');
  busy(true, '检索中…', _wCodes.length + ' 个编码');
  try{
    _lastRp = await post('/api/report/lookup', { codes:_wCodes, container_id:cid,
      std_only:false, std_prefer:true, strategy:_wStrategy });
    if(_lastRp.strategies && _lastRp.strategies.length) _wStrategies = _lastRp.strategies;
    renderWResult();
    renderBar();
    if(!quiet){
      const miss = (_lastRp.missing != null) ? _lastRp.missing
        : (_lastRp.items || []).filter(x=>!x.found).length;
      toast('命中 ' + _lastRp.matched + ' · 缺口 ' + miss, 'ok');
    }
  }catch(e){ toast('检索失败：' + e.message, 'err'); }
  busy(false);
}
function renderWResult(){
  const box = $('#wCaiResult');
  const tip = $('#wPickTip');
  if(!box) return;
  const n = pickCount();
  if(tip) tip.textContent = n ? ('已采用 ' + n + ' 张，会作为报告⑥的用图')
                              : '还没标记采用 —— 不标记也能出报告（按编码自动取图）';
  const r = _lastRp;
  if(!r){ box.innerHTML = ''; return; }
  const items = (r.items || []).filter(x => x.found);
  const miss  = (r.items || []).filter(x => !x.found).length;
  const recN  = items.filter(it => (it.photos || []).some(p => p.recommended)).length;

  box.innerHTML =
    '<div class="wclbar" style="margin:6px 0">' +
      '<span class="faint">命中 ' + items.length + ' · 缺口 ' + miss + ' · 已采用 ' + n + ' 张</span>' +
      '<span class="spacer"></span>' +
      '<label class="faint" title="决定每个编码「建议采用」哪一张；切换后按新策略重算">' +
        '自动选图 <select id="wPickStrategy" style="margin-left:4px">' +
        _strategyOptions() + '</select></label>' +
      '<button class="btn sm" id="wAdoptAll"' + (recN ? '' : ' disabled') +
        ' title="每个编码采用后端推荐的那张（按上面选的策略）">' +
        '全部采用建议图（' + recN + '）</button>' +
      '<button class="btn ghost sm" id="wClearPicks"' + (n ? '' : ' disabled') + '>清空采用</button>' +
    '</div>' +
    items.map(it=>{
      const pick = (_wPicks[it.code_norm] || []).map(String);
      const shots = (it.photos || []).map(p=>{
        const isPick = pick.includes(String(p.photo_id));
        const tag = p.recommended ? '<span class="rec">建议</span>' : '';
        return '<div class="wcai-shot' + (isPick ? ' pick' : '') + '" data-pid="' + p.photo_id +
          '" data-code="' + esc(it.code_norm) + '" title="点击' +
          (isPick ? '取消采用' : '设为报告用图') + (p.reasons && p.reasons.length ? '：' + esc(p.reasons[0]) : '') + '">' +
          '<img loading="lazy" src="/thumb/' + p.photo_id + '">' +
          // 「看大图」单独一个角标：点图片本身仍是采用/取消（肌肉记忆不能改），
          // 这个角标只负责放大看细节，且必须 stopPropagation 防止误触发采用。
          '<span class="wcai-zoom" data-zoom="' + p.photo_id + '"' +
            ' data-cap="' + esc(it.code || it.code_norm || '') + '"' +
            ' data-taken="' + esc(p.taken_at || '') + '"' +
            ' title="看大图（点图片本身 = 设为报告用图）">⤢</span>' +
          (isPick ? '<span class="rec mine">✓</span>' : tag) + '</div>';
      }).join('');
      const rec = (it.photos || []).find(p => p.recommended);
      return '<div class="wcai-item"><b class="code">' + esc(it.code) + '</b> · ' +
        (it.photo_count || 0) + ' 张可用' +
        '<button class="btn ghost sm" data-adopt="' + esc(it.code_norm) + '"' +
        (rec ? '' : ' disabled') + ' title="采用推荐的那张">采用建议图</button>' +
        '<div class="wcai-shots">' + shots + '</div></div>';
    }).join('');

  box.querySelectorAll('.wcai-shot').forEach(el=>el.onclick = ()=>{
    const code = el.dataset.code, pid = el.dataset.pid;
    const arr = _wPicks[code] || (_wPicks[code] = []);
    const i = arr.indexOf(pid);
    if(i >= 0) arr.splice(i, 1); else arr.push(pid);
    if(!arr.length) delete _wPicks[code];
    savePicks();
    renderWResult();
    renderBar();                       // ④ 状态（已选 N 张）跟着变
  });
  box.querySelectorAll('[data-adopt]').forEach(b=>b.onclick = ()=>{
    const code = b.dataset.adopt;
    const it = (r.items || []).find(x => x.code_norm === code);
    const rec = it && (it.photos || []).find(p => p.recommended);
    if(!rec) return;
    _wPicks[code] = [String(rec.photo_id)];
    savePicks(); renderWResult(); renderBar();
  });
  // 切换自动选图策略 → 按新策略重算「建议采用」的那张
  const ps = $('#wPickStrategy');
  if(ps) ps.onchange = ()=>{
    _wStrategy = ps.value;
    const lb = (_wStrategies.find(s => s.key === _wStrategy) || {}).label || _wStrategy;
    wLookup(getCid(), true).then(()=>toast('已切换为「' + lb + '」，建议图已重算', 'ok'));
  };
  // 看大图：复用照片页那个查看器（自带拍照时间）。
  // ⚠️ 必须 stopPropagation —— 角标在缩略图内部，不拦会顺带触发「采用/取消」。
  box.querySelectorAll('[data-zoom]').forEach(el=>el.onclick = (e)=>{
    e.stopPropagation();
    openViewer('/img/' + el.dataset.zoom, el.dataset.cap, el.dataset.taken);
  });
  const aa = $('#wAdoptAll');
  if(aa) aa.onclick = ()=>adoptAllRecommended(r);
  const cp = $('#wClearPicks');
  if(cp) cp.onclick = ()=>{
    if(pickCount() && !window.confirm('清空本柜已选的全部用图？')) return;
    for(const k of Object.keys(_wPicks)) delete _wPicks[k];
    savePicks(); renderWResult(); renderBar();
    toast('已清空采用', 'ok');
  };
}
/* 批量采用：每个编码取后端推荐的那张。
   ⚠️ 覆盖前必须确认 —— 手动挑过的会被冲掉，而那些往往是老板特意选的。 */
function adoptAllRecommended(r){
  const withRec = (r.items || []).filter(x => x.found && (x.photos || []).some(p => p.recommended));
  if(!withRec.length) return toast('这次检索没有带「建议采用」的结果', 'err');
  const cur = pickCount();
  if(cur && !window.confirm('把 ' + withRec.length + ' 个编码全部设为建议图？\n\n' +
      '会覆盖你已手动指定的 ' + cur + ' 张用图。')) return;
  withRec.forEach(x=>{
    const rec = x.photos.find(p => p.recommended);
    if(rec) _wPicks[x.code_norm] = [String(rec.photo_id)];
  });
  savePicks(); renderWResult(); renderBar();
  toast('已批量采用 ' + withRec.length + ' 个编码的建议图', 'ok');
}

/* ── ⑤ 生成报告（不含取材）── */
function detailReport(){
  return '<div class="wdh">生成选项</div>' +
    '<div class="genopts">' +
      '<label><input type="checkbox" id="wReverse" checked> ⑥倒序（对齐样例）</label>' +
      '<label>画质 <select id="wLong"><option value="1200" selected>1200px（推荐）</option>' +
        '<option value="1600">1600px</option></select></label>' +
      '<label title="④选了图就用它；没选则按编码自动取一张">' +
        '<input type="checkbox" id="wUsePicks" checked> ⑥用④选定的照片</label>' +
    '</div>' +
    // 结果卡由**状态**渲染 —— 直接塞 DOM 会被 loadProgress 的重绘冲掉
    '<div id="wGenResult">' + _genResultHtml + '</div>' +
    '<div id="wRepBox">' + detailReportList() + '</div>';
}
function detailReportList(){
  if(!_reports) return '<div class="faint">读取报告…</div>';
  const cno = _prog.container_no;
  const mine = (_reports.items || []).filter(f => f.container_no === cno);
  if(!mine.length) return '<div class="faint">这个柜还没生成过报告。</div>';
  return '<div class="wdh" style="margin-top:12px">本柜历史报告（' + mine.length + '）</div>' +
    '<div class="wdlist">' + mine.slice(0,5).map(f=>
      '<div class="row"><span class="nm" title="' + esc(f.name) + '">' + esc(f.name) + '</span>' +
      '<span class="faint">' + fmtSize(f.bytes) + '</span>' +
      '<span class="faint">' + esc((f.mtime||'').replace('T',' ').slice(0,16)) + '</span>' +
      '<a class="btn ghost sm" href="' + esc(f.download) + '">下载</a></div>').join('') + '</div>' +
    (mine.length > 5
      ? '<div class="faint" style="margin-top:6px">仅显示 5 份，全部见「报告档案」</div>' : '');
}
async function loadReports(){
  try{ _reports = await api('/api/report/loading-list'); }
  catch(e){ _reports = { items: [] }; }
}
async function genReport(cid){
  const usePicks = $('#wUsePicks') && $('#wUsePicks').checked;
  // picks 新格式 {codes, trucks, conds}：只在「真动过」时才带对应键 ——
  // trucks: [] 是「明确一张都不要」（⑦ 留空），没动过则不带键（后端自动取）。
  // 监装照没动过但编码选了 → 只带 codes，监装照照旧自动。
  const sup = supTouched();
  const picks = (usePicks && (pickCount() || sup)) ? Object.assign(
    pickCount() ? { codes: { ..._wPicks } } : {},
    sup ? { trucks: _wTrucks.slice(), conds: { ..._wConds } } : {}
  ) : null;
  busy(true, '正在生成报告…');
  try{
    const r = await post('/api/report/loading-docx', {
      container_id: cid,
      reverse: $('#wReverse').checked,
      long_edge: parseInt($('#wLong').value) || 1200,
      picks: picks || undefined });
    _genResultHtml = '<div class="panel" style="margin:8px 0 0">' +
      '<div class="phead"><h3>已生成 ' + esc(r.container_no) + '</h3></div>' +
      '<div class="faint">清单 ' + (((r.summary || {}).row_total) ?? '—') + ' 行 · ' +
        '嵌入图片 ' + r.photos + ' 张 · ' + (r.bytes / 1048576).toFixed(1) + ' MB</div>' +
      '<div class="row" style="margin-top:8px"><a class="btn sm" href="' + esc(r.download) + '">下载 docx</a>' +
      '<a class="btn ghost sm" href="#" id="wToReport2">去报告档案</a></div></div>';
    toast('装柜报告已生成（' + r.photos + ' 图）', 'ok');
    _reports = null;              // 让本柜历史重新拉（否则看不到刚生成的这份）
    loadProgress(false);
  }catch(e){
    toast('生成失败：' + e.message, 'err');
    _genResultHtml = '<span class="tag err">生成失败：' + esc(e.message) + '</span>';
    loadProgress(false);
  }
  busy(false);
}

/* ── 每步的绑定 ── */
function bindStep(key){
  const cid = getCid();
  const goProducts = $('#wToProducts') || $('#wToProducts2');
  if(goProducts) goProducts.onclick = e=>{ e.preventDefault(); go('products'); };

  if(key === 'container'){
    const b = $('#wNew'); if(b) b.onclick = openContainerModal;
    const sw = $('#wSwitch'); if(sw) sw.onclick = ()=>{ const s = $('#wizCid'); if(s) s.focus(); };
    const sv = $('#wMetaSave'); if(sv) sv.onclick = saveMeta;
    const rs = $('#wMetaReset'); if(rs) rs.onclick = ()=>{ metaReset(); };
    $$('#wDetail [data-mf]').forEach(el=>{ el.oninput = metaSync; });
    metaSync();
    loadRecent();
  }
  if(key === 'checklist'){
    const b = $('#wImpCl'); if(b) b.onclick = ()=>openImportChecklistModal(cid);
    const t = $('#wTmpl'); if(t) t.onclick = ()=>{ window.location.href = '/api/products/template'; };
    bindChecklist(cid);
  }
  if(key === 'photos'){
    const b = $('#wImpPh'); if(b) b.onclick = ()=>openImportPhotosModal(cid);
    // 治理抽屉开关（2026-10-20 老板：从下方折叠面板改成右侧抽屉，不占高度）。
    // ⚠️ 必须绑在 innerHTML 之后 —— 按钮是标题行的一部分，早于此是 null（点了没反应）。
    // 🔴 必须设 **style.display**，不能只加 class：#wizGovWrap 在 index.html 里带
    //    内联 style="display:none"，内联优先级高于 CSS 类 —— `.on{display:flex}`
    //    会被压住，表现就是「class 加上了、display 仍是 none、点了没反应」（老板报的）。
    // 🔴 2026-10-21：开关按钮**本身会被抽屉盖住**（抽屉 fixed 右侧 560px/z-index 70，
    //    按钮在标题行最右缘），所以「再点一次开关关闭」这条路径在真实鼠标下不可用。
    //    关闭改由三条独立路径承担：抽屉内 ✕ 按钮 / Esc / 点面板外（见文件头注释）。
    //    开关按钮保留为「打开」入口（抽屉关着时它在最右缘、点得到）。
    const gw = $('#wizGovWrap'), gt = $('#wGovToggle');
    // 切到③时收起抽屉 —— 但**别把用户刚开的抽屉又关掉**：renderBody 会因
    // 各种刷新（loadProgress / 治理轮询）重跑并再次 bindStep，若无条件
    // display='none'，用户打开抽屉后下一次刷新就自己消失了。
    // 判据用 _govOpen（本文件顶部的抽屉状态），不是读 style.display。
    if(gw) gw.style.display = _govOpen ? 'flex' : 'none';
    if(gt && gw) gt.onclick = ()=>{
      if(_govOpen) closeGovDrawer(); else openGovDrawer();
    };
    loadBatches(); loadGovernInfo();          // 治理面板在这一步里，随用随刷
    // 左侧树（用途/分类/监装待确认）+ 批量选择操作条（与照片库同款实现）
    selReset();                               // 别把照片库那边的勾选带进来
    selSetIds(W_SEL_IDS);
    // 🔴 必须是多选结构 {usages,kinds}：写成旧的 {usage,kind} 会让
    //    _wTree.kinds.length 抛 TypeError（async 函数里变成 rejected
    //    promise，静默吞掉）→ 进③首屏列表一张不出，要等用户点了树才恢复
    //    （2026-10-19 多选改造漏改这一处，CDP 实测抓到）。
    _wTree = {usages:[], kinds:[], pending:false};
    _wCarton = {on:false, off:0, n:0, total:0, html:''};   // 箱号分组开关复位
    const cb = $('#wShCarton'); if(cb) cb.classList.remove('on');
    loadWizardPhotos(cid, true);
    loadSupPending(cid);                      // 监装细分确认待办（喂树上的计数）
    refreshWizardTree();
    // 筛选控件：改动即刷新（只改显示、不写库）。箱号模式开着 → 刷组。
    const e0 = $('#wShState');
    if(e0) e0.onchange = ()=>{ _wReload(cid, true); refreshWizardTree(); };
    const ql = $('#wShQ');
    if(ql) ql.addEventListener('keydown', e=>{ if(e.key === 'Enter'){ _wReload(cid, true); refreshWizardTree(); } });
    const ul = $('#wShUnlinked');
    if(ul) ul.onchange = ()=>{ _wReload(cid, true); refreshWizardTree(); };
    const sb = $('#wShSearch'); if(sb) sb.onclick = ()=>{ _wReload(cid, true); refreshWizardTree(); };
    // 关联待办下拉（2026-10-15 老板需求）：改动即刷新，列表与树同口径
    const wc = $('#wShCand');
    if(wc) wc.onchange = ()=>{ _wReload(cid, true); refreshWizardTree(); };
    const rs = $('#wShReset');
    if(rs) rs.onclick = ()=>{
      ['wShState','wShKind','wShUsage','wShCand'].forEach(id=>{ const e = $('#'+id); if(e) e.value = ''; });
      if(ql) ql.value = '';
      if(ul) ul.checked = false;
      _wTabs = tabsInit();          // 重置也把分组档拨回「全部」
      _wTree = {usages:[], kinds:[], pending:false};   // 树的选中一起清
      $('#wizShots').classList.remove('pending');
      _showSupBar(false);
      _wReload(cid, true);
      refreshWizardTree();
    };
    // 按箱号分组开关：与五档选项卡互斥显示；组内点照片照常进抽屉
    const cb2 = $('#wShCarton');
    if(cb2) cb2.onclick = ()=>{
      _wCarton.on = !_wCarton.on;
      cb2.classList.toggle('on', _wCarton.on);
      const tabs = $('#wShTabs'); if(tabs) tabs.style.display = _wCarton.on ? 'none' : '';
      const grid = $('#wizShots');
      if(grid){
        grid.classList.toggle('grid', !_wCarton.on);
        grid.classList.toggle('glist', _wCarton.on);
      }
      _wReload(cid, true);
    };
    // 系统识别 + 人工确认的两个清理入口（2026-10-15 需求2/3）——
    // 现在收在「更多 ▾」里（工具条分区），点完一项就收起下拉
    const _closeMore = ()=>{ const m = $('#wMoreDrop'); if(m) m.classList.remove('open'); };
    const ci = $('#wCleanInvalid');
    if(ci) ci.onclick = ()=>{ _closeMore(); _openCleanInvalid(); };
    const db = $('#wDupBtn');
    if(db) db.onclick = ()=>{ _closeMore(); _openDupModal(); };
    // 「更多 ▾」开关。⚠️ ③ 的 DOM 是进视图才渲染的 —— 必须在这里（渲染后）
    // 绑，模块加载期 $('#wMoreBtn') 是 null，绑了会打断整个 wizard.js。
    // stopPropagation：别让 document 那个「点外面关」的监听立刻把它关掉。
    const mb2 = $('#wMoreBtn');
    if(mb2) mb2.onclick = e=>{ e.stopPropagation();
      const d = $('#wMoreDrop'); if(d) d.classList.toggle('open'); };
    // 批量选择（标记无效 / 改判分类）：成功后的刷新走 photos:changed 监听
    // （下面那个），这里只负责把操作条接到③的 id 上。
    // ⚠️ 必须 !selOn() 切换：写死 true 的话，进了选择模式再点顶部按钮
    //    （文字已变成「退出选择」）退不出来（2026-10-15 修，与照片库一致）。
    $('#wSelBtn').onclick = ()=>selSetMode(!selOn(), W_SEL_IDS, ()=>{
      window.dispatchEvent(new Event('photos:changed'));
    });
    selBindBar(W_SEL_IDS, ()=>{
      window.dispatchEvent(new Event('photos:changed'));
    });
    // 批量改判分类（2026-10-15 需求2）：③ 与照片库同一份实现 —— 勾一批 →
    // 选分类 → 应用（POST /api/photos/kind，只写 kind 标记不动文件）。
    // 改完清勾选、**不退出选择模式**（与照片库行为一致）。
    const wsk = $('#wSelKind');
    if(wsk && wsk.options.length<=1){
      wsk.innerHTML = '<option value="">改判分类…</option>' +
        Object.keys(KIND_LABELS).map(k=>'<option value="'+esc(k)+'">'+
          esc(KIND_LABELS[k])+'</option>').join('');
    }
    const wskd = $('#wSelKindDo');
    if(wskd) wskd.onclick = async ()=>{
      const k = wsk ? wsk.value : '';
      if(!k) return toast('先选要改成哪个分类', 'err');
      if(!selSize()) return toast('先勾选照片', 'err');
      try{
        const r = await post('/api/photos/kind', {photo_ids: selIds(), kind: k});
        toast('已把 ' + r.updated + ' 张改判为「' + kindName(k) + '」', 'ok');
        if(wsk) wsk.value = '';
        selClear(); selUpdBar(W_SEL_IDS);
        // 列表/徽章/树/待办计数一把刷（改分类会动「按分类」计数与关联待办集合）
        window.dispatchEvent(new Event('photos:changed'));
      }catch(e){ toast('改判失败：' + e.message, 'err'); }
    };
    // 全选当前筛选结果（2026-10-15 需求1）：口径与列表一致（含当前档）
    const waf = $('#wSelAllFiltered');
    if(waf) waf.onclick = async ()=>{
      const qs = new URLSearchParams(Object.assign({}, _wBaseQs(cid),
        {flag: _wTabs.tab, limit: 5000, offset: 0}));
      if(_wTabs.tab === 'invalid') qs.set('invalid', 'only');
      if(_wTabs.tab === 'ignored') qs.set('ignored', 'only');
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
    // ⚠️ 不再给 #wShMore 绑「加载更多」：它是页码容器，onclick 由 renderPager
    //    逐页重绑。容器级 onclick 会被页码按钮冒泡触发 → 一次点击加载两遍。
  }
  if(key === 'picks'){
    bindPickTabs(); renderPickTabs(); bindStatsToggle();
    const lk = $('#wLookup2'); if(lk) lk.onclick = ()=>{ _lpFor = ''; wLookup(cid); };
    loadPicks();
    loadSup();
    loadSupPhotos(cid);
    bindSupReset();
    // 自动：进④就载入本柜清单编码 → 直接检索出图。
    // 老板点进来是为了「看图挑图」，让他先点两次「载入」再点「检索」是白挡路。
    // 每个柜只自动跑一次（_lpFor），重复进页面不重刷。
    if(_lpFor !== cid){
      _lpFor = cid;
      wLoadCodes(cid, true).then(n => { if(n) wLookup(cid, true); });
    }else if(_lastRp){
      renderWResult();
    }
  }
  if(key === 'report'){
    const b = $('#wGen'); if(b) b.onclick = ()=>genReport(cid);
    const toR = $('#wToReport'); if(toR) toR.onclick = e=>{ e.preventDefault(); go('report'); };
    const toR2 = $('#wToReport2'); if(toR2) toR2.onclick = e=>{ e.preventDefault(); go('report'); };
    if(!_reports) loadReports().then(()=>{
      const b2 = $('#wRepBox'); if(b2) b2.innerHTML = detailReportList();
    });
  }
}
function metaReset(){
  $$('#wDetail [data-mf]').forEach(el=>{ el.value = _metaDraft[el.dataset.mf] || ''; });
  metaSync();
}
async function bindChecklist(cid){
  await loadChecklistRows(cid);
  if(_active !== 'checklist') return;
  const body = $('#wDetail');
  if(body) body.innerHTML = detailChecklist();      // 行数据到位后重画表格
  const bs = $('#wClBatch');
  if(bs) bs.onchange = async ()=>{
    if(!confirmLeave()) { bs.value = _clBatch; return; }
    _clBatch = bs.value; _clFor = '';
    await bindChecklist(cid);
  };
  const sv = $('#wClSave'); if(sv) sv.onclick = saveChecklist;
  const rs = $('#wClReset'); if(rs) rs.onclick = ()=>{
    $$('#wizClBody [data-cl]').forEach(el=>{
      const r = _clRows[+el.dataset.i];
      el.value = r ? (r[el.dataset.cl] == null ? '' : r[el.dataset.cl]) : '';
    });
    clSync();
  };
  const pv = $('#wClPrev'); if(pv) pv.onclick = ()=>{
    if(_clPage <= 0) return; _clPage--; body.innerHTML = detailChecklist(); bindChecklist2();
  };
  const nx = $('#wClNext'); if(nx) nx.onclick = ()=>{
    _clPage++; body.innerHTML = detailChecklist(); bindChecklist2();
  };
  bindChecklist2();
}
function bindChecklist2(){
  $$('#wizClBody [data-cl]').forEach(el=>{ el.oninput = clSync; });
  clSync();
}

async function loadRecent(){
  const box = $('#wRecent'); if(!box) return;
  try{
    const d = await api('/api/containers');
    const items = (d.items || []).filter(c => c.container_no !== '_UNCATEGORIZED').slice(0, 5);
    box.innerHTML = items.length
      ? '<div class="faint" style="width:100%">最近柜（点一下切换）：</div>' +
        items.map(c=>'<button class="btn ghost sm wrec" data-cid="' + esc(c.id) + '">' +
          esc(c.container_no) + (c.checklist_rows ? (' · ' + c.checklist_rows + ' 行') : '') + '</button>').join(' ')
      : '<div class="faint">还没有其它柜。</div>';
    $$('#wRecent .wrec').forEach(b=>b.onclick = ()=>setCid(b.dataset.cid));
  }catch(e){ box.innerHTML = ''; }
}

/* ── 启动与跨模块跳转 ── */
onCidChange(()=>{
  _genResultHtml = ''; _reports = null;
  _clBatch = ''; _clRows = []; _clFor = '';
  _lpFor = ''; _lastRp = null; _wCodes = [];   // ④ 的编码池/检索结果是柜的
  _shOffset = 0;
  _supGroups = null;                            // 监装照片候选同样是柜的
  loadPicks();
  loadSup();
  loadProgress(false);
});
// 🔴 柜作业已经**并进柜页**，不再是独立 tab（2026-10-08）。
//    这里还注册 'containers' 的 onTab：从别的页点「柜」回来时，
//    如果正停在作业流里，要按当前柜重刷一遍（否则显示的是上一个柜的进度）。
onTab('containers', ()=>{
  loadContainerOptions();
  // ⚠️ **无条件**跑 loadProgress：它是脏柜锚点的自愈路径。
  //    默认落在柜列表（作业视图是隐藏的），只在作业视图里跑的话，
  //    换机器后打开页面 → 锚点脏着却没人去自愈 → 常驻提示条永远不出现，
  //    等于把老板上次报的那个「整页 500」换成了「静默不吱声」。
  loadProgress(false);
});
// 资产页的导入/生成动作完成后广播刷新（避免与 wizard 互相 import 成环）
window.addEventListener('wizard:refresh', ()=>loadProgress(true));
/* ②' 抽屉里关联/解除 → photos:changed（2026-10-14 老板：刷新要保持当前位置）：
   向导③的照片网格与五档徽章也要跟着更新 —— 否则关联完待确认档徽章还是旧数字。
   与 photos.js 的 listener 各管各的视图（那边刷照片库页，这边刷③），
   同样两条：不弹回顶部（scrollY 先记后还）、不缩回第一页（补回翻过的页数）。
   ⚠️ 只在作业视图里跑：照片库页面的抽屉操作不该触发③重拉（省一轮全柜请求）。 */
window.addEventListener('photos:changed', async ()=>{
  if(!inWizView() || !getCid() || !$('#wizShots') || !$('#wShTabs')) return;
  const y = window.scrollY;
  if(_wCarton.on){
    // 箱号分组模式：重拉组列表，并把之前翻过的组补回来
    const keepCartonOff = _wCarton.off;
    await loadCartonGroups(getCid(), true);
    let guard = 0;
    while(_wCarton.off < keepCartonOff && _wCarton.n < _wCarton.total && guard++ < 50){
      const n0 = _wCarton.n;
      await loadCartonGroups(getCid(), false);
      if(_wCarton.n === n0) break;
    }
  }else{
    const keepOff = _wTabs.off;
    await loadWizardPhotos(getCid(), true);
    let guard = 0;
    while(_wTabs.off < keepOff && _wTabs.n < _wTabs.total && guard++ < 50){
      const n0 = _wTabs.n;
      await loadWizardPhotos(getCid(), false);
      if(_wTabs.n === n0) break;          // 服务端没有更多了，停（防死循环）
    }
  }
  window.scrollTo(0, y);
  // 待办计数/卡片装饰、树计数一起跟新（标记无效会让待办集合变小；
  // 抽屉里改判分类也会动「按分类」的计数 —— 不刷树，改完分类左边
  // 的数字还是旧的，老板一眼看出没同步，2026-10-15）
  // ⚠️ 先 await loadSupPending：树的「待确认」计数读 _supPend，
  //    并行发会拿到上一轮的旧数。
  await loadSupPending(getCid());
  refreshWizardTree();
  // 进度摘要数字（步骤条上的「N 张 · 治理 x/y」）跟着刷 —— 只重绘步骤条
  // DOM，不碰 body、不跳步。drawer 关联后不再发 wizard:refresh（它带
  // advance 语义会把③推到④），摘要的时效就靠这里补。
  renderBar();
});
/* 「更多 ▾」下拉：点外面自动关（2026-10-15 工具条分区）。
   ⚠️ 只注册**一次**、处理器里现查元素 —— ③ 的 DOM 是进视图才渲染的，
   模块加载期 $('#wMoreDrop') 是 null；而 bindStep 每进一次③都会跑，
   监听挂进去会栈泄漏（进一次多一层）。按钮自己的 click 里
   stopPropagation，不会被这个监听立刻关掉。 */
document.addEventListener('click', e=>{
  const d = $('#wMoreDrop');
  if(d && d.classList.contains('open') && !d.contains(e.target))
    d.classList.remove('open');
});
// 进入柜作业（柜列表每行 / 建柜后的快速进入条 / 照片库「去③」都走这条）。
// ⚠️ step 允许为空：**没给就落到第一个未完成的步骤** —— 老板点进来要的是
//    「下一步该干什么」，不是每次都从头看一遍①。
window.addEventListener('wizard:goto', e=>{
  const d = e.detail || {};
  const k = d.step;
  if(k && STEPS.indexOf(k) < 0) return;
  if(!confirmLeave()) return;
  if(d.cid) setCid(d.cid);
  showWizView(true);
  _active = k || defaultActive();
  // 2026-10-18 刷新保持柜作业：记住当前柜 + 步骤
  try{ localStorage.setItem('plWiz', '1'); localStorage.setItem('plStep', _active); }catch(e){}
  loadContainerOptions();
  loadProgress(false);
  window.scrollTo(0, 0);
});

/* 「← 柜列表」：回柜列表换别的柜干。
   老板要「在柜里也能进其他柜的作业」—— 两条路：
   ①这个返回键回列表（每行都能进）；②右上角「当前柜」下拉直接切柜。
   回来要刷新列表：刚在作业流里导了清单/照片，行数得是最新的。 */
function backToContainers(){
  if(!confirmLeave()) return;
  showWizView(false);
  try{ localStorage.setItem('plWiz', '0'); }catch(e){}   // 回列表：刷新恢复列表视图
  try{ loadContainers(($('#cQ') && $('#cQ').value.trim()) || ''); }catch(e){}
  window.scrollTo(0, 0);
}
$('#wizBack').onclick = backToContainers;

export function gotoStep(key){ window.dispatchEvent(new CustomEvent('wizard:goto', { detail:{ step:key } })); }
export { loadProgress, confirmLeave };

/* ── 治理抽屉的三条关闭路径（2026-10-21 老板报「打开了关闭不了」）──
   根因：抽屉 fixed 右侧 560px / z-index 70，把**唯一**的关闭入口（标题行
   最右缘的开关按钮）盖住了 —— 真实鼠标点到的是抽屉本身，不是按钮。
   （程序化 t.click() 绕过命中测试，所以老断言全绿、缺陷没被发现。）
   现在关闭有三条独立路径，任何一条都能关：
     ① 抽屉内顶栏「✕ 关闭」按钮（index.html #gGovClose）
     ② Esc（onEscape，prio 5 —— 比批次抽屉(10)低，批次抽屉开着时 Esc 先关它）
     ③ 点抽屉外关闭（document mousedown，不引入新遮罩层，避免层级打架）
   ⚠️ 这段绑在**模块级**：bindStep 会随重绘反复跑，绑在那里会被覆盖/丢失。
   ⚠️ 排除项很重要：
     - #wGovToggle：mousedown 若把它当"外面"先关了，click 又按 _govOpen
       重新打开 → 关不掉还反复弹。
     - #bMask/#bDrawer：批次抽屉是从治理面板里呼出的（照片批次按钮就在面板
       顶部），点它不该连带关掉治理抽屉。
     - 其他浮层（产品抽屉/照片详情/大图/模态）：点它们是在跟下层交互。 */
const _GOV_KEEP_OPEN = '#wGovToggle,#bMask,#bDrawer,#pDetail,#pMask,#drawer,#mask,#stdEd,.modal-overlay';
(function bindGovDrawerClose(){
  const cb = $('#gGovClose');
  if(cb) cb.onclick = ()=>closeGovDrawer();
  // Esc：只在自己开着时关，关了消费掉这次按键（别把下面开着的层也一起关了）
  onEscape(()=>{
    if(govDrawerIsOpen()){ closeGovDrawer(); return true; }
  }, 5);
  // 点抽屉外关闭
  document.addEventListener('mousedown', e=>{
    if(!_govOpen) return;
    const gw = $('#wizGovWrap');
    if(!gw) return;
    const t = e.target;
    if(!t) return;
    if(gw.contains(t)) return;
    if(t.closest && t.closest(_GOV_KEEP_OPEN)) return;
    closeGovDrawer();
  });
})();