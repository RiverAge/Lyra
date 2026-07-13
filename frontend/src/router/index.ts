import { createRouter, createWebHistory } from "vue-router"

/**
 * Lyra 路由
 *
 * 职责：
 * - /         → 重定向到 /library（曲库为主入口）
 * - /library  → 曲库分页列表（LibraryView）
 * - /track/:id                 → track 详情页壳（TrackDetailView）
 * - /track/:id/lyrics-editor   → 逐字歌词编辑器（LyricsEditorView）
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
      redirect: "/library",
    },
    {
      path: "/library",
      name: "library",
      component: () => import("@/views/LibraryView.vue"),
    },
    {
      path: "/track/:id",
      name: "track-detail",
      component: () => import("@/views/TrackDetailView.vue"),
    },
    {
      path: "/track/:id/lyrics-editor",
      name: "lyrics-editor",
      component: () => import("@/views/LyricsEditorView.vue"),
    },
    // 兜底：未匹配路由回到曲库
    {
      path: "/:pathMatch(.*)*",
      redirect: "/library",
    },
  ],
})

export default router
