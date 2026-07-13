import { http } from "@/apis/http"

/**
 * 曲库 API
 *
 * 后端契约：GET /library?limit=20&offset=0
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

export async function fetchLibrary(query: LibraryQuery = {}): Promise<LibraryPage> {
  const params = {
    limit: query.limit ?? 20,
    offset: query.offset ?? 0,
  }
  return http.get<LibraryPage>("/library", { params }).then((res) => res.data)
}

export async function fetchTrackById(id: string): Promise<TrackItem> {
  return http.get<TrackItem>(`/library/${id}`).then((res) => res.data)
}
