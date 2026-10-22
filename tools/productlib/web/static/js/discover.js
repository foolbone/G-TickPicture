// discover.js —— 由 index.html 内联脚本拆分而来，逻辑未改
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS, fmtTaken } from './core.js';
import { openDrawer, setDrawerList } from './drawer.js';
import { loadStats } from './home.js';

/* ── 发现新产品（含批量）── */
let _dcItems = [];
async function loadDiscover(){
  try{
    const bid = $('#dcBatchFilter')?.value || '';
    const url = '/api/discover' + (bid? ('?batch='+encodeURIComponent(bid)) : '');
    const d = await api(url);
    _dcItems = d.items;
    $('#dcCount').textContent = '候选 ' + d.items.length;
    setRevCount('#rtDc', d.items.length);
    $('#dcBar').style.display = d.items.length? 'flex':'none';
    $('#dcSelCnt').textContent = '共 '+d.items.length+' 个候选';
    // 2026-10-17 老板规则：库外编码不进本柜报告、后续柜导入清单时自动回捞
    // （relink_due_to_checklist）—— 把这件事在页面上说清，让用户放心先跳过。
    $('#dcHint').textContent = '这些编码不在已导入清单中，不会进本柜报告 —— '
      + '本柜优先处理「待确认关联」；对应清单在后续柜导入时会自动关联这些照片，不急。'
      + (d.ignored ? ('已忽略 ' + d.ignored + ' 个候选编码（忽略后不再出现）') : '');
    $('#dcEmpty').style.display = d.items.length? 'none':'block';
    $('#dcList').innerHTML = d.items.map(p=>{
      const both = p.sources.includes('vision') && p.sources.includes('ocr');
      const src = both ? '多模态+OCR' : (p.sources.includes('vision') ? '多模态读码' : 'OCR');
      const conf = Math.round(p.confidence*100);
      const confTag = conf>=85 ? 'ok' : (conf>=70 ? 'acc' : 'warn');
      // 每张缩略图都带拍照时间（到秒）—— 10-05 老板要求：只要展示图片的地方都要显示
      const ptimes = p.photo_times||{};
      const thumbs = p.photo_ids.slice(0,8).map(id=>
        '<figure class="dcthumb-w" title="'+esc(ptimes[id]||'无 EXIF 时间')+'">'+
        '<img class="dcthumb" src="/thumb/'+id+'" data-full="'+id+'">'+
        '<figcaption>'+fmtTaken(ptimes[id], {clock:true})+'</figcaption></figure>').join('');
      return '<div class="panel dc-card" data-code="'+esc(p.code)+'">'+
        '<div class="row">'+
          '<label class="dcpick" style="display:flex;align-items:center;gap:6px"><input type="checkbox" data-dc-code="'+esc(p.code)+'"></label>'+
          '<span class="tag '+confTag+'">置信 '+conf+'%</span>'+
          '<span class="tag">'+src+'</span>'+
          '<span class="tag">'+p.photo_count+' 张照片</span>'+
          '<span class="code">'+esc(p.raw)+'</span>'+
          (p.raw!==p.code ? '<span class="faint">归一 '+esc(p.code)+'</span>' : '')+
          '<span class="spacer"></span>'+
          '<button class="btn sm" data-dc-confirm="'+esc(p.code)+'">确认入库</button>'+
          '<button class="btn ghost sm" data-dc-ignore="'+esc(p.code)+'"'+
            ' title="永久忽略这个编码（之后任何照片读出它都不再出现）">忽略编码</button>'+
          '<button class="btn ghost sm" data-dc-skip="'+esc(p.code)+'"'+
            ' title="本次忽略：这些照片退出关联队列，新产品先不入库；'+
            '可在照片库「已忽略」档恢复，后续柜导入同一编码时会自动关联">本次忽略</button>'+
        '</div>'+
        '<div class="row dc-thumbs">'+thumbs+'</div>'+
        '<div class="dc-edit" style="display:none"></div>'+
      '</div>';
    }).join('');
  }catch(e){ toast('加载候选失败：'+e.message,'err'); }
}
function dcToggleEdit(code){
  const card = document.querySelector('.dc-card[data-code="'+CSS.escape(code)+'"]');
  if(!card) return;
  const edit = card.querySelector('.dc-edit');
  if(edit.style.display==='block'){ edit.style.display='none'; return; }
  edit.style.display='block';
  edit.innerHTML = '<div class="row">'+
    '<span class="muted">确认写入产品库：</span>'+
    '<span class="code">'+esc(code)+'</span>'+
    '<input type="text" class="dcName" placeholder="品名（选填，建议填）">'+
    '<input type="text" class="dcSpec" placeholder="规格（选填）">'+
    '<button class="btn sm" data-dc-save="'+esc(code)+'">保存入库</button>'+
    '<button class="btn ghost sm" data-dc-cancel="">取消</button>'+
  '</div>';
}
async function dcSave(code, card){
  const nameEl = card.querySelector('.dcName');
  const specEl = card.querySelector('.dcSpec');
  const item = _dcItems.find(x=>x.code===code);
  try{
    const r = await post('/api/products/from-photo',{
      code, name:(nameEl?nameEl.value:'').trim(), spec:(specEl?specEl.value:'').trim(),
      photo_ids: item? item.photo_ids : [], by:'user'});
    toast('已入库 '+code+'，自动关联 '+r.linked+' 张来源照片','ok');
    loadDiscover(); loadStats();
  }catch(e){ toast('入库失败：'+e.message,'err'); }
}
$('#dcReload').onclick = ()=> loadDiscover();
$('#dcBatch').onclick = ()=>{
  const codes = _dcItems.map(x=>x.code);
  if(!codes.length) return;
  if(!confirm('把全部 '+codes.length+' 个候选编码确认入库？（仍会按各自来源照片自动关联）')) return;
  dcBatchDo(codes);
};
$('#dcBatchDo').onclick = ()=>{
  const codes = $$('#dcList .dcpick input:checked').map(c=>c.dataset.dcCode);
  if(!codes.length) return toast('先勾选要确认的候选','err');
  dcBatchDo(codes);
};
$('#dcBatchIgnore').onclick = ()=>{
  const codes = $$('#dcList .dcpick input:checked').map(c=>c.dataset.dcCode);
  if(!codes.length) return toast('先勾选要忽略的候选','err');
  if(!confirm('忽略选中的 '+codes.length+' 个候选？（之后不再出现）')) return;
  Promise.all(codes.map(c=>post('/api/discover/ignore',{code:c}))).then(()=>{ toast('已忽略 '+codes.length+' 个','ok'); loadDiscover(); });
};
async function dcBatchDo(codes){
  let ok=0;
  for(const code of codes){
    const item = _dcItems.find(x=>x.code===code);
    try{
      await post('/api/products/from-photo',{code, name:'', spec:'',
        photo_ids: item? item.photo_ids : [], by:'user'}); ok++;
    }catch(e){ /* 跳过单个失败 */ }
  }
  toast('已批量入库 '+ok+' / '+codes.length+' 个','ok'); loadDiscover(); loadStats();
}
$('#dcList').addEventListener('click', e=>{
  const t = e.target;
  if(!(t instanceof HTMLElement)) return;
  if(t.dataset.dcConfirm){ dcToggleEdit(t.dataset.dcConfirm); return; }
  if(t.dataset.dcIgnore){
    if(confirm('忽略编码 '+t.dataset.dcIgnore+'？之后不再出现在发现列表。')){
      post('/api/discover/ignore',{code:t.dataset.dcIgnore})
        .then(()=>loadDiscover())
        .catch(err=>toast('忽略失败：'+err.message,'err'));
    }
    return;
  }
  // 本次忽略（2026-10-18 需求4）：把该候选的来源照片全部标记忽略 ——
  // 退出待关联/候选/新产品队列；照片库「已忽略」档可恢复。
  if(t.dataset.dcSkip){
    const item = _dcItems.find(x=>x.code===t.dataset.dcSkip);
    const ids = (item && item.photo_ids) || [];
    if(!ids.length) return toast('这个候选没有来源照片', 'err');
    if(!confirm('本次忽略 '+t.dataset.dcSkip+' 的 '+ids.length+' 张照片？\n\n'+
        '这些照片会退出关联队列（新产品先不入库），可在照片库「已忽略」档恢复；'+
        '后续柜导入同一编码时会自动关联上。')) return;
    post('/api/photos/ignore',{photo_ids: ids, ignored: true, by: 'web'})
      .then(r=>{ toast('已忽略 '+r.updated+' 张照片', 'ok'); loadDiscover(); loadStats(); })
      .catch(err=>toast('忽略失败：'+err.message,'err'));
    return;
  }
  if(t.dataset.dcSave){
    const card = t.closest('.dc-card');
    if(card) dcSave(t.dataset.dcSave, card);
    return;
  }
  if(t.dataset.dcCancel!==undefined){
    const edit = t.closest('.dc-edit');
    if(edit) edit.style.display='none';
    return;
  }
  if(t.classList.contains('dcthumb') && t.dataset.full){
    // 点击时按当前网格取序列，避免与同页其它网格互相覆盖
    setDrawerList($$('#dcList .dcthumb[data-full]').map(e=>e.dataset.full));
    openDrawer(t.dataset.full);
  }
});

export { dcSave, _dcItems, dcToggleEdit, loadDiscover, dcBatchDo };

/* ── 按柜号批次筛选 ── */
async function loadDiscoverBatches(){
  try{
    const d = await api('/api/batches?kind=photos');
    const sel = $('#dcBatchFilter');
    if(!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">全部批次</option>' +
      (d.items||[]).map(b=>{
        const label = b.container_no ? ('【'+esc(b.container_no)+'】') : '';
        return '<option value="'+esc(b.id)+'">'+label+esc(b.name||b.id)+
               ' ('+(b.unique||b.item_count||0)+' 张)</option>';
      }).join('');
    if(cur) sel.value = cur;
  }catch(e){ /* 静默 */ }
}
$('#dcBatchFilter').onchange = ()=>loadDiscover();

onTab('review', loadDiscover);
onTab('review', loadDiscoverBatches);
