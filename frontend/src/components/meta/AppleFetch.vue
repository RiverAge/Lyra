<template>
  <section class="card p-4">
    <header class="mb-3 flex items-center justify-between">
      <h3 class="text-base font-semibold text-primary">
        Apple 元数据
      </h3>
      <span
        v-if="appleResult"
        class="rounded-sm bg-accent-subtle px-2 py-1 text-xs font-medium text-accent"
      >
        song_id: {{ appleResult.song_id }}
      </span>
    </header>

    <!-- 输入参数 -->
    <div class="mb-3 flex flex-wrap items-end gap-3">
      <label class="flex flex-col gap-1 text-sm text-secondary">
        <span>storefront</span>
        <input
          v-model="storefront"
          type="text"
          placeholder="us"
          class="w-24 rounded-md border border-default bg-base px-2 py-1.5 text-sm text-primary outline-none focus:border-accent"
          :disabled="appleLoading"
        >
      </label>
      <label class="flex flex-col gap-1 text-sm text-secondary">
        <span>lang</span>
        <input
          v-model="lang"
          type="text"
          placeholder="zh-Hans"
          class="w-32 rounded-md border border-default bg-base px-2 py-1.5 text-sm text-primary outline-none focus:border-accent"
          :disabled="appleLoading"
        >
      </label>
      <BaseButton
        variant="primary"
        :disabled="appleLoading || !trackId"
        @click="onFetch"
      >
        {{ appleLoading ? "拉取中…" : "拉取 Apple 元数据" }}
      </BaseButton>
    </div>

    <!-- 错误提示 -->
    <p
      v-if="appleError"
      class="mb-3 rounded-md border border-default bg-subtle px-3 py-2 text-sm text-danger"
    >
      {{ appleError }}
    </p>

    <!-- 结果表格 -->
    <div v-if="appleResult && rows.length > 0" class="overflow-x-auto">
      <table class="w-full border-collapse text-sm">
        <thead>
          <tr class="border-b border-default text-left text-secondary">
            <th class="py-2 pr-4 font-medium">字段</th>
            <th class="py-2 pr-4 font-medium">值</th>
            <th class="py-2 font-medium w-10 text-center">选择</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.field"
            class="border-b border-subtle align-top"
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
              <input
                v-model="selected"
                type="checkbox"
                :value="row.field"
                class="accent-accent"
              >
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p
      v-else-if="appleResult && rows.length === 0"
      class="text-sm text-tertiary"
    >
      Apple 返回空字段集（authoritative_fields 为空）。
    </p>

    <p v-else class="text-sm text-tertiary">
      点击「拉取 Apple 元数据」从 Apple WebAPI 获取权威字段。
    </p>
  </section>
</template>

<script setup lang="ts">
import { useMetaStore } from "@/stores/meta"
import BaseButton from "@/components/ui/BaseButton.vue"
import type { AuthoritativeFields } from "@/apis/meta"

const props = defineProps<{
  trackId: string
}>()

const emit = defineEmits<{
  /** 上抛当前勾选的权威字段（供 MetaTab 生成 diff） */
  (e: "fields-selected", payload: AuthoritativeFields): void
}>()

const store = useMetaStore()
const { appleLoading, appleError, appleResult } = storeToRefs(store)

const storefront = ref("us")
const lang = ref("zh-Hans")
const selected = ref<string[]>([])

const rows = computed(() => {
  const fields = appleResult.value?.authoritative_fields
  if (!fields) return []
  return Object.entries(fields).map(([field, values]) => ({
    field,
    values,
  }))
})

async function onFetch(): Promise<void> {
  selected.value = []
  emit("fields-selected", {})
  await store.loadApple(props.trackId, storefront.value, lang.value)
  // 拉取成功后默认全选，便于直接对比
  const fields = store.appleResult?.authoritative_fields
  if (fields) {
    selected.value = Object.keys(fields)
    emit("fields-selected", fields)
  }
}

// 勾选变化时上抛对应字段子集（仅含勾选项的完整值列表）
watch(
  selected,
  (next) => {
    const source = store.appleResult?.authoritative_fields
    if (!source) {
      emit("fields-selected", {})
      return
    }
    const out: AuthoritativeFields = {}
    for (const k of next) {
      const v = source[k]
      if (v) out[k] = v
    }
    emit("fields-selected", out)
  },
  { deep: true },
)

// 切换 track 时清空选择
watch(
  () => props.trackId,
  () => {
    selected.value = []
    emit("fields-selected", {})
  },
)
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
