import { http } from "@/apis/http"

/**
 * Settings API
 *
 * 后端契约：
 * - GET /settings → AppSettings（credits_base_url 空串=直连 music.apple.com）
 * - PUT /settings（body: { credits_base_url: string }）→ AppSettings
 *
 * 响应已由 http.ts 拦截器解包，直接用返回值。
 */

export interface AppSettings {
  credits_base_url: string
  updated_at: number
}

export async function fetchSettings(): Promise<AppSettings> {
  return http.get<AppSettings>("/settings").then((res) => res.data)
}

export async function saveSettings(payload: {
  credits_base_url: string
}): Promise<AppSettings> {
  return http.put<AppSettings>("/settings", payload).then((res) => res.data)
}
