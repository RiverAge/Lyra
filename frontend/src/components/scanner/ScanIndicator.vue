<template>
  <div ref="rootEl" class="scan-indicator">
    <!-- 小条指示器：点击 toggle 浮层 -->
    <button
      class="si-trigger"
      :title="stateLabel"
      @click="open = !open"
    >
      <!-- 状态点 -->
      <span class="si-dot" :class="dotClass" />

      <!-- 扫描中：迷你进度条 + 百分比 -->
      <template v-if="scannerStore.isScanning">
        <div class="si-bar">
          <div class="si-bar-fill" :style="{ width: progressWidth }" />
        </div>
        <span class="si-pct">{{ percentLabel || "…" }}</span>
      </template>

      <!-- 非扫描：状态文字（窄屏只剩点） -->
      <span v-else class="si-label">{{ compactLabel }}</span>
    </button>

    <!-- 浮层（Teleport + absolute，点击外部关闭） -->
    <Teleport to="body">
      <Transition name="si-pop">
        <div v-if="open" class="si-popover" :style="popoverStyle" @click.stop>
        <div class="si-pop-head">
          <div class="flex items-center gap-2">
            <span class="si-dot" :class="dotClass" />
            <span class="text-sm font-medium text-primary">{{ stateLabel }}</span>
          </div>
          <button class="si-close" title="关闭" @click="open = false">
            <Icon name="X" :size="14" />
          </button>
        </div>

        <!-- 扫描中：进度详情 -->
        <div v-if="scannerStore.isScanning" class="si-body">
          <div class="si-line">
            已处理 <span class="font-mono font-medium text-primary">{{ scannerStore.count }}</span>
            <template v-if="scannerStore.totalFiles > 0">
              / <span class="font-mono font-medium text-primary">{{ scannerStore.totalFiles }}</span> 首
            </template>
            <template v-else>首</template>
            <span v-if="percentLabel" class="ml-2 font-mono font-medium text-accent">{{ percentLabel }}</span>
          </div>
          <div class="si-line text-tertiary">
            文件夹 <span class="font-mono text-primary">{{ scannerStore.folderCount }}</span> 个
            <span v-if="elapsedLabel" class="ml-3">{{ elapsedLabel }}</span>
            <span v-if="etaLabel" class="ml-3">剩余 {{ etaLabel }}</span>
          </div>
          <div v-if="scannerStore.totalFiles > 0" class="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-hover">
            <div class="h-full rounded-full bg-accent-gradient transition-all duration-300" :style="{ width: progressWidth }" />
          </div>
        </div>

        <!-- 非扫描：上次完成 + 库内数 -->
        <div v-else class="si-body">
          <div v-if="scannerStore.lastScannedAt" class="si-line">
            上次完成：{{ formatTimestamp(scannerStore.lastScannedAt) }}
          </div>
          <div v-else-if="scannerStore.isIdle" class="si-line text-tertiary">
            尚未扫描
          </div>
          <span v-if="scannerStore.count > 0 && !scannerStore.isScanning" class="si-line text-tertiary">
            库内 <span class="font-mono text-primary">{{ scannerStore.count }}</span> 首
          </span>
        </div>

        <!-- 错误 / 库未配置 -->
        <p v-if="scannerStore.isError && scannerStore.errorMessage" class="si-alert text-danger">
          {{ scannerStore.errorMessage }}
        </p>
        <p v-if="scannerStore.isNotInitialized" class="si-alert text-warning">
          曲库尚未初始化：请检查后端 library_root 配置
        </p>

        <!-- 触发扫描 -->
        <div class="si-pop-foot">
          <BaseButton
            variant="primary"
            size="sm"
            icon="RefreshCw"
            :disabled="scannerStore.triggering || scannerStore.isScanning || !scannerStore.libraryConfigured"
            @click="onTrigger"
          >
            {{ scannerStore.triggering ? "触发中…" : "触发扫描" }}
          </BaseButton>
          <div class="flex items-center gap-1.5 text-xs text-tertiary">
            <span class="si-dot" :class="scannerStore.connected ? 'si-dot-success' : 'si-dot-muted'" />
            {{ scannerStore.connected ? "SSE 已连接" : "SSE 未连接" }}
          </div>
        </div>
          <p v-if="scannerStore.triggerError" class="si-alert text-danger">{{ scannerStore.triggerError }}</p>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
/* global HTMLElement, MouseEvent, Node */
import { useScannerStore } from "@/stores/scanner"
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"

/**
 * ScanIndicator — header 扫描指示器（小条 + 点击浮层）
 *
 * 取代 LibraryView 的 ScanProgress 大卡片：
 * - 小条：idle 绿点 / scanning 迷你进度条+百分比 / error 红点 / 未初始化黄点
 * - 点击 → Teleport 浮层（absolute 定位在指示器下方，点外部关闭）
 *   含：状态 + 进度详情 / 上次完成 + 库内数 + 触发扫描按钮 + SSE 状态
 *
 * SSE 订阅由 App.vue 统一开（跨页面常驻），本组件只读 store 状态。
 *
 * 约束：auto-import 已注入 ref/computed/onMounted/onUnmounted。
 */

