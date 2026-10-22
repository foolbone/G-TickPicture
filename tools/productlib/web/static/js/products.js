// products.js —— 由 index.html 内联脚本拆分而来，逻辑未改
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, onEscape, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS, fmtTaken, fmtGap, diffSec, getCid } from './core.js';
import { openModal } from './modal.js';
import { shotCard, bindShots } from './photos.js';
import { openDrawer, setDrawerList } from './drawer.js';
import { loadStats } from './home.js';

/* ── 产品 ── */
const P_PAGE = 50;
let pPage = 0;
let pCodes = [];    // 当前页的编码顺序 —— 抽屉「上一个/下一个」靠它走
let pTotal = 0, pPages = 1;
let pSel = '';      // 当前打开的产品（翻页/重渲染后要把高亮补回去）
let pDraft = {};    // 字段编辑的已保存值快照 —— 判断「有没有未保存改动」用它比

/* ── 标准图区：手动上传（多张）+ 已有的裁剪版 ──
   为什么单独成块而不是塞进照片分组：上传的标准图**不需要**这个产品在库里有照片，
   「0 张照片」的产品同样可以有自己的标准图（客户/厂家直接给的图）。
   混在照片堆里会让人以为没照片就不能传。 */
const STD_KINDS = ['label','product','packaging','unknown'];
function pStdBlockHTML(code){
  return '<div class="bgroup pstd-block">'+
    '<div class="bgh"><span class="tag std">标准图</span>'+
      '<span class="faint">上传照片作为该产品的标准图，可多张；导出标准库与报告取材都优先用它</span>'+
      '<span class="spacer"></span>'+
      '<select id="pStdKind" style="width:110px">'+
        STD_KINDS.map(k=>'<option value="'+k+'"'+(k==='product'?' selected':'')+'>'+KIND_LABELS[k]+'</option>').join('')+
      '</select>'+
      '<button class="btn sm" id="pStdUpload">上传标准图</button>'+
      '<input type="file" id="pStdFiles" accept="image/*" multiple hidden>'+
    '</div>'+
    '<div id="pStdList"><span class="faint">读取标准图…</span></div>'+
  '</div>';
}

async function loadPStdList(code){
  const box = $('#pStdList');
  if(!box) return;
  try{
    const d = await api('/api/standard-images?code='+encodeURIComponent(code));
    const items = d.items||[];
    const up = items.filter(s=>s.origin==='upload');
    if(!items.length){
      box.innerHTML = '<div class="faint" style="font-size:12px;padding:4px 0">'+
        '还没有标准图 —— 点右上「上传标准图」，或从库内照片「制作标准图」。</div>';
      return;
    }
    box.innerHTML = '<div class="faint" style="font-size:12px;margin-bottom:4px">'+
      (up.length? ('手动上传 '+up.length+' 张') : '') +
      (up.length && up.length<items.length? ' · ' : '') +
      '裁剪 '+(items.length-up.length)+' 张 · 共 '+items.length+' 张（导出时全部采用）</div>'+
      '<div class="pstd-grid">'+items.map(s=>{
        const isUp = s.origin==='upload';
        return '<div class="pstd-cell">'+
          '<img loading="lazy" src="'+esc(s.url||('/std-img/'+s.id))+'" alt="">'+
          '<div class="c1"><span class="tag '+(isUp?'ok':'')+'">'+
            (isUp? '上传':'裁剪')+'</span> '+kindChip(s.kind)+'</div>'+
          '<div class="faint c2" title="'+esc(s.orig_name||'')+'">'+
            (s.width||'?')+'×'+(s.height||'?')+
            (isUp&&s.orig_name? ' · '+esc(s.orig_name) : '')+'</div>'+
          '<button class="x" data-pstd-del="'+esc(s.id)+'" title="删除该标准图">×</button>'+
        '</div>';
      }).join('')+'</div>';
    $$('#pStdList [data-pstd-del]').forEach(x=>x.onclick=async()=>{
      if(!confirm('删除这张标准图？（只删标准图资产，不动原照片；库里没照片的上传图删了就没了）')) return;
      try{
        await api('/api/standard-images/'+x.dataset.pstdDel,{method:'DELETE'});
        toast('已删除标准图','ok');
        loadPStdList(code); loadProducts(false);
      }catch(e){ toast('删除失败：'+e.message,'err'); }
    });
  }catch(e){
    box.innerHTML = '<span class="faint">标准图读取失败：'+esc(e.message)+'</span>';
  }
}

/* 上传：一次可多选，逐个显示成败。一批里一张坏图不阻断其余（后端已按此实现）。 */
async function uploadPStdFiles(){
  const inp = $('#pStdFiles');
  const code = pSel;
  if(!inp || !inp.files || !inp.files.length) return;
  if(!code){ toast('先选中一个产品','err'); return; }
  const files = Array.from(inp.files);
  const kind = ($('#pStdKind')||{}).value || 'product';
  const fd = new FormData();
  fd.append('code', code);
  fd.append('kind', kind);
  files.forEach(f=>fd.append('files', f));
  const btn = $('#pStdUpload');
  if(btn){ btn.disabled = true; btn.textContent = '上传中…'; }
  try{
    const r = await api('/api/standard-images/upload', {method:'POST', body:fd});
    // 部分成功必须如实说，不能只报成功（铁律：缺口不许渲染成结论态）
    if(r.failed){
      toast('成功 '+r.uploaded+' 张，失败 '+r.failed+' 张（'
            + (r.errors||[]).slice(0,2).map(e=>e.filename+': '+e.error).join('；')
            + '）', 'warn');
    }else{
      toast('已上传 '+r.uploaded+' 张标准图','ok');
    }
    inp.value = '';                   // 清空以便重传同名文件
    await loadPStdList(code);
    loadProducts(false); loadStats();
  }catch(e){
    toast('上传失败：'+e.message,'err');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '上传标准图'; }
  }
}

