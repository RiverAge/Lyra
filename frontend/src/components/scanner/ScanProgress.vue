<template>
  <div class="card p-4">
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
      <BaseButton
        variant="primary"
        size="sm"
        icon="RefreshCw"
        :disabled="scannerStore.triggering || scannerStore.isScanning"
        :title="scannerStore.isScanning ? '扫描进行中' : '触发扫描'"
        @click="onTrigger"
      >
        {{ scannerStore.triggering ? "触发中…" : "触发扫描" }}
      </BaseButton>
    </div>

    <!-- 进度数值 -->
    <div v-if="scannerStore.isScanning" class="mb-3 text-xs text-secondary">
      <!-- 第一行：已扫 / 总数 + 百分比 -->
      <div class="flex items-center gap-4">
        <span>
          已处理 <span class="font-mono font-medium text-primary">{{ scannerStore.count }}</span>
          <template v-if="scannerStore.totalFiles > 0">
            / <span class="font-mono font-medium text-primary">{{ scannerStore.totalFiles }}</span> 首
          </template>
          <template v-else>
            首
          </template>
        </span>
        <span v-if="percentLabel" class="font-mono font-medium text-accent">
          {{ percentLabel }}
        </span>
      </div>
      <!-- 第二行：文件夹 + 耗时 + ETA -->
      <div class="mt-1 flex items-center gap-4">
        <span>
          文件夹 <span class="font-mono font-medium text-primary">{{ scannerStore.folderCount }}</span> 个
        </span>
        <span v-if="elapsedLabel" class="text-tertiary">
          {{ elapsedLabel }}
        </span>
        <span v-if="etaLabel" class="text-tertiary">
          剩余 {{ etaLabel }}
        </span>
      </div>
      <!-- 进度条 -->
      <div v-if="scannerStore.totalFiles > 0" class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-hover">
        <div
          class="h-full rounded-full bg-accent-gradient transition-all duration-300"
          :style="{ width: progressWidth }"
        />
      </div>
    </div>

    <!-- 已完成/空闲摘要 -->
    <div v-else class="mb-3 text-xs text-secondary">
      <span v-if="scannerStore.lastScannedAt">
        上次完成：{{ formatTimestamp(scannerStore.lastScannedAt) }}
      </span>
      <span v-else-if="scannerStore.isIdle">
        尚未扫描
      </span>
      <!-- 非扫描态的 count 含 hash 跳过文件（=已入库），mutagen 失败的文件
           也计入 count 但未入库，故此数为近似值（自用场景偏差极小） -->
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
import BaseButton from "@/components/ui/BaseButton.vue"

/**
 * 扫描进度组件
 *
 * 设计：
 * - onMounted 拉一次 status（拿快照） + startProgress 开 SSE 订阅
 * - onUnmounted 调 stopProgress 关闭 EventSource（防内存泄漏）
 * - 触发扫描按钮 → store.trigger()，409 由 store 翻译为「扫描进行中」
 * - 状态徽章用 token 类名（bg-success/bg-warning/bg-danger/bg-subtle）
 * - 进度展示：总数 + 已扫 + 百分比 + ETA（已扫 ≥10 才显示 ETA 防抖）
 */

/** ETA 防抖阈值：已扫文件数低于此值时不显示 ETA（早期速率不稳定） */
const _ETA_MIN_PROCESSED = 10

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

const percentLabel = computed(() => {
  const total = scannerStore.totalFiles
  if (total <= 0) return ""
  const pct = Math.min(100, Math.round((scannerStore.count / total) * 100))
  return `${pct}%`
})

const progressWidth = computed(() => {
  const total = scannerStore.totalFiles
  if (total <= 0) return "0%"
  const pct = Math.min(100, (scannerStore.count / total) * 100)
  return `${pct}%`
})

const elapsedLabel = computed(() => {
  const started = scannerStore.startedAt
  if (!started) return ""
  const now = Date.now()
  const elapsedMs = Math.max(0, now - started)
  if (elapsedMs < 1000) return "刚启动"
  return formatDuration(elapsedMs)
})

const etaLabel = computed(() => {
  const total = scannerStore.totalFiles
  const processed = scannerStore.count
  const started = scannerStore.startedAt

  // 条件不足时不显示 ETA
  if (total <= 0 || processed < _ETA_MIN_PROCESSED || !started) return ""

  const remaining = total - processed
  if (remaining <= 0) return ""

  const now = Date.now()
  const elapsedMs = Math.max(1, now - started)
  const rate = processed / elapsedMs // files per ms
  const etaMs = remaining / rate

  return formatDuration(etaMs)
})

/** 格式化毫秒时长为人类可读字符串（如 "45s"、"2m30s"、"1h12m"） */
function formatDuration(ms: number): string {
  const sec = Math.max(0, Math.round(ms / 1000))
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return `${m}m${s}s`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return `${h}h${rm}m`
}

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
