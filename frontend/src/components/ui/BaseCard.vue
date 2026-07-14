<template>
  <div :class="computedClass">
    <slot />
  </div>
</template>

<script setup lang="ts">
/**
 * BaseCard — 统一卡片容器
 *
 * 封装 .card 工具类，可选 hoverable 挂 .card-hover（hover 时阴影加深 + 微上浮）。
 * elevated=true 用 .card-elevated（最高层，dock/modal 浮层）。
 *
 * 用法：
 * <BaseCard class="p-4">内容</BaseCard>
 * <BaseCard hoverable class="p-4">可交互卡片</BaseCard>
 * <BaseCard elevated>浮层</BaseCard>
 */
const props = withDefaults(
  defineProps<{
    hoverable?: boolean
    elevated?: boolean
  }>(),
  {
    hoverable: false,
    elevated: false,
  },
)

const computedClass = computed(() => {
  const classes: string[] = []
  if (props.elevated) {
    classes.push("card-elevated")
  } else {
    classes.push("card")
  }
  if (props.hoverable) {
    classes.push("card-hover")
  }
  return classes.join(" ")
})
</script>

<style scoped>
/* BaseCard 无 scoped 样式——靠 .card / .card-hover / .card-elevated 工具类控制 */
</style>
