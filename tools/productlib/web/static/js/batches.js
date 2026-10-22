// batches.js —— 由 index.html 内联脚本拆分而来，逻辑未改
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, onEscape, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS } from './core.js';
import { loadCurrent, loadKinds } from './photos.js';
import { loadStats } from './home.js';

/* 治理 */
let gTimer = null;
let _batchItems = [];

/* 治理面板折叠：默认收起 —— 它是低频操作，不该在照片库占大半屏。
   ⚠️ 但治理**进行中必须自动展开**：进度条藏在折叠里，老板会以为卡死了
   （"没有进度"主观上等于卡死 —— 这是全 App 排查过的老教训）。 */
const GOV_FOLD_KEY = 'govFold';
function setGovFold(open){
  const body = $('#govBody'), arrow = $('#govArrow');
  if(body) body.style.display = open ? '' : 'none';
  if(arrow) arrow.textContent = open ? '▼' : '▶';
  try{ localStorage.setItem(GOV_FOLD_KEY, open ? '1' : '0'); }catch(e){}
}
function initGovFold(){
  let open = false;                       // 默认收起
  try{ open = localStorage.getItem(GOV_FOLD_KEY) === '1'; }catch(e){}
  setGovFold(open);
  const head = $('#govHead');
  if(head) head.onclick = e=>{
    // 点批次按钮不算折叠切换（它有自己的 onclick，这里别抢）
    if(e.target.closest('#bOpen')) return;
    const body = $('#govBody');
    setGovFold(!body || body.style.display === 'none');
  };
}
initGovFold();
function refreshGovernHint(){
  const bid = $('#gBatch').value;
  const b = _batchItems.find(x=>x.id===bid);
  const pending = bid ? (b? b.pending : 0)
    : _batchItems.reduce((a,x)=>a+(x.pending||0), 0);
  const failed = bid ? (b? b.failed : 0)
    : _batchItems.reduce((a,x)=>a+(x.failed||0), 0);
  $('#gHint').textContent = bid
    ? ('所选批次：' + (b? (b.unique+' 张唯一 · 待治理 '+b.pending+' · 失败 '+b.failed+' · 已关联 '+b.linked) : '未知'))
    : ('全部批次：待治理 ' + pending + ' 张 · 失败 ' + failed + ' 张');
  const allDone = _batchItems.length>0 && pending===0;
  const gReset = $('#gReset');
  if(gReset) gReset.style.display = allDone ? 'inline-block' : 'none';
  const gResetHint = $('#gResetHint');
  if(gResetHint) gResetHint.style.display = allDone ? 'block' : 'none';
  // 有失败照片时才显示「重试失败」
  const gRetry = $('#gRetry');
  if(gRetry) gRetry.style.display = failed>0 ? 'inline-block' : 'none';
  // 收起时在标题上给摘要 —— 不展开也能知道"还有多少没治理"
  const badge = $('#govBadge');
  if(badge){
    if(pending > 0){
      badge.textContent = '待治理 ' + pending;
      badge.className = 'tag warn';
    }else if(failed > 0){
      badge.textContent = '失败 ' + failed;
      badge.className = 'tag err';
    }else{
      badge.textContent = '已全部治理';
      badge.className = 'tag ok';
    }
  }
}
async function loadGovernInfo(){
  try{
    const s = await api('/api/stats');
    if(!gTimer) $('#gText').textContent = '待治理 ' + s.pending + ' / 共 ' + s.photos + ' 张'
      + (s.vision_enabled ? ' · 多模态已启用（' + s.vision_model + '）'
                          : ' · 多模态未配置（降级运行）');
  }catch(e){}
  refreshGovernHint();
  resumeGovern();
}
function resumeGovern(){
  if(gTimer) return;
  api('/api/govern/status').then(s=>{
    // 进来时治理正在跑 → 展开面板，让进度可见
    if(s && s.running){ setGovFold(true); gTimer = setInterval(pollGovern, 1000); pollGovern(); return; }
    // 没在跑但最近一次任务有失败 → 恢复失败诊断面板（2026-10-18 老板反馈
    // 「治理失败，看不到原因」：面板只在完成瞬间渲染一次，刷新就没了）。
    // status.tasks 里有完整的 result（含 errors 归类），直接重渲染。
    const tasks = (s && s.tasks) || [];
    const last = tasks.length ? tasks[tasks.length - 1] : null;
    if(last && last.result && last.result.failed){
      showGovErrors(last.result);
      setGovFold(true);
    }else if(last && last.error){
      const box = $('#gErrBox');
      if(box){
        box.style.display = 'block';
        box.innerHTML = '<div class="gerr-h err">最近一次治理整体失败：'
          + esc(last.error) + '</div>';
      }
      setGovFold(true);
    }
  }).catch(()=>{});
}
$('#gRun').onclick = async ()=>{
  const lim = parseInt($('#gLimit').value)||null;
  const bid = $('#gBatch').value;
  try{
    const r = await post('/api/govern',{limit:lim, batch_id:bid,
      use_vision:$('#gVision').checked, use_ocr:$('#gOcr').checked});
    if(!r.started) return toast(r.reason,'err');
    gTimer = setInterval(pollGovern, 1000);
    setGovFold(true);          // 进度条要看得见，否则像卡死
    toast('治理已启动'+(bid?'（仅所选批次）':'（全部待治理）')
          +(r.vision_enabled?'':'（多模态未配置，降级运行）'));
  }catch(e){ toast('启动失败：'+e.message,'err'); }
};
$('#gBatch').onchange = refreshGovernHint;
$('#gReset').onclick = async ()=>{
  const bid = $('#gBatch').value;
  const b = _batchItems.find(x=>x.id===bid);
  const scopeName = bid ? ('批次「'+(b? b.name : bid)+'」') : '全部照片';
  const n = bid ? (b? b.unique : 0) : (await api('/api/stats')).photos;
  const cost = (await api('/api/stats')).vision_enabled
    ? ('多模态已启用：每张约 2 次调用、10 秒上下，全量约 ' + Math.max(1, Math.round(n*10/60)) + ' 分钟，按你的 API 计费。')
    : '当前未配多模态，将按降级规则重跑（很快）。';
  const skipLinked = !!($('#gSkipLinked') && $('#gSkipLinked').checked);
  if(!confirm('把' + scopeName + '（' + n + ' 张）重置为待治理并重新跑？\n'
      + '· OCR 结果有缓存，这部分秒级\n'
      + '· ' + cost + '\n'
      + (skipLinked
        ? '· 已关联的照片会跳过（关联保持不动）；其余的自动关联清掉重算\n'
        : '· 范围内的自动关联会清掉重算')
      + '；人工关联不受影响')) return;
  try{
    const r = await post('/api/govern',{reset:true, batch_id:bid,
      use_vision:$('#gVision').checked, use_ocr:$('#gOcr').checked,
      skip_linked:skipLinked});
    if(!r.started) return toast(r.reason,'err');
    gTimer = setInterval(pollGovern, 1000);
    setGovFold(true);
    const gResetHint = $('#gResetHint'); if(gResetHint) gResetHint.style.display = 'none';
    toast('重新治理已启动（' + scopeName + '，' + n + ' 张）');
  }catch(e){ toast('启动失败：'+e.message,'err'); }
};
/* 重试失败：只把所选范围内 failed 的照片重置为 pending 再跑，不清关联 */
$('#gRetry').onclick = async ()=>{
  const bid = $('#gBatch').value;
  const b = _batchItems.find(x=>x.id===bid);
  const n = bid ? (b? b.failed : 0)
    : _batchItems.reduce((a,x)=>a+(x.failed||0), 0);
  if(!n) return toast('所选范围没有失败的照片','err');
  const scopeName = bid ? ('批次「'+(b? b.name : bid)+'」') : '全部批次';
  if(!confirm('重试' + scopeName + '的 ' + n + ' 张失败照片？\n'
      + '· 只重跑失败的，已完成/已跳过的不动\n'
      + '· 不会清掉任何关联（失败照片本来就没产生关联）')) return;
  try{
    const r = await post('/api/govern',{retry_failed:true, batch_id:bid,
      use_vision:$('#gVision').checked, use_ocr:$('#gOcr').checked});
    if(!r.started) return toast(r.reason,'err');
    gTimer = setInterval(pollGovern, 1000);
    setGovFold(true);
    toast('重试失败已启动（' + scopeName + '，' + n + ' 张）');
  }catch(e){ toast('启动失败：'+e.message,'err'); }
};
/* OCR 补跑（2026-10-15 需求4）：给治理过但没有 OCR 文本的照片补跑
   本地小模型 + 按当前产品库重新匹配。零多模态开销，可中断续跑。 */
