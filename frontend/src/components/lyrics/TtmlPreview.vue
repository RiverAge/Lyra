<template>
  <div ref="rootEl" class="ttml-preview rounded-md border border-line-subtle bg-surface">
    <!-- 头部：行数 + 逐字/逐行 + 注音/翻译标记 -->
    <div class="flex items-center justify-between gap-2 border-b border-line-subtle px-3 py-2">
      <span class="text-xs text-tertiary">{{ lineCount }} 行</span>
      <div v-if="sync.lines.value.length > 0" class="flex items-center gap-1">
        <span
          class="inline-flex items-center rounded-sm px-1.5 py-0.5 text-[11px] font-medium"
          :class="isCharLevel ? 'bg-accent-subtle text-accent' : 'bg-subtle text-tertiary'"
        >{{ isCharLevel ? "逐字" : "逐行" }}</span>
        <span
          v-if="hasTransliteration"
          class="inline-flex items-center rounded-sm bg-subtle px-1.5 py-0.5 text-[11px] font-medium text-tertiary"
        >注音</span>
        <span
          v-if="hasTranslation"
          class="inline-flex items-center rounded-sm bg-subtle px-1.5 py-0.5 text-[11px] font-medium text-tertiary"
        >翻译</span>
      </div>
    </div>

    <!-- 无内容 -->
    <p v-if="!ttml" class="p-4 text-sm text-tertiary">
      无内容
    </p>

    <!-- 解析失败 -->
    <p v-else-if="sync.parseError.value" class="p-3 text-sm text-danger">
      解析失败：{{ sync.parseError.value }}
    </p>

    <!-- 逐字歌词体 -->
    <div v-else ref="bodyEl" class="max-h-[var(--tp-max-height,320px)] overflow-auto px-3 py-2">
      <div
        v-for="(line, idx) in sync.lines.value"
        :key="idx"
        :ref="(el) => setLineRef(el, idx)"
        class="my-0.5 rounded-sm px-2 py-0.5 transition-colors"
        :class="lineClass(idx, line)"
      >
        <!-- 主歌词 -->
        <p class="whitespace-pre-wrap break-words text-[13px] leading-relaxed">
          <template v-if="line.spans.length > 0">
            <span
              v-for="(sp, si) in line.spans"
              :key="si"
              :class="isSpanActive(idx, si) ? 'font-bold text-accent' : 'text-secondary'"
            >{{ sp.text }}</span>
          </template>
          <template v-else>
            <span :class="idx === sync.currentIndex.value ? 'text-primary' : 'text-secondary'">{{ line.text }}</span>
          </template>
        </p>
        <!-- 注音行（逐字罗马音逐字高亮 / 逐行注音整行） -->
        <p
          v-if="line.transliteration && line.transliteration.length > 0"
          class="whitespace-pre-wrap break-words text-[11px] leading-snug"
        >
          <template v-if="line.transliteration.length > 1">
            <span
              v-for="(sp, si) in line.transliteration"
              :key="si"
              :class="isRomaSpanActive(idx, si) ? 'font-medium text-accent' : 'text-tertiary'"
            >{{ sp.text }}</span>
          </template>
          <template v-else>
            <span :class="idx === sync.currentIndex.value ? 'text-secondary' : 'text-tertiary'">{{ line.transliteration[0].text }}</span>
          </template>
        </p>
        <!-- 翻译行（逐字翻译逐字高亮 / 逐行翻译整行小字） -->
        <p
          v-if="line.translation"
          class="whitespace-pre-wrap break-words text-[11px] leading-snug"
        >
          <template v-if="Array.isArray(line.translation) && line.translation.length > 1">
            <span
              v-for="(sp, si) in line.translation"
              :key="si"
              :class="isTransSpanActive(idx, si) ? 'font-medium text-accent' : 'text-tertiary'"
            >{{ sp.text }}</span>
          </template>
          <template v-else>
            <span :class="idx === sync.currentIndex.value ? 'text-secondary' : 'text-tertiary'">{{
              Array.isArray(line.translation) ? line.translation[0]?.text : line.translation
            }}</span>
          </template>
        </p>
      </div>
      <p v-if="sync.lines.value.length === 0" class="p-4 text-sm text-tertiary">
        未提取到歌词行
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
/* global Element, HTMLElement */
import { useLyricSync } from "@/composables/useLyricSync"
import type { LyricLine } from "@/composables/useLyricSync"

