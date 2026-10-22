// home.js —— 概览页：顶部统计卡 + 批次统计 + 系统说明
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS } from './core.js';

/* ── 概览 ── */
async function loadStats(){
  const s = await api('/api/stats');
  // 模型名单独包一层 .vm：窄窗口下 CSS 只藏这一段（顶栏必须一行），
  // 全文始终留在 title 上，信息不丢。改文案时别把它塞回纯 textContent。
  const vp = $('#visionPill');
  const vBase = '多模态：已启用';
  const vFull = s.vision_enabled ? vBase + '（' + s.vision_model + '）' : '多模态：未配置（降级运行）';
  vp.innerHTML = s.vision_enabled
    ? vBase + '<span class="vm">（' + esc(s.vision_model) + '）</span>'
    : '多模态：未配置（降级运行）';
  vp.title = vFull;
  vp.className = 'pill' + (s.vision_enabled?'':' warn');
  $('#topStat').innerHTML = '产品 <b>'+s.products+'</b> · 照片 <b>'+s.photos+'</b> · 关联 <b>'+s.links+'</b>';

  const cov = s.products ? Math.round(s.with_photos/s.products*100) : 0;
  $('#cards').innerHTML = [
    ['产品', s.products, ''],
    ['有照片的产品', s.with_photos+' / '+s.products, cov>=50?'ok':'warn'],
    ['照片', s.photos, ''],
    ['待治理', s.pending, s.pending>0?'warn':'ok'],
    ['待关联', s.unlinked, s.unlinked>0?'warn':'ok'],
    ['关联', s.links, ''],
  ].map(([l,n,c])=>'<div class="card '+c+'"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>').join('');

  loadBatchStats();
}

/* 批次统计：汇总卡 + 明细表（与批次抽屉同源 /api/batches） */
async function loadBatchStats(){
  let d;
  try{ d = await api('/api/batches'); }catch(e){ return; }
  const items = d.items || [];
  $('#homeBatchEmpty').style.display = items.length? 'none':'block';
  if(!items.length){ $('#batchCards').innerHTML=''; $('#homeBatchBody').innerHTML=''; return; }

  const total = items.length;
  const doneN = items.filter(b=>b.pending===0 && b.failed===0 && b.unique>0).length;
  const failN = items.filter(b=>(b.failed||0)>0).length;
  const linkedSum = items.reduce((a,b)=>a+(b.linked||0),0);
  $('#batchCards').innerHTML = [
    ['批次总数', total, ''],
    ['已完成', doneN+' / '+total, doneN===total?'ok':''],
    ['有失败', failN, failN>0?'warn':'ok'],
    ['已关联照片', linkedSum, linkedSum>0?'ok':'warn'],
  ].map(([l,n,c])=>'<div class="card '+c+'"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>').join('');

  $('#homeBatchBody').innerHTML = items.map(b=>{
    const done = b.unique - (b.pending||0) - (b.failed||0);
    const prog = b.unique? Math.round(done/b.unique*100) : 0;
    const progTag = (b.pending===0 && b.failed===0 && b.unique>0)
      ? '<span class="tag ok">完成</span>'
      : '<span class="tag '+(b.pending?'warn':'')+'">'+done+'/'+b.unique+'</span>';
    const fails = b.failed? ' <span class="tag err">失败 '+b.failed+'</span>' : '';
    return '<tr>'+
      '<td>'+esc(b.name||b.id)+'</td>'+
      '<td class="faint">'+(b.created_at||'').replace('T',' ').slice(0,16)+'</td>'+
      '<td>'+b.unique+' <span class="faint">/ '+b.total+'</span></td>'+
      '<td>'+progTag+fails+' <div class="bar" style="margin:2px 0 0;height:5px"><i style="width:'+prog+'%"></i></div></td>'+
      '<td>'+(b.linked||0)+'</td></tr>';
  }).join('');
}

export { loadStats, loadBatchStats };

onTab('home', loadStats);
