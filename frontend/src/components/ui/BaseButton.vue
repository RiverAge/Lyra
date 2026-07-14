<template>
  <button
    :class="computedClass"
    :disabled="disabled"
  >
    <slot />
  </button>
</template>

<script setup lang="ts">
/**
 * BaseButton — 统一按钮组件
 *
 * 三级 variant：
 * - primary:   实心填充（bg-accent + text-white），主操作（保存/拉取/确认写入）
 * - secondary: 浅底描边（bg-surface + border），次操作（撤销/重试/重置）
 * - ghost:     透明无边（bg-transparent），弱操作（返回/刷新/翻页/图标按钮）
 *
 * 变体：
 * - danger: 叠加到 primary 或 secondary 上，改用 danger 色调（删除/取消）
 * - size: sm（xs 文字 + 紧凑内距）/ md（sm 文字 + 标准内距）
 *
 * 用法：
 * <BaseButton variant="primary" @click="save">保存</BaseButton>
 * <BaseButton variant="ghost" size="sm" @click="back">← 返回</BaseButton>
 * <BaseButton variant="primary" danger @click="del">删除</BaseButton>
 */
const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost"
    size?: "sm" | "md"
    danger?: boolean
    disabled?: boolean
  }>(),
  {
    variant: "secondary",
    size: "md",
    danger: false,
    disabled: false,
  },
)

const baseClass = "inline-flex items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-40"

const sizeClass = computed(() =>
  props.size === "sm"
    ? "px-2.5 py-1 text-xs"
    : "px-3 py-1.5 text-sm",
)

const variantClass = computed(() => {
  // danger 变体优先
  if (props.danger) {
    if (props.variant === "primary") {
      return "bg-danger text-white hover:opacity-90"
    }
    // secondary + danger
    return "border border-danger text-danger hover:bg-danger/5"
  }
  switch (props.variant) {
    case "primary":
      return "bg-accent text-white hover:bg-accent-hover active:bg-accent-pressed"
    case "ghost":
      return "bg-transparent text-secondary hover:bg-hover"
    case "secondary":
    default:
      return "bg-surface border border-default text-primary hover:bg-hover"
  }
})

const computedClass = computed(() =>
  [baseClass, sizeClass.value, variantClass.value].join(" "),
)
</script>

<style scoped>
/* BaseButton 无额外 scoped 样式——全部通过 Tailwind token 类名控制 */
</style>
