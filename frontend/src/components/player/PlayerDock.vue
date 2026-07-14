<template>
  <Teleport to="body">
    <Transition name="dock">
      <div
        v-if="playerStore.currentTrack"
        class="card-elevated fixed inset-x-0 bottom-0 z-40 mx-auto flex items-center gap-4 border-t px-4 py-2.5 md:max-w-6xl"
      >
        <!-- 左：封面 + 标题 -->
        <div class="flex min-w-0 flex-shrink-0 items-center gap-3 md:w-56">
          <img
            v-if="hasCover && !coverError"
            :src="`/api/library/${playerStore.currentTrack.id}/artwork`"
            :alt="trackTitle"
            class="h-11 w-11 flex-shrink-0 rounded-sm object-cover"
            @error="coverError = true"
          >
          <div
            v-else
            class="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-sm bg-subtle text-tertiary"
          >
            <Icon name="Music" :size="16" />
          </div>
          <div class="min-w-0">
            <p class="truncate text-sm font-medium text-primary">
              {{ trackTitle }}
            </p>
            <p class="truncate text-xs text-secondary">
              {{ trackArtist }}
            </p>
          </div>
        </div>

        <!-- 中：进度条 + 控制 -->
        <div class="flex flex-1 flex-col items-center gap-1.5">
          <!-- 控制按钮 -->
          <div class="flex items-center gap-1">
            <button
              class="rounded-sm p-1.5 text-secondary transition-colors hover:bg-hover hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!hasPrev"
              title="上一首"
              @click="playerStore.prev"
            >
              <Icon name="SkipBack" :size="16" />
            </button>
            <button
              class="flex h-9 w-9 items-center justify-center rounded-full bg-accent-gradient text-on-accent transition-all duration-150 hover:shadow-lg hover:-translate-y-px active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!hasTrack"
              :title="playing ? '暂停' : '播放'"
              @click="togglePlay"
            >
              <Icon :name="playing ? 'Pause' : 'Play'" :size="16" />
            </button>
            <button
              class="rounded-sm p-1.5 text-secondary transition-colors hover:bg-hover hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
              :disabled="!hasNext"
              title="下一首"
              @click="playerStore.next"
            >
              <Icon name="SkipForward" :size="16" />
            </button>
          </div>

          <!-- 进度条 -->
          <div class="flex w-full items-center gap-2">
            <span class="w-10 text-right font-mono text-xs text-tertiary">
              {{ formatTime(currentTime) }}
            </span>
            <div
              ref="progressBarEl"
              class="group relative h-1.5 flex-1 cursor-pointer rounded-full bg-hover"
              @mousedown="onScrubStart"
            >
              <div
                class="absolute left-0 top-0 h-full rounded-full bg-accent transition-[width] duration-150"
                :style="{ width: progressPercent + '%' }"
              />
              <div
                class="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-surface opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
                :style="{ left: progressPercent + '%' }"
              />
            </div>
            <span class="w-10 font-mono text-xs text-tertiary">
              {{ formatTime(duration) }}
            </span>
          </div>
        </div>

        <!-- 右：音量 + 错误 -->
        <div class="flex flex-shrink-0 items-center gap-2 md:w-56 md:justify-end">
          <p
            v-if="error"
            class="flex items-center gap-1 text-xs text-danger"
            :title="error"
          >
            <Icon name="AlertCircle" :size="13" />
            <span class="hidden lg:inline">{{ error }}</span>
          </p>
          <div v-if="transcoding" class="flex items-center gap-1 text-xs text-accent">
            <Icon name="Loader2" :size="13" spin />
            <span class="hidden lg:inline">转码中</span>
          </div>
          <button
            class="rounded-sm p-1.5 text-secondary transition-colors hover:bg-hover hover:text-primary"
            :title="muted ? '取消静音' : '静音'"
            @click="playerStore.toggleMute"
          >
            <Icon :name="muted ? 'VolumeX' : 'Volume2'" :size="16" />
          </button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            class="h-1 w-16 cursor-pointer accent-[var(--color-accent)]"
            :value="volume"
            @input="onVolumeInput"
          >
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- audio 元素：脱离视觉层，仅由逻辑驱动 -->
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
</template>

<script setup lang="ts">
/* global Event, HTMLAudioElement, HTMLDivElement, HTMLInputElement, MouseEvent, DOMRect */
import { usePlayerStore } from "@/stores/player"
import { http } from "@/apis/http"
import Icon from "@/components/ui/icons/Icon.vue"