let ocrbfTimer = null;
$('#gOcrBackfill').onclick = async ()=>{
  const bid = $('#gBatch').value;
  const b = _batchItems.find(x=>x.id===bid);
  const scopeName = bid ? ('批次「'+(b? b.name : bid)+'」') : '全部照片';
  if(!confirm('给'+scopeName+'里没有 OCR 文本的照片补跑本地 OCR？\n'
      + '· 只跑本地小模型，不花多模态额度\n'
      + '· 读出的编码会按当前产品库重新匹配：精确命中自动关联，其余进「待确认关联」\n'
      + '· 已有 OCR 文本的照片自动跳过，中断了再点一次接着跑')) return;
  try{
    const r = await post('/api/govern/ocr-backfill',
      {container_id:'', batch_id:bid});
    if(!r.started) return toast(r.reason, 'err');
    ocrbfTimer = setInterval(pollOcrBackfill, 1000);
    setGovFold(true);
    toast('OCR 补跑已启动（' + scopeName + '）');
  }catch(e){ toast('启动失败：'+e.message, 'err'); }
};
async function pollOcrBackfill(){
  const s = await api('/api/govern/ocr-backfill/status');
  const pct = s.total? Math.round(s.done/s.total*100) : 0;
  $('#gBar').style.width = pct+'%';
  $('#gText').textContent = s.running
    ? ('OCR 补跑中 '+s.done+'/'+s.total+'（'+pct+'%）· 已自动关联 '+s.linked+' 条 · 当前：'+s.file)
    : (s.error ? ('失败：'+s.error)
      : ('OCR 补跑完成：补提 '+s.done+' 张，自动关联 '+s.linked+' 条'
        + '（其余命中进「待确认关联」，抽屉里也能看到 OCR 文本了）'));
  if(!s.running){
    clearInterval(ocrbfTimer); ocrbfTimer=null;
    loadStats(); loadGovernInfo(); loadBatches();
    window.dispatchEvent(new Event('photos:changed'));
    window.dispatchEvent(new Event('wizard:refresh'));
    if(s.error) toast('OCR 补跑失败：'+s.error, 'err');
    else toast('OCR 补跑完成：补提 '+s.done+' 张，自动关联 '+s.linked+' 条', 'ok');
  }
}
/* 多任务（2026-10-18 老板需求 4）：不同批次可并行治理。
   status.tasks 每任务一行；进度条聚合运行中任务；完成报告按任务逐个 toast
   （_govSeen 去重，避免每秒轮询重复弹）。 */
