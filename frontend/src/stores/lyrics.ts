import type {
  Candidate,
  DeleteSidecarResponse,
  LyricSource,
  MatchDecision,
  MatchResponse,
  SidecarItem,
  WriteSidecarResponse,
} from "@/apis/lyrics"
import {
  deleteSidecar,
  listSidecars,
  matchLyrics,
  writeSidecar,
} from "@/apis/lyrics"

/**
 * 歌词 Store
 *
 * 职责：
 * - 在线匹配状态（decision/reason/best/candidates/best_ttml/lyric_source）
 * - 已有 sidecar 列表
 * - 提供 match / loadSidecars / adopt / removeSidecar 操作
 * - 维护 loading/error 状态供视图消费
 *
 * 约束：
 * - auto-import 已注入 defineStore / ref / computed，不要手动 import
 * - state 全用 ref，禁 reactive
 * - catch 必须 unknown，错误经 normalizeError 归一化
 * - 只 import 类型和 apis/lyrics
 */

export const useLyricsStore = defineStore("lyrics", () => {
  // ---- 在线匹配 ----
  const matchResult = ref<MatchResponse | null>(null)
  const matching = ref(false)
  const matchError = ref<string | null>(null)

  // ---- 已有 sidecar ----
  const sidecars = ref<SidecarItem[]>([])
  const loadingSidecars = ref(false)
  const sidecarsError = ref<string | null>(null)

  // ---- 写操作（采纳 / 删除）----
  const writing = ref(false)
  const deleting = ref<LyricSource | null>(null)
  const writeError = ref<string | null>(null)
  const lastMessage = ref<string | null>(null)

  // ---- 派生：匹配决策相关 ----
  const decision = computed<MatchDecision | null>(
    () => matchResult.value?.decision ?? null,
  )
  const reason = computed<string>(() => matchResult.value?.reason ?? "")
  const best = computed<Candidate | null>(() => matchResult.value?.best ?? null)
  const candidates = computed<Candidate[]>(() => matchResult.value?.candidates ?? [])
  const bestTtml = computed<string | null>(
    () => matchResult.value?.best_ttml ?? null,
  )
  const lyricSource = computed<LyricSource | null>(
    () => matchResult.value?.lyric_source ?? null,
  )

  /** 是否可采纳：有真实 ttml 且来源合法（netease/qq）。 */
  const canAdopt = computed<boolean>(() => {
    if (!bestTtml.value) return false
    const src = lyricSource.value
    return src === "netease" || src === "qq"
  })

  /** 在线匹配。 */
  async function runMatch(trackId: string, providers = "netease,qq"): Promise<void> {
    matching.value = true
    matchError.value = null
    lastMessage.value = null
    try {
      const result = await matchLyrics(trackId, providers)
      matchResult.value = result
    } catch (e: unknown) {
      matchError.value = normalizeMatchError(e)
    } finally {
      matching.value = false
    }
  }

  /** 加载已有 sidecar 列表。 */
  async function loadSidecars(trackId: string): Promise<void> {
    loadingSidecars.value = true
    sidecarsError.value = null
    try {
      const result = await listSidecars(trackId)
      sidecars.value = result.sidecars
    } catch (e: unknown) {
      sidecarsError.value = normalizeSidecarError(e)
    } finally {
      loadingSidecars.value = false
    }
  }

  /** 采纳最佳匹配 → 写 sidecar。source 用 lyric_source（netease/qq），不是 apple。 */
  async function adoptBest(trackId: string): Promise<boolean> {
    if (!bestTtml.value || !canAdopt.value) return false
    const source = lyricSource.value
    if (!source) return false
    writing.value = true
    writeError.value = null
    lastMessage.value = null
    try {
      const res: WriteSidecarResponse = await writeSidecar(
        trackId,
        source,
        bestTtml.value as string,
      )
      if (res.written) {
        lastMessage.value = `已写入 ${source} sidecar：${res.path}`
      } else {
        lastMessage.value = `写入未生效（${source}）`
      }
      // 写后刷新 sidecar 列表
      await loadSidecars(trackId)
      return res.written
    } catch (e: unknown) {
      writeError.value = normalizeSidecarError(e)
      return false
    } finally {
      writing.value = false
    }
  }

  /** 删除 sidecar。 */
  async function removeSidecar(trackId: string, source: LyricSource): Promise<boolean> {
    deleting.value = source
    writeError.value = null
    lastMessage.value = null
    try {
      const res: DeleteSidecarResponse = await deleteSidecar(trackId, source)
      if (res.deleted) {
        sidecars.value = sidecars.value.filter((s) => s.source !== source)
        lastMessage.value = `已删除 ${source} sidecar`
      } else {
        lastMessage.value = `${source} sidecar 不存在（幂等）`
      }
      return res.deleted
    } catch (e: unknown) {
      writeError.value = normalizeSidecarError(e)
      return false
    } finally {
      deleting.value = null
    }
  }

  function resetMatch(): void {
    matchResult.value = null
    matchError.value = null
  }

  function resetAll(): void {
    matchResult.value = null
    matchError.value = null
    sidecars.value = []
    loadingSidecars.value = false
    sidecarsError.value = null
    writing.value = false
    deleting.value = null
    writeError.value = null
    lastMessage.value = null
  }

  return {
    // 在线匹配
    matchResult,
    matching,
    matchError,
    decision,
    reason,
    best,
    candidates,
    bestTtml,
    lyricSource,
    canAdopt,
    // sidecar
    sidecars,
    loadingSidecars,
    sidecarsError,
    // 写操作
    writing,
    deleting,
    writeError,
    lastMessage,
    // actions
    runMatch,
    loadSidecars,
    adoptBest,
    removeSidecar,
    resetMatch,
    resetAll,
  }
})

/**
 * 匹配错误归一化：把 http 错误转成本地化文案。
 */
function normalizeMatchError(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { status?: number; data?: unknown } }).response
    if (resp?.status === 404) return "曲目不存在"
    if (resp?.status === 422) return "track_id 非数字"
    if (resp?.status === 503) return "读取音频失败（store 未初始化或音频损坏）"
    if (resp?.status === 400) return "未知的 provider"
  }
  if (e instanceof Error) return e.message
  return "在线匹配失败"
}

/**
 * sidecar 错误归一化。
 */
function normalizeSidecarError(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { status?: number; data?: unknown } }).response
    if (resp?.status === 404) return "sidecar 不存在"
    if (resp?.status === 422) return "track_id 非数字"
    if (resp?.status === 400) return "未知的 source"
  }
  if (e instanceof Error) return e.message
  return "sidecar 操作失败"
}
