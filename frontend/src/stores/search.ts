import { searchTracks } from "@/apis/library"
import type { TrackItem } from "@/apis/library"

/* global setTimeout, clearTimeout */

/**
 * 全局搜索 Modal store（⌘K / Ctrl+K 触发）
 *
 * 单例状态：open/query/results/loading/activeIndex。
 * SearchModal.vue 消费渲染；App.vue（或任意按钮）调 open() 打开。
 *
 * 输入 debounce 200ms 后调 /api/library/search；空 query 清空结果。
 * 键盘导航：moveActive(+1/-1) 上下选，selectActive() 选中跳转。
 *
 * 约束：auto-import 已注入 defineStore / ref，不要手动 import。
 */

const DEBOUNCE_MS = 200
const RESULT_LIMIT = 10

export const useSearchStore = defineStore("search", () => {
  const open = ref(false)
  const query = ref("")
  const results = ref<TrackItem[]>([])
  const loading = ref(false)
  const activeIndex = ref(-1) // -1 = 无选中；键盘上下移动

  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let lastReqId = 0

  function setOpen(v: boolean): void {
    open.value = v
    if (!v) {
      // 关闭时清状态（下次打开是干净的）
      query.value = ""
      results.value = []
      loading.value = false
      activeIndex.value = -1
      if (debounceTimer) {
        clearTimeout(debounceTimer)
        debounceTimer = null
      }
    }
  }

  function openModal(): void {
    setOpen(true)
  }

  /** 输入变化：debounce 后搜。清空时立即清结果。 */
  function onInput(value: string): void {
    query.value = value
    activeIndex.value = -1
    if (debounceTimer) {
      clearTimeout(debounceTimer)
    }
    const trimmed = value.trim()
    if (!trimmed) {
      results.value = []
      loading.value = false
      return
    }
    loading.value = true
    debounceTimer = setTimeout(() => {
      void runSearch(trimmed)
    }, DEBOUNCE_MS)
  }

  async function runSearch(q: string): Promise<void> {
    const reqId = ++lastReqId
    try {
      const res = await searchTracks(q, RESULT_LIMIT)
      // 丢弃过期请求（用户已继续输入）
      if (reqId !== lastReqId) return
      results.value = res.items
      activeIndex.value = res.items.length > 0 ? 0 : -1
    } catch {
      if (reqId !== lastReqId) return
      results.value = []
      activeIndex.value = -1
    } finally {
      if (reqId === lastReqId) loading.value = false
    }
  }

  /** 键盘上下移动选中项，clamp 在 [-1, len-1]。 */
  function moveActive(delta: number): void {
    const len = results.value.length
    if (len === 0) return
    const next = activeIndex.value + delta
    activeIndex.value = Math.max(-1, Math.min(len - 1, next))
  }

  /** 返回当前选中项（或 null）。调用方负责跳转 + 关闭。 */
  function activeItem(): TrackItem | null {
    const i = activeIndex.value
    if (i < 0 || i >= results.value.length) return null
    return results.value[i]
  }

  return {
    open,
    query,
    results,
    loading,
    activeIndex,
    setOpen,
    openModal,
    onInput,
    moveActive,
    activeItem,
  }
})
