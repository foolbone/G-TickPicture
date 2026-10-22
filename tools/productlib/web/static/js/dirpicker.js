// dirpicker.js —— 本地目录选择弹窗（通过 /api/browse 浏览后端文件系统）
import { $, api, esc, toast } from './core.js';

let _callback = null;
let _current = '';

function _ensureDialog(){
  if ($('#dirPicker')) return;
  const dlg = document.createElement('div');
  dlg.id = 'dirPicker';
  dlg.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;display:none;align-items:center;justify-content:center;';
  dlg.innerHTML =
    '<div style="background:#fff;border-radius:10px;width:560px;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,.2)">' +
      '<div style="padding:14px 18px;border-bottom:1px solid #eee;display:flex;align-items:center;gap:8px">' +
        '<strong style="font-size:15px">选择目录</strong>' +
        '<span class="spacer" style="flex:1"></span>' +
        '<button class="btn ghost sm" id="dpClose">×</button>' +
      '</div>' +
      '<div style="padding:10px 18px;border-bottom:1px solid #eee;display:flex;align-items:center;gap:8px">' +
        '<button class="btn ghost sm" id="dpUp" title="上级目录">↑ 上级</button>' +
        '<span id="dpPath" style="font-size:13px;color:#555;word-break:break-all;flex:1"></span>' +
      '</div>' +
      '<div id="dpList" style="flex:1;overflow-y:auto;padding:8px 0;min-height:280px"></div>' +
      '<div style="padding:12px 18px;border-top:1px solid #eee;display:flex;align-items:center;gap:8px">' +
        '<span id="dpSel" style="font-size:13px;color:#888;flex:1">未选择</span>' +
        '<button class="btn ghost sm" id="dpCancel">取消</button>' +
        '<button class="btn sm" id="dpOk" disabled>选择此目录</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(dlg);
  dlg.addEventListener('click', e => { if (e.target === dlg) _close(); });
  $('#dpClose').onclick = _close;
  $('#dpCancel').onclick = _close;
  $('#dpUp').onclick = () => _load(_current ? null : '');
  $('#dpOk').onclick = () => {
    if (_callback && _current) { _callback(_current); _close(); }
  };
}

async function _load(path){
  _ensureDialog();
  const url = '/api/browse' + (path ? ('?path=' + encodeURIComponent(path)) : '');
  try{
    const d = await api(url);
    _current = d.current || '';
    $('#dpPath').textContent = _current || '（选择盘符）';
    $('#dpUp').style.visibility = d.parent ? 'visible' : 'hidden';
    $('#dpSel').textContent = _current ? ('当前：' + _current) : '未选择';
    $('#dpOk').disabled = !_current;
    const list = $('#dpList');
    if (!d.items.length){
      list.innerHTML = '<div style="padding:40px;text-align:center;color:#aaa;font-size:14px">空目录</div>';
    } else {
      list.innerHTML = d.items.map(it =>
        '<div class="dp-item" data-path="'+esc(it.path)+'" style="padding:8px 18px;cursor:pointer;display:flex;align-items:center;gap:10px;font-size:14px;border-radius:0">' +
          '<span style="font-size:18px">📁</span>' +
          '<span style="flex:1">'+esc(it.name)+'</span>' +
          '<span style="color:#ccc;font-size:12px">进入 ›</span>' +
        '</div>'
      ).join('');
      list.querySelectorAll('.dp-item').forEach(el => {
        el.onmouseenter = () => el.style.background = '#f0f4ff';
        el.onmouseleave = () => el.style.background = '';
        el.onclick = () => _load(el.dataset.path);
      });
    }
  }catch(e){
    $('#dpList').innerHTML = '<div style="padding:40px;text-align:center;color:#c00;font-size:14px">读取失败：'+esc(e.message)+'</div>';
  }
}

function _close(){
  const dlg = $('#dirPicker');
  if (dlg) dlg.style.display = 'none';
  _callback = null;
}

/**
 * 弹出目录选择器，用户选好后调用 callback(absPath)
 */
export function pickDirectory(callback){
  _callback = callback;
  _ensureDialog();
  $('#dirPicker').style.display = 'flex';
  _load('');
}

/** 给指定 input 旁边加一个"选择目录"按钮 */
export function attachDirPicker(inputId, buttonId){
  const input = document.getElementById(inputId);
  if (!input) return;
  // 检查按钮是否已存在
  let btn = document.getElementById(buttonId);
  if (!btn){
    btn = document.createElement('button');
    btn.id = buttonId;
    btn.className = 'btn ghost sm';
    btn.textContent = '选择目录';
    btn.style.marginLeft = '6px';
    input.parentNode.insertBefore(btn, input.nextSibling);
  }
  btn.onclick = () => pickDirectory(path => {
    input.value = path;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
}
