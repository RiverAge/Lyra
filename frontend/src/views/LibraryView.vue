<template>
  <div class="mx-auto max-w-6xl px-6 py-6">
    <!-- 页头 -->
    <div class="mb-6 flex items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-primary">
          曲库
        </h1>
        <p class="mt-1 text-sm text-secondary">
          浏览音乐库内的曲目
        </p>
      </div>
      <div class="flex items-center gap-3">
        <BaseInput
          v-model="searchKeyword"
          placeholder="搜索曲目…"
          icon="Search"
          class="w-48"
        />
        <BaseButton
          variant="ghost"
          size="md"
          icon="RefreshCw"
          icon-only
          title="刷新"
          @click="reload"
        />
      </div>
    </div>

    <!-- 扫描进度（顶部条，播放器已全局化） -->
    <div class="mb-4">
      <ScanProgress />
    </div>

    <!-- 主体：卡片网格 -->
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
</template>

<script setup lang="ts">
import { useLibraryStore } from "@/stores/library"
import BaseButton from "@/components/ui/BaseButton.vue"
import BaseInput from "@/components/ui/BaseInput.vue"
import TrackList from "@/components/library/TrackList.vue"
import ScanProgress from "@/components/scanner/ScanProgress.vue"

/**
 * 曲库分页列表视图
 * - 首次进入自动加载第 1 页
 * - 点击 track 卡片 → router.push('/track/' + id)
 * - 搜索框预留（v-model 绑定，当前仅本地状态，后端搜索能力后续接入）
 * - 播放器已全局化为 PlayerDock（App.vue 挂载）
 */
const libraryStore = useLibraryStore()
const router = useRouter()

const searchKeyword = ref("")

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
