// report.js —— **报告档案**（2026-10-11 精简）。
// 三步取材/生成流程已整段移除（老板 10-11）：出报告只走「柜作业⑤」，
// 生成选项与④用图都在那边配。这一页只负责**档案**：
// 概览卡 + 按柜/文件名筛选 + 下载/删除。
// 柜号**只用后端 container_no**（后端按 `CNTR#<柜号>-` 解析）——
// 前端自己写正则必然与后端漂移（两处各写一份必然漂移），已去掉。
import { $, $$, api, del, esc, toast, onTab } from './core.js';

function fmtSize(b){ return b >= 1048576 ? (b/1048576).toFixed(1)+' MB'
                                          : Math.max(1, Math.round(b/1024))+' KB'; }
let _rfAll = [];
async function loadReportFiles(){
  let d;
  try{ d = await api('/api/report/loading-list'); }
  catch(e){ return; }
  _rfAll = d.items || [];
  _renderRfContainers();
  renderReportFiles();
}
function _renderRfContainers(){
  const sel = $('#rfContainer');
  if(!sel) return;
  const nos = [...new Set(_rfAll.map(f=>f.container_no).filter(Boolean))].sort();
  const cur = sel.value;
  sel.innerHTML = '<option value="">全部柜（'+nos.length+'）</option>'
    + nos.map(n=>'<option value="'+esc(n)+'">'+esc(n)+'</option>').join('');
  if(cur && nos.indexOf(cur) >= 0) sel.value = cur;
}
function renderReportFiles(){
  const cid = ($('#rfContainer')||{}).value || '';
  const q = (($('#rfQ')||{}).value || '').trim().toLowerCase();
  const items = _rfAll.filter(f =>
    (!cid || f.container_no === cid) &&
    (!q || (f.name || '').toLowerCase().indexOf(q) >= 0));

  // 资产概览（全量口径 —— 筛选只改显示，不改结论）
  const bytesAll = _rfAll.reduce((a, x)=>a + (x.bytes || 0), 0);
  const month = new Date().toISOString().slice(0, 7);
  const monthNew = _rfAll.filter(f=>String(f.mtime || '').slice(0, 7) === month).length;
  const cntrs = new Set(_rfAll.map(f=>f.container_no).filter(Boolean)).size;
  const card = (n, l)=>'<div class="card"><div class="n">'+esc(n)+'</div>'
    +'<div class="l">'+esc(l)+'</div></div>';
  const box = $('#rfCards');
  if(box) box.innerHTML = card(_rfAll.length, '总份数')
    + card(fmtSize(bytesAll), '占用空间')
    + card(monthNew, '本月新增')
    + card(cntrs, '已归档柜数');

  const tot = $('#rpFilesTotal');
  if(tot) tot.textContent = _rfAll.length
    ? ('显示 '+items.length+' / 共 '+_rfAll.length+' 份 · 占用 '+fmtSize(bytesAll)) : '';
  $('#rpFilesEmpty').style.display = items.length? 'none':'block';
  $('#rpFilesBody').innerHTML = items.map(f=>{
    const cno = f.container_no || '';
    return '<tr><td>'+esc(f.name)+'</td>'
      +'<td>'+(cno ? '<span class="tag acc">'+esc(cno)+'</span>'
                   : '<span class="faint">未解析出柜号</span>')+'</td>'
      +'<td class="faint">'+fmtSize(f.bytes)+'</td>'
      +'<td class="faint">'+esc((f.mtime||'').replace('T',' ').slice(0,16))+'</td>'
      +'<td><a class="btn sm" href="'+esc(f.download)+'">下载</a> '
      +'<button class="btn ghost sm" data-rf-del="'+esc(f.name)+'">删除</button></td></tr>';
  }).join('');
  $$('#rpFilesBody [data-rf-del]').forEach(b=>b.onclick=async ()=>{
    const name = b.dataset.rfDel;
    if(!confirm('删除已生成的报告？\n\n'+name+'\n\n删了就没了，需要的话要重新生成（到柜作业⑤按柜重跑一次）。')) return;
    try{
      await del('/api/report/loading-file?path='+encodeURIComponent(name));
      toast('已删除（还能重新生成）','ok');
      loadReportFiles();
    }catch(e){ toast('删除失败：'+e.message,'err'); }
  });
}
$('#rpFilesReload').onclick = loadReportFiles;
// 档案筛选：只改显示，不动数据
$('#rfContainer').onchange = renderReportFiles;
$('#rfQ').addEventListener('keydown', e=>{ if(e.key === 'Enter') renderReportFiles(); });
$('#rfSearch').onclick = renderReportFiles;
$('#rfReset').onclick = ()=>{
  const s = $('#rfContainer'), q = $('#rfQ');
  if(s) s.value = '';
  if(q) q.value = '';
  renderReportFiles();
};

onTab('report', loadReportFiles);
