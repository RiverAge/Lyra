<template>
  <div class="mx-auto max-w-6xl px-6 py-8">
    <!-- 页头 -->
    <div class="mb-7">
      <h1 class="mb-2 text-3xl font-semibold tracking-tight text-primary">
        曲库
      </h1>
      <p class="text-sm text-secondary">
        音乐元数据与歌词管理工具 · 当前共 {{ totalText }} 首曲目
      </p>
      <div class="mt-3.5 flex items-center gap-4 text-xs text-tertiary">
        <span class="pill"><span class="dot" />后端已连接</span>
        <span class="meta-item"><b>扫描</b> {{ scanStatusText }}</span>
        <span class="meta-item"><b>转码</b> ALAC → Opus 实时</span>
      </div>
    </div>

    <!-- 统计卡 -->
    <StatsCards :stats="libraryStore.stats" class="mb-6" />

    <!-- 扫描进度（自带 card，scanning 时展开） -->
    <ScanProgress v-if="showScanner" class="mb-6" />

    <!-- 操作工具条 -->
    <div class="toolbar-row">
      <div class="flex-1" />
      <BaseButton variant="ghost" size="sm" icon="RefreshCw" icon-only title="刷新" @click="reload" />
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
import { useLibraryStore } from "@/stores/library"
import { useScannerStore } from "@/stores/scanner"
import BaseButton from "@/components/ui/BaseButton.vue"
import StatsCards from "@/components/library/StatsCards.vue"
import TrackTable from "@/components/library/TrackTable.vue"
import ScanProgress from "@/components/scanner/ScanProgress.vue"

/**
 * 曲库首页（B 布局重写）
 *
 * 布局自上而下：页头 → 统计卡 → 扫描进度 → 工具条(刷新) → 表格 → 分页
 * - onMounted：loadPage(1) + loadStats()（统计与列表独立加载）
 * - 全局搜索走 ⌘K SearchModal（App.vue 挂载），列表只做分页浏览
 * - 点击表格行 → /track/:id
 */

const libraryStore = useLibraryStore()
const scannerStore = useScannerStore()
const router = useRouter()

onMounted(() => {
  void libraryStore.loadPage(1)
  void libraryStore.loadStats()
  // 开 SSE 订阅扫描进度：连接后后端会推 init 事件（带真实 state/count/total），
  // 即使此刻扫描还没开始（startup 的 _initial_scan 是异步 task，可能晚于
  // 页面 onMounted），SSE 连上后扫描一启动会持续推送，store 实时更新。
  //
  // 不能只靠 ScanProgress.onMounted 的 startProgress——它只在 showScanner=true
  // 时渲染，而 F5 后 store 是初始 idle/0 → showScanner=false → 不渲染 →
  // 不开 SSE → 死锁，扫描启动了 Library 也收不到，进度块永不出现
  // （"点 Settings 再回来才有"是因为 Settings 的 refreshStatus 晚一拍
  // 撞上 scanning；F5 又消失是同样死锁重演）。这里在 Library 级开 SSE 打破死锁。
  // refreshStatus 仍调一次拿即时快照（SSE init 之前先用上）。
  void scannerStore.refreshStatus()
  scannerStore.startProgress()
})

onUnmounted(() => {
  scannerStore.stopProgress()
})

// 扫描进度仅在 scanning 或刚扫完时显示（idle 且无进度则隐藏）
const showScanner = computed(() =>
  scannerStore.isScanning || scannerStore.totalFiles > 0,
)
const scanStatusText = computed(() =>
  scannerStore.isScanning ? "进行中" : "空闲",
)

const totalText = computed(() => libraryStore.total.toLocaleString("en-US"))

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
/* meta 后代 b 加粗 */
.meta-item b {
  color: var(--theme-text-secondary);
  font-weight: 500;
}

/* pill 状态点 */
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: var(--radius-full);
  background-color: var(--theme-bg-subtle);
  border: 1px solid var(--theme-border-default);
  font-size: 12px;
  color: var(--theme-text-secondary);
}
.pill .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--theme-success);
}

/* 筛选条 + 右侧操作一行：FilterBar 用 flex-1 占满，页面级 margin/border 在此定义 */
.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--theme-border-default);
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
