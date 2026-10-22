// containers.js —— 柜（流程主线第一步，2026-10-05 v3）
//
// 柜页职责：① 建柜 → 详情面板里补元数据 / 核对清单 / 看批次 → ⑤ 出报告。
// 柜详情是聚合面板（元数据 / 清单行核对 / 照片批次 / 柜况代表图），
// 数据来自 GET /api/containers/{cid} —— 报告页吃同一份数据，数字不会漂。
import { $, $$, api, post, esc, toast, emptyHtml, go, onTab, onEscape, fmtTaken,
         fmtDur, workRange, workDur,
         getCid, setCid, enterWizard, showWizView } from './core.js';
import { openModal } from './modal.js';

const UNC = '_UNCATEGORIZED';

/** 柜列表「作业时长」单元格：起止一行（主）+ 时长一行（次）。
 *  口径与文案全在 core.js 的 workRange/workDur 里（与 Vue3 新端同一份），
 *  这里只负责排版与警示标签。 */
function workCell(w){
  let dur = workDur(w);
  if(!w.scattered) dur += ' · '+w.segments+' 段';
  const warn = w.trusted ? ''
    : ' <span class="tag warn" title="这个柜的照片时间取自文件写入时刻，不是快门时刻 —— 时长可能只是拷贝耗时">⚠ 文件时刻</span>';
  const scat = w.scattered ? ' <span class="tag warn">数据零散</span>' : '';
  return '<div class="wt">'+esc(workRange(w))+'</div>'+
         '<div class="wt-d">'+esc(dur)+warn+scat+'</div>';
}
/* 键序 = 老板分类表编号序（0101–0104）；文案不带编号，括号内英文 = 报告区块④对应版位 */
const COND_LABELS = {
  empty_container: '空柜（Empty container）',
  container_side: '柜侧（Container No.）',
  container_seal: '封条（Seal No.）',
  container_lock: '锁门（Locked door）',
};

/* ── 柜下拉：导入表单 / 清单导入 / 报告页共用一份列表 ──
   三处 select 各记各的已选值（localStorage），刷新后不丢。 */
export async function loadContainerOptions(){
  let items = [];
  try{ items = (await api('/api/containers')).items || []; }catch(e){ return items; }
  const opts = items.map(c=>{
    const label = c.container_no===UNC ? '（未分柜）' : c.container_no;
    const n = c.checklist_rows ? (' · '+c.checklist_rows+' 行') : '';
    return '<option value="'+esc(c.id)+'">'+esc(label)+n+'</option>';
  }).join('');
  // 🔴 **锚点自愈**（2026-10-07 老板在全新环境用绿色包遇到的崩）：
  //   localStorage['plCid'] 是按 origin 存的，**跨库共用** —— 在 A 机器/旧库
  //   选过的柜号，绿色包在 B 机器的空库里照样会被读出来，于是
  //   `/api/containers/<旧id>/progress` 直接把「柜不存在」抛成 500，
  //   整页报错「读取向导进度失败：Internal Server Error」。
  //   柜号是**这个库里的**东西，锚点指向库里没有的柜就是脏数据 —— 这里就地修掉，
  //   顺带把 toast 说清楚（铁律 16：提示要具体到可操作）。
  const cur = getCid();
  if(cur && !items.some(c => c.id === cur)){
    setCid('');
    // ⚠️ 这里**只 toast 不长驻提示**：向导页会另外挂一条可关闭的常驻条
    //    （`renderAnchorWarn`），两处都弹同一句话会重复。
    //    其他页（照片库/报告档案…）没有常驻条，靠这一下 toast 告知。
    const where = items.length
      ? '已经帮你切到「' + (items[0].container_no || '（未分柜）') + '」'
      : '当前这个柜库里还没有柜 —— 先到「柜」页新建一个';
    toast('上次选的柜在这个库里没有（换机器/换库后浏览器里还留着旧柜号），' + where,
          'warn');
  }
  $$('.ctnSel').forEach(sel=>{
    // 写类（data-anchor）：跟随全局锚点，是唯一真相；
    // 筛选类（资产页按柜筛选）：只填选项，自身 onchange 由页面负责。
    sel.innerHTML = '<option value="">'+(sel.dataset.emptyLabel || '选择柜…')+'</option>' + opts;
    if(sel.dataset.anchor){
      sel.value = getCid();
      // 用 addEventListener（不覆盖报告中心自己的 onchange）：切柜即广播
      sel.addEventListener('change', ()=>{ setCid(sel.value); });
    }
  });
  // 自愈后若库里确实有柜，落一个默认柜，避免停在空选择上
  if(!getCid() && items.length){
    const first = items[0].id;
    setCid(first);
    $$('.ctnSel[data-anchor]').forEach(sel=>{ sel.value = first; });
  }
  return items;
}

