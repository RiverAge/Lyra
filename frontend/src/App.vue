<template>
  <div class="flex min-h-screen flex-col bg-base">
    <!-- Header（持久化） -->
    <header class="sticky top-0 z-50 border-b border-subtle bg-surface/80 backdrop-blur-md">
      <div class="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
        <RouterLink to="/" class="flex items-center gap-2 transition-opacity hover:opacity-80">
          <img src="/favicon.svg" alt="Lyra" class="h-7 w-7">
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
          <div class="mx-1 h-5 w-px bg-border-default" />
          <BaseButton
            variant="ghost"
            size="sm"
            :icon="appStore.theme === 'light' ? 'Moon' : 'Sun'"
            icon-only
            :title="appStore.theme === 'light' ? '切换暗色' : '切换亮色'"
            @click="appStore.toggleTheme"
          />
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
    <main class="flex-1 pb-24">
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>

    <!-- 全局播放器 Dock（fixed bottom，导航不消失） -->
    <PlayerDock />
  </div>
</template>

<script setup lang="ts">
import { useAppStore } from "@/stores/app"
import { usePlayerStore } from "@/stores/player"
import BaseButton from "@/components/ui/BaseButton.vue"
import PlayerDock from "@/components/player/PlayerDock.vue"

/**
 * 全局应用壳
 *
 * 设计：
 * - header 持久化（sticky），导航链接 + 主题切换 + 设置
 * - 全局 PlayerDock 挂载一次，导航时不卸载
 * - 主题在 setup 阶段初始化（initTheme），音量在挂载后初始化（initVolume）
 * - page transition 保留（0.18s）
 * - pb-24 给 dock 留出底部空间
 */
const appStore = useAppStore()
const playerStore = usePlayerStore()
const route = useRoute()
const router = useRouter()

appStore.initTheme()

const navLinks = [
  { to: "/library", label: "曲库" },
] as const

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function goSettings(): void {
  void router.push("/settings")
}

// 全局初始化音量（原 AudioPlayer onMounted 职责上移至此）
onMounted(() => {
  playerStore.initVolume()
})
</script>

<style scoped>
/* App.vue 无额外 scoped 样式——全部通过 Tailwind token 类名控制 */
</style>
