<template>
  <div class="flex min-h-screen flex-col bg-base">
    <!-- Header（持久化） -->
    <header class="sticky top-0 z-50 bg-surface/80 backdrop-blur-md">
      <div class="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
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
  </div>
</template>

<script setup lang="ts">
import BaseButton from "@/components/ui/BaseButton.vue"

/**
 * 全局应用壳
 *
 * 设计：
 * - header 持久化（sticky），导航链接 + 设置
 * - 无全局 PlayerDock——播放器局部化在 track 详情页 + 编辑器（audioManager 单例跨页面共享）
 * - 固定浅色主题（见 tokens.css 单一 :root）
 */
const route = useRoute()
const router = useRouter()

const navLinks = [
  { to: "/library", label: "曲库" },
] as const

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function goSettings(): void {
  void router.push("/settings")
}
</script>

<style scoped>
/* App.vue 无额外 scoped 样式——全部通过 Tailwind token 类名控制 */
</style>
