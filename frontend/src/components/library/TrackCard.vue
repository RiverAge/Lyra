<template>
  <div
    class="card card-hover group cursor-pointer overflow-hidden"
    @click="handleNavigate"
  >
    <!-- 封面区 -->
    <div class="relative aspect-square overflow-hidden bg-subtle">
      <img
        v-if="track.has_cover && !imgError"
        :src="`/api/library/${track.id}/artwork`"
        :alt="track.title"
        loading="lazy"
        class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        @error="imgError = true"
      >
      <div
        v-else
        class="flex h-full w-full items-center justify-center text-tertiary"
      >
        <Icon name="Music" :size="40" />
      </div>

      <!-- hover 播放按钮 -->
      <button
        class="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 backdrop-blur-[2px] transition-opacity duration-200 group-hover:opacity-100"
        title="播放"
        @click.stop="handlePlay"
      >
        <span class="flex h-12 w-12 items-center justify-center rounded-full bg-accent-gradient text-on-accent shadow-lg transition-transform duration-200 hover:scale-110">
          <Icon name="Play" :size="22" />
        </span>
      </button>
    </div>

    <!-- 信息区 -->
    <div class="p-3">
      <p class="truncate text-sm font-medium text-primary">
        {{ track.title || "（无标题）" }}
      </p>
      <p class="mt-0.5 truncate text-xs text-secondary">
        {{ track.artist || "—" }}
      </p>
      <!-- 底栏：album + duration + codec -->
      <div class="mt-2 flex items-center gap-2 text-xs text-tertiary">
        <span v-if="track.album" class="min-w-0 flex-1 truncate">
          {{ track.album }}
        </span>
        <span v-else class="flex-1" />
        <span class="font-mono">{{ formatDuration }}</span>
        <span
          v-if="codecLabel"
          class="rounded-sm bg-subtle px-1.5 py-0.5 font-mono uppercase"
        >{{ codecLabel }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TrackItem } from "@/apis/library"
import { usePlayerStore } from "@/stores/player"
import Icon from "@/components/ui/icons/Icon.vue"

/**
 * 曲库卡片项（替代 TrackListItem 的表格行版）
 * - 点击卡片主体 → 跳详情页
 * - 点击 hover 播放按钮 → playerStore.playTrack（不入队，单曲播放）
 * - hover：card-hover 动效 + 封面浮出半透明遮罩 + Play 按钮 + 封面微缩放
 */
const props = defineProps<{
  track: TrackItem
}>()

const emit = defineEmits<{
  (e: "navigate", id: string): void
}>()

const playerStore = usePlayerStore()

// 封面加载失败回退：has_cover=1 但 artwork 端点 404（文件缺封面/后端未启动）时回退占位图标
const imgError = ref(false)

// track 变化时重置错误状态（分页/刷新后重新尝试加载）
watch(
  () => props.track.id,
  () => { imgError.value = false },
)

const formatDuration = computed(() => formatMs(Number(props.track.duration) || 0))

const codecLabel = computed(() => {
  const c = String(props.track.codec || "").toLowerCase()
  return c || ""
})

function handleNavigate(): void {
  emit("navigate", props.track.id)
}

function handlePlay(): void {
  playerStore.playTrack(props.track)
}

/** ms → mm:ss（超 1h 显示 h:mm:ss） */
function formatMs(ms: number): string {
  if (!ms || ms < 0) return "--:--"
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  const mm = String(m).padStart(2, "0")
  const ss = String(s).padStart(2, "0")
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, "0")}:${ss}`
  }
  return `${mm}:${ss}`
}
</script>

<style scoped>
/* TrackCard 无 scoped 样式——靠 .card / .card-hover 工具类 + token 控制 */
</style>