const _govSeen = new Set();
let _govHadRunning = false;
async function pollGovern(){
  const s = await api('/api/govern/status');
  const tasks = s.tasks || [];
  const running = tasks.filter(t=>t.running);
  const anyRunning = running.length > 0;
  if(anyRunning) _govHadRunning = true;
  let d=0, tot=0;
  running.forEach(t=>{ d+=(t.done||0); tot+=(t.total||0); });
  const pct = tot? Math.round(d/tot*100) : 0;
  $('#gBar').style.width = pct+'%';
  // 运行中把「开始」换成「停止」（2026-10-17）—— 治理会吃满 CPU，
  // 用户必须能随时叫停，而不是只能等或杀进程。停止请求不带批次 = 停全部。
  $('#gRun').style.display = anyRunning ? 'none' : '';
  $('#gStop').style.display = anyRunning ? '' : 'none';
  if(anyRunning){                       // 运行中隐藏上一轮的失败面板（完成时按新结果重渲染）
    const _eb = $('#gErrBox');
    if(_eb && _eb.style.display !== 'none') _eb.style.display = 'none';
  }
  const lines = tasks
    .filter(t=>t.running || t.result || t.error)
    .slice(-6)
    .map(t=>{
      const label = '['+(t.batch_id? (t.name||t.batch_id) : '全部照片')+'] ';
      if(t.running){
        const p = t.total? Math.round(t.done/t.total*100) : 0;
        return label+'治理中 '+t.done+'/'+t.total+'（'+p+'%）· 当前：'+(t.file||'');
      }
      if(t.error) return label+'失败：'+t.error;
      if(t.result) return label+'完成：治理 '+t.result.done+' 张，自动关联 '
        +t.result.linked+' 条，跳过 '+t.result.skipped+' 张，耗时 '
        +t.result.seconds+' 秒'+(t.result.stopped?'（已按停止请求收尾）':'');
      return '';
    }).filter(Boolean);
  $('#gText').innerHTML = lines.length? lines.map(l=>esc(l)).join('<br>') : '未开始';
  tasks.forEach(t=>{
    const sig = t.key + '@' + (t.started||'');
    if(!t.running && (t.result || t.error) && !_govSeen.has(sig)){
      _govSeen.add(sig);
      if(t.error) toast('治理失败（'+(t.batch_id? t.name : '全部照片')+'）：'+t.error,'err');
      else if(t.result){
        const nm = t.batch_id? t.name : '全部照片';
        if(t.result.stopped){
          toast('治理已停止（'+nm+'）：已治理的保留，剩下的下次接着跑','ok');
        }else if(t.result.done === 0){
          toast('「'+nm+'」没有待治理的照片（全部已治理过）','ok');
        }else{
          toast('治理完成（'+nm+'）：'+t.result.done+' 张，自动关联 '+t.result.linked+' 条','ok');
        }
        // 🔴 有失败时必须说清「为什么失败、怎么解决」——只报「失败 N 张」等于
        //    把排查成本全推给用户（2026-10-06：换电脑治理失败率高但无从下手）。
        showGovErrors(t.result);
      }
    }
  });
  if(!anyRunning && _govHadRunning){
    clearInterval(gTimer); gTimer=null;
    _govHadRunning = false;
    loadStats(); loadGovernInfo(); loadBatches();
    // 通知向导刷新（③④合并后，就绪度/照片数/治理数都变了）
    window.dispatchEvent(new Event('wizard:refresh'));
  }
}

