import type { TrackItem, LibraryPage, LibraryStats } from "@/apis/library"
import { fetchLibrary, fetchLibraryStats } from "@/apis/library"

/**
 * 曲库 Store
 *
 * 职责：
 * - 维护曲库分页列表（items/total/limit/offset）
 * - 维护曲库聚合统计（stats：曲目数/专辑数/总时长/无损占比）
 * - 提供 loadPage(pageSize, pageNo) 翻页能力 + loadStats() 刷新统计
 *
 * 全局搜索走 ⌘K SearchModal（跨库模糊匹配跳详情页），列表只做分页浏览，
 * 不再有列表内筛选（FilterBar 已移除）。
 *
 * 约束：
 * - auto-import 已注入 defineStore / ref，不要手动 import
 * - state 全用 ref，禁 reactive
 */

export const useLibraryStore = defineStore("library", () => {
  // 列表数据
  const items = ref<TrackItem[]>([])
  const total = ref(0)
  const limit = ref(20)
  const offset = ref(0)

  // 聚合统计
  const stats = ref<LibraryStats | null>(null)
  const statsLoading = ref(false)

  // 状态
  const loading = ref(false)
  const error = ref<string | null>(null)

  // 派生：当前页码（从 1 开始）
  const page = computed(() => Math.floor(offset.value / limit.value) + 1)
  const totalPages = computed(() =>
    limit.value > 0 ? Math.max(1, Math.ceil(total.value / limit.value)) : 1,
  )

  async function loadPage(pageNo: number, pageSize = limit.value): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const nextOffset = Math.max(0, (pageNo - 1) * pageSize)
      const result: LibraryPage = await fetchLibrary({
        limit: pageSize,
        offset: nextOffset,
      })
      items.value = result.items
      total.value = result.total
      limit.value = result.limit || pageSize
      offset.value = result.offset
    } catch (e: unknown) {
      error.value = normalizeError(e)
    } finally {
      loading.value = false
    }
  }

  /** 刷新聚合统计（与列表独立加载，互不阻塞） */
  async function loadStats(): Promise<void> {
    statsLoading.value = true
    try {
      stats.value = await fetchLibraryStats()
    } catch {
      // 统计加载失败不阻塞主列表；保留旧 stats（若有）
      statsLoading.value = false
      return
    }
    statsLoading.value = false
  }

  /**
   * 直接设置 stats（SSE 扫描完成事件带 stats 回调用）。
   * 跳过 HTTP——后端完成事件已算好 stats 推过来，省一次全表聚合请求。
   */
  function setStats(s: LibraryStats): void {
    stats.value = s
    statsLoading.value = false
  }

  // 重新加载当前页 + 刷新统计
  async function reload(): Promise<void> {
    await loadPage(page.value, limit.value)
    await loadStats()
  }

  // 上一页 / 下一页
  async function nextPage(): Promise<void> {
    if (page.value < totalPages.value) {
      await loadPage(page.value + 1, limit.value)
    }
  }

  async function prevPage(): Promise<void> {
    if (page.value > 1) {
      await loadPage(page.value - 1, limit.value)
    }
  }

  function reset(): void {
    items.value = []
    total.value = 0
    offset.value = 0
    stats.value = null
    error.value = null
    loading.value = false
  }

  return {
    items,
    total,
    limit,
    offset,
    stats,
    statsLoading,
    loading,
    error,
    page,
    totalPages,
    loadPage,
    loadStats,
    setStats,
    reload,
    nextPage,
    prevPage,
    reset,
  }
})

/**
 * 简易错误归一化：将任意 unknown 错误转成字符串。
 * 业务层尽量用本地化的文案，这里只兜底。
 */
function normalizeError(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { status?: number; data?: unknown } }).response
    if (resp?.status === 503) {
      return "曲库尚未初始化，请先触发扫描或检查后端配置"
    }
    if (resp?.status === 404) {
      return "未找到曲库资源"
    }
  }
  if (e instanceof Error) return e.message
  return "请求失败"
}
