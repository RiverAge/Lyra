/**
 * audioManager — 全局音频单例（模块级，非组件非 store）
 *
 * 设计意图：
 * - 跨 `/track/:id` 和 `/track/:id/lyrics-editor` 两个路由共享同一个 audio 实例，
 *   切页面不重载、不中断播放、不丢进度（同 track）。
 * - **命令式 loadTrack 替代 PlayerDock 的双 watch 派生**：playTrack 同步 setPlaying(true)+改 src
 *   时，src watch 与 playing watch 抢跑导致 readyState 不足 play() reject。改为 loadTrack
 *   内部顺序执行 probe→load→等 canplay→play，彻底消除竞态。
 * - 暴露 reactive ref（currentTime/duration/playing/...）供组件订阅，方法（loadTrack/play/...）供调用。
 * - volume 持久化 localStorage（迁自 player store）。
 *
 * 约束：
 * - `new Audio()` 懒初始化（typeof window 守卫，SSR 安全，本仓库 SPA 无 SSR 但保持守卫）。
 * - probePlayback 复用 http.head（token 注入 + 401 拦截），不用裸 fetch。
 * - 转码流（ALAC→Opus chunked）el.duration 可能 NaN，effectiveDuration 用 track.duration 兜底。
 */
/* global Audio, HTMLAudioElement, HTMLMediaElement, setTimeout, clearTimeout */
import type { Ref } from "vue"
import type { TrackItem } from "@/apis/library"
import { http } from "@/apis/http"

// ---- 模块级单例状态（import 即共享）----
let audioEl: HTMLAudioElement | null = null

const currentTime = ref(0) // 秒
const duration = ref(0) // 秒
const playing = ref(false)
const volume = ref(0.8)
const muted = ref(false)
const currentTrackId = ref<string | null>(null)
const currentTrack = ref<TrackItem | null>(null)
const error = ref<string | null>(null)
const transcoding = ref(false)
// 拖拽中标志（scrubbing 时不回写 currentTime，避免抖动）
let scrubbing = false

/** effectiveDuration：audio.duration 拿不到（转码流）时用 track.duration 兜底。 */
const effectiveDuration = computed(() => {
  if (duration.value > 0 && Number.isFinite(duration.value)) return duration.value
  const ms = currentTrack.value?.duration
  return ms ? ms / 1000 : 0
})

/** 进度百分比（0-100）。 */
const progressPercent = computed(() => {
  const dur = effectiveDuration.value
  if (!dur || dur <= 0) return 0
  return Math.min(100, (currentTime.value / dur) * 100)
})

// ---- audio 元素懒初始化 + 事件绑定 ----
function getAudioEl(): HTMLAudioElement {
  if (audioEl) return audioEl
  if (typeof window === "undefined" || typeof Audio === "undefined") {
    // SSR 守卫：本仓库 SPA 不会进，但保持防御
    throw new Error("Audio not available")
  }
  audioEl = new Audio()
  audioEl.preload = "metadata"
  initVolume()
  audioEl.volume = volume.value
  audioEl.muted = muted.value

  audioEl.addEventListener("loadedmetadata", () => {
    duration.value = audioEl?.duration || 0
  })
  audioEl.addEventListener("timeupdate", () => {
    if (scrubbing) return
    currentTime.value = audioEl?.currentTime || 0
    clearTranscoding()
  })
  audioEl.addEventListener("play", () => {
    playing.value = true
    clearTranscoding()
  })
  audioEl.addEventListener("pause", () => {
    playing.value = false
  })
  audioEl.addEventListener("ended", () => {
    currentTime.value = 0
    playing.value = false
    // 不自动 next（校对场景不切歌）
  })
  audioEl.addEventListener("error", () => {
    const code = audioEl?.error?.code
    if (transcoding.value) {
      error.value = code
        ? `ALAC 转码失败（code ${code}），请确认 ffmpeg 可用`
        : "ALAC 转码失败，请确认 ffmpeg 可用"
    } else if (code === 3 || code === 4) {
      error.value = `浏览器不支持此音频格式（code ${code}）`
    } else {
      error.value = code ? `音频加载失败（code ${code}）` : "音频加载失败"
    }
    playing.value = false
  })
  return audioEl
}

function clearTranscoding(): void {
  if (transcoding.value) transcoding.value = false
}

// ---- HEAD 预检（迁自 PlayerDock.probePlayback）----
/**
 * HEAD 预检 /api/play/{id}：读 X-Lyra-Transcoded/Codec/Reason，
 * 给播放前精准状态（转码中 / ffmpeg 缺失 / 格式不支持）。
 * 返回 true 可继续加载，false 已设 error（预检确定失败）。
 */