/**
 * TTML 预览组件（单一逐字同步视图 + 注音/翻译行）
 *
 * 直接展示同步歌词，无 tab 切换：
 * - 主歌词：逐字行渲染 spans（当前 span 加粗+accent），纯文本行整行高亮
 * - 注音行：逐字罗马音（QQ）渲染 spans 当前音节加粗 accent；逐行注音（netease）整行
 * - 翻译行：整行小字，当前行高亮
 * - 当前行变化 → 自动滚到视口中央
 *
 * 同步引擎复用 useLyricSync（parseTtml 读多 div track：main + translation + transliteration）。
 */
const props = defineProps<{
  ttml: string | null
  /** 预览区最大高度（MatchPanel 右栏主体传 480px） */
  maxHeight?: string
  /** 当前播放时间（毫秒），同步高亮驱动；不传则不高亮 */
  currentTimeMs?: number
}>()

const rootEl = ref<HTMLElement | null>(null)
const bodyEl = ref<HTMLElement | null>(null)
const lineRefs = ref<(Element | null)[]>([])

function setLineRef(el: unknown, idx: number): void {
  lineRefs.value[idx] = (el as Element | null)
}

// currentTimeMs 可选，转成 Ref 喂给 useLyricSync
const currentTimeMsRef = computed(() => props.currentTimeMs ?? 0)
const ttmlRef = computed(() => props.ttml)

const sync = useLyricSync(currentTimeMsRef, ttmlRef)

const lineCount = computed(() => sync.lines.value.length)

/** 是否含逐字时间轴（任一行有 spans） */
const isCharLevel = computed(() =>
  sync.lines.value.some((l) => l.spans.length > 0),
)

/** 是否有注音行（任一行 transliteration 非空） */
const hasTransliteration = computed(() =>
  sync.lines.value.some((l) => l.transliteration && l.transliteration.length > 0),
)

/** 是否有翻译行（任一行 translation 非空：string 非空 或 spans 非空） */
const hasTranslation = computed(() =>
  sync.lines.value.some((l) => {
    if (!l.translation) return false
    return typeof l.translation === "string" ? !!l.translation : l.translation.length > 0
  }),
)

/** 行级 class：当前行 + 纯文本行 → 整行 inset-bar-active；当前行 + 逐字行 → 轻底色；非当前 → 无 */
function lineClass(idx: number, line: LyricLine): string {
  if (idx !== sync.currentIndex.value) return ""
  // 当前行：逐字行轻底色（不抢 span 高亮），纯文本行整行色条高亮
  return line.spans.length > 0 ? "bg-accent-subtle" : "inset-bar-active"
}

/** 主歌词 span 是否当前活跃：行匹配 + span 匹配 */
function isSpanActive(idx: number, si: number): boolean {
  return idx === sync.currentIndex.value && si === sync.currentSpanIndex.value
}

/** 注音 span 是否当前活跃：行匹配 + 注音 span 匹配 */
function isRomaSpanActive(idx: number, si: number): boolean {
  return idx === sync.currentIndex.value && si === sync.currentTransliterationSpanIndex.value
}

/** 翻译 span 是否当前活跃：行匹配 + 翻译 span 匹配 */
function isTransSpanActive(idx: number, si: number): boolean {
  return idx === sync.currentIndex.value && si === sync.currentTranslationSpanIndex.value
}

// 当前行变化 → 滚到视口中央
watch(
  () => sync.currentIndex.value,
  async (idx) => {
    if (idx < 0) return
    await nextTick()
    const el = lineRefs.value[idx]
    if (el instanceof HTMLElement) {
      el.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  },
)
</script>

<style scoped>
/* v-bind(maxHeight) 注入 --tp-max-height，根元素内联 style，
   .tp-body/.tp-raw 的 tw 任意值 max-h-[var(--tp-max-height,320px)] 读它 */
.ttml-preview {
  --tp-max-height: v-bind(maxHeight ? maxHeight : "320px");
}
</style>
