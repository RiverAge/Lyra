import { createRouter, createWebHistory } from "vue-router"

/**
 * Lyra 路由（占位）
 *
 * 职责：
 * - 提供基础路由壳，为后续业务页面挂载留位
 * - 当前仅保留占位路由，业务路由后续按需扩展
 *
 * 约束：
 * - 模式使用 createWebHistory（Vite dev server 支持 history fallback）
 * - auto-import 未覆盖 vue-router 的命名导出，此处显式 import
 */

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: () => import("@/views/HomeView.vue"),
    },
    // 占位：后续业务路由在此扩展（如 /library、/diff、/lyrics、/editor）
  ],
})

export default router
