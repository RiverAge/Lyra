<template>
  <div class="flex min-h-screen flex-col bg-base">
    <!-- Header -->
    <header class="border-b border-default bg-surface px-6 py-4">
      <div class="mx-auto flex max-w-6xl items-center justify-between">
        <RouterLink to="/" class="flex items-center gap-2">
          <img src="/favicon.svg" alt="Lyra" class="h-6 w-6">
          <span class="text-xl font-semibold text-primary">Lyra</span>
        </RouterLink>
        <div class="flex items-center gap-2">
          <BaseButton
            variant="ghost"
            size="sm"
            @click="appStore.toggleTheme"
          >
            {{ themeLabel }}
          </BaseButton>
          <BaseButton
            variant="ghost"
            size="sm"
            @click="goSettings"
          >
            设置
          </BaseButton>
        </div>
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
import BaseButton from "@/components/ui/BaseButton.vue"

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
