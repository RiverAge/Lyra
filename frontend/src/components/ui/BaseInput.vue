<template>
  <div :class="wrapperClass">
    <Icon
      v-if="iconName"
      :name="iconName"
      :size="14"
      class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-tertiary"
    />
    <input
      :value="modelValue"
      :type="type"
      :placeholder="placeholder"
      :disabled="disabled"
      :class="inputClass"
      v-bind="$attrs"
      @input="onInput"
      @focus="onFocus"
      @blur="onBlur"
    >
  </div>
</template>

<script setup lang="ts">
/**
 * BaseInput — 统一输入框
 *
 * 设计：
 * - 圆角 sm（6px，不再 8px）
 * - focus 时 .input-ring（glow 阴影 + accent 边框），替代单纯 border 换色
 * - 支持 leading icon（搜索框等）
 * - v-model 双向绑定（modelValue / update:modelValue）
 *
 * 用法：
 * <BaseInput v-model="kw" placeholder="搜索曲目…" icon="Search" />
 * <BaseInput v-model="storefront" placeholder="us" class="w-24" />
 */
/* global Event, FocusEvent, HTMLInputElement */
import Icon from "@/components/ui/icons/Icon.vue"
import type { IconName } from "@/components/ui/icons/paths"

const props = withDefaults(
  defineProps<{
    modelValue: string
    type?: string
    placeholder?: string
    disabled?: boolean
    icon?: IconName
  }>(),
  {
    type: "text",
    placeholder: "",
    disabled: false,
  },
)

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void
  (e: "focus", event: FocusEvent): void
  (e: "blur", event: FocusEvent): void
}>()

const iconName = computed(() => props.icon ?? null)

const wrapperClass = "relative inline-flex"

const inputClass = computed(() => [
  "input-ring w-full rounded-sm border border-line-subtle bg-surface px-2.5 py-1.5 text-sm text-primary placeholder:text-tertiary disabled:opacity-50",
  iconName.value ? "pl-8" : "",
  "disabled:cursor-not-allowed",
])

function onInput(e: Event): void {
  emit("update:modelValue", (e.target as HTMLInputElement).value)
}

function onFocus(e: FocusEvent): void {
  emit("focus", e)
}

function onBlur(e: FocusEvent): void {
  emit("blur", e)
}
</script>

<style scoped>
/* BaseInput 无额外 scoped 样式——靠 .input-ring 工具类 + token 类名控制 */
</style>
