import { http } from "@/apis/http"

/**
 * 扫描 API
 *
 * 后端契约：
 * - GET /scanner/status         → ScannerStatus
 * - GET /scanner/progress       → SSE 流（前端用 EventSource 直连，不走 axios）
 * - POST /scanner/trigger        → 202 + {message, state:"scanning"}；已在扫返回 409
 */

export type ScannerState =
  | "idle"
  | "scanning"
  | "error"
  | "not_initialized"

export interface ScannerStatus {
  state: ScannerState
  scan_type?: string
  count?: number
  folder_count?: number
  started_at?: number | null
  last_scanned_at?: number | null
  error_message?: string | null
  library_root?: string | null
  library_configured?: boolean
}

export interface ScannerTriggerResult {
  message: string
  state: ScannerState
}

export async function fetchScannerStatus(): Promise<ScannerStatus> {
  return http.get<ScannerStatus>("/scanner/status").then((res) => res.data)
}

/**
 * 触发扫描。409（已在扫）会被拦截器抛出，调用方自行 catch 处理。
 */
export async function triggerScan(): Promise<ScannerTriggerResult> {
  return http.post<ScannerTriggerResult>("/scanner/trigger").then((res) => res.data)
}
