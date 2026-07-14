<template>
  <div>
    <!-- 加载态：骨架卡片 -->
    <div
      v-if="loading"
      class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4"
    >
      <div
        v-for="i in skeletonCount"
        :key="i"
        class="card overflow-hidden"
      >
        <div class="aspect-square animate-pulse bg-hover" />
        <div class="space-y-2 p-3">
          <div class="h-3 w-3/4 animate-pulse rounded-sm bg-hover" />
          <div class="h-2.5 w-1/2 animate-pulse rounded-sm bg-hover" />
        </div>
      </div>
    </div>

    <!-- 空态 -->
    <div
      v-else-if="empty"
      class="flex flex-col items-center justify-center px-6 py-20 text-center"
    >
      <div class="mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-subtle text-tertiary">
        <Icon name="Music" :size="24" />
      </div>
      <p class="mb-1 text-sm font-medium text-primary">
        曲库为空
      </p>
      <p class="text-xs text-secondary">
        请先扫描音乐库根目录
      </p>
    </div>

    <!-- 错误态 -->
    <div
      v-else-if="error"
      class="flex flex-col items-center justify-center px-6 py-20 text-center"
    >
      <div class="mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-danger-subtle text-danger">
        <Icon name="AlertCircle" :size="24" />
      </div>
      <p class="mb-1 text-sm font-medium text-danger">
        加载失败
      </p>
      <p class="mb-4 text-xs text-secondary">
        {{ error }}
      </p>
      <BaseButton variant="secondary" size="sm" icon="RefreshCw" @click="$emit('retry')">
        重试
      </BaseButton>
    </div>

    <!-- 数据卡片网格 -->
    <div
      v-else
      class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4"
    >
      <TrackCard
        v-for="track in tracks"
        :key="track.id"
        :track="track"
        @navigate="(id) => $emit('navigate', id)"
      />
    </div>

    <!-- 分页 -->
    <div
      v-if="!empty && !error"
      class="mt-6 flex items-center justify-between border-t border-subtle pt-4"
    >
      <span class="text-xs text-tertiary">
        第 <span class="font-mono text-secondary">{{ page }}</span> /
        <span class="font-mono text-secondary">{{ totalPages }}</span> 页 ·
        共 <span class="font-mono text-secondary">{{ total }}</span> 首
      </span>
      <div class="flex items-center gap-2">
        <BaseButton
          variant="ghost"
          size="sm"
          icon="ChevronLeft"
          icon-only
          :disabled="page <= 1"
          title="上一页"
          @click="$emit('prev')"
        />
        <BaseButton
          variant="ghost"
          size="sm"
          icon="ChevronRight"
          icon-only
          :disabled="page >= totalPages"
          title="下一页"
          @click="$emit('next')"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TrackItem } from "@/apis/library"
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"
import TrackCard from "@/components/library/TrackCard.vue"

/**
 * 曲库列表容器（grid 化，替代原 table 布局）
 * - 受控组件：数据/分页状态由父组件（LibraryView）通过 props 注入
 * - 事件：navigate(id) / prev / next / retry
 * - 响应式 grid：2列(移动) / 3列(sm) / 4列(lg)
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

const skeletonCount = computed(() => Math.min(8, props.tracks.length || 8))

const empty = computed(
  () => !props.loading && (!props.tracks || props.tracks.length === 0),
)
</script>

<style scoped>
/* TrackList 无额外 scoped 样式 */
</style>
