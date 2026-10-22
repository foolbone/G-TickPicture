// phototree.js —— 照片页左侧「用途 → 分类」树形筛选（2026-10-14 老板需求）
//
// 需求原话：「照片页（包括柜作业里，和照片库），需要将用途和分类在左侧以
// 类似树形，先用途后分类的方式，让用户能够快速知道有哪些分类，并进行筛选」。
//
// 多选（2026-10-19 老板需求：「左侧按分类可以支持多选」）：
//   value 从单选 {usage, kind} 改为多选集合 {usages: [], kinds: []}，
//   每项是 checkbox 样式，点击 toggle 进/出集合。后端 photo_where_sql
//   的 kind/usage 支持逗号分隔 IN（_unset 可与具体项混选），
//   列表/徽章/ facets 全部同源 —— 数字不会漂。
//
// 设计（为什么是树 + 计数，而不是又一行下拉）：
//   ① 下拉里看不到「有哪些」—— 树把用途/分类的全集和**当前范围下各有多少张**
//      直接摆出来，「监装 37」一眼可见，还能看出分布；
//   ② 高频筛选从工具栏那一长串里提到左侧常驻，不用每次点开下拉找；
//   ③ 计数与列表**同源**（/api/photos/facets 与 /api/photos 共用
//      photo_where_sql），树上点进去的条数不会对不上。
//
// 交叉筛选：选了「监装」后，分类计数只算监装照的（点进去不会是 0）；
// 选了某个分类后，用途计数只算该分类的。多选时交叉口径 = 已选集合的并集。
//
// 柜作业③还多一段「监装待确认」（细分待办合并进来，不单独占块）——
// showPending=true 时渲染，选中即按待办集合筛选（pending=1）。
import { $, $$, api, esc, KIND_LABELS } from './core.js';

/** 用途的展示名（与 fUsage 下拉一致：空值算「未分类」）。
 *  编号（01/02/03）只决定节点顺序，文案不带编号（2026-10-17 老板原话）。 */
function usageLabel(u){
  if(!u || u === '_unset') return '未分类';
  return u;
}
function kindLabel(k){
  // facets 把 NULL 归到 '_unset'（IFNULL），与用途侧同款 —— 显示成
  // 「未分类」，别把内部键名裸露给用户（2026-10-15）
  if(k === '_unset') return '未分类';
  return KIND_LABELS[k] || k || '未识别';
}

/** 树的一节（多选 checkbox 样式，2026-10-19）。
 *  sections: [{key, title, items:[{v, label, n}], values:[]（已选集合）}]
 *
 *  ⚠️ 已选但当前计数为 0 的项要**补回来**（2026-10-19）：交叉筛选下该项
 *  在另一维范围内没有照片 → facets 的 GROUP BY 里没有它 → 若是单选无所谓，
 *  多选就会「勾了却找不到地方取消」，而且列表条数对不上还找不到原因。
 *  补成 n=0 显示，高亮保留，再点一次照样能移出集合。 */
function sectionHtml(sec){
  if(!sec.items.length && !(sec.values || []).length){
    return '<div class="ptree-sec"><div class="ptree-t">'+esc(sec.title)+'</div>'+
      '<div class="faint" style="font-size:12px">（没有）</div></div>';
  }
  const vals = sec.values || [];
  const seen = new Set(sec.items.map(it=>it.v));
  const items = sec.items.concat(
    vals.filter(v=>!seen.has(v)).map(v=>({v: v, label: sec.labelOf(v), n: 0})));
  const rows = items.map(it=>{
    const on = vals.indexOf(it.v) >= 0;
    return '<button class="ptree-i'+(on?' on':'')+'" data-v="'+esc(it.v)+'"'+
      ' title="'+esc(it.label)+'（'+it.n+' 张）'+(on?' —— 再点一次取消':'')+'">'+
      '<span class="ptree-cb"></span>'+
      '<span class="ptree-l">'+esc(it.label)+'</span>'+
      '<span class="ptree-n'+(it.n?'':' zero')+'">'+it.n+'</span></button>';
  }).join('');
  // 多选的反操作：勾了三项要一个一个点掉太笨，选中时给个「清空」
  const clr = vals.length
    ? '<button class="ptree-clr" data-clr="1" title="清空本段已选（'+vals.length+
      ' 项）">清空</button>'
    : '';
  const cnt = vals.length ? '<span class="ptree-cnt">'+vals.length+'</span>' : '';
  return '<div class="ptree-sec" data-sec="'+esc(sec.key || '')+'">'+
    '<div class="ptree-t">'+esc(sec.title)+cnt+clr+'</div>'+rows+'</div>';
}

