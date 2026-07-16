<template>
  <div class="rounded-lg border border-line bg-surface p-3">
    <div class="mb-2 flex items-baseline justify-between gap-3">
      <span class="text-sm font-semibold text-primary">歌词同步预览</span>
      <span class="text-xs text-tertiary">边播边校对，编辑后实时反映新时间</span>
    </div>
    <!-- 播放控件（audioManager 单例） -->
    <SyncControls />
    <!-- 同步歌词：当前 span/行高亮 + 自动滚动 -->
    <div ref="bodyEl" class="mt-2.5 max-h-80 overflow-auto">
      <p
        v-for="(line, idx) in lines"
        :key="idx"
        :ref="(el) => setLineRef(el, idx)"
        class="whitespace-pre-wrap break-words rounded-sm px-2 py-0.5 my-0.5 text-[13px] leading-relaxed transition-colors"
        :class="lineClass(idx, line)"
      >
        <template v-if="line.spans.length > 0">
          <span
            v-for="(sp, si) in line.spans"
            :key="si"
            :class="isSpanActive(idx, si) ? 'font-bold text-accent' : 'text-secondary'"
          >{{ sp.text }}</span>
        </template>
        <template v-else>
          <span :class="idx === currentIndex ? 'text-primary' : 'text-secondary'">{{ line.text }}</span>
        </template>
      </p>
      <p v-if="lines.length === 0" class="p-4 text-sm text-tertiary">
        无歌词行
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
/* global Element, HTMLElement */
import { useAudioManager } from "@/lib/audioManager"
import { useEditorStore } from "@/stores/editor"
import SyncControls from "@/components/lyrics/SyncControls.vue"
import { findCurrentSpanIndex } from "@/composables/useLyricSync"
import type { LyricLine } from "@/composables/useLyricSync"

/**
 * SyncPreview — 编辑器整行歌词同步预览
 *
 * 订阅 editorStore.lines（LineModel[]，已有 begin_ms/end_ms + spans）构造 LyricLine[]，
 * 驱动源是 audioManager.currentTime×1000（听音校对，非 wavesurfer）。
 * 编辑 span 时间写回 → doc 更新 → lines 自动刷新 → 播放按新时间走。
 *
 * 逐字行：渲染 spans，当前 span 加粗+accent；纯文本行：整行高亮。
 * 不复用 useLyricSync（它接 ttml 字符串走 parseTtml），这里直接用 editorStore.lines
 * 构造 LyricLine[]，行内二分复用 findCurrentSpanIndex。
 */
const editor = useEditorStore()
const audio = useAudioManager()

/** editorStore.lines → LyricLine[]（保留 spans 逐字时间）。 */
const lines = computed<LyricLine[]>(() =>
  editor.lines.map((l) => ({
    text: l.text,
    beginMs: l.begin_ms,
    endMs: l.end_ms,
    spans: l.spans.map((s) => ({
      text: s.text,
      beginMs: s.begin_ms,
      endMs: s.end_ms,
    })),
  })),
)

const currentIndex = ref(-1)
const currentSpanIndex = ref(-1)
const currentTimeMs = computed(() => Math.round(audio.currentTime.value * 1000))

watch(lines, () => {
  currentIndex.value = -1
  currentSpanIndex.value = -1
})

watch(currentTimeMs, (t) => {
  const arr = lines.value
  if (arr.length === 0) return
  if (t < 0) {
    currentIndex.value = -1
    currentSpanIndex.value = -1
    return
  }
  // 行级二分：最后一个 beginMs <= t
  let lo = 0
  let hi = arr.length - 1
  let li = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (arr[mid].beginMs <= t) {
      li = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  if (li !== currentIndex.value) currentIndex.value = li
  // 行内 span 二分（复用 findCurrentSpanIndex，纯文本行返回 -1）
  const si = li >= 0 ? findCurrentSpanIndex(arr[li].spans, t) : -1
  if (si !== currentSpanIndex.value) currentSpanIndex.value = si
})

/** 行级 class：当前行 + 纯文本行 → 整行 inset-bar-active；当前行 + 逐字行 → 轻底色 */
function lineClass(idx: number, line: LyricLine): string {
  if (idx !== currentIndex.value) return ""
  return line.spans.length > 0 ? "bg-accent-subtle" : "inset-bar-active"
}

/** span 是否当前活跃 */
function isSpanActive(idx: number, si: number): boolean {
  return idx === currentIndex.value && si === currentSpanIndex.value
}

const bodyEl = ref<HTMLElement | null>(null)
const lineRefs = ref<(Element | null)[]>([])

function setLineRef(el: unknown, idx: number): void {
  lineRefs.value[idx] = (el as Element | null)
}

// 当前行变化 → 滚到视口中央
watch(currentIndex, async (idx) => {
  if (idx < 0) return
  await nextTick()
  const el = lineRefs.value[idx]
  if (el instanceof HTMLElement) {
    el.scrollIntoView({ behavior: "smooth", block: "center" })
  }
})
</script>

<style scoped>
/* 全部通过 Tailwind token 类名 + 全局 .inset-bar-active 控制 */
</style>
