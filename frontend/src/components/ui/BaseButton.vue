<template>
  <button
    :class="computedClass"
    :disabled="disabled"
    :title="title"
  >
    <Icon
      v-if="iconName"
      :name="iconName"
      :size="iconSize"
    />
    <slot v-if="!iconOnly" />
    <Icon
      v-if="iconRightName"
      :name="iconRightName"
      :size="iconSize"
    />
  </button>
</template>

<script setup lang="ts">
/**
 * BaseButton — 统一按钮组件
 *
 * 三级 variant：
 * - primary:   accent 渐变填充 + 白字，主操作（保存/拉取/确认写入）
 * - secondary: surface 底 + subtle 边框，次操作（撤销/重试/重置）
 * - ghost:     透明无边，弱操作（返回/刷新/翻页）
 *
 * 变体：
 * - danger: 叠加到 primary 或 secondary 上，改用 danger 色调（删除/取消）
 * - size: sm（xs 文字 + 紧凑内距）/ md（sm 文字 + 标准内距）
 * - icon / iconRight: 图标 name，左侧/右侧内联 SVG
 * - iconOnly: 纯图标按钮（方形 padding，用于播放器控制）
 *
 * 用法：
 * <BaseButton variant="primary" icon="Save" @click="save">保存</BaseButton>
 * <BaseButton variant="ghost" size="sm" icon="ArrowLeft" @click="back">返回曲库</BaseButton>
 * <BaseButton variant="primary" danger icon="Trash2" icon-only @click="del" title="删除" />
 */
import Icon from "@/components/ui/icons/Icon.vue"
import type { IconName } from "@/components/ui/icons/paths"

const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost"
    size?: "sm" | "md"
    danger?: boolean
    disabled?: boolean
    icon?: IconName
    iconRight?: IconName
    iconOnly?: boolean
    title?: string
  }>(),
  {
    variant: "secondary",
    size: "md",
    danger: false,
    disabled: false,
    iconOnly: false,
  },
)

const iconName = computed(() => props.icon ?? null)
const iconRightName = computed(() => props.iconRight ?? null)

const iconSize = computed(() => (props.size === "sm" ? 14 : 16))

const baseClass =
  "inline-flex items-center justify-center gap-1.5 rounded-sm cursor-pointer transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:shadow-none"

const sizeClass = computed(() => {
  if (props.iconOnly) {
    // 纯图标按钮：方形 padding，加 border 让 hover 有可识别容器
    return props.size === "sm" ? "p-1.5 border border-transparent" : "p-2 border border-transparent"
  }
  return props.size === "sm"
    ? "px-2.5 py-1 text-xs"
    : "px-3.5 py-1.5 text-sm"
})

const variantClass = computed(() => {
  // danger 变体优先
  if (props.danger) {
    if (props.variant === "primary") {
      return "bg-danger text-on-accent hover:opacity-90 hover:shadow-md active:translate-y-0"
    }
    // secondary + danger
    return "bg-danger-subtle text-danger hover:bg-danger/20"
  }
  switch (props.variant) {
    case "primary":
      return "bg-accent-gradient text-on-accent hover:shadow-lg hover:brightness-105 active:shadow-md"
    case "ghost":
      // icon-only ghost：hover 加边框+底色，形成可识别按钮容器（浅底上原 bg-hover 太微弱）
      if (props.iconOnly) {
        return "bg-transparent text-secondary hover:bg-hover hover:border-line hover:text-primary"
      }
      return "bg-transparent text-secondary hover:bg-hover hover:text-primary"
    case "secondary":
    default:
      return "bg-surface text-secondary hover:bg-hover hover:text-primary hover:shadow-sm"
  }
})

const computedClass = computed(() =>
  [baseClass, sizeClass.value, variantClass.value].join(" "),
)
</script>

<style scoped>
/* BaseButton 无额外 scoped 样式——全部通过 Tailwind token 类名控制 */
</style>
