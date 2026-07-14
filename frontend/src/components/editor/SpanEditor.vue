<template>
  <section class="card p-4">
    <header class="mb-3 flex items-center justify-between gap-2">
      <h3 class="text-base font-medium text-primary">
        编辑面板
      </h3>
      <span v-if="selection" class="text-xs text-secondary">
        行 {{ selection.lineIndex + 1 }}
        <template v-if="selection.spanIndex !== null">
          · span {{ selection.spanIndex + 1 }}
        </template>
        <template v-else> · 行级</template>
      </span>
    </header>

    <!-- 未选中 -->
    <p v-if="!selection" class="py-4 text-center text-sm text-tertiary">
      点击时间轴上的 span 或行时间以编辑
    </p>

    <!-- 编辑表单 -->
    <div v-else class="flex flex-col gap-3">
      <!-- span 文本预览（仅 span 级） -->
      <div v-if="spanText" class="rounded-sm bg-subtle px-2 py-1 text-sm text-primary">
        {{ spanText }}
      </div>

      <!-- begin_ms -->
      <label class="flex items-center gap-2 text-sm text-secondary">
        <span class="w-20 shrink-0">begin_ms</span>
        <input
          v-model.number="beginInput"
          type="number"
          class="input-ring w-32 rounded-sm border border-subtle bg-surface px-2 py-1 font-mono text-sm text-primary"
        />
        <span class="font-mono text-xs text-tertiary">
          {{ formatTime(beginInput ?? 0) }}
        </span>
      </label>

      <!-- end_ms -->
      <label class="flex items-center gap-2 text-sm text-secondary">
        <span class="w-20 shrink-0">end_ms</span>
        <input
          v-model.number="endInput"
          type="number"
          class="input-ring w-32 rounded-sm border border-subtle bg-surface px-2 py-1 font-mono text-sm text-primary"
        />
        <span class="font-mono text-xs text-tertiary">
          {{ formatTime(endInput ?? 0) }}
        </span>
      </label>

      <!-- 写回按钮 -->
      <div class="flex items-center gap-2">
        <BaseButton
          variant="primary"
          size="sm"
          icon="Check"
          :disabled="store.patching || !canSubmit"
          @click="onSubmit"
        >
          {{ store.patching ? "写回中..." : "写回此项" }}
        </BaseButton>
        <span v-if="store.lastPatchOk" class="text-xs text-success">
          已写回
        </span>
      </div>

      <!-- 错误 -->
      <p v-if="store.patchError" class="text-xs text-danger">
        {{ store.patchError }}
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { formatTime } from "@/apis/editor"
import { useEditorStore } from "@/stores/editor"
import BaseButton from "@/components/ui/BaseButton.vue"

/**
 * Span 编辑面板
 *
 * 职责：
 * - 接收选中项（span/line 的索引与时间）→ 本地编辑 begin/end
 * - 「写回此项」→ store.patchSelection(trackId, {line_index, span_index, begin_ms, end_ms})
 * - 旁边显示 mm:ss.mmm 辅助
 *
 * 设计：
 * - beginInput/endInput 为本地 ref，selection 变化时同步
 *   （watch selection，把 selection.beginMs/endMs 拷进来）
 * - 写回成功后 store 会刷新 selection 的 begin/end，watch 再同步回 input
 *
 * 约束：
 * - auto-import 已注入 ref / computed / watch
 * - 走 store.patchSelection，不直接调 apis
 */

const props = defineProps<{ trackId: string }>()

const store = useEditorStore()

/** 当前选中项（从 store 取，便于 watch 同步）。 */
const selection = computed(() => store.selection)

/** 选中 span 的文本（span 级才有）。 */
const spanText = computed(() => {
  if (!store.selection || store.selection.spanIndex === null) return ""
  return store.selectedSpan?.text ?? ""
})

// 本地输入副本（毫秒整数）
const beginInput = ref<number | null>(null)
const endInput = ref<number | null>(null)

// selection 变化时同步本地输入
watch(
  () => store.selection,
  (sel) => {
    if (!sel) {
      beginInput.value = null
      endInput.value = null
      return
    }
    beginInput.value = sel.beginMs
    endInput.value = sel.endMs
  },
  { immediate: true },
)

/** 是否可提交：选中存在且 begin/end 均为有效数字且 end>begin。 */
const canSubmit = computed(() => {
  if (!selection.value) return false
  const b = beginInput.value
  const e = endInput.value
  if (b === null || e === null) return false
  if (!Number.isFinite(b) || !Number.isFinite(e)) return false
  return e > b
})

/** 写回此项。 */
async function onSubmit(): Promise<void> {
  if (!selection.value || !canSubmit.value) return
  await store.patchSelection(props.trackId, {
    line_index: selection.value.lineIndex,
    span_index: selection.value.spanIndex,
    begin_ms: Math.round(beginInput.value ?? 0),
    end_ms: Math.round(endInput.value ?? 0),
  })
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