async function loadProducts(reset){
  if(reset) pPage = 0;
  const q = $('#pQ').value.trim();
  const sort = ($('#pSort') && $('#pSort').value) || 'gap';
  const container = ($('#pContainer') && $('#pContainer').value) || '';
  // 「待确认」筛选走独立的 cand 参数：any=任一 / code=读码候选 / group=同组候选。
  // 与列表角标同一份 store.cand_counts()，筛出来的点开一定有东西。
  let has = $('#pHas').value, cand = '';
  if(has.indexOf('cand') === 0){
    cand = has === 'cand' ? 'any' : (has === 'cand_code' ? 'code' : 'group');
    has = '';
  }
  const d = await api('/api/products?q='+encodeURIComponent(q)+'&has='+has
    +'&cand='+cand+'&sort='+sort+'&container='+encodeURIComponent(container)
    +'&limit='+P_PAGE+'&offset='+(pPage*P_PAGE));
  const rows = d.items, total = d.total||0;
  const pages = Math.max(1, Math.ceil(total/P_PAGE));
  pTotal = total; pPages = pages;
  pCodes = rows.map(r=>r.code_norm);
  $('#pgInfo').textContent = '第 '+(pPage+1)+' / '+pages+' 页 · 共 '+total+' 条';
  $('#pgPrev').disabled = pPage<=0;
  $('#pgNext').disabled = pPage>=pages-1;
  $('#pEmpty').style.display = rows.length? 'none':'block';
  $('#pBody').innerHTML = rows.map(p=>{
    const t = p.photo_count>0 ? '<span class="tag ok">'+p.photo_count+'张</span>'
                              : '<span class="tag" style="opacity:.5">0</span>';
    // 待确认角标：读码（照片里真读出这个编码，强证据）/ 同组（跟已关联照片
    // 同一段连拍，需人工判断）。分开显示 —— 两类证据强度完全不同。
    // 与详情候选区同源，标了点开就一定有，不会出现「标了 N 张、一张没有」。
    const cc = p.cand_code||0, cg = p.cand_group||0;
    const ct = [];
    if(cc) ct.push('<span class="tag warn" title="照片里读出这个编码、还没关联（强证据，优先确认）">读码 '+cc+'</span>');
    if(cg) ct.push('<span class="tag acc" title="与已关联照片同一段连拍、还没确认（需人工判断）">同组 '+cg+'</span>');
    const cand = ct.length ? ct.join('')
      : '<span class="faint" style="opacity:.4">—</span>';
    // 柜号：从 origins 或批次关联获取（列表接口暂不返回，留空占位）
    return '<tr data-code="'+esc(p.code_norm)+'"'+(p.code_norm===pSel?' class="sel"':'')+'>'+
      '<td class="code" title="'+esc(p.code)+'">'+esc(p.code)+'</td>'+
      '<td title="'+esc(p.name||'')+'">'+esc(p.name||'<span class="faint">未命名</span>')+'</td>'+
      '<td class="faint" title="'+esc(p.spec||'')+'" style="font-size:12px">'+
        (p.spec? esc(p.spec) : '<span style="opacity:.4">—</span>')+'</td>'+
      '<td>'+t+'</td>'+
      '<td>'+cand+'</td>'+
      '<td>'+(p.has_standard
        ? '<span class="tag ok" title="已制作标准图，导出时优先采用">标</span>'
        : '<span class="tag" style="opacity:.35" title="还没做标准图">—</span>')+'</td>'+
      '<td class="faint" style="font-size:11px" title="'+esc(p.container_list||'')+'">'+
        (p.container_list ? esc(p.container_list.split(',')[0]) + (p.container_list.includes(',')?'…':'') : '<span style="opacity:.4">—</span>')+
      '</td>'+
      // 资产化：来源柜 / 被引用 —— 跨柜复用是产品库最大的价值，必须看得见
      '<td class="faint" style="font-size:11px" title="第一次被哪个柜的清单带进来">'+
        (p.source_container_no ? esc(p.source_container_no) : '<span style="opacity:.4">—</span>')+'</td>'+
      '<td class="faint" style="font-size:11px" title="被这些柜的清单引用：'+esc((p.used_by||[]).join('、')||'无')+'">'+
        ((p.used_by||[]).length ? (p.used_by.length + (p.used_by.length>1?' 柜':' 柜')) : '<span style="opacity:.4">—</span>')+'</td>'+
      '</tr>';
  }).join('');
  $$('#pBody tr').forEach(tr=>tr.onclick=()=>{ selectProduct(tr.dataset.code); });
}

/* 选中（并打开）一个产品：抽屉状态、列表高亮、位置显示三处一起走，
   翻页/搜索后回来还是同一个。 */
function selectProduct(code){
  pSel = code;
  $$('#pBody tr').forEach(x=>x.classList.toggle('sel', x.dataset.code===code));
  openProduct(code);
}

/* 抽屉里的「上一个 / 下一个」：走当前列表的顺序，走到页边界自动翻页。
   有未保存的字段修改时先拦一下 —— 无声丢改动比多问一句难受得多。 */
