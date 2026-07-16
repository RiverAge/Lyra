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
  /** 艺人模糊匹配（LIKE），不传=不过滤 */
  artist?: string
  /** 专辑模糊匹配（LIKE），不传=不过滤 */
  album?: string
  /** 编码格式精确匹配（大小写不敏感，如 ALAC），不传=不过滤 */
  codec?: string
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
  // 只透传非空过滤参数（空串/undefined 不发，避免后端按空串过滤）
  if (query.artist) params.artist = query.artist
  if (query.album) params.album = query.album
  if (query.codec) params.codec = query.codec
  return http.get<LibraryPage>("/library", { params }).then((res) => res.data)
}

export async function fetchLibraryStats(): Promise<LibraryStats> {
  return http.get<LibraryStats>("/library/stats").then((res) => res.data)
}

export async function fetchTrackById(id: string): Promise<TrackItem> {
  return http.get<TrackItem>(`/library/${id}`).then((res) => res.data)
}

