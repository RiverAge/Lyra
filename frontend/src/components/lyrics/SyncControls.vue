<template>
  <div class="flex items-center gap-2 rounded-md bg-subtle px-2.5 py-2">
    <!-- 播放/暂停 -->
    <button
      class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-none bg-accent text-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
      :disabled="!audio.currentTrackId.value"
      :title="audio.playing.value ? '暂停' : '播放'"
      @click="audio.togglePlay"
    >
      <Icon :name="audio.playing.value ? 'Pause' : 'Play'" :size="14" />
    </button>

    <!-- 进度条（可拖拽 seek） -->
    <div
      ref="progressBarEl"
      class="group relative h-1 min-w-0 flex-1 cursor-pointer rounded-full bg-hover"
      @mousedown="onScrubStart"
    >
      <div class="absolute left-0 top-0 h-full rounded-full bg-accent" :style="{ width: audio.progressPercent.value + '%' }" />
      <div
        class="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-surface opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
        :style="{ left: audio.progressPercent.value + '%' }"
      />
    </div>

    <!-- 时间 -->
    <span class="shrink-0 font-mono text-xs tabular-nums text-tertiary">
      {{ formatTime(audio.currentTime.value) }}<span class="mx-0.5 opacity-40">/</span>{{ formatTime(audio.effectiveDuration.value) }}
    </span>

    <!-- 转码/错误指示 -->
    <Icon v-if="audio.transcoding.value" name="Loader2" :size="12" spin class="shrink-0 text-accent" />
    <span v-if="audio.error.value" class="grid h-4 w-4 shrink-0 place-items-center rounded-full bg-danger-subtle text-xs font-semibold text-danger" :title="audio.error.value">!</span>

    <!-- 音量 -->
    <button
      class="flex items-center justify-center rounded-sm border-none bg-transparent p-1 text-secondary transition-colors hover:bg-hover hover:text-primary"
      :title="audio.muted.value ? '取消静音' : '静音'"
      @click="audio.toggleMute"
    >
      <Icon :name="audio.muted.value ? 'VolumeX' : 'Volume2'" :size="14" />
    </button>
    <input
      type="range"
      min="0"
      max="1"
      step="0.01"
      class="sc-vol h-1 w-14 cursor-pointer"
      :value="audio.volume.value"
      @input="onVolumeInput"
    >
  </div>
</template>

<script setup lang="ts">
/* global HTMLDivElement, HTMLInputElement, MouseEvent, DOMRect, Event */
import Icon from "@/components/ui/icons/Icon.vue"
import { useAudioManager } from "@/lib/audioManager"

/**
 * SyncControls — 歌词校对用轻量播放控件条
 *
 * 紧贴 TtmlPreview 上方，调 audioManager 单例。
 * - 播放/暂停 + 可拖拽进度条 + 时间 + 转码/错误指示 + 音量
 * - 拖拽 seek 用 mousedown/mousemove/mouseup，scrubbing 期间不回写（避免抖动）
 * - 不引入第三方库
 */
const audio = useAudioManager()

const progressBarEl = ref<HTMLDivElement | null>(null)
let cachedBarRect: DOMRect | null = null

function ratioFromEvent(e: MouseEvent): number {
  if (!cachedBarRect) return 0
  return Math.min(1, Math.max(0, (e.clientX - cachedBarRect.left) / cachedBarRect.width))
}

function onScrubStart(e: MouseEvent): void {
  const bar = progressBarEl.value
  if (!bar) return
  audio.scrubStart()
  cachedBarRect = bar.getBoundingClientRect()
  // 点击即 seek 到该位置
  const r = ratioFromEvent(e)
  const dur = audio.effectiveDuration.value
  audio.scrubMove(r * dur)
  window.addEventListener("mousemove", onScrubMove)
  window.addEventListener("mouseup", onScrubEnd)
}

function onScrubMove(e: MouseEvent): void {
  const dur = audio.effectiveDuration.value
  if (!dur || !cachedBarRect) return
  audio.scrubMove(ratioFromEvent(e) * dur)
}

function onScrubEnd(e: MouseEvent): void {
  const dur = audio.effectiveDuration.value
  const r = cachedBarRect ? ratioFromEvent(e) : 0
  audio.scrubEnd(r * dur)
  cachedBarRect = null
  window.removeEventListener("mousemove", onScrubMove)
  window.removeEventListener("mouseup", onScrubEnd)
}

function onVolumeInput(e: Event): void {
  audio.setVolume(Number((e.target as HTMLInputElement).value))
}

function formatTime(sec: number): string {
  if (!sec || sec < 0 || !Number.isFinite(sec)) return "--:--"
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  const ss = String(s).padStart(2, "0")
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, "0")}:${ss}`
  }
  return `${String(m).padStart(2, "0")}:${ss}`
}
</script>

<style scoped>
/* 音量滑块：accent-color 无 tw 等价（width/height/cursor 转 tw，仅 accent-color 保留 scoped） */
.sc-vol {
  accent-color: var(--theme-accent);
}
</style>