async function gotoProduct(delta){
  if(!pCodes.length) return;
  const i = pCodes.indexOf(pSel);
  if(i < 0) return;
  if(!confirmLeave()) return;
  let ni = i + delta;
  if(ni < 0){
    if(pPage <= 0){ toast('已经是第一个','ok'); return; }
    pPage--; await loadProducts(false); ni = pCodes.length - 1;
  }else if(ni >= pCodes.length){
    if(pPage >= pPages-1){ toast('已经是最后一个','ok'); return; }
    pPage++; await loadProducts(false); ni = 0;
  }
  const code = pCodes[ni];
  if(!code) return;
  selectProduct(code);
  const tr = $$('#pBody tr').find(t=>t.dataset.code===code);
  if(tr) tr.scrollIntoView({block:'nearest'});
}

/* 字段编辑：有没有改动 / 能不能离开 —— 保存前离开要问，别静默丢。 */
function pendingEdit(){
  return $$('#pShots [data-pf]').some(i => (i.value||'') !== (pDraft[i.dataset.pf]||''));
}
function confirmLeave(){
  if(!pendingEdit()) return true;
  return confirm('有未保存的字段修改。\n\n离开将丢失这些修改，确定吗？');
}
async function openProduct(code){
  openProductDrawer();   // 先滑出抽屉再取数，体感更快
  pSel = code;
  const [d, prod, cand, rej] = await Promise.all([
    api('/api/products/'+encodeURIComponent(code)+'/photos'),
    api('/api/products/'+encodeURIComponent(code)).catch(()=>null),
    api('/api/products/'+encodeURIComponent(code)+'/candidates').catch(()=>({items:[]})),
    // 已标记「无关联」的清单 —— 标记是**可撤销**的，入口必须一直在，
    // 否则老板点错一次就永远找不回那张照片（照片本身没删，但找不回了）。
    api('/api/products/'+encodeURIComponent(code)+'/candidates/rejected').catch(()=>({items:[]})),
  ]);
  const stdSet = new Set(d.standard_photo_ids||[]);
  // 标题区给足信息：编码 + 品名/规格 + 各类计数，一眼判断这个产品的素材齐不齐
  const _f = prod || {};
  const _cands = (cand.items||[]).length + (cand.group_siblings||[]).length
                + (cand.panoramas||[]).length;
  $('#pTitle').innerHTML = '<span class="code">'+esc(code)+'</span>'+
    (_f.name? ' <span class="muted">'+esc(_f.name)+'</span>' : '')+
    (_f.spec? ' <span class="faint">'+esc(_f.spec)+'</span>' : '')+
    ' <span class="tag ok">'+d.items.length+' 张照片</span>'+
    // 标准图张数用 standard_count（裁剪+上传总数），不用 stdSet.size ——
    // 后者是「源照片数」，一个源照片可存多版本，且上传的不挂照片。
    (d.standard_count? ' <span class="tag ok">'+d.standard_count+' 张标准图</span>' : '')+
    (_cands? ' <span class="tag warn">'+_cands+' 张待确认</span>' : '');
  // 位置：「第 n / 总数 条 + 第 n / m 个」—— 切换产品时不至于不知道走到哪了
  const _pi = pCodes.indexOf(code);
  if($('#pPos')) $('#pPos').textContent = _pi>=0
    ? ('第 '+(pPage*P_PAGE+_pi+1)+' / '+pTotal+' 条')
    : '';
  if($('#pPrev')) $('#pPrev').disabled = (_pi<=0 && pPage<=0);
  if($('#pNext')) $('#pNext').disabled = (_pi>=pCodes.length-1 && pPage>=pPages-1);
  // 显示删除按钮并绑定
  const delBtn = $('#pDelete');
  if(delBtn){
    delBtn.style.display = '';
    delBtn.dataset.code = code;
  }

  // ① 来源信息：清单导入 / 照片新发现确认 + 关联柜号 + 箱号
  const origins = (prod && prod.origins) || null;
  let originRow = '';
  if(origins){
    const srcLabel = origins.source_type === 'from_photo'
      ? '<span class="tag warn">照片新发现确认</span>'
      : origins.source_type === 'checklist'
        ? '<span class="tag ok">清单导入</span>'
        : '<span class="tag">来源未知</span>';
    const containers = origins.containers || [];
    const cnTags = containers.length
      ? containers.map(c => '<span class="chip">'+esc(c.container_no || c.name || c.id)+'</span>').join('')
      : '<span class="faint">无</span>';
    // 箱号：从关联照片中提取
    const cartons = [...new Set((d.items||[]).map(p=>p.carton_no).filter(Boolean))];
    const cartonHtml = cartons.length
      ? '<span class="carton-tags">'+cartons.map(c=>'<span class="chip">'+esc(c)+'</span>').join('')+'</span>'
      : '<span class="faint">无</span>';
    originRow = '<div class="origin-row">'+
      '<div class="origin-line"><span class="origin-label">来源</span>'+srcLabel+'</div>'+
      '<div class="origin-line"><span class="origin-label">关联柜号</span>'+cnTags+'</div>'+
      '<div class="origin-line"><span class="origin-label">涉及箱号</span>'+cartonHtml+'</div>'+
      '</div>';
  }
  // ② 产品字段编辑（品名/规格/材质 —— 直接决定语义匹配质量）
  //    改成「改完点保存」：原来失焦即存，改错了没法撤、也不知道到底存没存。
  //    编辑条是 sticky 的，滚到哪都能看见保存按钮。
  const f = prod || {};
  pDraft = { name: f.name||'', spec: f.spec||'', material: f.material||'' };
  const editRow = '<div class="pedit">'+
    '<span class="faint">字段：</span>'+
    [['name','品名'],['spec','规格'],['material','材质']].map(([k,label])=>
      '<label class="pef">'+label+
      '<input type="text" data-pf="'+k+'" value="'+esc(pDraft[k])+'" placeholder="未填写"></label>').join('')+
    '<button class="btn sm" id="peSave" disabled>保存修改</button>'+
    '<button class="btn sm ghost" id="peReset" disabled>还原</button>'+
    '<span class="faint" id="peMsg"></span></div>';

  // ② 按批次分组（「哪些批次没拍到」的提示已按老板要求移除 —— 那是噪音，
  //    真要核对整箱拍没拍全，看照片数和箱号就够）
  const groups = {};
  d.items.forEach(p=>{ const k = p.batch_id||'_none'; (groups[k]=groups[k]||[]).push(p); });
  const batchName = id => {
    const b = (d.batches||[]).find(x=>x.id===id);
    return b? (b.name||id) : (id==='_none'? '未归属批次' : (id||''));
  };
  // ── 标准图区（2026-10-06 新增手动上传：一个产品可多张）──
  //   两条来源并存：① 手动上传的文件（origin=upload，与库内照片无关）
  //                 ② 从库内照片裁剪（origin=crop，老机制）
  //   放在照片分组之上：上传的标准图与"这个产品有没有照片"无关，
  //   埋在照片堆里会让人以为"没照片就不能传标准图"。
  let html = originRow + editRow + pStdBlockHTML(code);
  Object.keys(groups).forEach(k=>{
    html += '<div class="bgroup"><div class="bgh">'+esc(batchName(k))+
      ' <span class="faint">· '+groups[k].length+' 张</span></div>'+
      '<div class="grid">'+groups[k].map(p=>shotCard(p, true, stdSet)).join('')+'</div></div>';
  });
  const hasCandidates = (cand.items||[]).length > 0 || (cand.group_siblings||[]).length > 0;
  if(!d.items.length){
    if(hasCandidates){
      html += '<div class="empty-compact">已关联 0 张照片，下方有候选照片待确认'
        +'<br><button class="btn sm ghost" data-go="review" style="margin-top:4px">去新产品确认</button></div>';
    } else {
      html += emptyHtml('🖼️','这个产品还没有关联到任何照片','在人工标注确认里认领，或确认清单编码与照片上的是否一致',
        '<button class="btn sm ghost" data-go="review">去新产品确认</button>');
    }
  }

  // ── 待确认区：同组待确认 + 可能关联 ──
  // ⚠️ 原来两块上下排列，第二块被推到很下面，老板看不见。
  //    改成**并排两列**，两块一起出现在视野里。
  const siblings = cand.group_siblings||[];
  const cands = cand.items||[];
  if(siblings.length || cands.length){
    html += '<div class="confirm-row">';

    // ③ 同组待确认：已关联照片的同组其他照片（标签特写+全景图连拍），强语义推荐
    if(siblings.length){
      const sg = {};
      siblings.forEach(s=>{ (sg[s.group_idx]=sg[s.group_idx]||[]).push(s); });
      html += '<div class="bgroup confirm-col" style="border-color:#C99A4E">'+
        '<div class="bgh" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'+
        '<span class="tag warn">同组待确认</span> '+
        '<span class="faint">· '+siblings.length+' 张同组连拍</span>'+
        '<span class="spacer"></span>'+
        '<label style="font-size:12px;cursor:pointer"><input type="checkbox" id="sibSelAll"> 全选</label>'+
        '<button class="btn sm" id="sibBatchLink" disabled>关联选中</button></div>'+
        '<div class="confirm-body">'+
        Object.keys(sg).map(gid=>{
          const items = sg[gid];
          return '<div style="margin-top:8px"><span class="faint" style="font-size:12px">组 '+esc(gid)+' · '+items.length+' 张</span>'+
            '<div class="cand-list">'+items.map((s,i)=>{
              return '<div class="cand-item">'+
                '<input type="checkbox" class="sib-check" value="'+s.photo_id+'" style="margin-right:4px">'+
                '<img loading="lazy" src="'+s.thumb+'" data-full="'+s.photo_id+'" class="cand-thumb">'+
                '<div class="cand-info">'+
                  '<div class="cand-row">'+
                    '<span class="tag warn">同组连拍</span>'+
                    '<span class="faint">'+(s.photo_kind? kindName(s.photo_kind):'未分类')+'</span>'+
                  '</div>'+
                  '<div class="faint" style="margin-top:3px">'+esc(s.file)+
                    ' · '+fmtTaken(s.taken_at)+(i? ' · '+fmtGap(diffSec(items[i-1].taken_at, s.taken_at)) : '')+'</div>'+
                '</div>'+
                '<button class="btn sm ghost" data-sib-link="'+s.photo_id+'" data-code="'+esc(code)+'">单张关联</button>'+
                '<button class="btn sm ghost" data-rej="'+s.photo_id+'" data-code="'+esc(code)+'" title="标记为无关联：之后不在待确认里显示，可撤销">无关联</button>'+
              '</div>';
            }).join('')+'</div></div>';
        }).join('')+'</div></div>';
    }

    // ④ 可能关联的图片：读出来像但尚未关联的候选照片，一键关联
    if(cands.length){
      html += '<div class="bgroup confirm-col">'+
        '<div class="bgh" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'+
        '可能关联的图片 <span class="faint">· '+cands.length+' 张候选</span>'+
        '<span class="spacer"></span>'+
        '<label style="font-size:12px;cursor:pointer"><input type="checkbox" id="candSelAll"> 全选</label>'+
        '<button class="btn sm" id="candBatchLink" disabled>关联选中</button></div>'+
        '<div class="confirm-body">'+
        '<div class="cand-list">'+cands.map(c=>{
          const bm = c.best_match||{};
          const modeTag = bm.mode==='exact'
            ? '<span class="tag ok">精确</span>'
            : '<span class="tag warn">模糊·核对</span>';
          const srcTag = bm.src==='vision' ? '多模态读码' : 'OCR';
          return '<div class="cand-item">'+
            '<input type="checkbox" class="cand-check" value="'+c.photo_id+'" style="margin-right:4px">'+
            '<img loading="lazy" src="'+c.thumb+'" data-full="'+c.photo_id+'" class="cand-thumb">'+
            '<div class="cand-info">'+
              '<div class="cand-row">'+modeTag+
                '<span class="tag">'+srcTag+'</span>'+
                '<span class="code">读出「'+esc(bm.raw||'')+'」</span>'+
                '<span class="faint">置信 '+Math.round((bm.score||0)*100)+'%</span>'+
              '</div>'+
              '<div class="faint" style="margin-top:3px">'+esc(c.file)+
                ' · '+fmtTaken(c.taken_at)+'</div>'+
            '</div>'+
            '<button class="btn sm ghost" data-cand-link="'+c.photo_id+'" data-code="'+esc(code)+'">单张关联</button>'+
            '<button class="btn sm ghost" data-rej="'+c.photo_id+'" data-code="'+esc(code)+'" title="标记为无关联：之后不在可能关联的图片里显示，可撤销">无关联</button>'+
          '</div>';
        }).join('')+'</div></div></div>';
    }

    // ④-2 可能的全景图（2026-10-11）：由已关联的**标签近景**推出来的邻近照片。
    //    产品本体照/包装照上没有编码，系统认不出来，只能"建议 + 人工确认"。
    //    ⚠️ 展示按时间可信度自适应：只有相机原图(exif)才写「间隔 N 秒」——
    //       微信转来的图 taken_at 是**接收**时间（实测 35% 同秒、与拍摄差 2.7 天），
    //       写秒数就是给假数字，一律改成"同组 / 紧邻"这种序列关系。
    const panos = (cand.panoramas||[]);
    if(panos.length){
      html += '<div class="bgroup confirm-col" style="border-color:#0F766E">'+
        '<div class="bgh" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'+
        '<span class="tag" style="background:#ccfbf1;color:#0f766e">可能的全景图</span>'+
        '<span class="faint">· '+panos.length+' 张待确认 · 这张产品本体照可能还没拍全</span>'+
        '</div>'+
        '<div class="confirm-body">'+
        '<div class="faint" style="font-size:12px;margin:4px 0 6px">'+
          '系统只能按拍照顺序猜，<b>请对着图确认</b>是这一件货的全景 —— 认错了点「无关联」。</div>'+
        '<div class="cand-list">'+panos.map(s=>{
          const relTag = s.same_group
            ? '<span class="tag ok">同组连拍</span>'
            : (s.gap_txt ? '<span class="tag">间隔 '+esc(s.gap_txt)+'</span>'
                         : '<span class="tag">紧邻拍摄</span>');
          const usedTag = (s.used_by || 0) > 0
            ? '<span class="tag warn" title="这张全景可能装着不止一件货（整托盘常常如此）">已用于 '+s.used_by+' 个产品</span>' : '';
          return '<div class="cand-item">'+
            '<img loading="lazy" src="'+s.thumb+'" data-full="'+s.photo_id+'" class="cand-thumb">'+
            '<div class="cand-info">'+
              '<div class="cand-row">'+relTag+
              '<span class="faint">'+(s.photo_kind? kindName(s.photo_kind):'未分类')+'</span>'+
              usedTag+'</div>'+
              '<div class="faint" style="margin-top:3px">'+esc(s.file)+
                (s.gap_txt ? '' : ' · 顺序在近景旁边')+'</div>'+
            '</div>'+
            '<button class="btn sm ghost" data-cand-link="'+s.photo_id+'" data-code="'+esc(code)+'">单张关联</button>'+
            '<button class="btn sm ghost" data-rej="'+s.photo_id+'" data-code="'+esc(code)+'" title="标记为无关联：之后不再推荐，可撤销">无关联</button>'+
          '</div>';
        }).join('')+'</div></div></div>';
    }
    html += '</div>';
  }

  // ⑤ 已标记「无关联」：默认折叠（多数时候这里只有一两张），但入口一直在。
  //    标记是人工判断，判断会变 —— 必须能反悔，否则点错一次这张照片就
  //    永久从候选里消失了（照片没删，但再也找不回来）。
  const rejs = rej.items||[];
  if(rejs.length){
    html += '<div class="bgroup" style="margin-top:10px;border-color:#B4B2A9">'+
      '<div class="bgh" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;cursor:pointer" id="rejToggle">'+
        '<span class="tag">已标记无关联</span> '+
        '<span class="faint">· '+rejs.length+' 张不再出现在待确认里</span>'+
        '<span class="spacer"></span><span class="faint" id="rejArrow">展开</span>'+
      '</div>'+
      '<div class="confirm-body" id="rejBody" style="display:none">'+
        '<div class="cand-list">'+rejs.map(r=>{
          return '<div class="cand-item">'+
            '<img loading="lazy" src="'+r.thumb+'" data-full="'+r.photo_id+'" class="cand-thumb">'+
            '<div class="cand-info">'+
              '<div class="cand-row"><span class="tag">无关联</span>'+
                (r.reason? '<span class="faint">'+esc(r.reason)+'</span>' : '')+
              '</div>'+
              '<div class="faint" style="margin-top:3px">'+esc(r.created_at||'')+'</div>'+
            '</div>'+
            '<button class="btn sm ghost" data-unrej="'+r.photo_id+'" data-code="'+esc(code)+'">撤销</button>'+
          '</div>';
        }).join('')+'</div></div></div>';
  }

  $('#pShots').innerHTML = html;
  bindShots('#pShots');
  // 标准图：列出现有（上传/裁剪分标）+ 绑定上传入口
  loadPStdList(code);
  const _up = $('#pStdUpload'), _files = $('#pStdFiles');
  if(_up && _files){
    _up.onclick = ()=>_files.click();
    _files.onchange = uploadPStdFiles;
  }
  // 注：手动关联照片面板已按老板要求移除（10-02）

  // 字段编辑：改完点「保存」，没点之前不算数（回车 = 保存）
  const peInputs = $$('#pShots [data-pf]');
  function peSync(){
    const dirty = pendingEdit();
    const s = $('#peSave'), r = $('#peReset'), m = $('#peMsg');
    if(s) s.disabled = !dirty;
    if(r) r.disabled = !dirty;
    if(m) m.textContent = dirty? '有未保存的修改' : '';
  }
  async function peSave(){
    const payload = {};
    peInputs.forEach(i=>{
      const k = i.dataset.pf, v = (i.value||'').trim();
      if(v !== (pDraft[k]||'')) payload[k] = v;
    });
    if(!Object.keys(payload).length) return;
    try{
      await patch('/api/products/'+encodeURIComponent(code), payload);
      peInputs.forEach(i=>{ pDraft[i.dataset.pf] = (i.value||''); });
      peSync();
      if($('#peMsg')) $('#peMsg').textContent = '已保存';
      toast('已保存','ok');
      loadProducts(false);   // 列表里的品名同步刷新（不重置页码）
    }catch(e){ toast('保存失败：'+e.message,'err'); }
  }
  peInputs.forEach(i=>{
    i.oninput = peSync;
    i.onkeydown = e=>{ if(e.key==='Enter'){ e.preventDefault(); peSave(); } };
  });
  if($('#peSave')) $('#peSave').onclick = peSave;
  if($('#peReset')) $('#peReset').onclick = ()=>{
    peInputs.forEach(i=>{ i.value = pDraft[i.dataset.pf]||''; });
    peSync();
  };

  // 候选照片点击看大图
  $$('#pShots .cand-thumb').forEach(im=>im.onclick=()=>{
    setDrawerList([im.dataset.full]);
    openDrawer(im.dataset.full);
  });
  // 候选单张关联
  $$('#pShots [data-cand-link]').forEach(b=>b.onclick=async ()=>{
    try{
      await post('/api/links',{photo_id:b.dataset.candLink, code:b.dataset.code, by:'web'});
      toast('已关联','ok');
      loadStats();
      openProduct(b.dataset.code);
    }catch(e){ toast('关联失败：'+e.message,'err'); }
  });
  // 候选批量关联：全选 + 选中计数 + 批量按钮
  const candChecks = $$('#pShots .cand-check');
  const candSelAll = $('#candSelAll');
  const candBatchBtn = $('#candBatchLink');
  function updateCandBatch(){
    const checked = candChecks.filter(c=>c.checked);
    if(candBatchBtn) candBatchBtn.disabled = checked.length===0;
    if(candBatchBtn) candBatchBtn.textContent = checked.length? '关联选中('+checked.length+')' : '关联选中';
    if(candSelAll) candSelAll.checked = checked.length===candChecks.length && candChecks.length>0;
  }
  if(candSelAll) candSelAll.onchange = ()=>{
    candChecks.forEach(c=>c.checked=candSelAll.checked);
    updateCandBatch();
  };
  candChecks.forEach(c=>c.onchange=updateCandBatch);
  if(candBatchBtn) candBatchBtn.onclick = async ()=>{
    const pids = candChecks.filter(c=>c.checked).map(c=>c.value);
    if(!pids.length) return;
    try{
      await post('/api/links',{photo_ids:pids, code:code, by:'web'});
      toast('已批量关联 '+pids.length+' 张','ok');
      loadStats();
      openProduct(code);
    }catch(e){ toast('批量关联失败：'+e.message,'err'); }
  };

  // 同组单张关联
  $$('#pShots [data-sib-link]').forEach(b=>b.onclick=async ()=>{
    try{
      await post('/api/links',{photo_id:b.dataset.sibLink, code:b.dataset.code, by:'web'});
      toast('已关联同组照片','ok');
      loadStats();
      openProduct(b.dataset.code);
    }catch(e){ toast('关联失败：'+e.message,'err'); }
  });
  // 同组批量关联
  const sibChecks = $$('#pShots .sib-check');
  const sibSelAll = $('#sibSelAll');
  const sibBatchBtn = $('#sibBatchLink');
  function updateSibBatch(){
    const checked = sibChecks.filter(c=>c.checked);
    if(sibBatchBtn) sibBatchBtn.disabled = checked.length===0;
    if(sibBatchBtn) sibBatchBtn.textContent = checked.length? '关联选中('+checked.length+')' : '关联选中';
    if(sibSelAll) sibSelAll.checked = checked.length===sibChecks.length && sibChecks.length>0;
  }
  if(sibSelAll) sibSelAll.onchange = ()=>{
    sibChecks.forEach(c=>c.checked=sibSelAll.checked);
    updateSibBatch();
  };
  sibChecks.forEach(c=>c.onchange=updateSibBatch);
  if(sibBatchBtn) sibBatchBtn.onclick = async ()=>{
    const pids = sibChecks.filter(c=>c.checked).map(c=>c.value);
    if(!pids.length) return;
    try{
      await post('/api/links',{photo_ids:pids, code:code, by:'web'});
      toast('已批量关联 '+pids.length+' 张同组照片','ok');
      loadStats();
      openProduct(code);
    }catch(e){ toast('批量关联失败：'+e.message,'err'); }
  };

  // 标记「无关联」（读码候选 + 同组候选共用 data-rej）
  //
  // ⚠️ 必须有 confirm：这动作**藏起来后找不回**（虽然可撤销，但老板不会
  //    想到去展开那个折叠区找）。误点一次的代价远大于点一下确认框。
  $$('#pShots [data-rej]').forEach(b=>b.onclick=async ()=>{
    const pid = b.dataset.rej;
    if(!confirm('标记为「无关联」？\n\n之后这张照片不再出现在本产品的待确认列表里。\n只影响本产品 —— 它若是别的产品的候选，仍然照常出现。\n（标记可撤销，在下方「已标记无关联」里能还原）')) return;
    try{
      const r = await post('/api/products/'+encodeURIComponent(b.dataset.code)+'/candidates/reject',
                           {photo_ids:[pid], reason:'人工查看后确认无关联', by:'web'});
      toast(r.marked? '已标记为无关联' : '这张之前已标记过','ok');
      loadStats();
      openProduct(b.dataset.code);
    }catch(e){ toast('标记失败：'+e.message,'err'); }
  });

  // 撤销「无关联」—— 照片回到候选列表
  $$('#pShots [data-unrej]').forEach(b=>b.onclick=async ()=>{
    const pid = b.dataset.unrej;
    try{
      const r = await post('/api/products/'+encodeURIComponent(b.dataset.code)+'/candidates/unreject',
                           {photo_ids:[pid], by:'web'});
      toast(r.unmarked? '已撤销，照片回到待确认' : '这张本来就没有标记','ok');
      loadStats();
      openProduct(b.dataset.code);
    }catch(e){ toast('撤销失败：'+e.message,'err'); }
  });

  // 已标记区块折叠 / 展开
  const rejT = $('#rejToggle');
  if(rejT) rejT.onclick = ()=>{
    const b = $('#rejBody'), a = $('#rejArrow');
    if(!b) return;
    const open = b.style.display!=='none';
    b.style.display = open? 'none' : '';
    if(a) a.textContent = open? '展开' : '收起';
  };

}

