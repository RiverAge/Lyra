<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <!-- 页头 -->
    <div class="mb-7">
      <h1 class="mb-2 text-3xl font-semibold tracking-tight text-primary">
        曲库
      </h1>
      <p class="text-sm text-secondary">
        音乐元数据与歌词管理工具
      </p>
      <div class="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-tertiary">
        <span class="meta-item"><b>转码</b> ALAC → Opus 实时</span>
        <!-- 库概览：原四格统计卡内联到此行。数字滚动（useCountUp）：
             扫描完成 SSE 带 stats 进来时旧值→新值 ease-out 滚动。
             首屏加载直接显示初值不动画。无 stats（未加载）时不显示本段。 -->
        <template v-if="hasStats">
          <span class="meta-sep" />
          <span class="meta-item">
            <b>曲目</b>
            <span class="tabular-nums text-secondary">{{ trackCount.toLocaleString("en-US") }}</span>
          </span>
          <span class="meta-item">
            <b>专辑</b>
            <span class="tabular-nums text-secondary">{{ albumCount }}</span>
          </span>
          <span class="meta-item">
            <b>时长</b>
            <span class="tabular-nums text-secondary">{{ durationLabel }}</span>
          </span>
          <span class="meta-item">
            <b>无损</b>
            <span class="tabular-nums text-secondary">{{ losslessPct }}%</span>
          </span>
        </template>
      </div>
    </div>

    <!-- 表格 -->
    <TrackTable
      :tracks="libraryStore.items"
      :loading="libraryStore.loading"
      :error="libraryStore.error"
      :page="libraryStore.page"
      :page-size="libraryStore.limit"
      @navigate="onNavigate"
      @retry="reload"
    />

    <!-- 分页 -->
    <div class="mt-5 flex items-center justify-between text-sm text-secondary">
      <div>{{ pagerText }}</div>
      <div class="flex items-center">
        <button
          class="pg"
          :disabled="libraryStore.page <= 1"
          @click="libraryStore.prevPage"
        >‹</button>
        <button class="pg active">{{ libraryStore.page }}</button>
        <span class="px-1 text-xs text-tertiary">/ {{ libraryStore.totalPages }}</span>
        <button
          class="pg"
          :disabled="libraryStore.page >= libraryStore.totalPages"
          @click="libraryStore.nextPage"
        >›</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useCountUp } from "@/composables/useCountUp"
import { useLibraryStore } from "@/stores/library"
import TrackTable from "@/components/library/TrackTable.vue"

/**
 * 曲库首页（B 布局重写）
 *
 * 布局自上而下：页头(含库概览 inline) → 表格 → 分页
 * - 页头 meta 行内联四项统计（曲目/专辑/时长/无损占比），数字滚动
 *   （useCountUp）；扫描完成 SSE 带 stats 进来时旧值→新值 ease-out 滚动
 * - onMounted：loadPage(1) + loadStats()（统计与列表独立加载）
 * - 扫描进度/SSE/连接态均由 header ScanIndicator 统一展示（App.vue 级常驻）
 * - 全局搜索走 ⌘K SearchModal（App.vue 挂载），列表只做分页浏览
 * - 点击表格行 → /track/:id
 */

const libraryStore = useLibraryStore()
const router = useRouter()

onMounted(() => {
  void libraryStore.loadPage(1)
  void libraryStore.loadStats()
})

// ---- 库概览（页头内联）----
const hasStats = computed(() => libraryStore.stats !== null)
const trackCount = useCountUp(() => libraryStore.stats?.track_count ?? 0)
const albumCount = useCountUp(() => libraryStore.stats?.album_count ?? 0)
const totalDurationSec = useCountUp(() => libraryStore.stats?.total_duration_sec ?? 0)
const losslessPct = useCountUp(() =>
  libraryStore.stats ? Math.round(libraryStore.stats.lossless_ratio * 100) : 0,
)

// 总时长格式化：秒 → 选合适单位
const durationLabel = computed(() => {
  const sec = totalDurationSec.value
  if (!sec) return "0m"
  const h = sec / 3600
  if (h >= 1) return `${h.toFixed(1)}h`
  return `${Math.round(sec / 60)}m`
})

const pagerText = computed(() => {
  const limit = libraryStore.limit
  const start = libraryStore.total > 0 ? (libraryStore.page - 1) * limit + 1 : 0
  const end = Math.min(libraryStore.page * limit, libraryStore.total)
  return `显示 ${start}–${end} / 共 ${libraryStore.total.toLocaleString("en-US")} 首`
})

function onNavigate(id: string): void {
  void router.push(`/track/${id}`)
}

async function reload(): Promise<void> {
  await libraryStore.reload()
}
</script>

<style scoped>
/* meta-item：label(b) + 值 inline，b 后留缝 */
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.meta-item b {
  color: var(--theme-text-secondary);
  font-weight: 500;
}

/* meta 行分隔竖线：连接状态段与库概览段 */
.meta-sep {
  width: 1px;
  height: 12px;
  background-color: var(--theme-border-default);
}

/* 分页按钮：多伪类组合（:hover:not(:disabled):not(.active)）保留 scoped */
.pg {
  min-width: 28px;
  height: 28px;
  padding: 0 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--theme-border-default);
  background-color: var(--theme-bg-surface);
  font-size: 13px;
  color: var(--theme-text-secondary);
  cursor: pointer;
  font-variant-numeric: tabular-nums;
  transition: background-color var(--animate-duration-hover) ease, color var(--animate-duration-hover) ease;
}
.pg:hover:not(:disabled):not(.active) {
  background-color: var(--theme-bg-hover);
  color: var(--theme-text-primary);
}
.pg:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.pg.active {
  background-color: var(--theme-accent);
  color: var(--theme-on-accent);
  border-color: var(--theme-accent);
}
</style>