$('#gStop').onclick = async ()=>{
  try{
    const r = await post('/api/govern/stop');
    if(!r.ok) return toast(r.reason||'无法停止','err');
    $('#gText').textContent = '正在停止（当前这张跑完就收）…';
    toast('已请求停止，等当前这张跑完就收');
  }catch(e){ toast('停止失败：'+e.message,'err'); }
};

/* 失败诊断面板：按原因归类计数 + 给出每类的下一步动作。 */
function showGovErrors(r){
  const box = $('#gErrBox');
  if(!box) return;
  const errs = r.errors || [];
  if(!r.failed){ box.style.display='none'; return; }
  if(!errs.length){
    box.style.display = 'block';
    box.innerHTML = '<div class="gerr-h warn">失败 '+r.failed+' 张（没有拿到失败原因，'
      + '可能是进程被强制关闭）</div>';
    return;
  }
  const ACT = {
    '视觉模型不可用（去「设置」配 API）':
      '去「设置 → 多模态识别」填 API 地址 / Key / 模型名，保存后点「重试失败」。',
    'OCR 模型加载失败（检查 ocr 目录）':
      '确认程序目录下有 ocr\\ 文件夹，里面有 det.onnx / rec.onnx / keys.txt 三个文件。',
    '文件/模型缺失（照片路径或 ocr 目录）':
      '照片是「原地引用」的 —— 换电脑后原路径失效了。请把照片拷到本机后，重新导入该照片批次。',
    '图片读不出（文件损坏或格式不支持）':
      '这些图打不开或格式怪（HEIC/RAW 之类）。转成 jpg 再导入。',
    '网络/接口超时（视觉 API 不通）':
      '视觉模型接口不通：检查网络/Key 余额/模型名是否正确。不需要视觉模型就取消「使用多模态」勾选。',
    '数据库被另一个产品库进程占用':
      '多半是同时开了两个产品库（绿色包 + 源码版，或浏览器开着旧窗口）。'
      + '关掉多余的那个黑窗口，重新跑一次即可。'
      + '治理本身不会造成这个 —— 它每处理一张就提交一次，锁的时间极短。',
  };
  box.style.display = 'block';
  box.innerHTML = '<div class="gerr-h err">失败 '+r.failed+' 张，按原因分：</div>'+
    '<ul class="gerr-list">'+errs.map(e=>{
      const act = ACT[e.kind] || '';
      return '<li><b>'+esc(e.kind.replace(/^其它：/,''))+'</b> × '+e.count+
        (act? '<div class="gerr-act">→ '+esc(act)+'</div>' : '')+'</li>';
    }).join('')+'</ul>'+
    // 样例照片（后端 error_samples：[原因, 文件名, 错误详情]）—— 只给计数
    // 等于让用户自己猜是哪几张（2026-10-18 老板反馈「看不到原因」）。
    ((r.error_samples||[]).length
      ? '<details class="gerr-samples"><summary>看失败的样例照片（'+r.error_samples.length+'）</summary>'
        +'<ul class="gerr-list">'+r.error_samples.map(sp=>{
          const kind = sp[0], file = sp[1], msg = sp[2];
          const act = ACT[kind] || '';
          return '<li><b>'+esc(String(file||'').split('/').pop())+'</b>'
            +'<div class="gerr-act">'+esc(String(msg||'').replace(/^其它：/,''))+'</div>'
            +(act? '<div class="gerr-act">→ '+esc(act)+'</div>' : '')+'</li>';
        }).join('')+'</ul></details>'
      : '')+
    (r.vision_on===false
      ? '<div class="gerr-act">提示：当前<b>未启用</b>视觉模型 —— 手写码/模糊件读不出来就是这个原因。</div>'
      : '')+
    (r.ocr_on===false
      ? '<div class="gerr-act">提示：当前<b>未勾选</b>本地 OCR —— 标识卡上的编码读不出来就是这个原因。</div>'
      : '');
}