/* ── 柜列表 ── */
async function loadContainers(q){
  let d;
  const df = ($('#cDateFrom') && $('#cDateFrom').value) || '';
  const dt = ($('#cDateTo') && $('#cDateTo').value) || '';
  const ps = new URLSearchParams();
  if(q) ps.set('q', q);
  if(df) ps.set('date_from', df);
  if(dt) ps.set('date_to', dt);
  const qs = ps.toString();
  try{ d = await api('/api/containers'+(qs? '?'+qs : '')); }
  catch(e){ $('#cBody').innerHTML = ''; return; }
  const items = d.items || [];
  $('#cEmpty').style.display = items.length? 'none':'block';
  $('#cBody').innerHTML = items.map((c, ci)=>{
    const isUnc = c.container_no === UNC;
    const no = isUnc ? '<span class="faint">（未分柜）</span>' : esc(c.container_no);
    // 「柜作业」是这一行的**主操作**：建柜→清单→照片→选图→报告五步都从这里进。
    // 未分柜也允许进 —— 它里面第①步正好可以补柜号、把老数据挂到真柜上。
    const ops = '<button class="btn sm" data-c-wiz="'+c.id+'" title="进入这个柜的柜作业（五步走完一柜）">柜作业 →</button> '+
      '<button class="btn ghost sm" data-c-open="'+c.id+'">详情</button> '+
      '<button class="btn ghost sm" data-c-report="'+c.id+'"'+(isUnc?' disabled title="未分柜不能出报告"':'')+'>出报告</button>';
    return '<tr'+(isUnc? ' style="opacity:.62"':'')+'>'+
      // 序号（2026-10-20 老板）：跟随当前排序与筛选，纯视觉定位用
      '<td class="faint">'+(ci+1)+'</td>'+
      '<td><b>'+no+'</b>'+(isUnc? '<div class="faint">老数据还没归柜，点详情补挂</div>':'')+
        '<div class="faint">'+esc(c.client_name||'')+'</div></td>'+
      '<td class="faint">'+esc(c.seal_no||'—')+'</td>'+
      '<td>'+(c.checklist_rows || 0)+
        (c.row_unchecked? ' <span class="tag warn">未核对 '+c.row_unchecked+'</span>'
                        : (c.checklist_rows? ' <span class="tag ok">已核对</span>':''))+
        '</td>'+
      '<td>'+(c.photos||0)+' <span class="faint">/ 监装 '+(c.supervision||0)+'</span></td>'+
      '<td class="faint">'+(c.photo_batches||0)+' 批照片 · '+(c.checklist_batches||0)+' 批清单</td>'+
      // 作业时长（2026-10-20）：起止 + 净作业时长。零散数据不给时长，
      // 时间不可靠的挂个警示 —— 宁可少说，不能把拷贝耗时说成作业时长。
      '<td>'+(c.work ? workCell(c.work) : '<span class="faint">—</span>')+'</td>'+
      '<td>'+ops+'</td>'+
    '</tr>';
  }).join('');
  $$('#cBody [data-c-open]').forEach(b=>b.onclick=()=>openContainer(b.dataset.cOpen));
// 进柜作业：只发事件，不 import wizard.js ——
// wizard.js 已经 import 了本模块（loadContainerOptions / openContainerModal），
// 反向 import 会成环（ESM 循环依赖 = 运行期 undefined，静态检查全绿看不出来）。
$$('#cBody [data-c-wiz]').forEach(b=>b.onclick=()=>enterWizard(b.dataset.cWiz));
  $$('#cBody [data-c-report]').forEach(b=>b.onclick=()=>{
    // 出报告 = 进柜作业⑤（2026-10-11：报告档案页已精简为纯档案，不再有生成入口）
    enterWizard(b.dataset.cReport, 'report');
  });
}

