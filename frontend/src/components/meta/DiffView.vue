<template>
  <section class="card p-4">
    <header class="mb-3 flex items-center justify-between">
      <h3 class="text-base font-semibold text-primary">
        对比 & 写入
      </h3>
      <div class="flex items-center gap-2">
        <BaseButton
          variant="secondary"
          :disabled="diffLoading || !hasFields"
          @click="onCompute"
        >
          {{ diffLoading ? "对比中…" : "对比 before/after" }}
        </BaseButton>
        <BaseButton
          variant="primary"
          danger
          :disabled="!canWrite"
          @click="showConfirm = true"
        >
          写入标签
        </BaseButton>
      </div>
    </header>

    <!-- 错误/提示区 -->
    <p
      v-if="diffError"
      class="mb-3 rounded-md border border-default bg-bg-subtle px-3 py-2 text-sm text-danger"
    >
      {{ diffError }}
    </p>
    <p
      v-if="writeError"
      class="mb-3 rounded-md border border-default bg-bg-subtle px-3 py-2 text-sm text-danger"
    >
      {{ writeError }}
    </p>
    <div
      v-if="writeResult"
      class="mb-3 rounded-md border border-default bg-bg-subtle px-3 py-2"
    >
      <p class="text-sm font-medium text-success">
        写入成功：{{ writeResult.fields_written }} 个字段（{{ writeResult.format }}）
      </p>
      <p class="mt-1 text-xs text-secondary">
        track_id: {{ writeResult.track_id }} — 写操作不可逆，请回到库列表核对结果。
      </p>
    </div>

    <!-- 提示：未选择字段 -->
    <p
      v-if="!hasFields && !diffResult"
      class="text-sm text-tertiary"
    >
      先在上方 Apple / Credits 区勾选要写入的权威字段，再点「对比 before/after」生成差异。
    </p>

    <!-- diff 表 -->
    <div v-if="diffResult && diffRows.length > 0" class="overflow-x-auto">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="border-b border-default text-left text-secondary">
            <th class="py-2 pr-4 font-medium">字段</th>
            <th class="py-2 pr-4 font-medium">before</th>
            <th class="py-2 pr-4 font-medium">after</th>
            <th class="py-2 font-medium w-20 text-center">变更</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in diffRows"
            :key="row.field"
            class="border-b border-subtle align-top"
          >
            <td class="py-2 pr-4 font-mono text-xs text-primary">
              {{ row.field }}
            </td>
            <td class="py-2 pr-4 text-secondary">
              {{ formatValue(row.before) }}
            </td>
            <td class="py-2 pr-4 text-primary">
              {{ formatValue(row.after) }}
            </td>
            <td class="py-2 text-center">
              <span :class="kindClass(row.kind)">{{ kindLabel(row.kind) }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p
      v-else-if="diffResult && diffRows.length === 0"
      class="text-sm text-success"
    >
      无差异——所有选中字段已与当前标签一致。
    </p>

    <!-- 二次确认对话框（写操作不可逆 §7.2） -->
    <Teleport to="body">
      <div
        v-if="showConfirm"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        @click.self="showConfirm = false"
      >
        <div class="card max-w-md w-full p-5 shadow-md">
          <h4 class="mb-2 text-base font-semibold text-primary">
            确认写入标签？
          </h4>
          <p class="mb-4 text-sm text-secondary">
            写操作不可逆（无 Ctrl+Z，无自动备份）。将向 track
            <span class="font-mono text-primary">{{ trackId }}</span>
            写入 <span class="text-primary">{{ fieldCount }}</span> 个字段的权威值。
            请确认上方对比表无误后再继续。
          </p>
          <div
            v-if="writeError"
            class="mb-3 rounded-md border border-default bg-bg-subtle px-3 py-2 text-sm text-danger"
          >
            {{ writeError }}
          </div>
          <div class="flex justify-end gap-2">
            <BaseButton
              variant="secondary"
              :disabled="writeLoading"
              @click="showConfirm = false"
            >
              取消
            </BaseButton>
            <BaseButton
              variant="primary"
              danger
              :disabled="writeLoading"
              @click="onWrite"
            >
              {{ writeLoading ? "写入中…" : "确认写入" }}
            </BaseButton>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { useMetaStore } from "@/stores/meta"
import BaseButton from "@/components/ui/BaseButton.vue"
import type { AuthoritativeFields } from "@/apis/meta"

const props = defineProps<{
  trackId: string
  /** 当前选定的权威字段（来自 Apple/Credits 勾选，由 MetaTab 聚合后传入） */
  fields: AuthoritativeFields
}>()

const emit = defineEmits<{
  /** 写入成功，通知父组件刷新 diff 或清场 */
  (e: "written"): void
}>()

const store = useMetaStore()
const {
  diffLoading,
  diffError,
  diffResult,
  writeLoading,
  writeError,
  writeResult,
} = storeToRefs(store)

const showConfirm = ref(false)

const hasFields = computed(() => Object.keys(props.fields).length > 0)
const canWrite = computed(() => Boolean(diffResult.value) && hasFields.value)
const fieldCount = computed(() => Object.keys(props.fields).length)

interface DiffRow {
  field: string
  before: unknown
  after: unknown
  kind: "added" | "modified" | "removed" | "unchanged" | "unknown"
}

/**
 * 从 diffResult 派生对比表行。
 * 优先用后端 diffs 列表（含 kind），无 diffs 时从 before/after 键集并集推导。
 */
const diffRows = computed<DiffRow[]>(() => {
  const d = diffResult.value
  if (!d) return []
  const before = (d.before ?? {}) as Record<string, unknown>
  const after = (d.after ?? {}) as Record<string, unknown>

  if (Array.isArray(d.diffs) && d.diffs.length > 0) {
    return d.diffs.map((item) => {
      const field = String(item.field)
      return {
        field,
        before: item.before,
        after: item.after,
        kind: normalizeKind(item.kind, before[field], after[field]),
      }
    })
  }

  // fallback：并集推导
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]))
  return keys.map((field) => {
    const b = before[field]
    const a = after[field]
    return { field, before: b, after: a, kind: normalizeKind(undefined, b, a) }
  })
})

