// selbatch.js —— 批量选择模式（2026-10-12 照片库首发，2026-10-14 柜作业③复用）
//
// 为什么抽成模块：照片库和柜作业③各有一个操作条（不同 DOM id），但行为
// 完全一样（点卡片=勾选、跨页保留、批量置/撤销无效）。两份实现必然漂，
// 抽出来共用一份。选中集合是模块级单例 —— 两个页面看到的是同一批 photo id。
//
// 无效照片语义（schema.py 同款）：只写 is_invalid 标记，**永不删文件**
// （取证原件只读）；撤销清空留痕字段但保留记录。
import { $, $$, api, post, toast } from './core.js';

let _on = false;
const _set = new Set();

export function selOn(){ return _on; }
export function selIds(){ return [..._set]; }
export function selSize(){ return _set.size; }
export function selHas(id){ return _set.has(id); }
export function selToggle(id){
  if(_set.has(id)) _set.delete(id); else _set.add(id);
  // 顺手更新**当前生效**的操作条计数 —— 两个页面（照片库/柜作业③）共用
  // 这份勾选状态，各持各的条子，不能写死某一页的 id。
  selUpdBar(_curIds || {});
}
export function selClear(){ _set.clear(); }
export function selReset(){ _on = false; _set.clear(); }

/** 把一批 id 直接灌进勾选集（「全选筛选结果」用，2026-10-15 需求1）。
 *  与 selToggle 不同：只加不删 —— 已勾的保持勾选。 */
export function selAddIds(ids){
  (ids || []).forEach(id=>{ if(id) _set.add(id); });
  selUpdBar(_curIds || {});
}

/** 进入/退出选择模式。onDone 在批量动作成功后回调（各页面自己刷新）。
 *  ids.onMode：模式切换后回调（页面用它重绑卡片点击行为）。 */
export function selSetMode(on, ids, onDone){
  _on = !!on;
  if(!_on) _set.clear();
  const btn = $(ids.btn), bar = $(ids.bar);
  if(btn){
    btn.classList.toggle('on', _on);
    btn.textContent = _on ? '退出选择' : '批量选择';
  }
  if(bar) bar.style.display = _on ? 'flex' : 'none';
  selUpdBar(ids);
  selBindBar(ids, onDone);
  if(ids.onMode) ids.onMode();
}

export function selUpdBar(ids){
  const n = $(ids.n);
  if(n) n.textContent = _set.size;
}

/** 把操作条的按钮接到当前这份 id 配置上（每次模式切换/页面重绑时调）。
 *  [ids.clear] 「清除已选」（2026-10-15）：选错不用一个个点掉 —— 清空勾选集
 *  但**留在选择模式**（退出选择是 exit 的活，两个按钮语义不同）。 */
export function selBindBar(ids, onDone){
  const b = k => $(ids[k]);
  const ex = b('exit'); if(ex) ex.onclick = ()=>selSetMode(false, ids, onDone);
  const cl = b('clear');
  if(cl) cl.onclick = ()=>{
    _set.clear(); selUpdBar(ids);
    // 已加载卡片的 ✓ 也抹掉 —— 没加载到的页无所谓（翻到那里本来就是未勾态）
    (ids.boxSel ? $$(ids.boxSel + ' .shot') : [])
      .forEach(c=>c.classList.remove('sel-on'));
  };
  const all = b('all');
  if(all) all.onclick = ()=>{
    (ids.boxSel ? $$(ids.boxSel + ' .shot') : []).forEach(c=>{
      _set.add(c.dataset.id); c.classList.add('sel-on');
    });
    selUpdBar(ids);
  };
  const inv = b('invalid');
  if(inv) inv.onclick = ()=>_apply(ids, true, onDone);
  const val = b('valid');
  if(val) val.onclick = ()=>_apply(ids, false, onDone);
  // 本次忽略（2026-10-18）：新产品暂不入库、退出关联队列；恢复 = 回队列
  const ig = b('ignore');
  if(ig) ig.onclick = ()=>_applyIgnore(ids, true, onDone);
  const uig = b('unignore');
  if(uig) uig.onclick = ()=>_applyIgnore(ids, false, onDone);
}

async function _applyIgnore(ids, flag, onDone){
  if(!_set.size) return toast('先勾选照片', 'err');
  const doing = [..._set];
  try{
    const r = await post('/api/photos/ignore',
      {photo_ids: doing, ignored: flag, by: 'web'});
    toast((flag ? '已忽略 ' : '已恢复 ') + r.updated + ' 张照片', 'ok');
    _set.clear(); selUpdBar(ids);
    if(onDone) onDone(flag, r.updated);
  }catch(e){ toast('操作失败：' + e.message, 'err'); }
}

async function _apply(ids, flag, onDone){
  if(!_set.size) return toast('先勾选照片', 'err');
  const doing = [..._set];
  try{
    const r = await post('/api/photos/invalid',
      {photo_ids: doing, invalid: flag, by: 'web'});
    toast((flag ? '已标记 ' : '已取消 ') + r.updated + ' 张无效照片', 'ok');
    _set.clear(); selUpdBar(ids);
    if(onDone) onDone(flag, r.updated);
  }catch(e){ toast('操作失败：' + e.message, 'err'); }
}

/** 卡片点击行为：选择模式=勾选，普通模式=原逻辑（由调用方给）。 */
export function selCardClick(card, normal){
  if(_on){
    selToggle(card.dataset.id);
    card.classList.toggle('sel-on', _set.has(card.dataset.id));
    return;
  }
  normal(card);
}

/* 当前生效的 bar id 配置（selToggle 要用它更新计数条）。
   两个页面不会同时开选择模式，单例足够。 */
let _curIds = null;
export function selSetIds(ids){ _curIds = ids; }
function _barIds(){ return _curIds || {}; }
