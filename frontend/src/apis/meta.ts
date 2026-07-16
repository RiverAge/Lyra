import { http } from "@/apis/http"

/**
 * 元数据 API（M6-B）
 *
 * 后端契约（所有路径前缀 /api，由 http.ts baseURL 配置）：
 * - GET  /meta/fields                          → dict[str, object] 字段映射清单
 * - GET  /meta/{track_id}/apple?storefront&lang → AppleResponse
 * - GET  /meta/{track_id}/credits?storefront    → CreditsResponse
 * - POST /meta/{track_id}/diff                  → DiffResponse
 * - POST /meta/{track_id}/write                 → WriteResponse（写操作不可逆，调用方须 UI 二次确认）
 *
 * 错误约定（FastAPI HTTPException）：
 * - 400 song_id 不在标签
 * - 404 track 不存在
 * - 422 非数字 track_id
 * - 503 store 未初始化 / 全 region 失败
 * 响应已由 http.ts 拦截器解包，直接用返回值。
 */

/** 权威字段：字段名 → 值列表（多值标签如 ©wrt / ----:com.apple.iTunes:* ） */
export type AuthoritativeFields = Record<string, string[]>

export interface AppleResponse {
  track_id: string
  song_id: string
  storefront: string
  lang: string
  authoritative_fields: AuthoritativeFields
}

export interface CreditsResponse {
  track_id: string
  authoritative_fields?: AuthoritativeFields
  /** 永久无 credits 哨兵：真实页但无 roleNames，不重试/fallback */
  no_credits?: boolean
}

/** 单条字段差异（后端 diff 列表元素结构由后端定义，前端按宽容类型读取） */
export interface FieldDiff {
  field: string
  before?: unknown
  after?: unknown
  kind?: "added" | "modified" | "removed" | "unchanged"
  [key: string]: unknown
}

export interface DiffResponse {
  track_id: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  diffs: FieldDiff[]
}

export interface WriteResponse {
  track_id: string
  format: string
  fields_written: number
  new_tag_map: Record<string, unknown>
}

/** 字段来源：Apple WebAPI 或 Credits 网页爬取 */
export type FieldSource = "apple" | "credits"

/** 字段级状态：正常 / 永久无（哨兵）/ 临时失败可重试 */
export type FieldStatusKind = "ok" | "missing_permanent" | "failed_retryable"

/** 带状态标记的字段行（合并 Apple + Credits 后统一展示） */
export interface FieldWithStatus {
  field: string
  values: string[]
  source: FieldSource
  status: FieldStatusKind
}

/** 字段映射清单元素：语义字段名 → 各容器的 mutagen key（后端 /meta/fields 返回）。 */
export interface FieldInfo {
  semantic: string
  /** MP4/ALAC 容器的 mutagen key（如 "©nam"），可能 null */
  mp4: string | null
  /** FLAC 容器的 mutagen key（如 "title"），可能 null */
  flac: string | null
  /** MP3(ID3) 容器的 mutagen key（如 "TIT2"），可能 null */
  mp3: string | null
}

/** /meta/fields 返回结构：{fields: FieldInfo[]}。 */
export interface FieldMapResponse {
  fields: FieldInfo[]
}

/**
 * 从 axios 错误对象抽取后端错误信息。
 * FastAPI HTTPException 响应体形如 {detail: string} 或 {detail: [{msg: ...}]}。
 */
export function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "response" in err) {
    const response = (err as { response?: { data?: unknown; status?: number } }).response
    const data = response?.data
    if (data && typeof data === "object" && "detail" in data) {
      const detail = (data as { detail: unknown }).detail
      if (typeof detail === "string") return detail
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0]
        if (first && typeof first === "object" && "msg" in first) {
          return String((first as { msg: unknown }).msg)
        }
      }
    }
    if (response?.status) {
      return `${fallback}（HTTP ${response.status}）`
    }
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

/** 拉取支持的字段映射清单（语义字段名 → 各容器 mutagen key）。 */
export async function fetchFields(): Promise<FieldMapResponse> {
  return http.get<FieldMapResponse>("/meta/fields").then((res) => res.data)
}

/** 拉取 Apple WebAPI 权威元数据 */
export async function fetchApple(
  trackId: string,
  storefront = "us",
  lang = "zh-Hans",
): Promise<AppleResponse> {
  const params = { storefront, lang }
  return http.get<AppleResponse>(`/meta/${trackId}/apple`, { params }).then((res) => res.data)
}

/** 拉取 Credits 权威元数据（含 no_credits 哨兵） */
export async function fetchCredits(
  trackId: string,
  storefront = "us",
): Promise<CreditsResponse> {
  const params = { storefront }
  return http.get<CreditsResponse>(`/meta/${trackId}/credits`, { params }).then((res) => res.data)
}

/** 提交权威字段，生成 before/after/diffs 对比 */
export async function computeDiff(
  trackId: string,
  authoritativeFields: AuthoritativeFields,
): Promise<DiffResponse> {
  return http
    .post<DiffResponse>(`/meta/${trackId}/diff`, { authoritative_fields: authoritativeFields })
    .then((res) => res.data)
}

/** 将 after_fields 写入音频标签（不可逆，调用方须 UI 二次确认） */
export async function writeMeta(
  trackId: string,
  afterFields: AuthoritativeFields,
): Promise<WriteResponse> {
  return http
    .post<WriteResponse>(`/meta/${trackId}/write`, { after_fields: afterFields })
    .then((res) => res.data)
}
