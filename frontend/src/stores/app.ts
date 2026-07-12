/**
 * 全局应用状态 Store（占位）
 *
 * 职责：
 * - 管理主题状态（light / dark）
 * - 为后续扩展保留（如侧边栏折叠、toast 队列等）
 *
 * 约束：
 * - 本任务为占位实现，不预建业务状态
 * - auto-import 已注入 defineStore / storeToRefs，不要手动 import
 */

export const useAppStore = defineStore("app", () => {
  // 主题状态：light | dark
  const theme = ref<"light" | "dark">("light")

  // 初始化时从 localStorage 读取持久化主题（SSR 安全）
  function initTheme(): void {
    if (typeof window === "undefined") return
    const stored = localStorage.getItem("lyra-theme")
    if (stored === "dark" || stored === "light") {
      theme.value = stored
    }
    applyTheme(theme.value)
  }

  // 应用主题到 html[data-theme]
  function applyTheme(t: "light" | "dark"): void {
    if (typeof document === "undefined") return
    document.documentElement.setAttribute("data-theme", t)
  }

  // 切换主题
  function toggleTheme(): void {
    const next = theme.value === "light" ? "dark" : "light"
    theme.value = next
    if (typeof window !== "undefined") {
      localStorage.setItem("lyra-theme", next)
    }
    applyTheme(next)
  }

  // 显式设置主题
  function setTheme(t: "light" | "dark"): void {
    theme.value = t
    if (typeof window !== "undefined") {
      localStorage.setItem("lyra-theme", t)
    }
    applyTheme(t)
  }

  return {
    theme,
    initTheme,
    applyTheme,
    toggleTheme,
    setTheme,
  }
})
