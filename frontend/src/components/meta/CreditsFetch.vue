<template>
  <section class="rounded-md border border-default bg-surface p-4 shadow-sm">
    <header class="mb-3 flex items-center justify-between">
      <h3 class="text-base font-semibold text-primary">
        Credits 元数据
      </h3>
      <span
        v-if="creditsResult && !noCredits"
        class="rounded-sm bg-accent-subtle px-2 py-1 text-xs font-medium text-accent"
      >
        {{ creditsResult.track_id }}
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
          :disabled="creditsLoading"
        >
      </label>
      <button
        type="button"
        class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
        :disabled="creditsLoading || !trackId || noCredits"
        @click="onFetch"
      >
        {{ creditsLoading ? "拉取中…" : "拉取 Credits" }}
      </button>
    </div>

    <!-- 错误提示 -->
    <p
      v-if="creditsError"
      class="mb-3 rounded-md border border-default bg-bg-subtle px-3 py-2 text-sm text-danger"
    >
      {{ creditsError }}
    </p>

    <!-- 永久无 credits 哨兵：真实页但无 roleNames，不重试/fallback -->
    <div
      v-if="noCredits"
      class="mb-3 rounded-md border border-default bg-bg-subtle px-3 py-2"
    >
      <p class="text-sm font-medium text-warning">
        该曲目永久无 Credits 数据
      </p>
      <p class="mt-1 text-xs text-secondary">
        Credits 落地页有效但未检出角色信息，后端已标记为永久无数据，不会重试或 region fallback。
      </p>
    </div>

    <!-- 结果表格 -->
    <div v-else-if="creditsResult && rows.length > 0" class="overflow-x-auto">
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
      v-else-if="creditsResult && rows.length === 0"
      class="text-sm text-tertiary"
    >
      Credits 返回空字段集。
    </p>

    <p v-else class="text-sm text-tertiary">
      点击「拉取 Credits」从 Credits 网页抓取角色信息（经 role_map 映射到标签字段）。
    </p>
  </section>
</template>

<script setup lang="ts">
import { useMetaStore } from "@/stores/meta"
import type { AuthoritativeFields } from "@/apis/meta"

const props = defineProps<{
  trackId: string
}>()

const emit = defineEmits<{
  (e: "fields-selected", payload: AuthoritativeFields): void
}>()

const store = useMetaStore()
const { creditsLoading, creditsError, creditsResult } = storeToRefs(store)

const storefront = ref("us")
const selected = ref<string[]>([])

const noCredits = computed(() => creditsResult.value?.no_credits === true)

const rows = computed(() => {
  const fields = creditsResult.value?.authoritative_fields
  if (!fields) return []
  return Object.entries(fields).map(([field, values]) => ({
    field,
    values,
  }))
})

async function onFetch(): Promise<void> {
  selected.value = []
  emit("fields-selected", {})
  await store.loadCredits(props.trackId, storefront.value)
  // 拉取成功（非哨兵）后默认全选
  const fields = store.creditsResult?.authoritative_fields
  if (fields) {
    selected.value = Object.keys(fields)
    emit("fields-selected", fields)
  }
}

watch(
  selected,
  (next) => {
    const source = store.creditsResult?.authoritative_fields
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
