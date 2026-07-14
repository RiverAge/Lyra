<template>
  <div class="flex flex-col gap-4">
    <header class="card p-4">
      <h2 class="text-lg font-semibold text-primary">
        元数据
      </h2>
      <p class="mt-1 text-sm text-secondary">
        从 Apple WebAPI / Credits 拉取权威元数据，对比 before/after 后二次确认写入音频标签。
      </p>
      <p class="mt-1 text-xs text-tertiary">
        track_id:
        <span class="font-mono text-secondary">{{ trackId }}</span>
        · 已选字段：
        <span class="font-mono text-secondary">{{ selectedFieldCount }}</span>
      </p>
    </header>

    <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
      <AppleFetch
        :track-id="trackId"
        @fields-selected="onAppleSelected"
      />
      <CreditsFetch
        :track-id="trackId"
        @fields-selected="onCreditsSelected"
      />
    </div>

    <DiffView
      :track-id="trackId"
      :fields="mergedFields"
      @written="onWritten"
    />
  </div>
</template>

<script setup lang="ts">
import AppleFetch from "@/components/meta/AppleFetch.vue"
import CreditsFetch from "@/components/meta/CreditsFetch.vue"
import DiffView from "@/components/meta/DiffView.vue"
import { useMetaStore } from "@/stores/meta"
import type { AuthoritativeFields } from "@/apis/meta"

const props = defineProps<{
  trackId: string
}>()

const store = useMetaStore()

// Apple / Credits 各自勾选的字段子集
const appleSelected = ref<AuthoritativeFields>({})
const creditsSelected = ref<AuthoritativeFields>({})

/**
 * 合并策略：同字段 Credits 值覆盖 Apple 值（Credits 网页角色信息更细，
 * 是 Apple WebAPI ©wrt 的扩展来源）。两者均未选则不写入。
 */
const mergedFields = computed<AuthoritativeFields>(() => ({
  ...appleSelected.value,
  ...creditsSelected.value,
}))

const selectedFieldCount = computed(() => Object.keys(mergedFields.value).length)

function onAppleSelected(fields: AuthoritativeFields): void {
  appleSelected.value = fields
}

function onCreditsSelected(fields: AuthoritativeFields): void {
  creditsSelected.value = fields
}

function onWritten(): void {
  // 写入成功：清空选择，子组件结果展示仍在（用户可重新勾选对比）
  appleSelected.value = {}
  creditsSelected.value = {}
}

// 切换 track 时重置 store 会话状态 + 本地选择
watch(
  () => props.trackId,
  (next, prev) => {
    if (next !== prev) {
      store.reset("all")
      appleSelected.value = {}
      creditsSelected.value = {}
    }
  },
)
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
