// merge.js —— 由 index.html 内联脚本拆分而来，逻辑未改
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS } from './core.js';
import { openDrawer, setDrawerList } from './drawer.js';
import { loadStats } from './home.js';

/* ── 合并建议（含批量）── */
let _mgItems = [];
async function loadMerge(){
  try{
    const d = await api('/api/merge-suggestions');
    _mgItems = d.items;
    $('#mgCount').textContent = '建议 ' + d.items.length + ' 个产品';
    setRevCount('#rtMg', d.items.length);
    $('#mgEmpty').style.display = d.items.length? 'none':'block';
    $('#mgList').innerHTML = d.items.map(g=>{
      const photos = [].concat(g.exact, g.fuzzy);
      const chips = photos.map(ph=>{
        const tag = ph.mode==='exact'
          ? '<span class="tag ok">精确</span>'
          : '<span class="tag warn">模糊·'+esc(ph.mode)+'</span>';
        const src = ph.src==='vision' ? '多模态' : 'OCR';
        return '<div class="mg-photo" data-pid="'+esc(ph.photo_id)+'">'+
          '<img src="/thumb/'+esc(ph.photo_id)+'">'+
          '<div class="i">'+tag+
            '<div class="faint">'+src+' 读出「'+esc(ph.raw)+'」</div></div>'+
          '<button class="btn ghost sm" data-mg-one="'+esc(g.code)+'" data-pid="'+esc(ph.photo_id)+'">并入</button>'+
        '</div>';
      }).join('');
      return '<div class="panel mg-card" data-code="'+esc(g.code)+'">'+
        '<div class="row">'+
          '<span class="tag acc">产品</span>'+
          '<span class="code">'+esc(g.code)+'</span>'+
          '<span class="muted">'+esc(g.name||'')+'</span>'+
          '<span class="tag">'+g.exact.length+' 精确 / '+g.fuzzy.length+' 模糊</span>'+
          '<span class="spacer"></span>'+
          '<button class="btn sm" data-mg-all="'+esc(g.code)+'">全部并入（'+g.photo_count+'张）</button>'+
        '</div>'+
        '<div class="mg-photos">'+chips+'</div>'+
      '</div>';
    }).join('');
  }catch(e){ toast('加载合并建议失败：'+e.message,'err'); }
}
async function doMerge(code, photoIds){
  try{
    const r = await post('/api/merge/confirm',{code, photo_ids:photoIds, by:'user'});
    toast('已并入 '+r.linked+' 张照片到 '+code,'ok');
    loadMerge(); loadStats();
  }catch(e){ toast('并入失败：'+e.message,'err'); }
}
$('#mgBatch').onclick = async ()=>{
  if(!_mgItems.length) return;
  if(!confirm('把全部 '+_mgItems.length+' 个产品的合并建议并入？')) return;
  for(const g of _mgItems){
    const ids = [].concat(g.exact, g.fuzzy).map(ph=>ph.photo_id);
    try{ await post('/api/merge/confirm',{code:g.code, photo_ids:ids, by:'user'}); }catch(e){}
  }
  toast('已批量并入全部建议','ok'); loadMerge(); loadStats();
};
$('#mgReload').onclick = ()=> loadMerge();
$('#mgList').addEventListener('click', e=>{
  const t = e.target;
  if(!(t instanceof HTMLElement)) return;
  if(t.dataset.mgAll){
    const g = _mgItems.find(x=>x.code===t.dataset.mgAll);
    if(!g) return;
    const ids = [].concat(g.exact, g.fuzzy).map(ph=>ph.photo_id);
    if(confirm('把 '+ids.length+' 张照片全部并入产品 '+g.code+'？'))
      doMerge(g.code, ids);
    return;
  }
  if(t.dataset.mgOne){
    if(t.dataset.pid) doMerge(t.dataset.mgOne, [t.dataset.pid]);
    return;
  }
  if(t.tagName==='IMG' && t.parentElement.classList.contains('mg-photo')){
    setDrawerList($$('#mgList .mg-photo').map(e=>e.dataset.pid));
    openDrawer(t.parentElement.dataset.pid);
  }
});

export { loadMerge, _mgItems, doMerge };

onTab('review', loadMerge);
