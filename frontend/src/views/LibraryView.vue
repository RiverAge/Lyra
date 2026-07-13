<template>
  <div class="mx-auto max-w-6xl px-6 py-6 animate-fade-in">
    <!-- 页头 -->
    <div class="mb-6 flex items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-primary">
          曲库
        </h1>
        <p class="mt-1 text-xs text-secondary">
          浏览音乐库内的曲目
        </p>
      </div>
      <button
        class="rounded-md border border-default px-3 py-1.5 text-xs text-primary transition-colors hover:bg-hover"
        @click="reload"
      >
        刷新
      </button>
    </div>

    <!-- 主体：扫描进度 + 列表 -->
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div class="lg:col-span-2">
        <TrackList
          :tracks="libraryStore.items"
          :loading="libraryStore.loading"
          :error="libraryStore.error"
          :page="libraryStore.page"
          :total-pages="libraryStore.totalPages"
          :total="libraryStore.total"
          @navigate="onNavigate"
          @prev="libraryStore.prevPage"
          @next="libraryStore.nextPage"
          @retry="reload"
        />
      </div>

      <div class="space-y-4">
        <ScanProgress />
        <!-- 播放器浮窗：仅在有当前 track 时显示 -->
        <AudioPlayer v-if="playerStore.currentTrack" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useLibraryStore } from "@/stores/library"
import { usePlayerStore } from "@/stores/player"
import TrackList from "@/components/library/TrackList.vue"
import ScanProgress from "@/components/scanner/ScanProgress.vue"
import AudioPlayer from "@/components/player/AudioPlayer.vue"

/**
 * 曲库分页列表视图
 * - 首次进入自动加载第 1 页
 * - 点击 track 行 → router.push('/track/' + id)
 * - 右侧栏：扫描进度 + 播放器（条件渲染）
 */
const libraryStore = useLibraryStore()
const playerStore = usePlayerStore()
const router = useRouter()

onMounted(() => {
  void libraryStore.loadPage(1)
})

function onNavigate(id: string): void {
  void router.push(`/track/${id}`)
}

async function reload(): Promise<void> {
  await libraryStore.reload()
}
</script>

<style scoped>
/* LibraryView 无额外 scoped 样式 */
</style>
