<template>
  <div class="flex min-h-screen flex-col bg-base">
    <!-- Header（持久化） -->
    <header class="sticky top-0 z-50 bg-surface/80 backdrop-blur-md">
      <div class="mx-auto flex max-w-6xl items-center justify-between px-6 py-3 max-sm:px-4">
        <RouterLink to="/" class="flex items-center gap-2 transition-opacity hover:opacity-80">
          <img src="/favicon.svg?v=3a" alt="Lyra" class="h-7 w-7">
          <span class="text-lg font-semibold text-primary">Lyra</span>
        </RouterLink>
        <nav class="flex items-center gap-1">
          <RouterLink
            v-for="link in navLinks"
            :key="link.to"
            :to="link.to"
            class="flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-sm transition-colors"
            :class="isActive(link.to) ? 'bg-accent-subtle text-accent' : 'text-secondary hover:bg-hover hover:text-primary'"
          >
            {{ link.label }}
          </RouterLink>
          <div class="mx-1 h-5 w-px bg-hover" />
          <button
            class="search-trigger"
            title="搜索（Ctrl+K）"
            @click="openSearch"
          >
            <Icon name="Search" :size="14" class="shrink-0 text-tertiary" />
            <span class="search-trigger-label">搜索…</span>
            <kbd class="kbd">Ctrl K</kbd>
          </button>
          <ScanIndicator />
          <BaseButton
            variant="ghost"
            size="sm"
            icon="Settings"
            icon-only
            title="设置"
            @click="goSettings"
          />
        </nav>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1">
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>

    <!-- 全局搜索 Modal（Ctrl+K 触发） -->
    <SearchModal />
  </div>
</template>

<script setup lang="ts">
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"
import ScanIndicator from "@/components/scanner/ScanIndicator.vue"
import SearchModal from "@/components/search/SearchModal.vue"
import { useSearchStore } from "@/stores/search"
import { useScannerStore } from "@/stores/scanner"
import { useLibraryStore } from "@/stores/library"
import { useAnimationPref } from "@/composables/useAnimationPref"
import type { LibraryStats } from "@/apis/library"

/* global KeyboardEvent, EventTarget, HTMLElement */

/**
 * 全局应用壳
 *
 * 设计：
 * - header 持久化（sticky），导航链接 + 搜索入口 + 设置
 * - 无全局 PlayerDock——播放器局部化在 track 详情页 + 编辑器（audioManager 单例跨页面共享）
 * - 固定浅色主题（见 tokens.css 单一 :root）
 * - 全局搜索：Ctrl+K / Cmd+K /（非输入框时）触发 SearchModal
 */
const route = useRoute()
const router = useRouter()
const searchStore = useSearchStore()
const scannerStore = useScannerStore()
const libraryStore = useLibraryStore()
const { applyOnBoot: applyAnimationPref } = useAnimationPref()

// 扫描完成事件带 stats 回调：后端算好 stats 推过来，填 libraryStore.stats，
// 省一次 /library/stats HTTP 全表聚合。App 级注册 → 任意页面扫描完成都刷新。
scannerStore.setOnStats((s) => {
  libraryStore.setStats(s as unknown as LibraryStats)
})

const navLinks = [
  { to: "/library", label: "曲库" },
] as const

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function goSettings(): void {
  void router.push("/settings")
}

function openSearch(): void {
  searchStore.openModal()
}

/**
 * 全局快捷键：Ctrl+K / Cmd+K（任意位置）+ "/"（仅非输入态）触发搜索。
 * ESC 关闭由 SearchModal 内的 input 处理（聚焦在输入框上）。
 */
function onGlobalKeydown(e: KeyboardEvent): void {
  // Ctrl+K / Cmd+K：总触发
  if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
    e.preventDefault()
    searchStore.openModal()
    return
  }
  // "/" 键：仅当焦点不在输入类元素时触发（避免拦截输入 /）
  if (e.key === "/" && !isTypingTarget(e.target)) {
    e.preventDefault()
    searchStore.openModal()
  }
}

function isTypingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable
  )
}

onMounted(() => {
  window.addEventListener("keydown", onGlobalKeydown)
  // 动画偏好：读 localStorage 应用 <html>.no-anim（默认开动画）
  applyAnimationPref()
  // SSE 扫描进度订阅提升到 App 级：跨页面常驻（切走 Library 不断开）。
  // startProgress 幂等（已有 EventSource 则 return）。refreshStatus 拿即时快照。
  void scannerStore.refreshStatus()
  scannerStore.startProgress()
})
onUnmounted(() => {
  window.removeEventListener("keydown", onGlobalKeydown)
  scannerStore.stopProgress()
})
</script>

<style scoped>
/* App.vue 无额外 scoped 样式——全部通过 Tailwind token 类名控制 */

/* header 搜索入口按钮（仿 macOS spotlight 触发器） */
.search-trigger {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--theme-border-default);
  background-color: var(--theme-bg-subtle);
  cursor: pointer;
  transition: background-color var(--animate-duration-hover) ease,
    border-color var(--animate-duration-hover) ease;
}
.search-trigger:hover {
  background-color: var(--theme-bg-hover);
  border-color: var(--theme-border-strong);
}
.search-trigger-label {
  font-size: 13px;
  color: var(--theme-text-tertiary);
}
.search-trigger .kbd {
  display: inline-flex;
  align-items: center;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--theme-border-default);
  background-color: var(--theme-bg-surface);
  font-size: 10px;
  font-family: var(--font-mono, ui-monospace, monospace);
  color: var(--theme-text-tertiary);
}
@media (max-width: 640px) {
  /* 窄屏隐藏文字与快捷键提示，只留图标 */
  .search-trigger-label,
  .search-trigger .kbd {
    display: none;
  }
}
</style>
