<template>
  <div class="rounded-md border border-default bg-surface p-4 shadow-sm animate-fade-in">
    <div class="mb-3 flex items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-primary">
          扫描进度
        </h3>
        <span
          class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
          :class="badgeClass"
        >
          {{ stateLabel }}
        </span>
      </div>
      <button
        class="rounded-md border border-default px-3 py-1.5 text-xs text-primary transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="scannerStore.triggering || scannerStore.isScanning"
        :title="scannerStore.isScanning ? '扫描进行中' : '触发扫描'"
        @click="onTrigger"
      >
        {{ scannerStore.triggering ? "触发中…" : "触发扫描" }}
      </button>
    </div>

    <!-- 进度数值 -->
    <div v-if="scannerStore.isScanning" class="mb-3 flex items-center gap-6 text-xs text-secondary">
      <span>
        已扫描 <span class="font-mono font-medium text-primary">{{ scannerStore.count }}</span> 首
      </span>
      <span>
        文件夹 <span class="font-mono font-medium text-primary">{{ scannerStore.folderCount }}</span> 个
      </span>
      <span v-if="elapsedLabel" class="text-tertiary">
        {{ elapsedLabel }}
      </span>
    </div>

    <!-- 已完成/空闲摘要 -->
    <div v-else class="mb-3 text-xs text-secondary">
      <span v-if="scannerStore.lastScannedAt">
        上次完成：{{ formatTimestamp(scannerStore.lastScannedAt) }}
      </span>
      <span v-else-if="scannerStore.isIdle">
        尚未扫描
      </span>
      <span v-if="scannerStore.count > 0 && !scannerStore.isScanning" class="ml-3">
        库内 <span class="font-mono text-primary">{{ scannerStore.count }}</span> 首
      </span>
    </div>

    <!-- 错误信息 -->
    <p v-if="scannerStore.isError && scannerStore.errorMessage" class="mb-2 text-xs text-danger">
      {{ scannerStore.errorMessage }}
    </p>

    <!-- 库未配置 -->
    <p v-if="scannerStore.isNotInitialized" class="mb-2 text-xs text-warning">
      曲库尚未初始化：请检查后端 library_root 配置
    </p>

    <!-- 连接状态 -->
    <div class="flex items-center gap-2 text-xs text-tertiary">
      <span
        class="inline-block h-2 w-2 rounded-full"
        :class="scannerStore.connected ? 'bg-success' : 'bg-tertiary'"
      />
      <span>{{ scannerStore.connected ? "SSE 已连接" : "SSE 未连接" }}</span>
      <span v-if="scannerStore.triggerError" class="ml-2 text-danger">
        {{ scannerStore.triggerError }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useScannerStore } from "@/stores/scanner"

/**
 * 扫描进度组件
 *
 * 设计：
 * - onMounted 拉一次 status（拿快照） + startProgress 开 SSE 订阅
 * - onUnmounted 调 stopProgress 关闭 EventSource（防内存泄漏）
 * - 触发扫描按钮 → store.trigger()，409 由 store 翻译为「扫描进行中」
 * - 状态徽章用 token 类名（bg-success/bg-warning/bg-danger/bg-subtle）
 */
const scannerStore = useScannerStore()

onMounted(async () => {
  await scannerStore.refreshStatus()
  scannerStore.startProgress()
})

onUnmounted(() => {
  scannerStore.stopProgress()
})

async function onTrigger(): Promise<void> {
  const msg = await scannerStore.trigger()
  if (msg) {
    // 已由 store 写入 triggerError，此处只兜底 noop
    return
  }
  // 触发成功后立即拉一次 status 拿到 started_at
  await scannerStore.refreshStatus()
}

const stateLabel = computed(() => {
  switch (scannerStore.state) {
    case "scanning":
      return "扫描中"
    case "idle":
      return "空闲"
    case "error":
      return "错误"
    case "not_initialized":
      return "未初始化"
    default:
      return scannerStore.state
  }
})

const badgeClass = computed(() => {
  switch (scannerStore.state) {
    case "scanning":
      return "bg-accent-subtle text-accent"
    case "idle":
      return "bg-subtle text-secondary"
    case "error":
      return "bg-subtle text-danger"
    case "not_initialized":
      return "bg-subtle text-warning"
    default:
      return "bg-subtle text-tertiary"
  }
})

const elapsedLabel = computed(() => {
  const started = scannerStore.startedAt
  if (!started) return ""
  const now = Date.now()
  const elapsedMs = Math.max(0, now - started)
  if (elapsedMs < 1000) return "刚启动"
  const sec = Math.floor(elapsedMs / 1000)
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}m${s}s`
})

function formatTimestamp(ts: number): string {
  try {
    const d = new Date(ts)
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return String(ts)
  }
}
</script>

<style scoped>
/* ScanProgress 无额外 scoped 样式 */
</style>