$('#cSearch').onclick = ()=>loadContainers($('#cQ').value.trim());
$('#cDateClear').onclick = ()=>{ $('#cDateFrom').value=''; $('#cDateTo').value='';
  loadContainers($('#cQ').value.trim()); };
['cDateFrom','cDateTo'].forEach(id=>{
  const el = document.getElementById(id);
  if(el) el.onchange = ()=>loadContainers($('#cQ').value.trim());
});
$('#cQ').addEventListener('keydown', e=>{ if(e.key==='Enter') loadContainers($('#cQ').value.trim()); });
$('#cReload').onclick = ()=>{ loadContainers($('#cQ').value.trim()); loadContainerOptions(); };

/* ── 建柜（统一模态 —— 柜页标题区「＋新建柜」与向导①共用同一份实现）──
   内联表单原来紧挨着「搜柜号」筛选框，两个 input 排在一起，
   初次接触分不出哪个是要建、哪个是要查（v5 病灶 A）。 */
/* 可以带入上次取值的「不常变」字段。
   ⚠️ 柜号 / 封条号 / 到离柜时间**绝不在内** —— 这三个每次必变，
   自动带入就是替用户猜，猜错比空着危险得多。 */
const PREFILL_FIELDS = [['client_name','客户'], ['inspector','Inspector'], ['location','Location']];

export async function openContainerModal(){
  // 取不到预填值也**不能挡住建柜** —— 拿不到就按空处理，接口异常时照样能建柜。
  let d = { last:{}, recent:{}, from_container:'' };
  try{ d = await api('/api/containers/form-defaults'); }catch(_){}
  const last = d.last || {}, recent = d.recent || {};
  // 提示里**只列真正填上的字段** —— 说「已带入客户/Inspector/Location」
  // 而实际只带了客户，是句假话。
  const filled = PREFILL_FIELDS.filter(f => ((last[f[0]] || '') + '').trim());
  const hint = (d.from_container && filled.length)
    ? '<div class="faint" style="margin:0 0 8px">已带入上次建柜（' +
      esc(d.from_container) + '）的 ' + filled.map(f=>f[1]).join(' / ') +
      '，可修改</div>'
    : '';
  // 历史取值下拉：客户/地点常在几个固定值间切换，只记「上一次」不够用
  const dls = PREFILL_FIELDS.map(f=>{
    const vs = recent[f[0]] || [];
    if(!vs.length) return '';
    return '<datalist id="dl_' + f[0] + '">' +
      vs.map(v=>'<option value="'+esc(v)+'"></option>').join('') + '</datalist>';
  }).join('');
  openModal({
    title: '新建柜',
    width: 520,
    bodyHtml:
      hint +
      '<label>柜号 *</label>'+
      '<input type="text" name="container_no" placeholder="如 EMCU9914616" maxlength="40">'+
      '<label>封条号</label>'+
      '<input type="text" name="seal_no" placeholder="可后补，会进报告 General Information">'+
      '<label>客户</label>'+
      '<input type="text" name="client_name" list="dl_client_name" placeholder="可后补" value="'+esc(last.client_name||'')+'">'+
      '<label>Inspector</label>'+
      '<input type="text" name="inspector" list="dl_inspector" placeholder="可后补" value="'+esc(last.inspector||'')+'">'+
      '<label>Location</label>'+
      '<input type="text" name="location" list="dl_location" placeholder="可后补" value="'+esc(last.location||'')+'">'+
      '<label>到柜时间</label>'+
      '<input type="text" name="arrival_at" placeholder="2026-09-27 09:12">'+
      '<label>离柜时间</label>'+
      '<input type="text" name="departure_at" placeholder="2026-09-27 18:40">'+
      dls,
    okText: '创建',
    onOk: async (vals)=>{
      const no = (vals.container_no || '').trim();
      if(!no) return '柜号不能为空';
      try{
        const c = await post('/api/containers', {
          container_no: no,
          seal_no: (vals.seal_no || '').trim() || null,
          client_name: (vals.client_name || '').trim() || null,
          inspector: (vals.inspector || '').trim() || null,
          location: (vals.location || '').trim() || null,
          arrival_at: (vals.arrival_at || '').trim() || null,
          departure_at: (vals.departure_at || '').trim() || null,
        });
        toast('柜已创建：' + c.container_no, 'ok');
        loadContainers($('#cQ').value.trim());
        loadContainerOptions();
        setCid(c.id);            // 建完自动设为当前柜，广播给全站与柜作业
        // ⚠️ 不再自动打开柜详情抽屉（v6）：①「柜作业①」这一步已经能直接编辑
        //    柜信息了，抽屉多余；更要命的是它会**盖住右半边**，
        //    老板点「保存」都点不到（实测被遮挡）。
        window.dispatchEvent(new Event('wizard:refresh'));
        showCreatedBar(c.id, c.container_no);
        return true;
      }catch(e){ return '创建失败：' + e.message; }
    }
  });
}
$('#cNew').onclick = openContainerModal;
if($('#cEmptyNew')) $('#cEmptyNew').onclick = openContainerModal;   // 空态里的入口同上

