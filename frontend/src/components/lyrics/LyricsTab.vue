<template>
  <div class="flex flex-col gap-4">
    <!-- 顶部：在线匹配 -->
    <MatchPanel :track-id="trackId" />

    <!-- 下方：已有 sidecar -->
    <SidecarList :track-id="trackId" />

    <!-- 底部：进入逐字编辑器 -->
    <div class="flex items-center justify-end">
      <BaseButton variant="secondary" @click="goEditor">
        进入逐字编辑器
      </BaseButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import MatchPanel from "./MatchPanel.vue"
import SidecarList from "./SidecarList.vue"
import BaseButton from "@/components/ui/BaseButton.vue"
import { useLyricsStore } from "@/stores/lyrics"

/**
 * 歌词 tab 容器
 *
 * 职责：
 * - 接收 trackId prop，编排 MatchPanel + SidecarList
 * - trackId 变化时重置 store（防跨曲目残留状态）
 * - 底部「进入逐字编辑器」按钮 → router.push('/track/{id}/lyrics-editor')
 *
 * 约束：
 * - auto-import 已注入 watch / useRouter
 * - 由 TrackDetailView.vue 用 defineAsyncComponent 加载，无需自注册路由
 * - 不直接调 apis
 */
const props = defineProps<{ trackId: string }>()

const store = useLyricsStore()
const router = useRouter()

// trackId 变化时清空旧曲目的匹配状态与 sidecar（SidecarList onMounted 会重新加载）
watch(
  () => props.trackId,
  () => {
    store.resetAll()
  },
)

function goEditor(): void {
  void router.push(`/track/${props.trackId}/lyrics-editor`)
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