/* ── 产品详情抽屉 ──
   左右分栏（表格被压窄）与上下堆叠（点一下要滚到屏幕另一头）都不理想，
   最终方案：列表全宽，详情从右侧滑出盖上来 —— 关掉回到列表原位，
   翻页/搜索/滚动位置一个不丢。 */
function openProductDrawer(){
  $('#pDetail').classList.add('on');
  $('#pMask').classList.add('on');
}
/* force=true 用于「产品已删除」这种必须关的场景 —— 那时没得商量。
   正常关闭（按钮 / 遮罩 / Esc）都要先过 confirmLeave。 */
function closeProductDrawer(force){
  if(!force && !confirmLeave()) return;
  $('#pDetail').classList.remove('on');
  $('#pMask').classList.remove('on');
}
$('#pDetailClose').onclick = ()=>closeProductDrawer();
$('#pMask').onclick = ()=>closeProductDrawer();
onEscape(()=>{   // 只在自己开着时关，关了就消费掉这次 Esc（别再往下关批次抽屉）
  if($('#pDetail').classList.contains('on')){ closeProductDrawer(); return true; }
});
if($('#pPrev')) $('#pPrev').onclick = ()=>gotoProduct(-1);
if($('#pNext')) $('#pNext').onclick = ()=>gotoProduct(1);
// 键盘：抽屉开着且焦点不在输入框里时，↑← 上一个、↓→ 下一个
document.addEventListener('keydown', e=>{
  if(!$('#pDetail').classList.contains('on')) return;
  const t = e.target;
  if(t && (t.tagName==='INPUT' || t.tagName==='TEXTAREA' || t.isContentEditable)) return;
  if(e.key==='ArrowUp' || e.key==='ArrowLeft'){ e.preventDefault(); gotoProduct(-1); }
  else if(e.key==='ArrowDown' || e.key==='ArrowRight'){ e.preventDefault(); gotoProduct(1); }
});

