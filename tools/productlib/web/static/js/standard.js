// standard.js —— 标准图编辑器
// 标准库整库落盘已移到设置页（settings.js），由系统自动完成。
import { $, $$, api, post, patch, del, esc, toast, emptyHtml, busy, go, onTab, revTab, setRevCount, kindCls, kindName, kindChip, kindBadge, KIND_LABELS } from './core.js';

/* ── 标准图编辑器 ── */
function stdSuggest(kind){
  if(kind==='label')    return '标识卡类 → 横版 4:3，卡面占满、四边少留背景';
  if(kind==='product')  return '产品类 → 1:1 特写，主体居中';
  if(kind==='packaging')return '包装类 → 4:3，含可识别面（唛头/标签侧）';
  return '未分类 → 建议先去「预检照片入库」重跑分类，或按 4:3 裁出主体';
}
const STD = {pid:null, img:null, work:null, rot:0, crop:{x:0,y:0,w:0,h:0}, scale:1};
function stdRatioVal(){
  const v = parseFloat($('#stdRatio').value);
  return v>0 ? v : 0;
}
async function openStdEditor(pid, kind, defCode){
  // 没有源照片就别开编辑器 —— 否则会去请求 /img/undefined 并静默失败
  if(!pid){ toast('先选中一张照片，再制作标准图','err'); return; }
  STD.pid = pid; STD.rot = 0; STD.work = null; STD.img = null;
  $('#stdSug').textContent = stdSuggest(kind||'unknown');
  $('#stdKind').innerHTML = Object.keys(KIND_LABELS)
    .filter(k=>k!=='scene' && k!=='packing_list')
    .map(k=>'<option value="'+k+'"'+(k===(kind||'unknown')?' selected':'')+'>'+KIND_LABELS[k]+'</option>').join('');
  $('#stdCode').value = defCode || '';
  $('#stdMsg').textContent = '';
  $('#stdRatio').value = kind==='product' ? '1' : (kind==='label'||kind==='packing_list') ? '1.3333' : '0';
  $('#stdEd').classList.add('on');
  const img = new Image();
  img.onload = ()=>{ STD.img = img; applyStdRotation(); };
  img.onerror = ()=>{ toast('原图加载失败','err'); closeStdEditor(); };
  img.src = '/img/'+pid;
}
function closeStdEditor(){ $('#stdEd').classList.remove('on'); STD.work = null; stdZoomHide(); }
function stdWorkCanvas(){
  const img = STD.img;
  const c = document.createElement('canvas');
  const r = ((STD.rot % 360) + 360) % 360;
  const swap = (r===90 || r===270);
  c.width  = swap ? img.naturalHeight : img.naturalWidth;
  c.height = swap ? img.naturalWidth  : img.naturalHeight;
  const x = c.getContext('2d');
  x.translate(c.width/2, c.height/2);
  x.rotate(r * Math.PI/180);
  x.drawImage(img, -img.naturalWidth/2, -img.naturalHeight/2);
  return c;
}
function applyStdRotation(){
  STD.work = stdWorkCanvas();
  // stdEd 刚 .on 时布局可能还没完成，stage 尺寸为 0 会导致 canvas 缩成 0。
  // 用 requestAnimationFrame 等一帧布局完成后再算尺寸。
  requestAnimationFrame(()=>{
    const stage = document.querySelector('.std-stage');
    if(!stage || !STD.work) return;
    const sc = Math.min(stage.clientWidth*0.94/STD.work.width,
                        stage.clientHeight*0.94/STD.work.height, 1);
    STD.scale = sc;
    const cv = $('#stdCanvas');
    cv.width  = Math.max(1, Math.round(STD.work.width*sc));
    cv.height = Math.max(1, Math.round(STD.work.height*sc));
    stdResetCrop();
    stdDraw();
  });
}
function stdResetCrop(){
  const W = STD.work.width, H = STD.work.height, ratio = stdRatioVal();
  let w = W*0.8, h = H*0.8;
  if(ratio){ if(w/h > ratio) w = h*ratio; else h = w/ratio; }
  STD.crop = {x:(W-w)/2, y:(H-h)/2, w, h};
}
function stdClamp(x,y,w,h,W,H,ratio){
  w = Math.min(w, W); h = Math.min(h, H);
  if(ratio){
    if(w/h > ratio) w = h*ratio; else h = w/ratio;
    if(h>H){ h=H; w=h*ratio; }
    if(w>W){ w=W; h=w/ratio; }
  }
  return {x:Math.max(0,Math.min(W-w,x)), y:Math.max(0,Math.min(H-h,y)), w, h};
}
function stdHandles(){
  const c = STD.crop;
  return [{k:'nw',x:c.x,y:c.y},{k:'n',x:c.x+c.w/2,y:c.y},{k:'ne',x:c.x+c.w,y:c.y},
          {k:'w',x:c.x,y:c.y+c.h/2},{k:'e',x:c.x+c.w,y:c.y+c.h/2},
          {k:'sw',x:c.x,y:c.y+c.h},{k:'s',x:c.x+c.w/2,y:c.y+c.h},{k:'se',x:c.x+c.w,y:c.y+c.h}];
}
function stdDraw(){
  const cv = $('#stdCanvas'), x = cv.getContext('2d');
  x.clearRect(0,0,cv.width,cv.height);
  x.drawImage(STD.work, 0,0, cv.width, cv.height);
  const s = STD.scale, c = STD.crop;
  x.fillStyle = 'rgba(0,0,0,.55)';
  x.fillRect(0,0,cv.width, c.y*s);
  x.fillRect(0,(c.y+c.h)*s, cv.width, cv.height-(c.y+c.h)*s);
  x.fillRect(0, c.y*s, c.x*s, c.h*s);
  x.fillRect((c.x+c.w)*s, c.y*s, cv.width-(c.x+c.w)*s, c.h*s);
  x.strokeStyle = '#4da3ff'; x.lineWidth = 1.5;
  x.strokeRect(c.x*s, c.y*s, c.w*s, c.h*s);
  x.strokeStyle = 'rgba(255,255,255,.25)'; x.lineWidth = 1;
  for(let i=1;i<3;i++){
    x.beginPath(); x.moveTo((c.x+c.w*i/3)*s, c.y*s); x.lineTo((c.x+c.w*i/3)*s,(c.y+c.h)*s); x.stroke();
    x.beginPath(); x.moveTo(c.x*s,(c.y+c.h*i/3)*s); x.lineTo((c.x+c.w)*s,(c.y+c.h*i/3)*s); x.stroke();
  }
  x.fillStyle = '#fff';
  stdHandles().forEach(h=> x.fillRect(h.x*s-4, h.y*s-4, 8, 8));
}
/* ── 放大镜：跟随光标，按倍率从工作画布（已旋转）采样 ── */
function stdZoomLevel(){
  const v = parseFloat(($('#stdZoomSel')||{}).value);
  return (v>0) ? v : 0;            // 0 = 关
}
function stdZoomHide(){
  const b = $('#stdZoom'); if(b) b.classList.remove('on');
}
function stdZoomAt(pt){
  const box = $('#stdZoom'), lv = stdZoomLevel();
  if(!box || !lv || !STD.work){ stdZoomHide(); return; }
  const zc = $('#stdZoomCv'); if(!zc) return;
  const zx = zc.getContext('2d');
  // 放大镜 160px 视窗 -> 源图上取 160/lv 的区域
  let vw = Math.min(zc.width/lv,  STD.work.width);
  let vh = Math.min(zc.height/lv, STD.work.height);
  let sx = pt.x - vw/2, sy = pt.y - vh/2;
  sx = Math.max(0, Math.min(STD.work.width  - vw, sx));
  sy = Math.max(0, Math.min(STD.work.height - vh, sy));
  zx.imageSmoothingEnabled = false;              // 放大时保留硬边，便于对齐
  zx.clearRect(0,0,zc.width,zc.height);
  zx.drawImage(STD.work, sx, sy, vw, vh, 0,0, zc.width, zc.height);
  // 十字准线：中心即当前光标位置
  zx.strokeStyle = 'rgba(77,163,255,.95)'; zx.lineWidth = 1;
  zx.beginPath(); zx.moveTo(zc.width/2, 0); zx.lineTo(zc.width/2, zc.height); zx.stroke();
  zx.beginPath(); zx.moveTo(0, zc.height/2); zx.lineTo(zc.width, zc.height/2); zx.stroke();
  const lb = $('#stdZoomLv'); if(lb) lb.textContent = lv+'x';
  box.classList.add('on');
}
(function(){
  const cv = $('#stdCanvas');
  let mode = null, start = null, c0 = null;
  const pos = e=>{
    const r = cv.getBoundingClientRect();
    return {x:(e.clientX-r.left)/STD.scale, y:(e.clientY-r.top)/STD.scale};
  };
  const hit = pt=>{
    const s = STD.scale;
    for(const h of stdHandles())
      if(Math.abs(pt.x-h.x)<10/s && Math.abs(pt.y-h.y)<10/s) return h.k;
    return null;
  };
  cv.addEventListener('pointermove', e=>{ if(STD.work) stdZoomAt(pos(e)); });
  cv.addEventListener('pointerdown', e=>{ if(STD.work) stdZoomAt(pos(e)); });
  cv.addEventListener('pointerleave', stdZoomHide);
  cv.addEventListener('pointerdown', e=>{
    if(!STD.work) return;
    cv.setPointerCapture(e.pointerId);
    const pt = pos(e);
    const hk = hit(pt), c = STD.crop;
    mode = hk || ((pt.x>c.x && pt.x<c.x+c.w && pt.y>c.y && pt.y<c.y+c.h) ? 'move' : 'new');
    start = pt; c0 = {...STD.crop};
  });
  cv.addEventListener('pointermove', e=>{
    if(!mode || !STD.work) return;
    const pt = pos(e), W = STD.work.width, H = STD.work.height;
    const ratio = stdRatioVal();
    if(mode==='move'){
      STD.crop = stdClamp(c0.x+pt.x-start.x, c0.y+pt.y-start.y, c0.w, c0.h, W, H, ratio);
    } else if(mode==='new'){
      let w = Math.abs(pt.x-start.x), h = Math.abs(pt.y-start.y);
      const cx = (start.x+pt.x)/2, cy = (start.y+pt.y)/2;
      if(ratio){ if(w/h > ratio) w = h*ratio; else h = w/ratio; }
      w = Math.max(20,w); h = Math.max(20,h);
      STD.crop = stdClamp(cx-w/2, cy-h/2, w, h, W, H, ratio);
    } else {
      let {x,y,w,h} = c0;
      const dx = pt.x-start.x, dy = pt.y-start.y;
      if(mode.includes('w')){ x = c0.x+dx; w = c0.w-dx; }
      if(mode.includes('e')){ w = c0.w+dx; }
      if(mode.includes('n')){ y = c0.y+dy; h = c0.h-dy; }
      if(mode.includes('s')){ h = c0.h+dy; }
      if(ratio){
        if(mode==='n'||mode==='s'){ w = h*ratio; x = c0.x+(c0.w-w)/2; }
        else { h = w/ratio; if(mode==='n') y = c0.y+(c0.h-h); }
      }
      w = Math.max(20,w); h = Math.max(20,h);
      STD.crop = stdClamp(x,y,w,h,W,H,ratio);
    }
    stdDraw();
  });
  const up = ()=>{ mode = null; };
  cv.addEventListener('pointerup', up);
  cv.addEventListener('pointercancel', up);
})();
$('#stdRotL').onclick  = ()=>{ STD.rot = (STD.rot+270)%360; applyStdRotation(); };
$('#stdZoomSel').onchange = ()=>{ if(!stdZoomLevel()) stdZoomHide(); else toast('放大镜 '+stdZoomLevel()+'x：把光标移到图上即可', 'ok'); };
$('#stdReset').onclick = ()=>{ stdResetCrop(); stdDraw(); };
$('#stdRatio').onchange = ()=>{ stdResetCrop(); stdDraw(); };
$('#stdClose').onclick = closeStdEditor;
$('#stdSave').onclick = async ()=>{
  if(!STD.work) return;
  const code = $('#stdCode').value.trim();
  if(!code) return toast('先填产品编码','err');
  const c = STD.crop, LONG = 1600;
  const sc = Math.min(1, LONG/Math.max(c.w, c.h));
  const out = document.createElement('canvas');
  out.width = Math.max(1,Math.round(c.w*sc));
  out.height = Math.max(1,Math.round(c.h*sc));
  out.getContext('2d').drawImage(STD.work, c.x, c.y, c.w, c.h, 0,0, out.width, out.height);
  const blob = await new Promise(res=>out.toBlob(res,'image/jpeg',0.85));
  const reader = new FileReader();
  reader.onload = async ()=>{
    try{
      const r = await post('/api/standard-images',{code, photo_id:STD.pid,
        kind:$('#stdKind').value, image:reader.result.split(',')[1],
        width:out.width, height:out.height, by:'user'});
      const sid = (r && r.id) || '';
      // 保存后回看入口：直接看这张标准图 / 跳到产品库看该产品
      $('#stdMsg').innerHTML = '已保存（'+out.width+'×'+out.height+'）'+
        (sid? '<a class="lk" href="/std-img/'+esc(sid)+'" target="_blank" rel="noopener">打开该产品标准图</a>':'')+
        '<span class="lk" id="stdGoProd">在产品库查看</span>';
      const gp = $('#stdGoProd');
      // 动态 import：static 引入 products 会形成 standard→products→drawer→standard 环
      if(gp) gp.onclick = async ()=>{
        closeStdEditor(); go('products');
        try{ (await import('./products.js')).openProduct(code); }
        catch(e){ console.error(e); toast('跳转失败：'+e.message,'err'); }
      };
      toast('标准图已保存到 '+code,'ok');
      setTimeout(closeStdEditor, 4000);
    }catch(e){ toast('保存失败：'+e.message,'err'); }
  };
  reader.readAsDataURL(blob);
};

export { stdSuggest, applyStdRotation, stdZoomHide, stdResetCrop, STD, stdZoomLevel, stdClamp, stdWorkCanvas, openStdEditor, stdHandles, stdZoomAt, stdDraw, stdRatioVal, closeStdEditor };