/* ── 预检批次表 ── */
/* ── 照片批次抽屉：主线只留「导入 → 治理 → 浏览」，批次单独呼出 ── */
/* 「照片批次」按钮 (#bOpen) 就在治理抽屉 (#govPanel) 顶部 —— 从治理面板
   呼出的批次抽屉必须**叠在治理抽屉之上**，否则整块被 z-index 70 的
   #wizGovWrap 压住、里面一行都点不到（真机鼠标命中测试证实）。
   治理抽屉开着时把批次抽屉提到 75，关闭时复位到 CSS 里的 60。
   遮罩 #bMask 保持 55（不提到治理层之上）：否则点遮罩会先把治理抽屉
   整块压暗，而治理抽屉自己的「点外面关闭」已经能兜底。 */
function _govDrawerOpen(){
  const gw = $('#wizGovWrap');
  return !!(gw && gw.style.display !== 'none');
}
function openBatches(){
  $('#bDrawer').classList.add('on'); $('#bMask').classList.add('on');
  if(_govDrawerOpen()) $('#bDrawer').style.zIndex = '75';
  loadBatches();
}
function closeBatches(){
  $('#bDrawer').classList.remove('on'); $('#bMask').classList.remove('on');
  $('#bDrawer').style.zIndex = '';
}
$('#bOpen').onclick       = openBatches;
$('#bReload').onclick     = loadBatches;
$('#bClose').onclick      = closeBatches;
$('#bMask').onclick       = closeBatches;
/* 治理面板已搬进「柜作业③ 照片」（v6）。这里只留指引与跳转 ——
   用 window 自定义事件解耦，**不 import wizard.js**：wizard 要用本模块的
   loadBatches/loadGovernInfo，反向 import 会成环（photos↔drawer 就踩过）。 */
if($('#bGovGo')) $('#bGovGo').onclick = ()=>{
  window.dispatchEvent(new CustomEvent('wizard:goto', { detail:{ step:'photos' } }));
};
onEscape(()=>{   // 只在自己开着时关（Esc 逐层关，关了就消费这次按键）
  if($('#bDrawer').classList.contains('on')){ closeBatches(); return true; }
});
$('#bEmptyImport').onclick = ()=>{ closeBatches(); window.scrollTo(0,0); };

