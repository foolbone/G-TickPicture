// review.js —— 已跳过照片管理（设置页的撤销入口）
// 关联认领功能已移除，人工标注页只保留「新产品确认」。
import { $, $$, api, post, esc, toast, emptyHtml, onTab } from './core.js';
import { loadStats } from './home.js';

/* ── 已跳过的照片（撤销入口）── */
async function loadSkipped(){
  let d;
  try{ d = await api('/api/photos/skipped?limit=200'); }
  catch(e){ return; }
  $('#skTotal').textContent = d.total? ('共 '+d.total+' 张') : '';
  $('#skBody').innerHTML = d.items.map(p=>
    '<tr><td>'+esc(p.file)+'</td>'+
    '<td class="faint">'+((p.skip_at||'').replace('T',' ').slice(0,16))+'</td>'+
    '<td><button class="btn sm ghost" data-unskip="'+p.id+'">撤销跳过</button></td></tr>').join('');
  $('#skEmpty').innerHTML = d.total? '' :
    emptyHtml('🚫','还没有跳过任何照片','在照片详情里点「跳过」，决定会被记住');
  $('#skEmpty').style.display = d.total? 'none':'block';
  $$('#skBody [data-unskip]').forEach(b=>b.onclick=async ()=>{
    try{
      await post('/api/photos/skip',{photo_id:b.dataset.unskip, skip:false});
      toast('已撤销 —— 照片回到待认领队列','ok');
      loadSkipped(); loadStats();
    }catch(e){ toast('撤销失败：'+e.message,'err'); }
  });
}
$('#skReload').onclick = loadSkipped;

export { loadSkipped };

onTab('set', loadSkipped);