/* ── 建柜后的「快速进入柜作业」条（2026-10-08 老板要求）──
   ⚠️ 为什么不是 toast：toast 3 秒自动消失，老板建完柜要点进去时它早没了；
      而且 core.js 的 toast 是纯 textContent，塞不进按钮。
   常驻在列表顶部，进作业或再建一个柜才消失 —— 动作要**等得到人**，
   不能一闪而过。 */
function showCreatedBar(cid, containerNo){
  const bar = $('#ctNewBar');
  if(!bar) return;
  bar.innerHTML =
    '<div class="newbar">'+
      '<span>柜 <b>'+esc(containerNo)+'</b> 已创建 —— 接下来导清单、导照片、出报告都在这一个柜里做。</span>'+
      '<button class="btn sm" id="ctNewGo">进入柜作业 →</button>'+
      '<button class="btn ghost sm" id="ctNewLater">稍后</button>'+
    '</div>';
  bar.style.display = '';
  $('#ctNewGo').onclick = ()=>{ bar.style.display='none'; enterWizard(cid); };
  $('#ctNewLater').onclick = ()=>{ bar.style.display='none'; };
}

/* ── 柜详情抽屉 ── */
let _ctCur = null;
function openContainer(cid){ $('#ctDrawer').classList.add('on'); $('#ctMask').classList.add('on'); _loadDetail(cid); }
function closeContainer(){ $('#ctDrawer').classList.remove('on'); $('#ctMask').classList.remove('on'); }
$('#ctClose').onclick = closeContainer;
$('#ctMask').onclick = closeContainer;
$('#ctReload').onclick = ()=>_ctCur && _loadDetail(_ctCur);
$('#ctReport').onclick = ()=>{
  if(!_ctCur) return;
  closeContainer();
  enterWizard(_ctCur, 'report');   // 出报告 = 进柜作业⑤（报告页只留档案）
};
onEscape(()=>{ if($('#ctDrawer').classList.contains('on')){ closeContainer(); return true; } }, 15);