async function probePlayback(url: string): Promise<boolean> {
  const relPath = url.replace(/^\/api\//, "")
  try {
    const resp = await http.head(relPath, { validateStatus: () => true })
    if (resp.status >= 200 && resp.status < 300) {
      if (resp.headers["x-lyra-transcoded"] === "true") {
        transcoding.value = true
      }
      return true
    }
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
    error.value = `网络错误：${normalizeError(e)}`
    return false
  }
}

// ---- 核心：命令式 loadTrack（替代双 watch 派生，消除竞态）----
/**
 * 加载 track。同 track 不重载（保留进度，跨页面跳转不中断）；异 track 顺序执行
 * probe→load→等 canplay→（autoplay 或 playing 时）play。
 */
async function loadTrack(track: TrackItem, autoplay = false): Promise<void> {
  const el = getAudioEl()
  error.value = null

  // 同 track：不重载，只按需续播（跨页面跳转保留进度）
  if (currentTrackId.value === track.id) {
    currentTrack.value = track
    if (autoplay && !playing.value && el.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      void el.play().catch((e: unknown) => {
        error.value = `播放失败：${normalizeError(e)}`
      })
    }
    return
  }

  // 异 track：切源
  currentTrack.value = track
  currentTrackId.value = track.id
  currentTime.value = 0
  duration.value = 0
  transcoding.value = false
  coverErrorReset()

  const src = `/api/play/${track.id}`
  const ok = await probePlayback(src)
  if (!ok) return

  el.src = src
  el.load()

  // 等 canplay（readyState>=HAVE_CURRENT_DATA）再播，避免 not-suitable reject
  await waitUntilPlayable(el)
  // canplay 即转码首包就绪——无论是否自动播，转码 flag 都该清。
  // 否则进详情页不自动播时 transcoding 永远 true（play/timeupdate 不触发），
  // SyncControls 的 Loader2 一直转。
  clearTranscoding()
  if (autoplay || playing.value) {
    void el.play().catch((e: unknown) => {
      error.value = `播放失败：${normalizeError(e)}`
      playing.value = false
    })
  }
}

/** 等 audio 就绪到 HAVE_CURRENT_DATA，超时 8s 放弃（转码流首包慢）。 */
function waitUntilPlayable(el: HTMLAudioElement, timeoutMs = 8000): Promise<void> {
  if (el.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) return Promise.resolve()
  return new Promise((resolve) => {
    const onCanPlay = (): void => {
      el.removeEventListener("canplay", onCanPlay)
      el.removeEventListener("loadeddata", onCanPlay)
      clearTimeout(timer)
      resolve()
    }
    el.addEventListener("canplay", onCanPlay)
    el.addEventListener("loadeddata", onCanPlay)
    const timer = setTimeout(() => {
      el.removeEventListener("canplay", onCanPlay)
      el.removeEventListener("loadeddata", onCanPlay)
      resolve()
    }, timeoutMs)
  })
}

// 封面错误标志（与 PlayerDock 一致，供消费组件读）
const coverError = ref(false)
function coverErrorReset(): void {
  coverError.value = false
}

// ---- 播放控制 ----
function play(): void {
  const el = getAudioEl()
  if (!currentTrackId.value) return
  // 未就绪 → loadTrack(当前 track, autoplay)
  if (el.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    const t = currentTrack.value
    if (t) void loadTrack(t, true)
    return
  }
  void el.play().catch((e: unknown) => {
    error.value = `播放失败：${normalizeError(e)}`
  })
}

function pause(): void {
  audioEl?.pause()
}

function togglePlay(): void {
  if (playing.value) pause()
  else play()
}

function seek(sec: number): void {
  const el = getAudioEl()
  el.currentTime = sec
  currentTime.value = sec
}

/** 拖拽开始：暂停 timeupdate 回写。 */
function scrubStart(): void {
  scrubbing = true
}
/** 拖拽中：只更新 ref（不写 el.currentTime，避免频繁 seek）。 */
function scrubMove(sec: number): void {
  currentTime.value = sec
}
/** 拖拽结束：写 el.currentTime + 恢复 timeupdate。 */
function scrubEnd(sec: number): void {
  scrubbing = false
  const el = getAudioEl()
  el.currentTime = sec
  currentTime.value = sec
}

// ---- 音量 ----
function setVolume(v: number): void {
  volume.value = v
  if (audioEl) audioEl.volume = v
  if (v > 0) {
    muted.value = false
    if (audioEl) audioEl.muted = false
  }
  persistVolume(v)
}

function toggleMute(): void {
  muted.value = !muted.value
  if (audioEl) audioEl.muted = muted.value
}

function initVolume(): void {
  if (typeof window === "undefined") return
  const stored = localStorage.getItem("lyra-volume")
  if (stored !== null) {
    const v = Number(stored)
    if (!Number.isNaN(v) && v >= 0 && v <= 1) volume.value = v
  }
}

function persistVolume(v: number): void {
  if (typeof window === "undefined") return
  localStorage.setItem("lyra-volume", String(v))
}

function normalizeError(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

// ---- 模块初始化（首次 getAudioEl 时 initVolume，这里不主动创建 el）----
// 导出 useAudioManager：返回状态 ref + 方法
export function useAudioManager() {
  return {
    // 状态
    currentTime,
    duration,
    effectiveDuration,
    progressPercent,
    playing,
    volume,
    muted,
    currentTrackId,
    currentTrack,
    error,
    transcoding,
    coverError,
    // 方法
    loadTrack,
    play,
    pause,
    togglePlay,
    seek,
    scrubStart,
    scrubMove,
    scrubEnd,
    setVolume,
    toggleMute,
    // 供消费组件读 audio 元素（如需直接绑事件）
    getAudioEl,
  }
}

export type AudioManager = ReturnType<typeof useAudioManager>

/** 当前 track 是否正在播（供 Hero 按钮态）。 */
export function useIsCurrentPlaying(trackId: string | undefined): Ref<boolean> {
  return computed(() =>
    currentTrackId.value === trackId && playing.value,
  )
}