async function loadBatches(){
  let d;
  try{ d = await api('/api/batches'); }
  catch(e){ return; }
  _batchItems = d.items;
  $('#bTotal').textContent = _batchItems.length? ('共 '+_batchItems.length+' 个批次') : '';
  const bn = $('#bOpenN'); if(bn) bn.textContent = _batchItems.length;
  $('#bEmpty').style.display = _batchItems.length? 'none':'block';
  $('#bBody').innerHTML = _batchItems.map(b=>{
    const done = b.unique - b.pending - b.failed;
    const prog = b.unique? Math.round(done/b.unique*100) : 0;
    const progTag = b.pending===0 && b.failed===0 && b.unique>0
      ? '<span class="tag ok">完成</span>'
      : '<span class="tag '+(b.pending?'warn':'')+'">'+done+'/'+b.unique+'</span>';
    const fails = b.failed? ' <span class="tag err">失败 '+b.failed+'</span>' : '';
    return '<tr>'+
      '<td>'+esc(b.name||b.id)+'<div class="faint">'+b.id+'</div></td>'+
      '<td class="faint">'+(b.created_at||'').replace('T',' ').slice(0,16)+'</td>'+
      '<td>'+b.unique+' <span class="faint">/ '+b.total+'</span></td>'+
      '<td>'+progTag+fails+' <div class="bar" style="margin:2px 0 0"><i style="width:'+prog+'%"></i></div></td>'+
      '<td>'+(b.linked||0)+'</td>'+
      '<td><button class="btn ghost sm" data-b-view="'+b.id+'">查看</button> '+
        '<button class="btn sm" data-b-gov="'+b.id+'"'+(b.pending?'':' disabled')+'>治理</button> '+
        (b.failed? '<button class="btn ghost sm" data-b-retry="'+b.id+'">重试失败</button> ' : '')+
        '<button class="btn ghost sm" data-b-regov="'+b.id+'">重跑</button></td>'+
    '</tr>';
  }).join('');
  $$('#bBody [data-b-view]').forEach(el=>el.onclick=()=>{
    $('#fBatch').value = el.dataset.bView;
    loadCurrent(true);
    closeBatches();          // 切到主线的照片浏览，抽屉让位
  });
  $$('#bBody [data-b-gov]').forEach(el=>el.onclick=()=>govBatch(el.dataset.bGov, false));
  $$('#bBody [data-b-retry]').forEach(el=>el.onclick=()=>govBatch(el.dataset.bRetry, false, true));
  $$('#bBody [data-b-regov]').forEach(el=>el.onclick=()=>govBatch(el.dataset.bRegov, true));
  for(const selId of ['#gBatch','#fBatch']){
    const sel = $(selId);
    const cur = sel.value;
    // 批次 options 带柜号前缀（P5 资产化）—— 照片库以柜为主视角，
    // 光看批次名分不出这批属于哪个柜。
    sel.innerHTML = '<option value="">'+(selId==='#gBatch'?'全部批次':'全部批次')+'</option>'
      + _batchItems.map(b=>{
          const pre = b.container_no ? ('【'+esc(b.container_no)+'】') : '';
          return '<option value="'+b.id+'">'+pre+esc(b.name||b.id)+'（'+b.unique+'）</option>';
        }).join('');
    if([].some.call(sel.options, o=>o.value===cur)) sel.value = cur;
  }
  refreshGovernHint();
}
async function govBatch(bid, reset, retry_failed){
  const b = _batchItems.find(x=>x.id===bid);
  const n = b? (reset? b.unique : (retry_failed? b.failed : b.pending)) : 0;
  if(!n) return toast(reset? '该批次没有照片' : (retry_failed? '该批次没有失败的照片' : '该批次没有待治理照片'));
  const skipLinked = !!($('#gSkipLinked') && $('#gSkipLinked').checked);
  if(reset && !confirm('把批次「'+(b.name||bid)+'」的 '+n+' 张照片重置为待治理并重跑？\n'
      + (skipLinked
        ? '已关联的照片会跳过（关联保持不动）；其余的自动关联清掉重算。\n'
        : '该批次的自动关联会清掉重算。\n')
      + '人工关联不受影响。')) return;
  if(retry_failed && !confirm('重试批次「'+(b.name||bid)+'」的 '+n+' 张失败照片？\n'
      + '只重跑失败的，已完成/已跳过的不动；不会清掉任何关联。')) return;
  try{
    const r = await post('/api/govern',{batch_id:bid, reset:!!reset,
      retry_failed:!!retry_failed,
      use_vision:$('#gVision').checked, use_ocr:$('#gOcr').checked,
      skip_linked: skipLinked});
    if(!r.started) return toast(r.reason,'err');
    $('#gBatch').value = bid;
    gTimer = setInterval(pollGovern, 1000);
    setGovFold(true);
    /* 治理面板现在住在向导③里 —— 从批次抽屉启动治理时把老板带过去，
       否则进度条在隐藏的面板里 = 「没进度」，主观上等于卡死。 */
    window.dispatchEvent(new CustomEvent('wizard:goto', { detail:{ step:'photos' } }));
    toast((reset?'重新治理':(retry_failed?'重试失败':'治理'))+'已启动：批次「'+(b.name||bid)+'」（'+n+' 张）');
  }catch(e){ toast('启动失败：'+e.message,'err'); }
}

export { gTimer, pollGovern, closeBatches, govBatch, openBatches, _batchItems, loadGovernInfo, loadBatches, resumeGovern, refreshGovernHint, setGovFold };

export function getBatchItems(){ return _batchItems; }
export function setBatchItems(arr){ _batchItems = arr; }
onTab('batches', loadBatches);
onTab('batches', loadGovernInfo);
