<template>
  <div class="card overflow-hidden">
    <!-- 表头 -->
    <div class="border-b border-default bg-subtle">
      <table class="w-full table-fixed">
        <colgroup>
          <col class="w-[4%]">
          <col class="w-[30%]">
          <col class="w-[22%]">
          <col class="w-[22%]">
          <col class="w-[10%]">
          <col class="w-[8%]">
          <col class="w-[4%]">
        </colgroup>
        <thead>
          <tr class="text-xs font-medium text-tertiary uppercase">
            <th class="px-3 py-2" />
            <th class="px-3 py-2 text-left">
              标题
            </th>
            <th class="px-3 py-2 text-left">
              艺人
            </th>
            <th class="px-3 py-2 text-left">
              专辑
            </th>
            <th class="px-3 py-2 text-right">
              时长
            </th>
            <th class="px-3 py-2 text-right">
              格式
            </th>
            <th class="px-3 py-2" />
          </tr>
        </thead>
      </table>
    </div>

    <!-- 加载态：骨架行 -->
    <div v-if="loading" class="divide-y divide-subtle">
      <div
        v-for="i in skeletonRows"
        :key="i"
        class="flex items-center px-3 py-2.5"
      >
        <div class="mr-3 h-8 w-8 animate-pulse rounded-sm bg-hover" />
        <div class="h-3 flex-1 animate-pulse rounded-sm bg-hover" />
        <div class="ml-3 h-3 w-20 animate-pulse rounded-sm bg-hover" />
      </div>
    </div>

    <!-- 空态 -->
    <div v-else-if="empty" class="flex flex-col items-center justify-center px-6 py-16 text-center">
      <p class="mb-1 text-sm font-medium text-primary">
        曲库为空
      </p>
      <p class="text-xs text-secondary">
        请先扫描音乐库根目录
      </p>
    </div>

    <!-- 错误态 -->
    <div v-else-if="error" class="flex flex-col items-center justify-center px-6 py-16 text-center">
      <p class="mb-1 text-sm font-medium text-danger">
        加载失败
      </p>
      <p class="mb-3 text-xs text-secondary">
        {{ error }}
      </p>
      <BaseButton variant="secondary" size="sm" @click="$emit('retry')">
        重试
      </BaseButton>
    </div>

    <!-- 数据列表 -->
    <div v-else>
      <table class="w-full table-fixed">
        <colgroup>
          <col class="w-[4%]">
          <col class="w-[30%]">
          <col class="w-[22%]">
          <col class="w-[22%]">
          <col class="w-[10%]">
          <col class="w-[8%]">
          <col class="w-[4%]">
        </colgroup>
        <tbody>
          <TrackListItem
            v-for="track in tracks"
            :key="track.id"
            :track="track"
            @navigate="(id) => $emit('navigate', id)"
          />
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <div
      v-if="!empty && !error"
      class="flex items-center justify-between border-t border-default bg-subtle px-3 py-2"
    >
      <span class="text-xs text-tertiary">
        第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 首
      </span>
      <div class="flex items-center gap-2">
        <BaseButton
          variant="ghost"
          size="sm"
          :disabled="page <= 1"
          @click="$emit('prev')"
        >
          上一页
        </BaseButton>
        <span class="font-mono text-xs text-secondary">{{ page }}</span>
        <BaseButton
          variant="ghost"
          size="sm"
          :disabled="page >= totalPages"
          @click="$emit('next')"
        >
          下一页
        </BaseButton>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TrackItem } from "@/apis/library"
import BaseButton from "@/components/ui/BaseButton.vue"
import TrackListItem from "@/components/library/TrackListItem.vue"

/**
 * 曲库列表组件
 * - 受控组件：数据/分页状态由父组件（LibraryView）通过 props 注入
 * - 事件：navigate(id) / prev / next / retry
 */
const props = withDefaults(
  defineProps<{
    tracks: TrackItem[]
    loading?: boolean
    error?: string | null
    page?: number
    totalPages?: number
    total?: number
  }>(),
  {
    loading: false,
    error: null,
    page: 1,
    totalPages: 1,
    total: 0,
  },
)

defineEmits<{
  (e: "navigate", id: string): void
  (e: "prev"): void
  (e: "next"): void
  (e: "retry"): void
}>()

const skeletonRows = computed(() => Math.min(10, props.tracks.length || 10))

const empty = computed(
  () => !props.loading && (!props.tracks || props.tracks.length === 0),
)
</script>

<style scoped>
/* TrackList 无额外 scoped 样式 */
</style>
