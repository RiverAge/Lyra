<template>
  <div class="flex min-h-screen flex-col bg-base">
    <!-- Header -->
    <header class="border-b border-default bg-surface px-6 py-4">
      <div class="mx-auto flex max-w-6xl items-center justify-between">
        <RouterLink to="/" class="text-xl font-semibold text-primary">
          Lyra
        </RouterLink>
        <div class="flex items-center gap-4">
          <!-- 主题切换占位 -->
          <button
            class="rounded-md border border-default px-3 py-1.5 text-sm text-primary transition-colors hover:bg-hover"
            @click="appStore.toggleTheme"
          >
            {{ themeLabel }}
          </button>
          <button
            class="rounded-md border border-default px-3 py-1.5 text-sm text-primary transition-colors hover:bg-hover"
            @click="goSettings"
          >
            设置
          </button>
        </div>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1">
      <RouterView />
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

const router = useRouter()

const themeLabel = computed(() =>
  appStore.theme === "light" ? "🌙 暗色" : "☀️ 亮色"
)

function goSettings(): void {
  void router.push("/settings")
}
</script>

<style scoped>
/* App.vue 无额外 scoped 样式——全部通过 Tailwind token 类名控制 */
</style>
