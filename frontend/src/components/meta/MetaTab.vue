<template>
  <div class="flex flex-col gap-4">
    <header class="card p-4">
      <h2 class="text-lg font-semibold text-primary">
        元数据
      </h2>
      <p class="mt-1 text-sm text-secondary">
        拉取权威元数据，对比后确认写入音频标签。
      </p>
      <p class="mt-1 text-xs text-tertiary">
        track_id:
        <span class="font-mono text-secondary">{{ trackId }}</span>
        · 已选字段：
        <span class="font-mono text-secondary">{{ selectedFieldCount }}</span>
      </p>
    </header>

    <!-- 统一拉取区 -->
    <section class="card p-4">
      <header class="mb-3 flex items-center justify-between">
        <h3 class="text-base font-semibold text-primary">
          拉取元数据
        </h3>
        <span
          v-if="fetchAllPhase === 'done'"
          class="rounded-sm bg-accent-subtle px-2 py-1 text-xs font-medium text-success"
        >
          拉取完成
        </span>
      </header>

      <!-- 输入参数 + 拉取按钮 -->
      <div class="mb-3 flex flex-wrap items-end gap-3">
        <label class="flex flex-col gap-1 text-sm text-secondary">
          <span>storefront</span>
          <input
            v-model="storefront"
            type="text"
            placeholder="us"
            class="w-24 rounded-md border border-default bg-base px-2 py-1.5 text-sm text-primary outline-none focus:border-accent"
            :disabled="fetchAllLoading"
          >
        </label>
        <label class="flex flex-col gap-1 text-sm text-secondary">
          <span>lang</span>
          <input
            v-model="lang"
            type="text"
            placeholder="zh-Hans"
            class="w-32 rounded-md border border-default bg-base px-2 py-1.5 text-sm text-primary outline-none focus:border-accent"
            :disabled="fetchAllLoading"
          >
        </label>
        <BaseButton
          variant="primary"
          :disabled="fetchAllLoading || !trackId"
          @click="onFetchAll"
        >
          {{ fetchAllLoading ? fetchPhaseLabel : "拉取元数据" }}
        </BaseButton>
      </div>

      <!-- 来源级状态提示 -->
      <div class="flex flex-col gap-2">
        <!-- Apple 失败 -->
        <div
          v-if="appleSourceStatus === 'failed_retryable'"
          class="flex items-center gap-2 rounded-md border border-default bg-bg-subtle px-3 py-2"
        >
          <p class="text-sm text-danger">
            结构化信息拉取失败，可重试
          </p>
          <BaseButton
            variant="ghost"
            size="sm"
            :disabled="fetchAllLoading"
            @click="onRetrySource('apple')"
          >
            重试
          </BaseButton>
        </div>
        <!-- Credits 永久无 -->
        <div
          v-if="creditsSourceStatus === 'missing_permanent'"
          class="rounded-md border border-default bg-bg-subtle px-3 py-2"
        >
          <p class="text-sm text-tertiary">
            该曲目暂无制作人员信息
          </p>
        </div>
        <!-- Credits 失败 -->
        <div
          v-if="creditsSourceStatus === 'failed_retryable'"
          class="flex items-center gap-2 rounded-md border border-default bg-bg-subtle px-3 py-2"
        >
          <p class="text-sm text-danger">
            制作人员信息拉取失败，可重试
          </p>
          <BaseButton
            variant="ghost"
            size="sm"
            :disabled="fetchAllLoading"
            @click="onRetrySource('credits')"
          >
            重试
          </BaseButton>
        </div>
      </div>
    </section>

    <!-- 合并字段表 -->
    <section v-if="fieldRows.length > 0" class="card p-4">
      <header class="mb-3">
        <h3 class="text-base font-semibold text-primary">
          字段选择
        </h3>
        <p class="mt-1 text-xs text-tertiary">
          勾选要写入的权威字段，变更选择后需重新对比。
        </p>
      </header>
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-sm">
          <thead>
            <tr class="border-b border-default text-left text-secondary">
              <th class="py-2 pr-4 font-medium">
                字段
              </th>
              <th class="py-2 pr-4 font-medium">
                值
              </th>
              <th class="py-2 pr-4 font-medium w-16 text-center">
                来源
              </th>
              <th class="py-2 pr-4 font-medium w-16 text-center">
                状态
              </th>
              <th class="py-2 font-medium w-10 text-center">
                选择
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in fieldRows"
              :key="row.field"
              class="border-b border-subtle align-top"
              :class="row.status !== 'ok' ? 'opacity-50' : ''"
            >
              <td class="py-2 pr-4 font-mono text-xs text-primary">
                {{ row.field }}
              </td>
              <td class="py-2 pr-4 text-primary">
                <ul class="flex flex-col gap-0.5">
                  <li
                    v-for="(v, i) in row.values"
                    :key="`${row.field}-${i}`"
                    class="break-all"
                  >
                    {{ v }}
                  </li>
                </ul>
              </td>
              <td class="py-2 text-center">
                <span
                  class="rounded-sm px-1.5 py-0.5 text-xs font-medium"
                  :class="row.source === 'apple' ? 'bg-accent-subtle text-accent' : 'bg-bg-subtle text-secondary'"
                >
                  {{ row.source === "apple" ? "官方信息" : "制作人员" }}
                </span>
              </td>
              <td class="py-2 text-center">
                <span
                  v-if="row.status === 'missing_permanent'"
                  class="rounded-sm bg-bg-subtle px-1.5 py-0.5 text-xs font-medium text-tertiary"
                >
                  暂无
                </span>
                <span
                  v-else-if="row.status === 'failed_retryable'"
                  class="rounded-sm bg-bg-subtle px-1.5 py-0.5 text-xs font-medium text-danger"
                >
                  失败
                </span>
              </td>
              <td class="py-2 text-center">
                <input
                  v-model="selected"
                  type="checkbox"
                  :value="row.field"
                  :disabled="row.status !== 'ok'"
                  class="accent-accent"
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <DiffView
      :track-id="trackId"
      :fields="mergedFields"
      @written="onWritten"
    />
  </div>