export { pPage, openProduct, P_PAGE, loadProducts, closeProductDrawer, selectProduct, gotoProduct };

/* ── 产品列表工具栏 + 清单导入（产品库自己的控件，别放 drawer.js）── */
if($('#pSearch')) $('#pSearch').onclick = ()=>loadProducts(true);
$('#pQ').onkeydown = e=>{ if(e.key==='Enter') loadProducts(true); };
$('#pHas').onchange = ()=>loadProducts(true);
$('#pSort').onchange = ()=>loadProducts(true);
$('#pContainer').onchange = ()=>loadProducts(true);
// 加载柜号下拉 —— **只认产品清单里的柜号**（老板 10-05 口径）。
// 原来取 /api/batches?kind=photos 的照片批次柜号：既混进与产品无关的柜号
//（真实库里有 delivery 文件名被写进 container_no），又漏掉只登记在清单里、
// 还没拍照的柜号。选项后带产品数，按数量降序 —— 一眼知道哪个柜号货最多。
async function loadContainerOptions(){
  try{
    const d = await api('/api/products/containers');
    const sel = $('#pContainer');
    if(!sel) return;
    const items = d.items||[];
    const cur = sel.value;
    // label 由后端给（`_UNCATEGORIZED` 这类内部值统一显示成「未分柜」），
    // option 的 value 仍是原柜号 —— 筛选照旧能工作
    sel.innerHTML = '<option value="">全部柜号</option>' +
      items.map(it=>'<option value="'+esc(it.container_no)+'">'+
        esc(it.label || it.container_no)+'（'+it.products+' 件）</option>').join('');
    if(cur && items.some(x=>x.container_no===cur)) sel.value = cur;
    sel.title = '柜号取自产品清单（checklist 批次）登记的柜号';
  }catch(e){}
}
loadContainerOptions();
$('#pgPrev').onclick = ()=>{ if(pPage>0){ pPage--; loadProducts(false); window.scrollTo(0,0); } };
$('#pgNext').onclick = ()=>{ pPage++; loadProducts(false); window.scrollTo(0,0); };
/* ── 导入清单（统一模态 —— 资产页按钮与向导②共用同一份实现）──
   柜**只读展示**（取自全局锚点）：导入目标以锚点为准，不在这里再选一次柜，
   否则「在向导选了 A 柜、在资产页导到 B 柜」这种三份真相的毛病又会回来。 */
