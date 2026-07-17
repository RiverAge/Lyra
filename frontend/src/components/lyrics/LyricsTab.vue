<template>
  <LyricsWorkspace :track-id="trackId" />
</template>

<script setup lang="ts">
import LyricsWorkspace from "./LyricsWorkspace.vue"
import { useLyricsStore } from "@/stores/lyrics"
import type { TrackItem } from "@/apis/library"

/**
 * 歌词 tab 容器
 *
 * 退化为壳：实际工作台在 LyricsWorkspace（左来源选择器 + 右统一预览 + SyncControls 常驻）。
 * trackId 变化时重置 store（防跨曲目残留状态）。
 *
 * 约束：auto-import 已注入 watch；由 TrackDetailView.vue 用 defineAsyncComponent 加载。
 */
const props = defineProps<{
  trackId: string
  /** 当前 track（由父组件统一传入，本 tab 暂未使用，保持 prop 一致） */
  track?: TrackItem | null
}>()

const store = useLyricsStore()

// trackId 变化时清空旧曲目的匹配状态与 sidecar（LyricsWorkspace onMounted 会重新加载）
watch(
  () => props.trackId,
  () => {
    store.resetAll()
  },
)
</script>