/**
 * 全局播放器 Dock
 *
 * 设计：
 * - fixed bottom 全局浮层，App.vue 挂载一次，导航不消失
 * - <audio> 元素由本组件持有，src 由 playerStore.src 派生
 * - 三段式：左封面+标题 / 中控制+进度 / 右音量+错误
 * - SVG 图标替代 emoji（SkipBack/Play/Pause/SkipForward/Volume2/VolumeX）
 * - HEAD 预检读 X-Lyra-Transcoded/X-Lyra-Codec/X-Lyra-Reason，给精准错误提示
 * - 播放/暂停/seek/音量状态写入 store，store 是 single source of truth
 * - 进度条用 mousedown 拖拽 seek（不引入第三方库）
 * - 禁 setInterval 轮询，进度由 audio 的 timeupdate 事件驱动
 */
const playerStore = usePlayerStore()

const audioEl = shallowRef<HTMLAudioElement | null>(null)
const progressBarEl = shallowRef<HTMLDivElement | null>(null)
const error = ref<string | null>(null)
const transcoding = ref(false)
const coverError = ref(false)

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
const hasCover = computed(() => Boolean((playerStore.currentTrack as { has_cover?: boolean } | null)?.has_cover))

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

/**
 * src 变化时：HEAD 预检读响应头 → 设置 transcoding 标志 → 切源并自动播
 */
watch(
  () => src.value,
  async (next, prev) => {
    if (next === prev || !next) return
    error.value = null
    transcoding.value = false
    coverError.value = false
    const ok = await probePlayback(next)
    // 预检已确定失败（如 ffmpeg 缺失），不再让 <audio> 盲试覆盖精准提示
    if (!ok) return
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

/**
 * HEAD 预检：读 X-Lyra-Transcoded / X-Lyra-Codec / X-Lyra-Reason
 * 给出精准的播放前状态提示（转码中 / ffmpeg 缺失 / 格式不支持）
 *
 * 返回 true 表示可继续加载 <audio>，false 表示预检已确定失败（已设 error）。
 * 用统一 http 客户端（token 注入 + 401 拦截），validateStatus 让 503 也 resolve
 * 以便统一读响应头分支。http baseURL='/api'，src 是 '/api/play/xxx'，取后段。
 */
async function probePlayback(url: string): Promise<boolean> {
  // 从 /api/play/123 提取 play/123（去掉 /api 前缀，http 会补回）
  const relPath = url.replace(/^\/api\//, "")
  try {
    const resp = await http.head(relPath, {
      validateStatus: () => true,
    })
    if (resp.status >= 200 && resp.status < 300) {
      const transcoded = resp.headers["x-lyra-transcoded"]
      if (transcoded === "true") {
        transcoding.value = true
      }
      return true
    }
    // 非 2xx：按状态码和 reason 头给精准提示
    const reason = resp.headers["x-lyra-reason"]
    if (resp.status === 503 && reason === "ffmpeg-missing") {
      error.value = "未安装 ffmpeg，无法播放 ALAC"
    } else if (resp.status === 503) {
      error.value = "服务未就绪，请稍后重试"
    } else if (resp.status === 404) {
      error.value = "曲目不存在"
    } else if (resp.status === 422) {
      error.value = "无效曲目 ID"
    } else {
      error.value = `加载失败（${resp.status}）`
    }
    return false
  } catch (e: unknown) {
    // 网络错误等：不阻塞 <audio> 自身的 error 事件兜底
    error.value = `网络错误：${normalizeError(e)}`
    return false
  }
}

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

// 播放成功后清除转码中标志
function clearTranscoding(): void {
  if (transcoding.value) transcoding.value = false
}

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
  clearTranscoding()
}

function onPlay(): void {
  playerStore.setPlaying(true)
  clearTranscoding()
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
  // MediaError code 3 = MEDIA_ERR_DECODE, code 4 = MEDIA_ERR_SRC_NOT_SUPPORTED
  if (transcoding.value) {
    // 后端确认是转码流 → 转码失败
    error.value = code
      ? `ALAC 转码失败（code ${code}），请确认 ffmpeg 可用`
      : "ALAC 转码失败，请确认 ffmpeg 可用"
  } else if (code === 3 || code === 4) {
    // 非转码流但浏览器不可解码 → 格式不支持
    error.value = `浏览器不支持此音频格式（code ${code}）`
  } else {
    error.value = code ? `音频加载失败（code ${code}）` : "音频加载失败"
  }
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
  playerStore.setVolume(Number((e.target as HTMLInputElement).value))
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
/* dock 入场/出场动画 */
.dock-enter-active,
.dock-leave-active {
  transition: opacity 0.2s ease, transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
.dock-enter-from,
.dock-leave-to {
  opacity: 0;
  transform: translateY(100%);
}
</style>
