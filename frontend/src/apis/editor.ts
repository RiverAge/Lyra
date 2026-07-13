import { http } from "@/apis/http"

/**
 * 逐字歌词编辑器 API
 *
 * 后端契约（路径前缀 /api，已由 http.ts baseURL 注入）：
 * - GET   /lyrics/{track_id}/edit?source=apple        → LyricDocModel
 * - PATCH  /lyrics/{track_id}/edit?source=apple        body: PatchSpanRequest → EditorWriteResponse
 * - POST   /lyrics/{track_id}/edit                    body: LyricDocModel（含 source）→ EditorWriteResponse
 *
 * 错误：
 * - GET：400 不支持 source，404 track/sidecar 不存在，422 非数字 track_id，
 *        503 store 未初始化，500 解析失败
 * - PATCH：400 越界索引/不支持 source，404 track/sidecar 不存在
 * - POST：路径目标由 body.source 决定，错误同 GET/PATCH
 *
 * 约束：本文件仅 import http + 类型；auto-import 已注入类型符号但本项目
 * 按惯例把类型符号从 vue 显式不 import。这里不需要 ref/computed。
 */

/** 编辑器可选来源（与后端 sidecar 子目录一一对应）。 */
export type EditorSource = "apple" | "netease" | "qq"

/** 单个逐字 span：文本 + 起止毫秒。 */
export interface SpanModel {
  text: string
  begin_ms: number
  end_ms: number
}

/** 歌词行：key + 起止毫秒 + spans（空=纯文本行，text 有内容）+ 文本。 */
export interface LineModel {
  key: string
  begin_ms: number
  end_ms: number
  spans: SpanModel[]
  text: string
}

/** 整篇歌词文档：行列表 + 来源。 */
export interface LyricDocModel {
  lines: LineModel[]
  source: string
}

/** PATCH 请求体：span_index 给出→改 span；null→改 line。 */
export interface PatchSpanRequest {
  line_index: number
  span_index: number | null
  begin_ms: number
  end_ms: number
}

/** PATCH/POST 写回响应：返回写回后的完整文档（含路径信息）。 */
export interface EditorWriteResponse {
  track_id: string
  source: string
  path: string
  doc: LyricDocModel
}

/**
 * 读取某 track 某 source 的歌词文档（GET /lyrics/{track_id}/edit）。
 * 错误（400/404/422/503/500）会被 http.ts 抛出，调用方自行 catch。
 */
export async function getLyricDoc(
  trackId: string,
  source: EditorSource,
): Promise<LyricDocModel> {
  return http
    .get<LyricDocModel>(`/lyrics/${trackId}/edit`, { params: { source } })
    .then((res) => res.data)
}

/**
 * 局部 PATCH：改某 line 或某 span 的 begin/end（PATCH /lyrics/{track_id}/edit）。
 * span_index 给出 → 改 span；null → 改 line。
 */
export async function patchSpan(
  trackId: string,
  source: EditorSource,
  body: PatchSpanRequest,
): Promise<EditorWriteResponse> {
  return http
    .patch<EditorWriteResponse>(`/lyrics/${trackId}/edit`, body, {
      params: { source },
    })
    .then((res) => res.data)
}

/**
 * 全量保存：POST 完整 LyricDocModel（含 source），路径目标由 body.source 决定。
 */
export async function postLyricDoc(
  trackId: string,
  doc: LyricDocModel,
): Promise<EditorWriteResponse> {
  return http
    .post<EditorWriteResponse>(`/lyrics/${trackId}/edit`, doc)
    .then((res) => res.data)
}

/**
 * 时间格式化：毫秒整数 → mm:ss.mmm（如 83560 → 01:23.560）。
 * 超过 1 小时则退化显示 mm:ss.mmm（不引入 h，编辑器场景音频一般 < 1h）。
 */
export function formatTime(ms: number): string {
  const v = Number(ms) || 0
  if (v < 0) return "00:00.000"
  const totalMs = Math.floor(v)
  const totalSec = Math.floor(totalMs / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  const milli = totalMs % 1000
  const mm = String(m).padStart(2, "0")
  const ss = String(s).padStart(2, "0")
  const mmm = String(milli).padStart(3, "0")
  return `${mm}:${ss}.${mmm}`
}