async function _loadDetail(cid){
  let d;
  try{ d = await api('/api/containers/'+cid); }
  catch(e){ return toast('读取柜详情失败：'+e.message,'err'); }
  _ctCur = cid;
  const isUnc = d.is_uncategorized;
  $('#ctTitle').textContent = isUnc ? '（未分柜）' : d.container_no;
  $('#ctSub').textContent = [d.seal_no? ('封条 '+d.seal_no) : '', d.client_name||'']
    .filter(Boolean).join(' · ');

  const ps = d.photo_stats || {};
  const st = d.supervision_tags || {};
  const cond = d.condition_photos || {};
  const nCond = Object.values(cond).filter(Boolean).length;

  /* 元数据表单：改完显式保存（清单页的规矩：离开不自动猜） */
  const metaRow = (k, label, ph, type)=>{
    return '<div class="kv"><span class="k">'+label+'</span>'+
      '<input type="'+(type||'text')+'" id="ctF_'+k+'" value="'+esc(d[k]||'')+'" placeholder="'+esc(ph||'')+'" style="flex:1;min-width:120px"></div>';
  };
  let html = '<div class="dsec"><h4>柜信息（进报告 General Information）</h4>'+
    metaRow('seal_no','封条号','Seal No.') + metaRow('arrival_at','到柜时间','2026-09-27 09:12') +
    metaRow('departure_at','离柜时间','2026-09-27 18:40') + metaRow('inspector','Inspector','') +
    metaRow('location','Location','') + metaRow('product_name','Product','') +
    metaRow('client_name','Client','') +
    '<div class="kv"><span class="k">REMARKS</span><textarea id="ctF_remark" rows="2" style="flex:1">'+esc(d.remark||'')+'</textarea></div>'+
    '<div class="row" style="margin-top:6px"><button class="btn sm" id="ctSave">保存柜信息</button>'+
    '<span class="faint" id="ctSaveMsg"></span></div></div>';

  /* 概览数字（与报告页同源：row_total / row_unchecked 来自 container_detail） */
  html += '<div class="dsec"><h4>就绪度</h4>'+
    '<div class="row" style="gap:8px;flex-wrap:wrap">'+
    '<span class="tag '+(d.row_total? '':'')+'">清单行 '+d.row_total+'</span>'+
    (d.row_unchecked? '<span class="tag warn">未核对 '+d.row_unchecked+'</span>'
                     : (d.row_total? '<span class="tag ok">清单已核对</span>':'<span class="tag warn">还没导清单</span>'))+
    '<span class="tag">预检照片 '+(ps['预检']||0)+' · 监装照片 '+(ps['监装']||0)+'</span>'+
    '<span class="tag '+(nCond===4?'ok':'warn')+'">柜况图 '+nCond+'/4</span>'+
    (st['truck_head']? '<span class="tag ok">卡车头 1</span>' : '<span class="tag warn">缺卡车头</span>')+
    '</div></div>';

  /* 作业时长（2026-10-20 老板需求）：按连拍分组切段，逐段给起止/耗时。
     不对全柜取 MIN/MAX —— 跨 3 天的柜会报出「作业 334 小时」的假结论。
     后端最多回传 60 段（兜底柜有几百段），这里只铺最近 10 段。 */
  if(d.work){
    const segs = d.work_segments || [];
    const show = segs.slice(-10);
    html += '<div class="dsec"><h4>作业时长<span class="faint">（按连拍分组切段；时间取自文件写入时刻的段会标出来）</span></h4>'+
      '<div class="wsum">'+
        '<b class="wsum-r">'+esc(workRange(d.work))+'</b>'+
        '<span class="wsum-d">'+esc(workDur(d.work))+'</span>'+
        (d.work.trusted? '' : '<span class="tag warn">时间取自文件</span>')+
        (d.work.scattered? '<span class="tag warn">数据零散</span>':'')+
      '</div>'+
      '<table class="wsegt"><thead><tr><th>作业段</th><th class="rr">耗时</th>'+
        '<th class="rr">照片</th><th>时间来源</th></tr></thead><tbody>'+
      show.map(s=>'<tr>'+
        '<td class="mono">'+esc(fmtTaken(s.from,{full:true}))+' ~ '+esc(fmtTaken(s.to,{clock:true}))+'</td>'+
        '<td class="rr">'+(s.wide
          ? '<span class="faint" title="这一段的时间跨度超过 12 小时，不是连续作业，是数据零散">不可用</span>'
          : esc(fmtDur(s.span_sec)||'—'))+'</td>'+
        '<td class="rr">'+s.n+'</td>'+
        '<td>'+(s.trusted? '<span class="tag ok">拍摄时刻</span>'
                         : '<span class="tag warn">文件时刻</span>')+'</td>'+
      '</tr>').join('')+
      '</tbody></table>'+
      (segs.length<d.work_segments_total
        ? '<div class="faint" style="margin-top:6px">共 '+d.work_segments_total
          +' 段，只显示最近 '+show.length+' 段</div>'
        : '')+
      '</div>';
  } else {
    html += '<div class="dsec"><h4>作业时长</h4>'+
      '<div class="faint">这个柜还没有带拍摄时间的照片。</div></div>';
  }

  /* 柜况 4 图代表图（每类最新一张；报告④直接用这些） */
  html += '<div class="dsec"><h4>柜况代表图<span class="faint">（每类取最新一张，在照片详情里给监装照打标签即可换）</span></h4>'+
    '<div class="condgrid">'+ Object.keys(COND_LABELS).map(tag=>{
      const p = cond[tag];
      return '<div class="condslot'+(p? '':' missing')+'" data-tag="'+tag+'">'+
        (p? '<img loading="lazy" src="/thumb/'+p.id+'"><div class="cl">'+esc(COND_LABELS[tag])+'</div>'
           : '<div class="cl">'+esc(COND_LABELS[tag])+'<br><span class="faint">未打标</span></div>')+
      '</div>';
    }).join('') + '</div>'+
    '<div class="faint" style="margin-top:6px">打标入口：照片库 → 监装照片详情 → 「监装细分」。</div></div>';

  /* 批次（清单批次可展开核对行；照片批次跳照片库） */
  html += '<div class="dsec"><h4>批次（' + d.batches.length + '）</h4>';
  if(!d.batches.length){
    html += '<div class="faint">这个柜还没有任何批次 —— 去「照片库」导照片，或「产品库」导清单（记得选柜）。</div>';
  }else{
    html += '<table><thead><tr><th>批次</th><th style="width:80px">类型</th>'+
      '<th style="width:90px">数量</th><th style="width:140px">时间</th><th style="width:120px">操作</th></tr></thead><tbody>';
    for(const b of d.batches){
      const kind = b.kind==='checklist' ? '清单' : '照片';
      const n = b.kind==='checklist' ? (b.rows + ' 行') : (b.stats.uniq + '/' + b.stats.total);
      html += '<tr><td>'+esc(b.name||b.id)+'<div class="faint">'+b.id+'</div></td>'+
        '<td><span class="tag">'+kind+'</span></td>'+
        '<td>'+n+'</td>'+
        '<td class="faint">'+(b.created_at||'').replace('T',' ').slice(0,16)+'</td>'+
        '<td>'+(b.kind==='checklist'
          ? '<button class="btn ghost sm" data-ct-rows="'+b.id+'">核对清单</button>'
          : '<button class="btn ghost sm" data-ct-view="'+b.id+'">看照片</button>')+
        '</td></tr>'+
        '<tr id="ctRows_'+b.id+'" style="display:none"><td colspan="5" id="ctRowsBox_'+b.id+'"></td></tr>';
    }
    html += '</tbody></table>';
  }
  html += '</div>';
  $('#ctBody').innerHTML = html;

  $('#ctSave').onclick = async ()=>{
    const fields = {};
    for(const k of ['seal_no','arrival_at','departure_at','inspector',
                    'location','product_name','client_name','remark']){
      fields[k] = ($('#ctF_'+k)||{}).value?.trim?.() ?? null;
    }
    try{
      await api('/api/containers/'+cid, {method:'PUT', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(fields)});
      $('#ctSaveMsg').textContent = '已保存';
      setTimeout(()=>{ const m=$('#ctSaveMsg'); if(m) m.textContent=''; }, 1500);
      loadContainers($('#cQ').value.trim());
    }catch(e){ $('#ctSaveMsg').textContent = '保存失败：'+e.message; }
  };
  $$('#ctBody [data-ct-view]').forEach(b=>b.onclick=()=>{
    $('#fBatch').value = b.dataset.ctView;
    closeContainer();
    go('batches');
  });
  $$('#ctBody [data-ct-rows]').forEach(b=>b.onclick=()=>_toggleRows(b.dataset.ctRows, d));
}

