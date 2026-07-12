<template>
  <div class="flex min-h-screen flex-col bg-base">
    <!-- Header -->
    <header class="border-b border-default bg-surface px-6 py-4">
      <div class="mx-auto flex max-w-6xl items-center justify-between">
        <h1 class="text-xl font-semibold text-primary">
          Lyra
        </h1>
        <div class="flex items-center gap-4">
          <span class="text-sm text-secondary">前端骨架已就绪</span>
          <!-- 主题切换占位 -->
          <button
            class="rounded-md border border-default px-3 py-1.5 text-sm text-primary transition-colors hover:bg-hover"
            @click="appStore.toggleTheme"
          >
            {{ themeLabel }}
          </button>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex flex-1 items-center justify-center">
      <div class="text-center">
        <!-- 占位验证 div：验证 tokens.css 是否生效 -->
        <div class="mb-6 rounded-md bg-accent-subtle p-8 shadow-sm">
          <p class="mb-2 text-lg font-semibold text-primary">
            tokens.css 验证区
          </p>
          <p class="text-sm text-secondary">
            此区块使用 bg-accent-subtle + shadow-sm（语义 token 类名）
          </p>
        </div>

        <h2 class="mb-2 text-lg font-medium text-primary">
          全局布局壳已渲染
        </h2>
        <p class="text-sm text-secondary">
          数据主题：<span class="font-mono text-accent">{{ appStore.theme }}</span>
        </p>

        <RouterView />
      </div>
    </main>

    <!-- Footer -->
    <footer class="border-t border-default bg-surface px-6 py-3">
      <p class="text-center text-sm text-tertiary">
        Lyra — Music Metadata &amp; Lyrics Manager
      </p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { useAppStore } from "@/stores/app"

const appStore = useAppStore()
appStore.initTheme()

const themeLabel = computed(() =>
  appStore.theme === "light" ? "🌙 暗色" : "☀️ 亮色"
)
</script>

<style scoped>
/* App.vue 无额外 scoped 样式——全部通过 Tailwind token 类名控制 */
</style>
