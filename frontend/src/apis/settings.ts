import { http } from "@/apis/http"

/**
 * Settings API
 *
 * 后端契约：
 * - GET /settings → AppSettings（credits_base_url 空串=直连 music.apple.com）
 * - PUT /settings（body: { credits_base_url: string }）→ AppSettings
 * - GET /config → AppConfig（只读环境配置，运行期不可改）
 *
 * 响应已由 http.ts 拦截器解包，直接用返回值。
 */

export interface AppSettings {
  credits_base_url: string
  updated_at: number
}

/** 运行期环境配置（只读，LYRA_* 环境变量解析值） */
export interface AppConfig {
  music_library_root: string | null
  db_path: string
  static_dir: string | null
  log_level: string
  log_dir: string | null
  log_max_bytes: number
  log_backup_count: number
  library_configured: boolean
}

export async function fetchSettings(): Promise<AppSettings> {
  return http.get<AppSettings>("/settings").then((res) => res.data)
}

export async function saveSettings(payload: {
  credits_base_url: string
}): Promise<AppSettings> {
  return http.put<AppSettings>("/settings", payload).then((res) => res.data)
}

export async function fetchConfig(): Promise<AppConfig> {
  return http.get<AppConfig>("/config").then((res) => res.data)
}
