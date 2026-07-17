import { http } from "@/apis/http"

/**
 * 曲库 API
 *
 * 后端契约：
 * - GET /library?limit&offset&artist&album&codec → {items,total,limit,offset}
 * - GET /library/stats → {track_count,album_count,total_duration_sec,lossless_ratio}
 * 响应已由 http.ts 拦截器解包，直接用返回值。
 */

export interface TrackItem {
  id: string
  title: string
  artist: string
  album: string
  path: string
  codec: string
  duration: number
  [key: string]: unknown
}

export interface LibraryPage {
  items: TrackItem[]
  total: number
  limit: number
  offset: number
}

export interface LibraryQuery {
  limit?: number
  offset?: number
}

export interface LibraryStats {
  track_count: number
  album_count: number
  total_duration_sec: number
  lossless_ratio: number
}

export async function fetchLibrary(query: LibraryQuery = {}): Promise<LibraryPage> {
  const params: Record<string, string | number> = {
    limit: query.limit ?? 20,
    offset: query.offset ?? 0,
  }
  return http.get<LibraryPage>("/library", { params }).then((res) => res.data)
}

export async function fetchLibraryStats(): Promise<LibraryStats> {
  // 聚合统计在扫描期可能慢（后端有缓存但首次扫描/缓存失效时仍走全表扫），
  // 给比默认 15s 更长的超时，避免首页统计卡空白。扫描结束后瞬返回。
  return http
    .get<LibraryStats>("/library/stats", { timeout: 45000 })
    .then((res) => res.data)
}

/** 搜索结果条目（复用 TrackItem 结构，列表列集无 tag_map） */
export interface LibrarySearchResult {
  items: TrackItem[]
  q: string
  limit: number
}

/** 全局搜索（⌘K 搜索框用）：跨 title/artist/album 模糊匹配，返回前 N 条。 */
export async function searchTracks(
  q: string,
  limit = 10,
): Promise<LibrarySearchResult> {
  return http
    .get<LibrarySearchResult>("/library/search", { params: { q, limit } })
    .then((res) => res.data)
}

export async function fetchTrackById(id: string): Promise<TrackItem> {
  return http.get<TrackItem>(`/library/${id}`).then((res) => res.data)
}