export function openImportChecklistModal(cid){
  const useCid = cid || getCid();
  openModal({
    title: '导入货品清单',
    width: 520,
    bodyHtml:
      '<p class="faint">将导入到<b>当前所选柜</b>（在「柜作业」右上角切换柜）。'+
      '柜是流程第一步，无柜不导。</p>'+
      '<label>Excel 文件 *</label>'+
      '<input type="file" name="file" accept=".xls,.xlsx">',
    okText: '导入',
    onOk: async (vals, el)=>{
      if(!useCid) return '请先选择柜（到「柜」页进一个柜作业，或在本页的柜选择器里选）';
      const f = el.querySelector('input[name=file]').files[0];
      if(!f) return '请选择 Excel 文件（.xls / .xlsx）';
      const fd = new FormData();
      fd.append('file', f);
      fd.append('container_id', useCid);
      busy(true, '正在解析清单…', f.name);
      try{
        const r = await api('/api/products/import', {method:'POST', body: fd});
        busy(false);
        let msg = '清单导入完成：解析 '+r.parsed+' 条，新增 '+r.added+'，合并 '+r.updated+
          (r.errors.length? ('，跳过 '+r.errors.length+' 行（编码不合规）') : '');
        if(r.relink_error) msg += '。补关联未执行：' + r.relink_error;
        else if(r.relink && r.relink.written > 0) msg += '。补关联 +' + r.relink.written + ' 条';
        toast(msg, r.relink_error ? 'err' : 'ok');
        if(r.errors.length) console.warn(r.errors);
        loadStats(); loadProducts(true);
        window.dispatchEvent(new Event('wizard:refresh'));
        return true;
      }catch(e){ busy(false); return '导入失败：' + e.message; }
    }
  });
}
$('#pImport').onclick = ()=>openImportChecklistModal();
$('#pTmpl').onclick = ()=>{ window.location.href = '/api/products/template'; };
$('#pImport2').onclick = ()=>openImportChecklistModal();
/* 补关联：把已治理但没关联上的照片，用当前产品清单重匹配一次。
   照片先于清单导入时自动关联会全部落空（索引建自 products 表），
   清单导入时后端已自动补过一次；这里是手工兜底入口。 */
