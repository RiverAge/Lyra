import { http } from "@/apis/http"

/**
 * 歌词 API
 *
 * 后端契约（路径前缀 /api，已由 http.ts baseURL 注入）：
 * - GET  /lyrics/{track_id}/match?providers=netease,qq&limit=12&top_n=10 → MatchResponse
 * - GET  /lyrics/{track_id}/sidecars                              → SidecarListResponse
 * - GET  /lyrics/{track_id}/sidecar/{source}                      → SidecarResponse (404 不存在)
 * - POST /lyrics/{track_id}/sidecar/{source}  body:{content}      → WriteSidecarResponse
 * - DELETE /lyrics/{track_id}/sidecar/{source}                    → DeleteSidecarResponse (幂等)
 *
 * 错误：422 非数字 track_id，404 track 不存在 / sidecar 不存在，
 *      503 store/读音频失败，400 未知 provider。
 *
 * 约束：本文件仅 import http + 类型；auto-import 已注入类型符号，但本项目按
 * 惯例把类型符号从 vue 显式不 import（auto-import 提供 Ref/ComputedRef 等类型）。
 * 这里不需要 ref/computed，所以无需任何 vue 导入。
 */

/** 歌词来源（与后端 sidecar 子目录名一一对应）。 */
export type LyricSource = "apple" | "netease" | "qq"

/** 匹配决策（后端 scoring 阈值的语义化结果）。 */
export type MatchDecision = "accept" | "review" | "reject" | "not_found"

/** 单个候选：来源/标题/艺人/专辑/评分，预留扩展字段。 */
export interface Candidate {
  /** 来源 slug：后端 candidate_to_dict 已规整为 "netease" | "qq" */
  source: LyricSource
  id: number
  title: string
  /** 艺人数组（后端 candidate_to_dict 输出 artists: list[str]） */
  artists: string[]
  album: string
  score: number
  [key: string]: unknown
}

/** 在线匹配响应。best/candidates/best_ttml 可能为空。 */
export interface MatchResponse {
  track_id: string
  decision: MatchDecision
  reason: string
  best: Candidate | null
  candidates: Candidate[]
  lyrics: unknown
  lyric_source: LyricSource | null
  best_ttml: string | null
}

/** 按候选拉取的 TTML 预览响应。 */
export interface PreviewResponse {
  track_id: string
  candidate_id: number
  source: LyricSource
  ttml: string | null
}

/** sidecar 条目：来源/格式/物理路径/内容。 */
export interface SidecarItem {
  source: LyricSource
  format: "ttml" | "json"
  path: string
  content: string
}

/** sidecar 列表响应。 */
export interface SidecarListResponse {
  track_id: string
  sidecars: SidecarItem[]
}

/** 单个 sidecar GET 响应。format 后端实际只有 "ttml"，类型上放宽为 string。 */
export interface SidecarResponse {
  track_id: string
  source: string
  format: string
  path: string
  content: string
}

/** 写 sidecar 响应。 */
export interface WriteSidecarResponse {
  track_id: string
  source: string
  format: string
  path: string
  written: boolean
}

/** 删除 sidecar 响应（幂等：不存在返回 deleted=false）。 */
export interface DeleteSidecarResponse {
  track_id: string
  source: string
  path: string
  deleted: boolean
}

export interface MatchQuery {
  providers?: string
  limit?: number
  top_n?: number
}

/**
 * 在线匹配歌词。默认 providers=netease,qq。
 * 错误（404 track 不存在 / 422 非数字 id / 503 读音频失败 / 400 未知 provider）
 * 会被 http.ts 抛出，调用方自行 catch。
 */
export async function matchLyrics(
  trackId: string,
  providers = "netease,qq",
  query: MatchQuery = {},
): Promise<MatchResponse> {
  const params = {
    providers,
    limit: query.limit ?? 12,
    top_n: query.top_n ?? 10,
  }
  return http
    .get<MatchResponse>(`/lyrics/${trackId}/match`, { params })
    .then((res) => res.data)
}

/**
 * 按候选拉取 TTML 预览（不重跑匹配，只按 candidate.id 取词）。
 * 用于前端在候选列表里点选任意候选时，按需挂载到预览区。
 * 错误（400 未知 source / 404 track 不存在 / 422 非数字 id）由 http.ts 抛出。
 */
export async function previewCandidate(
  trackId: string,
  candidateId: number,
  source: LyricSource,
): Promise<PreviewResponse> {
  const params = { source, candidate_id: candidateId }
  return http
    .get<PreviewResponse>(`/lyrics/${trackId}/preview`, { params })
    .then((res) => res.data)
}

/** 列出某 track 已有的 sidecar。 */
export async function listSidecars(trackId: string): Promise<SidecarListResponse> {
  return http
    .get<SidecarListResponse>(`/lyrics/${trackId}/sidecars`)
    .then((res) => res.data)
}

/** 读取单个 sidecar（不存在 → 404，由调用方 catch）。 */
export async function readSidecar(
  trackId: string,
  source: LyricSource,
): Promise<SidecarResponse> {
  return http
    .get<SidecarResponse>(`/lyrics/${trackId}/sidecar/${source}`)
    .then((res) => res.data)
}

/** 写 sidecar（采纳歌词 / 编辑器保存）。 */
export async function writeSidecar(
  trackId: string,
  source: LyricSource,
  content: string,
): Promise<WriteSidecarResponse> {
  return http
    .post<WriteSidecarResponse>(`/lyrics/${trackId}/sidecar/${source}`, {
      content,
    })
    .then((res) => res.data)
}

/** 删除 sidecar（幂等）。 */
export async function deleteSidecar(
  trackId: string,
  source: LyricSource,
): Promise<DeleteSidecarResponse> {
  return http
    .delete<DeleteSidecarResponse>(`/lyrics/${trackId}/sidecar/${source}`)
    .then((res) => res.data)
}