</template>

<script setup lang="ts">
import DiffView from "@/components/meta/DiffView.vue"
import BaseButton from "@/components/ui/BaseButton.vue"
import { useMetaStore } from "@/stores/meta"
import type { AuthoritativeFields, FieldWithStatus } from "@/apis/meta"

const props = defineProps<{
  trackId: string
}>()

const store = useMetaStore()
const {
  fetchAllLoading,
  fetchAllPhase,
  appleSourceStatus,
  creditsSourceStatus,
  fieldStatusMap,
} = storeToRefs(store)

const storefront = ref("us")
const lang = ref("zh-Hans")
const selected = ref<string[]>([])

/** 合并字段表行（从 fieldStatusMap 派生，按字段名排序） */
const fieldRows = computed<FieldWithStatus[]>(() =>
  Object.values(fieldStatusMap.value).sort((a, b) =>
    a.field.localeCompare(b.field),
  ),
)

/** 当前勾选的权威字段（仅含 ok 状态的选中项） */
const mergedFields = computed<AuthoritativeFields>(() => {
  const out: AuthoritativeFields = {}
  for (const k of selected.value) {
    const entry = fieldStatusMap.value[k]
    if (entry && entry.status === "ok") {
      out[k] = entry.values
    }
  }
  return out
})

const selectedFieldCount = computed(() => Object.keys(mergedFields.value).length)

/** 拉取阶段文案（不暴露技术词） */
const fetchPhaseLabel = computed(() => {
  switch (fetchAllPhase.value) {
    case "apple":
      return "正在拉取结构化信息…"
    case "credits":
      return "正在拉取制作人员信息…"
    default:
      return "拉取中…"
  }
})

async function onFetchAll(): Promise<void> {
  selected.value = []
  store.clearDiff()
  await store.fetchAllMeta(props.trackId, storefront.value, lang.value)
  // 拉取完成后默认全选 ok 状态字段
  const okFields = Object.values(fieldStatusMap.value)
    .filter((f) => f.status === "ok")
    .map((f) => f.field)
  selected.value = okFields
}

async function onRetrySource(source: "apple" | "credits"): Promise<void> {
  await store.retrySource(props.trackId, source, storefront.value, lang.value)
  // 重试成功后补充新 ok 字段到选中列表
  const okFields = Object.values(fieldStatusMap.value)
    .filter((f) => f.status === "ok")
    .map((f) => f.field)
  const newSelected = new Set(selected.value)
  for (const f of okFields) {
    newSelected.add(f)
  }
  selected.value = [...newSelected]
}

function onWritten(): void {
  // 写入成功：清空选择，字段表仍在（用户可重新勾选对比）
  selected.value = []
}

// 勾选变化时立即清空 diffResult（P0 修复：防止旧 diff 与新勾选不一致）
watch(
  selected,
  () => {
    store.clearDiff()
  },
  { deep: true },
)

// 切换 track 时重置 store 会话状态 + 本地选择
watch(
  () => props.trackId,
  (next, prev) => {
    if (next !== prev) {
      store.reset("all")
      selected.value = []
    }
  },
)
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
