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
        <span class="pill"><span class="dot" />后端已连接</span>
        <span class="meta-item"><b>扫描</b> {{ scanStatusText }}</span>
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

    <!-- 扫描进度（自带 card，scanning 时展开） -->
    <ScanProgress v-if="showScanner" class="mb-6" />

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
import type { LibraryStats } from "@/apis/library"
import { useCountUp } from "@/composables/useCountUp"
import { useLibraryStore } from "@/stores/library"
import { useScannerStore } from "@/stores/scanner"
import TrackTable from "@/components/library/TrackTable.vue"
import ScanProgress from "@/components/scanner/ScanProgress.vue"

/**
 * 曲库首页（B 布局重写）
 *
 * 布局自上而下：页头(含库概览 inline) → 扫描进度 → 表格 → 分页
 * - 页头 meta 行内联四项统计（曲目/专辑/时长/无损占比），数字滚动
 *   （useCountUp）；扫描完成 SSE 带 stats 进来时旧值→新值 ease-out 滚动
 * - onMounted：loadPage(1) + loadStats()（统计与列表独立加载）
 * - 全局搜索走 ⌘K SearchModal（App.vue 挂载），列表只做分页浏览
 * - 点击表格行 → /track/:id
 */

const libraryStore = useLibraryStore()
const scannerStore = useScannerStore()
const router = useRouter()

// 扫描完成事件带 stats 回调：后端算好 stats 推过来，直接填 libraryStore.stats，
// 省一次 /library/stats HTTP 全表聚合请求。
scannerStore.setOnStats((s) => {
  libraryStore.setStats(s as unknown as LibraryStats)
})

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
  //
  // 扫描完成事件里后端会带 stats（避免前端再发一次 HTTP 全表聚合），
  // scannerStore 收到后填 libraryStore.stats，见 handleSseData completed 分支。
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
