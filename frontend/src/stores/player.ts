import type { TrackItem } from "@/apis/library"

/**
 * 播放器 Store
 *
 * 职责：
 * - 维护当前播放 track + 队列（简单列表，由 LibraryView 注入）
 * - 维护播放状态（playing/currentTime/duration/volume）
 * - 不持有 <audio> 元素本身（元素在 AudioPlayer.vue 里），store 只存数值状态
 *
 * 设计：
 * - 播放 src = `/api/play/${trackId}`（不走 axios，浏览器直接请求）
 * - 组件 watch currentTrack 切换 src，store 只负责状态切换语义
 * - volume 持久化到 localStorage
 */

export const usePlayerStore = defineStore("player", () => {
  // 当前播放 track（可能为 null = 未加载）
  const currentTrack = ref<TrackItem | null>(null)

  // 播放队列（用于上一首/下一首，简单实现）
  const queue = ref<TrackItem[]>([])
  const queueIndex = ref(-1)

  // 播放状态
  const playing = ref(false)
  const currentTime = ref(0) // 秒
  const duration = ref(0) // 秒
  const volume = ref(0.8)
  const muted = ref(false)

  // 派生 src（供 <audio> 使用，完整路径 /api/play/xxx）
  const src = computed(() => {
    const id = currentTrack.value?.id
    return id ? `/api/play/${id}` : ""
  })

  const hasNext = computed(() => queueIndex.value < queue.value.length - 1)
  const hasPrev = computed(() => queueIndex.value > 0)

  /**
   * 设置播放队列并指定起始项。
   * - tracks：队列（通常来自 LibraryView 当前页 items）
   * - startId：从队列中哪个 track 开始
   */
  function setQueue(tracks: TrackItem[], startId?: string): void {
    queue.value = tracks
    const idx = startId
      ? tracks.findIndex((t) => t.id === startId)
      : 0
    queueIndex.value = idx >= 0 ? idx : 0
    currentTrack.value = idx >= 0 ? tracks[idx] ?? null : null
    currentTime.value = 0
    duration.value = 0
    playing.value = true
  }

  function playTrack(track: TrackItem): void {
    // 单曲播放：清空队列，只放当前
    queue.value = [track]
    queueIndex.value = 0
    currentTrack.value = track
    currentTime.value = 0
    duration.value = 0
    playing.value = true
  }

  function togglePlay(): void {
    playing.value = !playing.value
  }

  function setPlaying(v: boolean): void {
    playing.value = v
  }

  function seek(timeSec: number): void {
    currentTime.value = timeSec
  }

  function setCurrentTime(timeSec: number): void {
    currentTime.value = timeSec
  }

  function setDuration(durSec: number): void {
    duration.value = durSec
  }

  function setVolume(v: number): void {
    volume.value = v
    if (v > 0) muted.value = false
    persistVolume(v)
  }

  function toggleMute(): void {
    muted.value = !muted.value
  }

  function next(): void {
    if (!hasNext.value) return
    queueIndex.value += 1
    currentTrack.value = queue.value[queueIndex.value] ?? null
    currentTime.value = 0
    duration.value = 0
    playing.value = true
  }

  function prev(): void {
    if (!hasPrev.value) return
    queueIndex.value -= 1
    currentTrack.value = queue.value[queueIndex.value] ?? null
    currentTime.value = 0
    duration.value = 0
    playing.value = true
  }

  function clear(): void {
    currentTrack.value = null
    queue.value = []
    queueIndex.value = -1
    playing.value = false
    currentTime.value = 0
    duration.value = 0
  }

  // 初始化 volume（从 localStorage）
  function initVolume(): void {
    if (typeof window === "undefined") return
    const stored = localStorage.getItem("lyra-volume")
    if (stored !== null) {
      const v = Number(stored)
      if (!Number.isNaN(v) && v >= 0 && v <= 1) {
        volume.value = v
      }
    }
  }

  function persistVolume(v: number): void {
    if (typeof window === "undefined") return
    localStorage.setItem("lyra-volume", String(v))
  }

  return {
    currentTrack,
    queue,
    queueIndex,
    playing,
    currentTime,
    duration,
    volume,
    muted,
    src,
    hasNext,
    hasPrev,
    setQueue,
    playTrack,
    togglePlay,
    setPlaying,
    seek,
    setCurrentTime,
    setDuration,
    setVolume,
    toggleMute,
    next,
    prev,
    clear,
    initVolume,
  }
})
