// modal.js —— 统一模态（2026-10-06 v5 写操作基础设施）
// 所有「创建 / 导入 / 生成 / 删除确认」类动作一律走模态，不再内联表单。
// 用法：openModal({ title, bodyHtml, okText, danger, width, onOk(values, el) })
//   onOk 返回 true / falsy → 成功，关闭
//   onOk 返回 string       → 当作错误显示在模态内（不关闭）
//   onOk 抛异常            → 异常 message 显示在模态内
//
// ⚠️ `true` 必须算成功：人类直觉是「返回 true = 成功」，而「truthy = 有错误」
//    会让 `return true` 静默变成「弹个错误框且关不掉」（2026-10-06 实测踩到）。
//    所以这里显式判 `err && err !== true`，只有**非空字符串**才当错误。
//   onOk 需要关闭但想自己控制（如多步）时返回 falsy 即可。
import { esc } from './core.js';

let _root = null;
function root(){
  if(!_root){
    _root = document.createElement('div');
    _root.id = 'modalRoot';
    document.body.appendChild(_root);
  }
  return _root;
}

export function openModal(opt){
  const o = opt || {};
  const width = o.width || 480;
  const ov = document.createElement('div');
  ov.className = 'modal-overlay';
  ov.innerHTML =
    '<div class="modal" style="max-width:' + width + 'px">' +
      '<div class="modal-head"><b>' + esc(o.title || '') + '</b>' +
        '<span class="x" data-m-close title="关闭">&times;</span></div>' +
      '<div class="modal-body">' + (o.bodyHtml || '') + '</div>' +
      '<div class="modal-foot">' +
        '<button class="btn' + (o.danger ? ' danger' : '') + '" data-m-ok>' + esc(o.okText || '确定') + '</button>' +
        '<button class="btn ghost" data-m-cancel>' + esc(o.cancelText || '取消') + '</button>' +
      '</div>' +
    '</div>';
  const body = ov.querySelector('.modal-body');
  const close = ()=>{ ov.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = e=>{
    if(e.key !== 'Escape') return;
    if(_dirty(ov)){ if(!window.confirm('有未保存内容，确定关闭？')) return; }
    close();
  };
  ov.addEventListener('click', e=>{
    if(e.target !== ov) return;
    if(_dirty(ov)){ if(!window.confirm('有未保存内容，确定关闭？')) return; }
    close();
  });
  ov.querySelector('[data-m-close]').onclick = ()=>{
    if(_dirty(ov)){ if(!window.confirm('有未保存内容，确定关闭？')) return; }
    close();
  };
  ov.querySelector('[data-m-cancel]').onclick = ()=>{
    if(_dirty(ov)){ if(!window.confirm('有未保存内容，确定关闭？')) return; }
    close();
  };
  const okBtn = ov.querySelector('[data-m-ok]');
  okBtn.onclick = async ()=>{
    okBtn.disabled = true;
    try{
      const vals = _collect(ov);
      const err = o.onOk ? (await o.onOk(vals, ov)) : null;
      // `true` 也算成功（见文件头注释）—— 只有非空字符串 / Error 才是错误
      if(err && err !== true){ _showErr(body, err); okBtn.disabled = false; return; }
      close();
    }catch(e){ _showErr(body, (e && e.message) ? e.message : String(e)); okBtn.disabled = false; }
  };
  _snapshot(ov);          // 记下初值快照（脏值判定要与它比，见 _dirty）
  root().appendChild(ov);
  document.addEventListener('keydown', onKey);
  const first = ov.querySelector('input,select,textarea');
  if(first) setTimeout(()=>{ try{ first.focus(); }catch(_){} }, 30);
  return { close, el: ov };
}

function _collect(ov){
  const vals = {};
  ov.querySelectorAll('[name]').forEach(el=>{
    vals[el.name] = (el.type === 'checkbox') ? el.checked : el.value;
  });
  return vals;
}
function _showErr(body, msg){
  let box = body.querySelector('.modal-err');
  if(!box){
    box = document.createElement('div');
    box.className = 'modal-err';
    body.appendChild(box);
  }
  box.textContent = msg;
}
/** 记下每个控件的初值。「脏不脏」要比的是**有没有改过**，不是「有没有填东西」。 */
function _snapshot(ov){
  ov.querySelectorAll('input,textarea,select').forEach(el=>{
    el.dataset.init = (el.type === 'checkbox') ? (el.checked ? '1' : '0')
                                               : (el.value || '');
  });
}
function _dirty(ov){
  // 与初值快照比对（2026-10-09）：原来是「非空即脏」，在建柜表单**预填**了
  // 上次输入的客户/地点之后，用户一个字没改、点取消也会被拦一句「有未保存
  // 内容」—— 那是纯噪音（老板明确不吃噪音提示）。快照比对才是「真的改过没」，
  // 也是本项目既定的离开拦截口径。空输入框的初值是 ''，改了才脏，行为不变。
  let d = false;
  ov.querySelectorAll('input,textarea,select').forEach(el=>{
    const cur = (el.type === 'checkbox') ? (el.checked ? '1' : '0') : (el.value || '');
    const init = el.dataset.init;
    if(init === undefined){ if(cur.trim() !== '') d = true; return; }
    if(cur !== init) d = true;
  });
  return d;
}
