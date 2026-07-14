<template>
  <div class="card p-4">
    <!-- 当前 track 信息 -->
    <div class="mb-3 flex items-start justify-between gap-3">
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-semibold text-primary">
          {{ trackTitle }}
        </p>
        <p class="truncate text-xs text-secondary">
          {{ trackArtist }}
        </p>
      </div>
      <div v-if="!hasTrack" class="text-xs text-tertiary">
        未选择曲目
      </div>
    </div>

    <!-- audio 元素：src 由 store 派生，完整 /api/play/xxx 路径 -->
    <audio
      ref="audioEl"
      class="hidden"
      :src="src"
      preload="metadata"
      @loadedmetadata="onLoadedMetadata"
      @timeupdate="onTimeUpdate"
      @ended="onEnded"
      @play="onPlay"
      @pause="onPause"
      @error="onError"
    />

    <!-- 进度条（可拖拽 seek） -->
    <div class="mb-3">
      <div
        ref="progressBarEl"
        class="group relative h-1.5 cursor-pointer rounded-full bg-hover"
        @mousedown="onScrubStart"
      >
        <div
          class="absolute left-0 top-0 h-full rounded-full bg-accent transition-[width] duration-150"
          :style="{ width: progressPercent + '%' }"
        />
        <div
          class="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-surface shadow-sm opacity-0 transition-opacity group-hover:opacity-100"
          :style="{ left: progressPercent + '%' }"
        />
      </div>
    </div>

    <!-- 控制条 -->
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <button
          class="rounded-md p-1.5 text-secondary transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!hasPrev"
          title="上一首"
          @click="playerStore.prev"
        >
          <span class="block text-base leading-none">⏮</span>
        </button>
        <button
          class="rounded-md border border-default bg-accent-subtle px-3 py-1.5 text-sm font-medium text-accent transition-colors hover:bg-accent hover:text-surface disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!hasTrack"
          @click="togglePlay"
        >
          {{ playLabel }}
        </button>
        <button
          class="rounded-md p-1.5 text-secondary transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!hasNext"
          title="下一首"
          @click="playerStore.next"
        >
          <span class="block text-base leading-none">⏭</span>
        </button>
      </div>

      <div class="font-mono text-xs text-tertiary">
        {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
      </div>

      <div class="flex items-center gap-2">
        <button
          class="rounded-md p-1.5 text-secondary transition-colors hover:bg-hover"
          :title="muted ? '取消静音' : '静音'"
          @click="playerStore.toggleMute"
        >
          {{ muted ? "🔇" : "🔊" }}
        </button>
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          class="h-1 w-20 cursor-pointer accent-[var(--color-accent)]"
          :value="volume"
          @input="onVolumeInput"
        >
      </div>
    </div>

    <!-- 错误提示 -->
    <p v-if="error" class="mt-2 text-xs text-danger">
      {{ error }}
    </p>
  </div>
</template>

<script setup lang="ts">
/* global Event, HTMLAudioElement, HTMLDivElement, HTMLInputElement, MouseEvent, DOMRect */
import { usePlayerStore } from "@/stores/player"

/**
 * 音频播放器组件
 *
 * 设计：
 * - <audio> 元素由本组件持有，src 由 playerStore.src 派生（/api/play/${trackId}）
 * - 播放/暂停/seek/音量状态写入 store，store 是 single source of truth
 * - store.currentTrack 变更时 watch 切换 src 并自动播
 * - 进度条用 mousedown 拖拽 seek（不引入第三方库）
 * - 禁 setInterval 轮询，进度由 audio 的 timeupdate 事件驱动
 */
const playerStore = usePlayerStore()

const audioEl = shallowRef<HTMLAudioElement | null>(null)
const progressBarEl = shallowRef<HTMLDivElement | null>(null)
const error = ref<string | null>(null)

const src = computed(() => playerStore.src)
const currentTime = computed(() => playerStore.currentTime)
const duration = computed(() => playerStore.duration)
const volume = computed(() => playerStore.volume)
const muted = computed(() => playerStore.muted)
const hasTrack = computed(() => !!playerStore.currentTrack)
const hasPrev = computed(() => playerStore.hasPrev)
const hasNext = computed(() => playerStore.hasNext)
const playing = computed(() => playerStore.playing)

const trackTitle = computed(() => playerStore.currentTrack?.title || "—")
const trackArtist = computed(
  () => playerStore.currentTrack?.artist || "",
)

const playLabel = computed(() => (playing.value ? "暂停" : "播放"))

const progressPercent = computed(() => {
  if (!duration.value || duration.value <= 0) return 0
  return Math.min(100, (currentTime.value / duration.value) * 100)
})

// 拖拽状态
let scrubbing = false

onMounted(() => {
  playerStore.initVolume()
  syncAudioVolume()
})

// src 变化时切源并自动播
watch(
  () => src.value,
  (next, prev) => {
    if (next === prev) return
    error.value = null
    nextTick(() => {
      const el = audioEl.value
      if (!el || !next) return
      el.load()
      if (playerStore.playing) {
        void el.play().catch((e: unknown) => {
          error.value = `播放失败：${normalizeError(e)}`
          playerStore.setPlaying(false)
        })
      }
    })
  },
)

// playing 状态变化时同步 audio 元素
watch(
  () => playing.value,
  (isPlaying) => {
    const el = audioEl.value
    if (!el || !src.value) return
    if (isPlaying) {
      void el.play().catch((e: unknown) => {
        error.value = `播放失败：${normalizeError(e)}`
        playerStore.setPlaying(false)
      })
    } else {
      el.pause()
    }
  },
)

// volume/muted 变化时同步到 audio 元素
watch([volume, muted], () => syncAudioVolume())

function syncAudioVolume(): void {
  const el = audioEl.value
  if (!el) return
  el.volume = volume.value
  el.muted = muted.value
}

function togglePlay(): void {
  playerStore.togglePlay()
}

function onLoadedMetadata(e: Event): void {
  const el = e.target as HTMLAudioElement
  playerStore.setDuration(el.duration || 0)
}

function onTimeUpdate(e: Event): void {
  if (scrubbing) return // 拖拽中不回写，避免抖动
  const el = e.target as HTMLAudioElement
  playerStore.setCurrentTime(el.currentTime || 0)
}

function onPlay(): void {
  playerStore.setPlaying(true)
}

function onPause(): void {
  // 用户在元素上直接暂停（如系统打断）时同步状态
  // 注意：togglePlay 已直接更新 playing，此处幂等
  playerStore.setPlaying(false)
}

function onEnded(): void {
  playerStore.setCurrentTime(0)
  if (hasNext.value) {
    playerStore.next()
  } else {
    playerStore.setPlaying(false)
  }
}

function onError(e: Event): void {
  const el = e.target as HTMLAudioElement
  const code = el.error?.code
  error.value = `音频加载失败${code ? `（code ${code}）` : ""}`
}

function seekFromEvent(e: MouseEvent): void {
  const el = audioEl.value
  const bar = progressBarEl.value
  if (!el || !duration.value || !bar) return
  const rect = bar.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
  const target = ratio * duration.value
  el.currentTime = target
  playerStore.seek(target)
}

// 拖拽期间缓存的进度条 rect，避免每帧重新查询 DOM
let cachedBarRect: DOMRect | null = null

function onScrubStart(e: MouseEvent): void {
  const bar = progressBarEl.value
  if (!bar) return
  scrubbing = true
  cachedBarRect = bar.getBoundingClientRect()
  seekFromEvent(e)
  window.addEventListener("mousemove", onScrubMove)
  window.addEventListener("mouseup", onScrubEnd)
}

function onScrubMove(e: MouseEvent): void {
  const el = audioEl.value
  if (!el || !duration.value || !cachedBarRect) return
  const ratio = Math.min(1, Math.max(0, (e.clientX - cachedBarRect.left) / cachedBarRect.width))
  const t = ratio * duration.value
  playerStore.setCurrentTime(t)
}

function onScrubEnd(): void {
  scrubbing = false
  cachedBarRect = null
  const el = audioEl.value
  if (el) {
    el.currentTime = playerStore.currentTime
  }
  window.removeEventListener("mousemove", onScrubMove)
  window.removeEventListener("mouseup", onScrubEnd)
}

function onVolumeInput(e: Event): void {
  const target = e.target as HTMLInputElement
  playerStore.setVolume(Number(target.value))
}

function formatTime(sec: number): string {
  if (!sec || sec < 0 || !Number.isFinite(sec)) return "--:--"
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  const mm = String(m).padStart(2, "0")
  const ss = String(s).padStart(2, "0")
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, "0")}:${ss}`
  }
  return `${mm}:${ss}`
}

function normalizeError(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}
</script>

<style scoped>
/* AudioPlayer 无额外 scoped 样式——按钮/进度条均用 token 类名 */
</style>
