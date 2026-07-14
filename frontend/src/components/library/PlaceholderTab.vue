<template>
  <div class="rounded-md border border-dashed border-default bg-subtle p-8 text-center">
    <p class="mb-1 text-sm font-medium text-secondary">
      该模块尚未加载
    </p>
    <p class="text-xs text-tertiary">
      等待对应 agent 合流后替换为真实 tab 组件
    </p>
    <p v-if="trackId" class="mt-3 font-mono text-xs text-tertiary">
      trackId: {{ trackId }}
    </p>
  </div>
</template>

<script setup lang="ts">
/**
 * 占位 Tab 组件
 *
 * 用途：TrackDetailView 的 tab 容器中，元数据/歌词 tab 在其他 agent 合流前
 * 用本组件占位，避免动态 import 不存在的路径导致 typecheck/build 失败。
 * 合流时由 architect 把 TabRegistry 里的 component 指向真实组件即可。
 */
defineProps<{
  trackId: string
}>()
</script>

<style scoped>
/* PlaceholderTab 无额外 scoped 样式 */
</style>
