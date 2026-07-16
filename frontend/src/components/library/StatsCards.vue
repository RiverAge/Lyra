<template>
  <div class="grid grid-cols-4 gap-3">
    <div class="rounded-md border border-line bg-surface p-4">
      <div class="mb-1.5 text-xs text-secondary">曲目总数</div>
      <div class="text-xl font-semibold tracking-tight tabular-nums text-primary">{{ formatCount(trackCount) }}</div>
      <div class="mt-0.5 text-xs text-tertiary">{{ albumCount > 0 ? `${formatCount(albumCount)} 张专辑` : "—" }}</div>
    </div>
    <div class="rounded-md border border-line bg-surface p-4">
      <div class="mb-1.5 text-xs text-secondary">专辑数</div>
      <div class="text-xl font-semibold tracking-tight tabular-nums text-primary">{{ formatCount(albumCount) }}</div>
      <div class="mt-0.5 text-xs text-tertiary">{{ artistHint }}</div>
    </div>
    <div class="rounded-md border border-line bg-surface p-4">
      <div class="mb-1.5 text-xs text-secondary">总时长</div>
      <div class="text-xl font-semibold tracking-tight tabular-nums text-primary">{{ formatDuration(totalDurationSec) }}<span class="ml-0.5 text-sm font-normal text-secondary">{{ durationUnit }}</span></div>
      <div class="mt-0.5 text-xs text-tertiary">≈ {{ formatDurationLong(totalDurationSec) }}</div>
    </div>
    <div class="rounded-md border border-line bg-surface p-4">
      <div class="mb-1.5 text-xs text-secondary">无损占比</div>
      <div class="text-xl font-semibold tracking-tight tabular-nums text-primary">{{ losslessPct }}<span class="ml-0.5 text-sm font-normal text-secondary">%</span></div>
      <div class="mt-0.5 text-xs text-tertiary">ALAC · FLAC · WAV</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { LibraryStats } from "@/apis/library"

/**
 * StatsCards — 首页四格统计卡（B 布局）
 *
 * 消费 libraryStore.stats：
 * - 曲目数 / 专辑数 / 总时长（秒→格式化）/ 无损占比（0~1 → %）
 * - stats 为 null（未加载/加载失败）时各格显示占位 "—"
 */

const props = defineProps<{
  stats: LibraryStats | null
}>()

const trackCount = computed(() => props.stats?.track_count ?? 0)
const albumCount = computed(() => props.stats?.album_count ?? 0)
const totalDurationSec = computed(() => props.stats?.total_duration_sec ?? 0)
const losslessPct = computed(() => {
  if (!props.stats) return "—"
  return Math.round(props.stats.lossless_ratio * 100).toString()
})

// 艺人数后端未给，避免误导，改用“无损 X 首”之类不出现的描述；这里给中性提示
const artistHint = computed(() => {
  if (!props.stats) return "—"
  return albumCount.value > 0 ? "按专辑去重" : "—"
})

// 总时长格式化：秒 → {display, unit}，选合适单位
const durationDisplay = computed(() => {
  const sec = totalDurationSec.value
  if (!sec) return "—"
  const h = sec / 3600
  if (h >= 1) return h.toFixed(1)
  return String(Math.round(sec / 60))
})
const durationUnit = computed(() => {
  const sec = totalDurationSec.value
  if (!sec) return ""
  const h = sec / 3600
  if (h >= 1) return "h"
  return "m"
})
function formatDuration(sec: number): string {
  return sec > 0 ? durationDisplay.value : "—"
}
function formatDurationLong(sec: number): string {
  if (!sec) return "—"
  const h = sec / 3600
  if (h >= 1) return `${h.toFixed(1)} 小时`
  const m = sec / 60
  return `${Math.round(m)} 分钟`
}

function formatCount(n: number): string {
  if (!props.stats) return "—"
  return n.toLocaleString("en-US")
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