/* ── 清单行核对（行快照直接展开；核对结论显式保存） ── */
async function _toggleRows(bid, d){
  const tr = $('#ctRows_'+bid);
  if(tr.style.display !== 'none'){ tr.style.display = 'none'; return; }
  tr.style.display = '';
  const box = $('#ctRowsBox_'+bid);
  box.innerHTML = '<span class="faint">读取行快照…</span>';
  try{
    const r = await api('/api/containers/'+d.id+'/checklist?batch='+encodeURIComponent(bid));
    const rows = r.items || [];
    if(!rows.length){ box.innerHTML = '<span class="faint">这个批次没有行快照（旧清单导入，重导一次即可生成）</span>'; return; }
    box.innerHTML = '<div class="scroller" style="max-height:420px;margin:4px 0"><table><thead><tr>'+
      '<th style="width:44px">#</th><th style="width:150px">编码</th><th>品名</th>'+
      '<th style="width:110px">箱号</th><th style="width:60px">Order</th>'+
      '<th style="width:70px">Loading</th><th style="width:90px">核对</th></tr></thead><tbody>'+
      rows.map(x=>{
        const cur = (x.check_result!=null && x.check_result!=='') ? x.check_result
                  : (x.check_import!=null && x.check_import!=='') ? x.check_import+' <span class="faint">(清单)</span>' : '';
        return '<tr><td class="faint">'+x.seq+'</td><td>'+esc(x.code)+'</td>'+
          '<td>'+esc(x.name||'')+'</td><td class="faint">'+esc(x.package_no||'')+'</td>'+
          '<td>'+esc(x.order_qty||'')+'</td><td>'+esc(x.loading_qty||'')+'</td>'+
          '<td><input class="crChk" data-b="'+x.batch_id+'" data-s="'+x.seq+'" value="'+esc(x.check_result||'')+'" '+
          'placeholder="PASS/FAIL" style="width:70px" title="当前：'+esc(String(x.check_result||'')||'未核对')+'"></td></tr>';
      }).join('') + '</tbody></table></div>'+
      '<div class="row"><button class="btn sm" id="crSave_'+bid+'">保存核对结论</button>'+
      '<span class="faint">空的 = 未核对，报告里留空（清单预填的 PASS 只作显示，不算我们核对过）</span></div>';
    $('#crSave_'+bid).onclick = async ()=>{
      const inputs = $$('#ctRowsBox_'+bid+' .crChk').filter(i=>i.dataset.b===bid);
      let n = 0, err = '';
      for(const i of inputs){
        try{
          await post('/api/checklist/rows/check', {batch_id: i.dataset.b, seq: +i.dataset.s,
            check_result: i.value.trim()});
          n++;
        }catch(e){ err = e.message; break; }
      }
      if(err) toast('保存到第 '+n+' 项失败：'+err,'err');
      else toast('已保存 '+n+' 行核对结论','ok');
      _loadDetail(d.id);
    };
  }catch(e){ box.innerHTML = '<span class="faint">读取失败：'+esc(e.message)+'</span>'; }
}

onTab('containers', ()=>{ loadContainers($('#cQ').value.trim()); loadContainerOptions(); });

export { loadContainers, openContainer, closeContainer };
