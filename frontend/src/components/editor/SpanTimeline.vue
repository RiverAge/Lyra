<template>
  <section class="rounded-md border border-default bg-surface p-4 shadow-sm">
    <header class="mb-3 flex items-center justify-between gap-2">
      <h3 class="text-base font-medium text-primary">
        Span 时间轴
      </h3>
      <span class="text-xs text-tertiary">
        共 {{ lines.length }} 行 · 当前 {{ currentTimeLabel }}
      </span>
    </header>

    <!-- 空状态 -->
    <p v-if="lines.length === 0" class="py-4 text-center text-sm text-tertiary">
      无歌词数据
    </p>

    <!-- 行列表 -->
    <ul v-else class="flex flex-col gap-2">
      <li
        v-for="(line, li) in lines"
        :key="line.key || li"
        :class="isLineCurrent(li) ? 'border-accent bg-accent-subtle' : 'border-subtle bg-subtle'"
        class="rounded-md border p-2"
      >
        <!-- 行头：行号 + key + begin/end -->
        <div class="flex items-center gap-2">
          <span class="font-mono text-xs text-tertiary">
            {{ String(li + 1).padStart(2, "0") }}
          </span>
          <span class="rounded-sm bg-bg-base px-1.5 py-0.5 font-mono text-xs text-secondary">
            {{ line.key || "—" }}
          </span>
          <button
            class="font-mono text-xs text-secondary transition-colors hover:text-primary"
            :title="`行 begin: ${formatTime(line.begin_ms)}`"
            @click="onSelectLine(li, 'begin')"
          >
            {{ formatTime(line.begin_ms) }}
          </button>
          <span class="text-tertiary">→</span>
          <button
            class="font-mono text-xs text-secondary transition-colors hover:text-primary"
            :title="`行 end: ${formatTime(line.end_ms)}`"
            @click="onSelectLine(li, 'end')"
          >
            {{ formatTime(line.end_ms) }}
          </button>
        </div>

        <!-- spans：逐字行 -->
        <div v-if="line.spans.length > 0" class="mt-2 flex flex-wrap gap-1">
          <button
            v-for="(span, si) in line.spans"
            :key="si"
            :class="isSpanCurrent(li, si) ? 'bg-accent text-white' : 'bg-bg-base text-primary hover:bg-hover'"
            class="rounded-sm px-1.5 py-0.5 text-sm transition-colors"
            :title="`${span.text}  ${formatTime(span.begin_ms)}→${formatTime(span.end_ms)}`"
            @click="onSelectSpan(li, si, span)"
          >
            {{ span.text }}
          </button>
        </div>

        <!-- 纯文本行：展示 text -->
        <p v-else class="mt-1 text-sm text-primary">
          {{ line.text || "（空文本行）" }}
        </p>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import type { LineModel, SpanModel } from "@/apis/editor"
import { formatTime } from "@/apis/editor"

/**
 * Span 时间轴
 *
 * 职责：
 * - 展示每行：行号 + key + begin/end（mm:ss.mmm）+ span 列表
 * - 当前播放 span 高亮（currentTimeMs 落在 span [begin_ms, end_ms]）
 * - 点击 span → emit('select', {lineIndex, spanIndex, span})
 * - 行级 begin/end 可点击 → emit('select', {lineIndex, spanIndex: null, ...})
 *
 * 约束：
 * - auto-import 已注入 computed
 * - 不直接调 store/apis，只靠 props/emit 与父组件通信
 */

const props = defineProps<{
  lines: LineModel[]
  currentTimeMs: number
}>()

const emit = defineEmits<{
  (e: "select", payload: {
    lineIndex: number
    spanIndex: number | null
    span: SpanModel | null
    line: LineModel
  }): void
}>()

/** 当前时间显示。 */
const currentTimeLabel = computed(() => formatTime(props.currentTimeMs))

/** 当前播放行：currentTimeMs 落在 [line.begin_ms, line.end_ms)。 */
function isLineCurrent(li: number): boolean {
  const line = props.lines[li]
  if (!line) return false
  return (
    props.currentTimeMs >= line.begin_ms && props.currentTimeMs < line.end_ms
  )
}

/** 当前播放 span：currentTimeMs 落在 span [begin_ms, end_ms)。 */
function isSpanCurrent(li: number, si: number): boolean {
  const line = props.lines[li]
  if (!line) return false
  const span = line.spans[si]
  if (!span) return false
  return (
    props.currentTimeMs >= span.begin_ms && props.currentTimeMs < span.end_ms
  )
}

/** 点击 span。 */
function onSelectSpan(li: number, si: number, span: SpanModel): void {
  const line = props.lines[li]
  if (!line) return
  emit("select", { lineIndex: li, spanIndex: si, span, line })
}

/** 点击行的 begin/end（spanIndex=null 表示选行级时间）。 */
function onSelectLine(li: number, _field: "begin" | "end"): void {
  const line = props.lines[li]
  if (!line) return
  emit("select", { lineIndex: li, spanIndex: null, span: null, line })
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
