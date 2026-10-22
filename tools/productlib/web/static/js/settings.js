// settings.js —— 设置页
import { $, $$, api, post, esc, toast, onTab } from './core.js';
import { loadStats } from './home.js';

/* ── 设置 ── */
async function loadFields(){
  const d = await api('/api/fields');
  $('#fieldsBody').innerHTML = d.fields.map(f=>
    '<tr><td class="code">'+esc(f.name)+'</td><td>'+esc(f.label)+'</td>'+
    '<td>'+(f.required?'<span class="tag err">必填</span>':'<span class="faint">选填</span>')+'</td>'+
    '<td class="muted">'+esc(f.desc)+'</td></tr>').join('');
  $('#kindsBody').innerHTML = Object.keys(d.kinds).map(k=>
    '<tr><td class="code">'+esc(k)+'</td><td class="muted">'+esc(d.kinds[k])+'</td></tr>').join('');
  const v = await api('/api/vision/config');
  $('#vBase').value = v.api_base; $('#vModel').value = v.model;
  $('#vMsg').textContent = v.enabled ? '已配置'+(v.has_key?'（key 已保存）':'') : '未配置 —— 治理会降级运行';
}
$('#vSave').onclick = async ()=>{
  try{
    const r = await post('/api/vision/config',{api_base:$('#vBase').value.trim(),
      api_key:$('#vKey').value.trim(), model:$('#vModel').value.trim()});
    toast('已保存','ok');
    $('#vMsg').textContent = r.enabled? '已配置，多模态已启用' : '未配置 —— 治理会降级运行';
    loadStats();
  }catch(e){ toast('保存失败：'+e.message,'err'); }
};
$('#vTest').onclick = async ()=>{
  toast('调用中…');
  try{
    const r = await post('/api/vision/test',{});
    toast('调用成功（'+r.seconds+'s）：'+JSON.stringify(r.classify),'ok');
    console.log(r);
  }catch(e){ toast('调用失败：'+e.message,'err'); }
};

/* ── 标准库自动落盘 ── */
const STD_EXP_DEFAULT = 'D:\\G-TickPicture\\标准产品库';
function loadStdExpDir(){
  try{ return localStorage.getItem('stdExpDir') || STD_EXP_DEFAULT; }
  catch(e){ return STD_EXP_DEFAULT; }
}
function saveStdExpDir(d){
  try{ localStorage.setItem('stdExpDir', d); }catch(e){}
}
$('#stdExpDir').value = loadStdExpDir();
$('#stdExpDir').onchange = ()=>{ saveStdExpDir($('#stdExpDir').value.trim()); };
$('#stdExpRun').onclick = async ()=>{
  const dir = $('#stdExpDir').value.trim();
  if(!dir) return toast('先填落盘目录','err');
  saveStdExpDir(dir);
  $('#stdExpRun').disabled = true;
  try{
    const r = await post('/api/export/standard',{dir});
    $('#stdExpMsg').innerHTML = '已落盘 <b>'+r.products+'</b> 个产品 / <b>'+r.photos+
      '</b> 张照片 → <b>'+esc(r.dir)+'</b>'+
      (r.missing? ('（'+r.missing+' 张源文件缺失已跳过）'):'');
    toast('落盘完成：'+r.photos+' 张照片','ok');
  }catch(e){ toast('落盘失败：'+e.message,'err'); }
  $('#stdExpRun').disabled = false;
};

export { loadFields };

onTab('set', loadFields);
