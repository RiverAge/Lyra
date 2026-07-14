<template>
  <section class="card p-4">
    <header class="mb-3 flex items-center justify-between gap-2">
      <h3 class="text-base font-medium text-primary">
        波形
      </h3>
      <div class="flex items-center gap-2">
        <BaseButton
          variant="primary"
          size="sm"
          :disabled="!ready && !decodeFailed"
          @click="onPlayPause"
        >
          {{ playing ? "暂停" : ready ? "播放" : "加载中" }}
        </BaseButton>
        <span class="font-mono text-xs text-secondary">
          {{ currentTimeLabel }}
        </span>
      </div>
    </header>

    <!-- 波形容器：onMounted 后 wavesurfer 挂载到这里 -->
    <div ref="waveformRef" class="w-full" />

    <!-- 加载中 -->
    <p v-if="!ready && !decodeFailed" class="mt-2 text-xs text-tertiary">
      正在解码音频…
    </p>

    <!-- 解码失败降级 -->
    <p v-if="decodeFailed" class="mt-2 text-xs text-warning">
      音频解码失败，仍可文本编辑。
    </p>
  </section>
</template>

<script setup lang="ts">
import WaveSurfer from "wavesurfer.js"
import { formatTime } from "@/apis/editor"
import BaseButton from "@/components/ui/BaseButton.vue"

/**
 * 波形组件（wavesurfer.js）
 *
 * 职责：
 * - onMounted 创建 wavesurfer，加载 /api/play/{trackId}
 * - emit ready / timeupdate / seek
 * - 暴露 play / pause / seek 方法（defineExpose）
 *
 * 设计：
 * - ws 用 shallowRef 持有（wavesurfer 实例非响应式代理友好）
 * - 颜色从 tokens.css 取（--color-border-default / --color-accent），
 *   取不到则回退硬编码（仅作为最终兜底，不破坏主题）
 * - ready 不触发即视为解码失败 → decodeFailed=true，UI 降级提示
 * - onUnmounted 必须 destroy + 置空，避免重复挂载与内存泄漏
 *
 * 约束：
 * - auto-import 已注入 ref / shallowRef / onMounted / onUnmounted / computed
 * - wavesurfer.js 是第三方库，显式 import（不在 auto-import 内）
 */

/* global HTMLElement, getComputedStyle */

const props = defineProps<{ trackId: string }>()

const emit = defineEmits<{
  (e: "ready", ok: boolean): void
  (e: "timeupdate", currentTimeMs: number): void
  (e: "seek", timeMs: number): void
}>()

const ws = shallowRef<WaveSurfer | null>(null)
const waveformRef = ref<HTMLElement | null>(null)

const ready = ref(false)
const decodeFailed = ref(false)
const playing = ref(false)
const currentTimeMs = ref(0)

/** 当前时间显示（mm:ss.mmm）。 */
const currentTimeLabel = computed(() => formatTime(currentTimeMs.value))

onMounted(() => {
  if (!waveformRef.value) return
  const style = getComputedStyle(document.documentElement)
  ws.value = WaveSurfer.create({
    container: waveformRef.value,
    waveColor: style.getPropertyValue("--color-border-default").trim() || "#999",
    progressColor: style.getPropertyValue("--color-accent").trim() || "#5b8def",
    url: `/api/play/${props.trackId}`,
    height: 80,
  })

  ws.value.on("ready", () => {
    ready.value = true
    emit("ready", true)
  })
  ws.value.on("play", () => {
    playing.value = true
  })
  ws.value.on("pause", () => {
    playing.value = false
  })
  ws.value.on("audioprocess", (time: number) => {
    currentTimeMs.value = Math.round(time * 1000)
    emit("timeupdate", currentTimeMs.value)
  })
  // timeupdate 在非播放（拖拽）时也触发，补一份
  ws.value.on("timeupdate", (time: number) => {
    currentTimeMs.value = Math.round(time * 1000)
    emit("timeupdate", currentTimeMs.value)
  })
  ws.value.on("interaction", (newTime: number) => {
    currentTimeMs.value = Math.round(newTime * 1000)
    emit("seek", currentTimeMs.value)
  })
  ws.value.on("error", () => {
    decodeFailed.value = true
    emit("ready", false)
  })
})

onUnmounted(() => {
  ws.value?.destroy()
  ws.value = null
})

/** 播放/暂停切换。 */
function onPlayPause(): void {
  ws.value?.playPause()
}

/** 播放。 */
function play(): void {
  void ws.value?.play()
}

/** 暂停。 */
function pause(): void {
  ws.value?.pause()
}

/**
 * 跳转到指定毫秒位置。
 * wavesurfer 内部以秒为单位，故除以 1000。
 */
function seek(timeMs: number): void {
  const dur = ws.value?.getDuration() ?? 0
  if (!dur) return
  const progress = timeMs / 1000 / dur
  if (progress < 0) return
  if (progress > 1) return
  ws.value?.seekTo(progress)
  currentTimeMs.value = timeMs
}

defineExpose({ play, pause, seek })
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