function normalizeKind(
  kind: unknown,
  before: unknown,
  after: unknown,
): DiffRow["kind"] {
  if (kind === "added" || kind === "modified" || kind === "removed" || kind === "unchanged") {
    return kind
  }
  if (before === undefined && after !== undefined) return "added"
  if (before !== undefined && after === undefined) return "removed"
  if (JSON.stringify(before) !== JSON.stringify(after)) return "modified"
  return "unchanged"
}

function formatValue(v: unknown): string {
  if (v === undefined || v === null) return "—"
  if (Array.isArray(v)) return v.length === 0 ? "[]" : v.join("; ")
  if (typeof v === "string") return v
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function kindLabel(kind: DiffRow["kind"]): string {
  switch (kind) {
    case "added":
      return "新增"
    case "modified":
      return "修改"
    case "removed":
      return "删除"
    case "unchanged":
      return "一致"
    default:
      return "—"
  }
}

function kindClass(kind: DiffRow["kind"]): string {
  switch (kind) {
    case "added":
      return "rounded-sm bg-accent-subtle px-1.5 py-0.5 text-xs font-medium text-success"
    case "modified":
      return "rounded-sm bg-accent-subtle px-1.5 py-0.5 text-xs font-medium text-accent"
    case "removed":
      return "rounded-sm bg-accent-subtle px-1.5 py-0.5 text-xs font-medium text-danger"
    case "unchanged":
      return "text-xs text-tertiary"
    default:
      return "text-xs text-tertiary"
  }
}

async function onCompute(): Promise<void> {
  await store.loadDiff(props.trackId, props.fields)
}

async function onWrite(): Promise<void> {
  const res = await store.doWrite(props.trackId, props.fields)
  if (res) {
    showConfirm.value = false
    emit("written")
    // 写入成功后刷新 diff，让 before 对齐新标签值
    await store.loadDiff(props.trackId, props.fields)
  }
}

// 切换 track 时关闭对话框、清场
watch(
  () => props.trackId,
  () => {
    showConfirm.value = false
  },
)
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
