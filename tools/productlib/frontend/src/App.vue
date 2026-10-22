<template>
  <el-container class="app-layout">
    <!-- 侧栏可收起：照片库网格一屏放十几张时，216px 常驻侧栏把可视宽度吃掉一截，
         现场又要往右看表格。收起后只留图标（56px），悬停出中文提示。
         状态落 localStorage —— 收起是个人偏好，不是业务数据。 -->
    <el-aside :width="collapsed ? '56px' : '216px'" class="app-aside"
              :class="{ folded: collapsed }">
      <!-- 品牌区兼首页入口：旧版首页 section 也不在导航里，
           概览是「进哪个都能看到的东西」，不值得占一个一级项。
           折叠态只留「集」字，hover 出全名。 -->
      <router-link to="/home" class="app-logo" :class="{ folded: collapsed }"
                   :title="collapsed ? '集刻 · 产品库' : ''">
        <template v-if="collapsed">集</template>
        <template v-else>集刻 · 产品库</template>
      </router-link>

      <!-- 五项，与旧版导航逐项对齐（柜/产品库/照片库/报告档案/设置）。
           「柜作业」是柜页内的第二视图、「批次」是照片库页内的第二视图、
           「新产品确认」从向导④进 —— 都不占一级项。
           折叠态靠 :collapse 让EP 只渲染图标。 -->
      <el-menu class="app-menu" :default-active="active" :collapse="collapsed"
               :collapse-transition="false" router>
        <el-menu-item index="/containers" title="柜">
          <el-icon><Box /></el-icon><template #title>柜</template>
        </el-menu-item>
        <el-menu-item index="/products" title="产品库">
          <el-icon><Goods /></el-icon><template #title>产品库</template>
        </el-menu-item>
        <el-menu-item index="/photos" title="照片库">
          <el-icon><Picture /></el-icon><template #title>照片库</template>
        </el-menu-item>
        <el-menu-item index="/report" title="报告档案">
          <el-icon><Document /></el-icon><template #title>报告档案</template>
        </el-menu-item>
        <el-menu-item index="/settings" title="设置">
          <el-icon><Setting /></el-icon><template #title>设置</template>
        </el-menu-item>
      </el-menu>

      <!-- 次级入口：不是导航项（页内视图的伴生入口 / 不该占一级的功能），
           用更轻的样式区分，避免被当成第 6、7 个一级项。
           折叠态给图标，否则只剩图标无从辨认是哪一项。 -->
      <div class="app-sub" v-show="!collapsed">
        <div class="sub-h">常用入口</div>
        <router-link to="/batches" class="sub-i" :class="{ on: route.path === '/batches' }">
          照片批次
        </router-link>
        <router-link to="/review" class="sub-i" :class="{ on: route.path === '/review' }">
          新产品确认
        </router-link>
        <router-link to="/wizard" class="sub-i" :class="{ on: route.path === '/wizard' }">
          柜作业（直接进）
        </router-link>
      </div>
      <!-- 折叠态的次级入口：图标行，常用功能收起后仍能一键到 -->
      <div class="app-sub-ic" v-show="collapsed">
        <router-link to="/batches" title="照片批次" class="sub-ic"
                     :class="{ on: route.path === '/batches' }">
          <el-icon><Tickets /></el-icon>
        </router-link>
        <router-link to="/review" title="新产品确认" class="sub-ic"
                     :class="{ on: route.path === '/review' }">
          <el-icon><Select /></el-icon>
        </router-link>
        <router-link to="/wizard" title="柜作业" class="sub-ic"
                     :class="{ on: route.path === '/wizard' }">
          <el-icon><Guide /></el-icon>
        </router-link>
      </div>

      <div class="app-foot">
        <template v-if="!collapsed">
          Vue 3 改造分支 · 旧版仍可用<br />
          <a href="/" style="color:var(--pl-color-primary)">返回旧版 →</a>
        </template>
      </div>

      <!-- 收起/展开按钮：放侧栏底边常驻，收起后也能再展开回来 -->
      <button class="fold-btn" type="button" @click="toggle"
              :title="collapsed ? '展开侧栏' : '收起侧栏'"
              :aria-label="collapsed ? '展开侧栏' : '收起侧栏'">
        <el-icon><component :is="collapsed ? 'DArrowRight' : 'DArrowLeft'" /></el-icon>
      </button>
    </el-aside>
    <el-main class="app-main">
      <div class="app-scroll">
        <router-view />
      </div>
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import {
  Box, Goods, Picture, Document, Setting,
  Tickets, Select, Guide, DArrowLeft, DArrowRight,
} from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const active = computed(() => route.path)

/* 收起状态：存localStorage（个人视图偏好，不上后端） */
const FOLD_KEY = 'plSideFold'
const collapsed = ref(false)
try { collapsed.value = localStorage.getItem(FOLD_KEY) === '1' } catch { collapsed.value = false }
watch(collapsed, (v) => {
  try { localStorage.setItem(FOLD_KEY, v ? '1' : '0') } catch { /* 隐私模式 */ }
})
function toggle() { collapsed.value = !collapsed.value }
</script>

<style scoped>
.app-foot { padding: 12px 20px; font-size: 11px; color: var(--pl-faint); line-height: 1.7;
  border-top: 1px solid var(--pl-line-2); margin-top: auto; }
.app-sub { border-top: 1px solid var(--pl-line-2); padding: 8px 0; }
.app-sub .sub-h { font-size: 11px; color: var(--pl-faint); padding: 4px 20px 6px; }
.app-sub .sub-i { display: block; padding: 6px 20px; font-size: 13px;
  color: var(--pl-muted); text-decoration: none; }
.app-sub .sub-i:hover { background: var(--pl-line-2); color: var(--pl-text); }
.app-sub .sub-i.on { background: var(--pl-brand-soft); color: var(--pl-brand-ink);
  font-weight: 600; }
/* 折叠态的次级入口：图标行，hover 出 title 提示 */
.app-sub-ic { border-top: 1px solid var(--pl-line-2); padding: 8px 0; }
.app-sub-ic .sub-ic {
  display: flex; align-items: center; justify-content: center;
  height: 36px; color: var(--pl-muted); text-decoration: none;
}
.app-sub-ic .sub-ic:hover { background: var(--pl-line-2); color: var(--pl-text); }
.app-sub-ic .sub-ic.on { color: var(--pl-brand-ink); }
/* 收起/展开按钮：底边常驻，收起后仍能展开回来 */
.fold-btn {
  flex: 0 0 auto; width: 100%; height: 34px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  background: var(--pl-panel); color: var(--pl-muted);
  border: 0; border-top: 1px solid var(--pl-line);
}
.fold-btn:hover { background: var(--pl-line-2); color: var(--pl-brand); }
</style>