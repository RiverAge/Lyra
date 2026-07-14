<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    :class="spinClass"
    aria-hidden="true"
    v-html="innerSvg"
  />
</template>

<script setup lang="ts">
/**
 * Icon — 内联 SVG 图标统一组件
 *
 * 设计：
 * - path data 集中在 paths.ts，零运行时依赖
 * - 24x24 viewBox，stroke=currentColor 继承文字色
 * - play/pause/skip 等填充型图标内部用 fill="currentColor" stroke="none" 覆盖
 * - Loader2 支持 spin 动画（loading 态）
 *
 * 用法：<Icon name="Play" :size="18" />
 *       <Icon name="Loader2" :size="16" spin />
 */
import { iconPaths, type IconName } from "./paths"

const props = withDefaults(
  defineProps<{
    name: IconName
    size?: number
    strokeWidth?: number
    spin?: boolean
  }>(),
  {
    size: 18,
    strokeWidth: 1.75,
    spin: false,
  },
)

const innerSvg = computed(() => iconPaths[props.name] ?? "")

const spinClass = computed(() =>
  props.spin
    ? "inline-block animate-[spin_0.8s_linear_infinite]"
    : "inline-block",
)
</script>

<style scoped>
/* Icon 无 scoped 样式——靠 stroke=currentColor + 尺寸 props 控制 */
</style>