/** ETA 防抖阈值：已扫文件数低于此值时不显示 ETA（早期速率不稳定） */
const _ETA_MIN_PROCESSED = 10

const scannerStore = useScannerStore()

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const popoverStyle = ref<Record<string, string>>({})

async function onTrigger(): Promise<void> {
  const msg = await scannerStore.trigger()
  if (msg) return // 已由 store 写入 triggerError
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

/** 小条上的紧凑文字（窄屏隐藏，只剩点） */
const compactLabel = computed(() => {
  if (scannerStore.isNotInitialized) return "未配置"
  if (scannerStore.isError) return "错误"
  return "空闲"
})

const dotClass = computed(() => {
  switch (scannerStore.state) {
    case "scanning":
      return "si-dot-accent"
    case "idle":
      return "si-dot-success"
    case "error":
      return "si-dot-danger"
    case "not_initialized":
      return "si-dot-warning"
    default:
      return "si-dot-muted"
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
  if (total <= 0 || processed < _ETA_MIN_PROCESSED || !started) return ""
  const remaining = total - processed
  if (remaining <= 0) return ""
  const now = Date.now()
  const elapsedMs = Math.max(1, now - started)
  const rate = processed / elapsedMs
  const etaMs = remaining / rate
  return formatDuration(etaMs)
})

/** 浮层定位：挂到 trigger 右下方。open 时 nextTick 测 trigger 位置。 */
watch(open, async (v) => {
  if (!v) return
  await nextTick()
  const trigger = rootEl.value?.querySelector<HTMLElement>(".si-trigger")
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  // 右对齐 trigger 右边缘，定位在其下方
  popoverStyle.value = {
    position: "fixed",
    top: `${rect.bottom + 6}px`,
    right: `${window.innerWidth - rect.right}px`,
  }
})

/** 点击外部关闭浮层（排除 trigger 自身，它由 @click toggle） */
function onDocClick(e: MouseEvent): void {
  if (!open.value) return
  const target = e.target as Node
  if (rootEl.value?.contains(target)) return
  // 浮层 Teleport 到 body，不在 rootEl 内，单独判 popover
  const pop = document.querySelector(".si-popover")
  if (pop?.contains(target)) return
  open.value = false
}

onMounted(() => {
  document.addEventListener("click", onDocClick)
})
onUnmounted(() => {
  document.removeEventListener("click", onDocClick)
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
/* 触发按钮：点 + 进度条/文字 */
.si-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  transition: background-color var(--animate-duration-hover) ease;
}
.si-trigger:hover {
  background-color: var(--theme-bg-hover);
}

/* 状态点 */
.si-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}
.si-dot-success { background-color: var(--theme-success); }
.si-dot-accent { background-color: var(--theme-accent); }
.si-dot-danger { background-color: var(--theme-danger); }
.si-dot-warning { background-color: var(--theme-warning); }
.si-dot-muted { background-color: var(--theme-text-tertiary); }

.si-label {
  font-size: 12px;
  color: var(--theme-text-secondary);
}

/* 迷你进度条 */
.si-bar {
  width: 32px;
  height: 4px;
  border-radius: var(--radius-full);
  background-color: var(--theme-bg-hover);
  overflow: hidden;
}
.si-bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background-color: var(--theme-accent);
}
.si-pct {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--theme-text-secondary);
}

/* 浮层（Teleport 到 body，fixed 定位由 JS 注入） */
.si-popover {
  z-index: 60;
  width: 260px;
  background-color: var(--theme-bg-surface);
  border: 1px solid var(--theme-border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 12px;
}
.si-pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.si-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--theme-text-tertiary);
  cursor: pointer;
  transition: background-color var(--animate-duration-hover) ease;
}
.si-close:hover {
  background-color: var(--theme-bg-hover);
  color: var(--theme-text-primary);
}
.si-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.si-line {
  font-size: 12px;
  color: var(--theme-text-secondary);
}
.si-alert {
  margin-top: 8px;
  font-size: 12px;
}
.si-pop-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--theme-border-subtle);
}

/* 浮层过渡：opacity + 轻微下移缩放，对齐 SearchModal 曲线/时长。
   关闭动画时由 tokens.css 的 html.no-anim * 全局兜底压成瞬时，此处不重复。 */
.si-pop-enter-active,
.si-pop-leave-active {
  transition: opacity 0.18s ease, transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.si-pop-enter-from,
.si-pop-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.98);
}

@media (max-width: 640px) {
  /* 窄屏隐藏文字，只剩点 + 进度条 */
  .si-label {
    display: none;
  }
  .si-popover {
    width: 240px;
  }
}
</style>
