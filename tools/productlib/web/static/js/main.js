// main.js —— 应用入口 / 组合根
//
// 职责只有两件：
//   1. 把各业务模块「装载进来」（侧效应 import）——它们各自用 onTab() 注册
//      「切到我这页要跑什么」，所以不 import 就等于该页永远空白。
//   2. 做一次性的启动动作（首屏数据、偏好恢复、全局快捷键）。
//
// ⚠️ 新增页面模块时，必须在这里补一行 import './xxx.js';
import { $, $$, go, getCid, enterWizard, revTab } from './core.js';
import { openModal } from './modal.js';

/* ── 装载业务模块（顺序无关，依赖由各模块内部 import 决定） ── */
import './wizard.js';     // 柜作业：五步主线（已并进柜页，从柜列表进入）
import './home.js';       // 概览
import './containers.js'; // 柜：柜列表 + 内嵌柜作业（建柜 → 清单/照片 → 报告）
import './batches.js';    // 预检照片入库：治理 + 批次
import './photos.js';     // 预检照片入库：照片浏览（挂在 batches 页内）
import './phototree.js';  // 照片页左侧「用途→分类」树形筛选（2026-10-14）
import './selbatch.js';   // 批量选择模式（照片库 / 柜作业③共用，2026-10-14）
import './products.js';   // 产品库
import './drawer.js';     // 照片抽屉
import './standard.js';   // 标准图编辑器
import './discover.js';   // 新产品确认：发现新产品
import './report.js';     // 预检照片检索
import './settings.js';   // 设置
import { attachDirPicker } from './dirpicker.js';  // 目录选择器

import { loadStats } from './home.js';
import { loadBatches, loadGovernInfo, openBatches, closeBatches } from './batches.js';
import { loadContainers, openContainer, loadContainerOptions } from './containers.js';
import { loadShots, setShotView } from './photos.js';
import { loadProducts } from './products.js';
import { openDrawer } from './drawer.js';
import { loadDiscover } from './discover.js';

/* ── 调试 / 端到端出口 ──
   ES module 作用域外（浏览器控制台、CDP 自动化脚本）拿不到模块内函数，
   这里集中挂一个命名空间，避免为每个函数单独 window.xxx = 污染全局。 */
window.PL = {
  go, loadStats, loadBatches, loadGovernInfo, openBatches, closeBatches,
  loadShots, setShotView, loadProducts, openDrawer,
  loadDiscover,
  loadContainers, openContainer, loadContainerOptions,
  openModal,                                     // 统一模态（e2e / 控制台用）
};

/* ── 启动 ── */
loadStats();
loadBatches();
loadGovernInfo();
loadContainerOptions();   // 所有 .ctnSel 柜下拉（导入 / 清单 / 报告页共用）

// 目录选择器：标准格式导入 / 检索导出 / 标准库落盘
// （照片导入的目录选择已随模态移到 photos.js 的 openImportPhotosModal 里，
//   模态元素是要时才建的，不能在启动时 attach）
attachDirPicker('stdFolder', 'stdPickDir');
attachDirPicker('stdExpDir', 'stdPickDir');
// 素材包导出目录（rpDir）随 ②取材 一并移除 —— 报告档案页没有导出功能了。

// `/` 聚焦当前页搜索框
document.addEventListener('keydown', e=>{
  if(e.key==='/' && document.activeElement.tagName!=='INPUT' && document.activeElement.tagName!=='TEXTAREA'){
    const t = $('section.on #pQ') || $('section.on #rfQ');
    if(t){ e.preventDefault(); t.focus(); }
  }
});

// 默认落在「柜」—— 2026-10-08 起柜作业并进柜页，进来先选/建柜，再进它的柜作业。
// 柜号由顶栏全局锚点贯穿全流程（getCid / setCid / onCidChange），
// 柜作业状态派生自 /api/containers/{cid}/progress，不落 localStorage 记账。
//
// 2026-10-18 老板需求：刷新后保持当前页面（此前刷新必回首页）——
//   plTab 存主 tab；在「柜」页且 plWiz=1 时恢复柜作业视图与步骤。
//   cid 已由 getCid 的 localStorage['plCid'] 天然恢复。
const _tab = (()=>{ try{ return localStorage.getItem('plTab') || ''; }catch(e){ return ''; } })();
go(_tab || 'containers');
try{
  const _wiz = localStorage.getItem('plWiz') === '1'
           && _tab === 'containers';
  if(_wiz && getCid()){
    // 等一帧：各模块的 onTab 注册与 wizard:goto 监听器都要就位
    setTimeout(()=>enterWizard(getCid(),
      localStorage.getItem('plStep') || ''), 0);
  }
  const _rev = localStorage.getItem('plRevTab');
  if(_rev) setTimeout(()=>revTab(_rev), 0);
}catch(e){}
