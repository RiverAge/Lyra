<template>
  <div class="flex items-center gap-2">
    <!-- 艺人：文本模糊筛选 -->
    <div
      class="flex items-center gap-1.5 rounded-sm border border-line bg-surface px-2.5 py-1.5 transition-colors focus-within:border-accent focus-within:shadow-[0_0_0_3px_rgba(24,24,27,0.08)]"
    >
      <Icon name="Search" :size="14" class="shrink-0 text-tertiary" />
      <input
        :value="filters.artist"
        type="text"
        placeholder="艺人"
        class="w-24 border-none bg-transparent text-sm text-primary outline-none placeholder:text-tertiary [font:inherit]"
        @input="onText('artist', $event)"
      >
      <button
        v-if="filters.artist"
        class="border-none bg-transparent px-0.5 text-base leading-none text-tertiary transition-colors hover:text-primary"
        title="清除艺人筛选"
        @click="clear('artist')"
      >×</button>
    </div>

    <!-- 专辑：文本模糊筛选 -->
    <div
      class="flex items-center gap-1.5 rounded-sm border border-line bg-surface px-2.5 py-1.5 transition-colors focus-within:border-accent focus-within:shadow-[0_0_0_3px_rgba(24,24,27,0.08)]"
    >
      <Icon name="Search" :size="14" class="shrink-0 text-tertiary" />
      <input
        :value="filters.album"
        type="text"
        placeholder="专辑"
        class="w-24 border-none bg-transparent text-sm text-primary outline-none placeholder:text-tertiary [font:inherit]"
        @input="onText('album', $event)"
      >
      <button
        v-if="filters.album"
        class="border-none bg-transparent px-0.5 text-base leading-none text-tertiary transition-colors hover:text-primary"
        title="清除专辑筛选"
        @click="clear('album')"
      >×</button>
    </div>

    <!-- 格式：固定列表下拉 -->
    <div class="relative flex items-center">
      <select
        :value="filters.codec"
        class="select-bare input-ring w-[120px] cursor-pointer rounded-sm border border-line bg-surface py-1.5 pl-3 pr-7 text-sm text-primary"
        @change="onCodec"
      >
        <option value="">格式（全部）</option>
        <option v-for="c in codecOptions" :key="c" :value="c">{{ c }}</option>
      </select>
      <Icon name="ChevronDown" :size="14" class="pointer-events-none absolute right-2.5 text-tertiary" />
    </div>

    <div class="flex-1" />

    <!-- 清空全部筛选 -->
    <button
      v-if="hasFilters"
      class="rounded-sm border border-line bg-surface text-xs text-secondary transition-colors hover:border-line-strong hover:text-primary"
      @click="$emit('clearFilters')"
    >清空筛选</button>
  </div>
</template>

<script setup lang="ts">
/* global HTMLInputElement, HTMLSelectElement, Event, setTimeout, clearTimeout */
import type { LibraryFilters } from "@/stores/library"
import Icon from "@/components/ui/icons/Icon.vue"

/**
 * FilterBar — B 布局筛选工具条
 *
 * - artist/album：文本模糊筛选（防抖 300ms，避免逐字打请求）
 * - codec：固定无损列表下拉（后端无 distinct 接口，固定列表够用）
 * - 有任意筛选时显示“清空筛选”
 */

defineProps<{
  filters: LibraryFilters
  hasFilters: boolean
}>()

const emit = defineEmits<{
  (e: "setFilter", key: keyof LibraryFilters, value: string): void
  (e: "clearFilters"): void
}>()

// 无损 codec 固定白名单（与后端统计口径一致）
const codecOptions = ["ALAC", "FLAC", "WAV", "APE", "DSD"]

// 文本输入防抖
const timers: Partial<Record<keyof LibraryFilters, ReturnType<typeof setTimeout>>> = {}

function onText(key: keyof LibraryFilters, e: Event): void {
  const val = (e.target as HTMLInputElement).value
  if (timers[key]) clearTimeout(timers[key])
  timers[key] = setTimeout(() => {
    emit("setFilter", key, val)
  }, 300)
}

function onCodec(e: Event): void {
  const val = (e.target as HTMLSelectElement).value
  emit("setFilter", "codec", val)
}

function clear(key: keyof LibraryFilters): void {
  if (timers[key]) clearTimeout(timers[key])
  emit("setFilter", key, "")
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名 + 全局 .select-bare/.input-ring 控制 */
</style>
