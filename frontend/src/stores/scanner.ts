/* global EventSource, MessageEvent */
import type { ScannerState, ScannerStatus } from "@/apis/scanner"
import { fetchScannerStatus, triggerScan } from "@/apis/scanner"

/**
 * 扫描 Store
 *
 * 职责：
 * - 维护扫描状态（state/count/folder_count/totalFiles/started_at 等）
 * - 提供 SSE 连接管理（startProgress / stopProgress）
 * - 提供触发扫描能力（trigger），409 时返回友好提示
 *
 * 约束：
 * - SSE 用浏览器原生 EventSource，不走 axios（baseURL 不适用）
 * - SSE URL 必须含 /api 前缀：`/api/scanner/progress`
 * - 组件卸载时必须 stopProgress（关闭 EventSource）
 */

export interface ScannerProgress {
  /** 已处理文件数（含 folder hash 跳过的文件；与后端 count 口径一致） */
  count: number
  folderCount: number
  /** 库中匹配扩展名文件总数（os.walk 统计，扫描中不变） */
  total: number
  timestamp: number
}

export const useScannerStore = defineStore("scanner", () => {
  const state = ref<ScannerState>("idle")
  const scanType = ref<string | null>(null)
  /** 已处理文件数（含 hash 跳过；非"实际入库数"，确保进度能到 100%） */
  const count = ref(0)
  const folderCount = ref(0)
  const totalFiles = ref(0)
  const startedAt = ref<number | null>(null)
  const lastScannedAt = ref<number | null>(null)
  const errorMessage = ref<string | null>(null)
  const libraryRoot = ref<string | null>(null)
  const libraryConfigured = ref(false)

  const connected = ref(false)
  const triggering = ref(false)
  const triggerError = ref<string | null>(null)

  // SSE 实例（不参与响应式，用 let 局部变量管理）
  let eventSource: EventSource | null = null

  /**
   * 扫描完成事件携带的 stats 回调。
   * 后端完成事件会带 stats（track_count/album_count/...），由调用方
   * （LibraryView）注册：收到后填进 libraryStore.stats，省一次 HTTP。
   * 默认 noop，避免 store 间横向耦合（scannerStore 不直接 import libraryStore）。
   */
  let _onStats: (stats: Record<string, unknown>) => void = () => {}

  function setOnStats(cb: (stats: Record<string, unknown>) => void): void {
    _onStats = cb
  }

  const isScanning = computed(() => state.value === "scanning")
  const isIdle = computed(() => state.value === "idle")
  const isError = computed(() => state.value === "error")
  const isNotInitialized = computed(() => state.value === "not_initialized")

  function applyStatus(s: ScannerStatus): void {
    state.value = s.state
    scanType.value = s.scan_type ?? null
    count.value = s.count ?? 0
    folderCount.value = s.folder_count ?? 0
    totalFiles.value = s.total_files ?? 0
    startedAt.value = s.started_at ?? null
    lastScannedAt.value = s.last_scanned_at ?? null
    errorMessage.value = s.error_message ?? null
    libraryRoot.value = s.library_root ?? null
    libraryConfigured.value = s.library_configured ?? false
  }

  async function refreshStatus(): Promise<void> {
    try {
      const s = await fetchScannerStatus()
      applyStatus(s)
    } catch (e: unknown) {
      // 状态接口失败：降级为 not_initialized 并记错
      state.value = "not_initialized"
      errorMessage.value = normalizeError(e)
    }
  }

  /**
   * 启动 SSE 进度订阅。
   * - SSE 流不走 axios，用浏览器原生 EventSource
   * - URL 含 /api 前缀（baseURL 在 axios 层配置，EventSource 不感知）
   */
  function startProgress(): void {
    if (eventSource) {
      // 已连接则不重复
      return
    }
    try {
      eventSource = new EventSource("/api/scanner/progress")
    } catch (e: unknown) {
      triggerError.value = `SSE 连接失败：${normalizeError(e)}`
      eventSource = null
      return
    }

    eventSource.onopen = () => {
      connected.value = true
    }

    eventSource.onmessage = (ev: MessageEvent<string>) => {
      handleSseData(ev.data)
    }

    eventSource.onerror = () => {
      connected.value = false
      // 不自动重启：由调用方决定是否重连（避免静默风暴）
      // 状态保留为最近一次值，UI 可提示"连接已断开"
    }
  }

  function handleSseData(raw: string): void {
    const data = parseRaw(raw)
    if (!data) return

    // 类型字段优先判定
    if (typeof data.type === "string") {
      switch (data.type) {
        case "connected":
          connected.value = true
          return
        case "init": {
          // init 事件含 state/count/folder_count/total/timestamp。
          // 注意：startedAt 不从此处取——init 的 timestamp 是「SSE 连接此刻」，
          // 不是扫描真正起点。扫描起点只认 refreshStatus() 拿到的后端
          // scanner_status.started_at（scan_all 启动时写入的真值）。
          // 否则刷新页面/SSE 重连后 elapsed 会从「重连那一刻」重新算，
          // 看着像「扫描才跑了 20s」（实际已跑几分钟）。
          if (typeof data.state === "string") {
            state.value = data.state as ScannerState
          }
          if (typeof data.count === "number") count.value = data.count
          if (typeof data.folder_count === "number") folderCount.value = data.folder_count
          if (typeof data.total === "number") totalFiles.value = data.total
          return
        }
        default:
          // 未知 type 忽略，保留最近状态
          return
      }
    }

    // 无 type 字段：实时进度或完成事件
    if (typeof data.count === "number") count.value = data.count
    if (typeof data.folder_count === "number") folderCount.value = data.folder_count
    if (typeof data.total === "number") totalFiles.value = data.total
    // 实时事件的 timestamp 是「广播此刻」，不是扫描起点，不用它覆盖 startedAt
    // （扫描起点只由 refreshStatus 的后端 started_at 赋值，见 init 分支注释）。
    if (typeof data.state === "string") {
      state.value = data.state as ScannerState
      if (data.state === "completed" || data.state === "idle") {
        lastScannedAt.value =
          typeof data.timestamp === "number" ? data.timestamp : Date.now()
        // 完成事件带 stats：回调填 libraryStore.stats（省一次 HTTP 全表聚合）。
        if (data.state === "completed" && data.stats && typeof data.stats === "object") {
          _onStats(data.stats as Record<string, unknown>)
        }
      }
    }
  }

  function stopProgress(): void {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    connected.value = false
  }

  async function trigger(): Promise<string | null> {
    triggering.value = true
    triggerError.value = null
    try {
      const result = await triggerScan()
      state.value = result.state
      return null
    } catch (e: unknown) {
      const msg = extractTriggerError(e)
      triggerError.value = msg
      return msg
    } finally {
      triggering.value = false
    }
  }

  function extractTriggerError(e: unknown): string {
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { status?: number; data?: unknown } }).response
      if (resp?.status === 409) {
        return "扫描进行中，请等待完成"
      }
    }
    return normalizeError(e)
  }

  function parseRaw(raw: string): Record<string, unknown> | null {
    // SSE comment（keepalive `:` 开头）忽略
    if (!raw || raw.startsWith(":")) return null
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === "object") {
        return parsed as Record<string, unknown>
      }
    } catch {
      // 非 JSON 数据忽略
    }
    return null
  }

  function normalizeError(e: unknown): string {
    if (e instanceof Error) return e.message
    return "请求失败"
  }

  return {
    // state
    state,
    scanType,
    count,
    folderCount,
    totalFiles,
    startedAt,
    lastScannedAt,
    errorMessage,
    libraryRoot,
    libraryConfigured,
    connected,
    triggering,
    triggerError,
    // derived
    isScanning,
    isIdle,
    isError,
    isNotInitialized,
    // actions
    applyStatus,
    refreshStatus,
    startProgress,
    stopProgress,
    trigger,
    setOnStats,
  }
})
