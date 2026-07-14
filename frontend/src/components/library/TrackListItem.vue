<template>
  <tr
    class="group cursor-pointer border-b border-subtle transition-colors hover:bg-hover"
    @click="handleClick"
  >
    <td class="px-3 py-2 text-primary">
      <img
        v-if="track.has_cover"
        :src="`/api/library/${track.id}/artwork`"
        :alt="track.title"
        loading="lazy"
        class="h-8 w-8 rounded-sm object-cover"
      >
      <div
        v-else
        class="flex h-8 w-8 items-center justify-center rounded-sm bg-subtle text-tertiary"
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
          <path d="M6 2v9.5a2 2 0 1 1-1-1.73V4l5-1v5.5a2 2 0 1 1-1-1.73V2z" />
        </svg>
      </div>
    </td>
    <td class="px-3 py-2.5 text-sm text-primary">
      <span class="line-clamp-1">{{ track.title || "（无标题）" }}</span>
    </td>
    <td class="px-3 py-2.5 text-sm text-secondary">
      <span class="line-clamp-1">{{ track.artist || "—" }}</span>
    </td>
    <td class="px-3 py-2.5 text-sm text-secondary">
      <span class="line-clamp-1">{{ track.album || "—" }}</span>
    </td>
    <td class="px-3 py-2.5 text-right font-mono text-xs text-tertiary whitespace-nowrap">
      {{ formattedDuration }}
    </td>
    <td class="px-3 py-2.5 text-right text-xs text-tertiary whitespace-nowrap uppercase">
      {{ codecLabel }}
    </td>
    <td class="px-3 py-2.5 text-right">
      <span
        class="inline-flex items-center rounded-full bg-accent-subtle px-2 py-0.5 text-xs font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100"
      >
        详情
      </span>
    </td>
  </tr>
</template>

<script setup lang="ts">
import type { TrackItem } from "@/apis/library"

/**
 * 单行 track 列表项
 * - 点击行跳转 /track/:id
 * - duration 后端给的是毫秒整数，转 mm:ss 显示
 */
const props = defineProps<{
  track: TrackItem
}>()

const emit = defineEmits<{
  (e: "navigate", id: string): void
}>()

const formattedDuration = computed(() => formatMs(Number(props.track.duration) || 0))

const codecLabel = computed(() => {
  const c = String(props.track.codec || "").toLowerCase()
  return c || "—"
})

function handleClick(): void {
  emit("navigate", props.track.id)
}

function formatMs(ms: number): string {
  if (!ms || ms < 0) return "--:--"
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  const mm = String(m).padStart(2, "0")
  const ss = String(s).padStart(2, "0")
  // 超过 1 小时显示 h:mm:ss
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, "0")}:${ss}`
  }
  return `${mm}:${ss}`
}
</script>

<style scoped>
/* TrackListItem 无额外 scoped 样式 */
</style>
