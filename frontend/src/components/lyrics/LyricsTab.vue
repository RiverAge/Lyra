<template>
  <div class="flex flex-col gap-6">
    <!-- section head -->
    <div class="flex items-baseline justify-between gap-4">
      <div>
        <h3 class="text-xl font-semibold tracking-tight text-primary">歌词</h3>
        <p class="mt-0.5 text-sm text-secondary">在线匹配候选歌词，或管理已有 sidecar 文件</p>
      </div>
    </div>

    <!-- 在线匹配（主从布局：左候选/右歌词，编辑器入口在工具栏） -->
    <MatchPanel :track-id="trackId" />

    <!-- 已有 sidecar -->
    <SidecarList :track-id="trackId" />
  </div>
</template>

<script setup lang="ts">
import MatchPanel from "./MatchPanel.vue"
import SidecarList from "./SidecarList.vue"
import { useLyricsStore } from "@/stores/lyrics"
import type { TrackItem } from "@/apis/library"

/**
 * 歌词 tab 容器
 *
 * 职责：
 * - section head + 垂直堆叠 MatchPanel（主从布局）/ SidecarList
 * - trackId 变化时重置 store（防跨曲目残留状态）
 * - 「逐字编辑器」入口已移入 MatchPanel 顶部工具栏
 *
 * 约束：
 * - auto-import 已注入 watch
 * - 由 TrackDetailView.vue 用 defineAsyncComponent 加载
 * - 不直接调 apis
 */
const props = defineProps<{
  trackId: string
  /** 当前 track（由父组件统一传入，本 tab 暂未使用，保持 prop 一致） */
  track?: TrackItem | null
}>()

const store = useLyricsStore()

// trackId 变化时清空旧曲目的匹配状态与 sidecar（SidecarList onMounted 会重新加载）
watch(
  () => props.trackId,
  () => {
    store.resetAll()
  },
)
</script>