$('#pRelink').onclick = async ()=>{
  toast('正在补关联…');
  try{
    const r = await api('/api/products/relink',{method:'POST'});
    if(r.written > 0){
      toast('补关联完成：新增 '+r.written+' 条关联，覆盖 '+r.candidates+' 张照片',
            'ok');
      loadStats(); loadProducts(true);
    }else if(r.candidates > 0){
      toast('没有新增关联：'+r.candidates+' 张照片的识别结果已存在或低于阈值', 'ok');
    }else if(r.scanned > 0){
      toast('没有可补的：'+r.scanned+' 张候选照片都没匹配上清单编码', 'ok');
    }else{
      toast('没有需要补关联的照片', 'ok');
    }
  }catch(err){ toast('补关联失败：'+err.message,'err'); }
};

// 注：#pFile 已随「内联 file input → 统一模态」移除，导入逻辑见 openImportChecklistModal

// 删除产品
$('#pDelete').onclick = async ()=>{
  const code = $('#pDelete').dataset.code;
  if(!code) return;
  if(!confirm('确定删除产品「'+code+'」？\n\n将同时删除：关联记录、标准图文件、批次关联。\n原照片不会被删除。')) return;
  try{
    await del('/api/products/'+encodeURIComponent(code));
    toast('已删除：'+code, 'ok');
    pSel = '';
    closeProductDrawer(true);   // 产品没了，抽屉直接关（不用问未保存改动）
    loadStats();
    loadProducts(true);
  }catch(e){ toast('删除失败：'+e.message, 'err'); }
};

onTab('products', loadProducts);
