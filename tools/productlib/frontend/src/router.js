import { createRouter, createWebHistory } from 'vue-router'
import Containers from './views/Containers.vue'
import Photos from './views/Photos.vue'
import Home from './views/Home.vue'
import Wizard from './views/Wizard.vue'
import Products from './views/Products.vue'
import Review from './views/Review.vue'
import Batches from './views/Batches.vue'
import Report from './views/Report.vue'
import Settings from './views/Settings.vue'

// history 模式 + /app/ base（vite base 同步）—— 服务端对 /app/* 非
// 静态路径回退 index.html（见 routes/app.py）。
export const router = createRouter({
  history: createWebHistory('/app/'),
  routes: [
    // 默认入口对齐旧版：/ 落在「柜」（干活的起点），概览在品牌区点进
    { path: '/', redirect: '/containers' },
    { path: '/photos', name: 'photos', component: Photos, meta: { title: '照片库' } },
    { path: '/containers', name: 'containers', component: Containers, meta: { title: '柜' } },
    { path: '/wizard', name: 'wizard', component: Wizard, meta: { title: '柜作业' } },
    { path: '/products', name: 'products', component: Products, meta: { title: '产品库' } },
    { path: '/review', name: 'review', component: Review, meta: { title: '新产品确认' } },
    { path: '/batches', name: 'batches', component: Batches, meta: { title: '照片批次' } },
    { path: '/report', name: 'report', component: Report, meta: { title: '报告档案' } },
    { path: '/settings', name: 'settings', component: Settings, meta: { title: '设置' } },
    { path: '/home', name: 'home', component: Home, meta: { title: '首页' } },
    // 以下不进侧栏一级项（对齐旧版信息架构），从页内视图/次级入口进：
    //   /batches  照片批次 —— 照片库页内也有「批次」第二视图
    //   /review   新产品确认 —— 照片库页有直达按钮
    //   /wizard   柜作业 —— 柜页内点柜号即进，这个路由用于直接输地址
    { path: '/:pathMatch(.*)*', redirect: '/containers' },
  ],
})

router.afterEach((to) => {
  document.title = (to.meta.title ? to.meta.title + ' · ' : '') + '集刻 · 产品库'
})
