<template>
  <div class="toolbar">
    <!-- 艺人：文本模糊筛选 -->
    <div class="filter-text">
      <Icon name="Search" :size="14" class="shrink-0 text-tertiary" />
      <input
        :value="filters.artist"
        type="text"
        placeholder="艺人"
        class="filter-input w-24 border-none bg-transparent text-sm text-primary outline-none placeholder:text-tertiary"
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
    <div class="filter-text">
      <Icon name="Search" :size="14" class="shrink-0 text-tertiary" />
      <input
        :value="filters.album"
        type="text"
        placeholder="专辑"
        class="filter-input w-24 border-none bg-transparent text-sm text-primary outline-none placeholder:text-tertiary"
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
    <div class="filter-select relative flex items-center">
      <select
        :value="filters.codec"
        class="filter-input filter-select-el"
        @change="onCodec"
      >
        <option value="">格式（全部）</option>
        <option v-for="c in codecOptions" :key="c" :value="c">{{ c }}</option>
      </select>
      <Icon name="ChevronDown" :size="14" class="filter-chevron" />
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
/* toolbar：FilterBar 内部 flex 布局容器。
   margin-bottom/border-bottom 不在此定义（由消费方控制页面级间距），
   消费方用 tw class（如 flex-1）控制自身在父容器的占位，无需 :deep 穿透。 */
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 文本筛选框容器：focus-within 非标准 ring（box-shadow，保留 scoped） */
.filter-text {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--theme-border-default);
  background-color: var(--theme-bg-surface);
  transition: border-color var(--animate-duration-hover) ease;
}
.filter-text:focus-within {
  border-color: var(--theme-accent);
  box-shadow: 0 0 0 3px rgba(24, 24, 27, 0.08);
}

/* input/select 共享 font:inherit（消除原生表单字体差异） */
.filter-input {
  font: inherit;
}

/* codec 下拉：appearance:none + padding-right 给 chevron 留位 */
.filter-select-el {
  appearance: none;
  -webkit-appearance: none;
  padding-right: 28px;
  width: 120px;
  cursor: pointer;
}
.filter-chevron {
  position: absolute;
  right: 10px;
  pointer-events: none;
  color: var(--theme-text-tertiary);
}
</style>