/** 拉计数并重绘。ctx 里带上**当前另一维**的选中值做交叉筛选。
 *  [o] {bar:容器选择器, ctx:()=>当前筛选上下文,
 *       value:{usages:[], kinds:[], pending}（多选集合）,
 *       onChange:(v)=>{}, showPending:bool, pendingN:number} */
export async function loadPhotoTree(o){
  const bar = $(o.bar);
  if(!bar) return;
  let d = {usage: {}, kind: {}};
  try{
    const ctx = o.ctx ? o.ctx() : {};
    d = await api('/api/photos/facets?' + new URLSearchParams({
      container_id: ctx.container_id || '',
      batch: ctx.batch || '', state: ctx.state || '',
      q: ctx.q || '', unlinked: ctx.unlinked ? 1 : 0,
      invalid: ctx.invalid || 'hide',
      // 交叉筛选：数用途时带上已选分类，数分类时带上已选用途。
      // 多选（2026-10-19）：逗号分隔传给后端 IN —— 与列表同一份
      // photo_where_sql，数字同源不漂。
      kind: (o.value.kinds || []).join(','),
      usage: (o.value.usages || []).join(','),
      todo: ctx.todo || ''}));
  }catch(e){
    bar.innerHTML = '<div class="faint">计数读取失败</div>';
    return;
  }
  const val = o.value;
  const usages = val.usages || [];
  const kinds = val.kinds || [];
  // 用途段：固定编号序（01 监装 → 02 预检 → 03 其他 → 未分类收尾）——
  //   编号（老板分类表）只用来定顺序，不上文案。三档的计数排序没收益。
  const USAGE_ORDER = ['监装', '预检', '其他', '_unset'];
  const usageRank = v => { const i = USAGE_ORDER.indexOf(v); return i < 0 ? 99 : i; };
  const usageItems = Object.entries(d.usage || {})
    .map(([v, n])=>({v: v, label: usageLabel(v), n: n}))
    .sort((a, b)=>usageRank(a.v) - usageRank(b.v) || b.n - a.n);
  // 分类段：项多，保持计数优先（快速看出哪类多），同数按中文序
  const kindItems = Object.entries(d.kind || {})
    .map(([v, n])=>({v: v, label: kindLabel(v), n: n}))
    .sort((a, b)=>b.n - a.n || a.label.localeCompare(b.label, 'zh'));
  let html = sectionHtml({key: 'usage', title: '按用途', items: usageItems,
                          values: val.pending ? [] : usages,
                          labelOf: usageLabel});
  html += sectionHtml({key: 'kind', title: '按分类', items: kindItems,
                       values: val.pending ? [] : kinds,
                       labelOf: kindLabel});
  if(o.showPending){
    const pn = (o.pendingN == null) ? null : o.pendingN;
    html += '<div class="ptree-sec"><div class="ptree-t">监装待确认</div>'+
      '<button class="ptree-i'+(val.pending?' on':'')+'" data-pending="1"'+
      ' title="细分还没人工确认的监装照（AI 建议不自动生效）'+
      (val.pending?' —— 再点一次取消':'')+'">'+
      '<span class="ptree-l">待确认细分</span>'+
      '<span class="ptree-n'+(pn?'':' zero')+'">'+
      (pn == null ? '…' : pn)+'</span></button></div>';
  }
  bar.innerHTML = html;
  // 绑定（多选 toggle，2026-10-19）：点未选=加入集合，点已选=移出；
  // pending 与 用途/分类互斥（待办是独立集合口径）
  $$('.ptree-i', bar).forEach(b=>{
    b.onclick = ()=>{
      if(b.dataset.pending){
        o.onChange({usages: [], kinds: [], pending: !val.pending});
        return;
      }
      const sec = b.closest('.ptree-sec');
      const isUsage = sec.dataset.sec === 'usage';
      const v = b.dataset.v;
      const toggle = (arr)=> {
        const i = arr.indexOf(v);
        return i >= 0 ? arr.filter(x=>x!==v) : arr.concat([v]);
      };
      if(isUsage){
        o.onChange({usages: toggle(usages), kinds: kinds, pending: false});
      }else{
        o.onChange({usages: usages, kinds: toggle(kinds), pending: false});
      }
    };
  });
  // 「清空」本段（2026-10-19）：多选的反操作，不然勾了五类要点五次
  $$('.ptree-clr', bar).forEach(b=>{
    b.onclick = ()=>{
      const isUsage = b.closest('.ptree-sec').dataset.sec === 'usage';
      if(isUsage) o.onChange({usages: [], kinds: kinds, pending: false});
      else o.onChange({usages: usages, kinds: [], pending: false});
    };
  });
}

/** 树是否可见地挂在某处（给调用方判断要不要刷新计数用）。 */
export function treeVisible(barSel){
  const el = $(barSel);
  return !!el && el.offsetParent !== null;
}
