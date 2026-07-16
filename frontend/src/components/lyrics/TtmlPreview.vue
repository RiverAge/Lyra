<template>
  <div ref="rootEl" class="ttml-preview">
    <!-- 头部：行数 + 预览/同步/原始 tab -->
    <div class="flex items-center justify-between border-b border-line-subtle px-3 py-2">
      <span class="text-xs text-tertiary">{{ lineCount }} 行</span>
      <div class="flex gap-0.5">
        <button
          class="rounded-sm border-none bg-transparent px-2.5 py-0.5 text-xs text-secondary transition-colors hover:bg-hover hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
          :class="{ 'bg-accent-subtle text-accent': mode === 'rendered' }"
          @click="mode = 'rendered'"
        >
          预览
        </button>
        <button
          class="rounded-sm border-none bg-transparent px-2.5 py-0.5 text-xs text-secondary transition-colors hover:bg-hover hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
          :class="{ 'bg-accent-subtle text-accent': mode === 'sync' }"
          :disabled="!hasTime"
          :title="hasTime ? '播放时歌词跟随高亮' : '该 TTML 无时间轴'"
          @click="mode = 'sync'"
        >
          同步
        </button>
        <button
          class="rounded-sm border-none bg-transparent px-2.5 py-0.5 text-xs text-secondary transition-colors hover:bg-hover hover:text-primary"
          :class="{ 'bg-accent-subtle text-accent': mode === 'raw' }"
          @click="mode = 'raw'"
        >
          原始
        </button>
      </div>
    </div>

    <!-- 无内容 -->
    <p v-if="!ttml" class="p-4 text-sm text-tertiary">
      无内容
    </p>

    <!-- 解析失败（预览/同步视图） -->
    <p v-else-if="sync.parseError.value && mode !== 'raw'" class="p-3 text-sm text-danger">
      解析失败：{{ sync.parseError.value }}<span class="ml-1 text-xs text-tertiary">（可切到「原始」查看源码）</span>
    </p>

    <!-- 预览视图：逐行纯文本（不高亮） -->
    <div v-else-if="mode === 'rendered'" class="tp-body">
      <p
        v-for="(line, idx) in sync.lines.value"
        :key="idx"
        class="whitespace-pre-wrap break-words rounded-sm px-2 py-0.5 text-sm leading-normal text-secondary"
      >
        {{ line.text }}
      </p>
      <p v-if="sync.lines.value.length === 0" class="p-4 text-sm text-tertiary">
        未提取到歌词行
      </p>
    </div>

    <!-- 同步视图：当前行高亮 + 自动滚动 -->
    <div v-else-if="mode === 'sync'" ref="syncBodyEl" class="tp-body">
      <p
        v-for="(line, idx) in sync.lines.value"
        :key="idx"
        :ref="(el) => setLineRef(el, idx)"
        class="tp-line"
        :class="{ 'tp-line-active': idx === sync.currentIndex.value }"
      >
        {{ line.text }}
      </p>
      <p v-if="sync.lines.value.length === 0" class="p-4 text-sm text-tertiary">
        未提取到歌词行
      </p>
      <p v-if="!hasTime && sync.lines.value.length > 0" class="p-4 text-sm text-tertiary">
        该 TTML 无时间轴，无法同步高亮。
      </p>
    </div>

    <!-- 原始视图：TTML 源码 -->
    <pre v-else class="tp-raw"><code>{{ ttml }}</code></pre>
  </div>
</template>

<script setup lang="ts">
/* global Element, HTMLElement */
import { useLyricSync } from "@/composables/useLyricSync"

/**
 * TTML 预览组件（预览/同步/原始三视图）
 *
 * - 预览：逐行纯文本（不高亮）
 * - 同步：当前行高亮 + 自动滚到视口中央（需传 currentTimeMs + TTML 有时间轴）
 * - 原始：TTML 源码（pre+code）
 *
 * 同步引擎复用 useLyricSync（parseTtml 读 begin/end）。
 * rendered/sync 共用 sync.lines（解析一次）。
 */
const props = defineProps<{
  ttml: string | null
  /** 预览区最大高度（MatchPanel 右栏主体传 480px） */
  maxHeight?: string
  /** 当前播放时间（毫秒），同步模式高亮驱动；不传则同步 tab 禁用 */
  currentTimeMs?: number
}>()

const mode = ref<"rendered" | "sync" | "raw">("rendered")
const rootEl = ref<HTMLElement | null>(null)
const syncBodyEl = ref<HTMLElement | null>(null)
const lineRefs = ref<(Element | null)[]>([])

function setLineRef(el: unknown, idx: number): void {
  lineRefs.value[idx] = (el as Element | null)
}

// currentTimeMs 可选，转成 Ref 喂给 useLyricSync
const currentTimeMsRef = computed(() => props.currentTimeMs ?? 0)
const ttmlRef = computed(() => props.ttml)

const sync = useLyricSync(currentTimeMsRef, ttmlRef)

const lineCount = computed(() => sync.lines.value.length)
/** TTML 是否含时间轴（任一行有 begin>0 或 end>0） */
const hasTime = computed(() =>
  sync.lines.value.some((l) => l.beginMs > 0 || l.endMs > 0),
)

// 切到 sync 时若该 ttml 无时间轴，回退 rendered
watch(hasTime, (ht) => {
  if (!ht && mode.value === "sync") mode.value = "rendered"
})

// 当前行变化 → 滚到视口中央
watch(
  () => sync.currentIndex.value,
  async (idx) => {
    if (idx < 0 || mode.value !== "sync") return
    await nextTick()
    const el = lineRefs.value[idx]
    if (el instanceof HTMLElement) {
      el.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  },
)
</script>

<style scoped>
/* v-bind(maxHeight) 注入 --tp-max-height（根元素内联 style），
   .tp-body/.tp-raw 用 var(--tp-max-height, 320px) 读它 */
.ttml-preview {
  border: 1px solid var(--theme-border-line-subtle, var(--theme-border-subtle));
  border-radius: var(--radius-md);
  background-color: var(--theme-bg-surface);
  --tp-max-height: v-bind(maxHeight ? maxHeight : "320px");
}

/* 预览/同步/原始主体：max-height 用 v-bind 变量 */
.tp-body {
  max-height: var(--tp-max-height, 320px);
  overflow: auto;
  padding: 8px 12px;
}
.tp-raw {
  max-height: var(--tp-max-height, 320px);
  overflow: auto;
  margin: 0;
  padding: 8px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--theme-text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

/* 同步模式歌词行基础 + 当前行高亮（inset box-shadow 色条，tw 无法表达） */
.tp-line {
  white-space: pre-wrap;
  word-break: break-word;
  padding: 2px 8px;
  margin: 1px 0;
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--theme-text-secondary);
  line-height: 1.5;
  transition: background-color var(--animate-duration-hover) ease, color var(--animate-duration-hover) ease;
}
.tp-line-active {
  background-color: var(--theme-accent-subtle);
  color: var(--theme-accent);
  font-weight: 500;
  box-shadow: inset 2px 0 0 var(--theme-accent);
}
</style>
