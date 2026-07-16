import {
  computeDiff,
  extractErrorMessage,
  fetchApple,
  fetchCredits,
  fetchFields,
  writeMeta,
} from "@/apis/meta"
import type {
  AppleResponse,
  AuthoritativeFields,
  CreditsResponse,
  DiffResponse,
  FieldMapResponse,
  FieldStatusKind,
  FieldWithStatus,
  WriteResponse,
} from "@/apis/meta"

/**
 * 元数据 Store（M6-B）
 *
 * 职责：
 * - 编排 Apple / Credits 拉取、diff 对比、写入流程的会话状态
 * - 暴露 loading / error / 结果数据 ref，供组件 storeToRefs 消费
 * - fetchAllMeta：串行拉取 Apple + Credits，合并为统一字段表（带状态标记）
 *
 * 约束：
 * - setup 风格 defineStore；state 全用 ref（禁 reactive）
 * - 只接触数据层（类型 + @/apis/meta 请求封装，后者封装 http）
 * - 错误经 extractErrorMessage 归一为字符串，组件按需展示
 * - 写操作不可逆：doWrite 仅在组件层二次确认后才调用，store 不做二次确认
 */

export const useMetaStore = defineStore("meta", () => {
  // ---- Apple ----
  const appleLoading = ref(false)
  const appleError = ref<string | null>(null)
  const appleResult = ref<AppleResponse | null>(null)

  // ---- Credits ----
  const creditsLoading = ref(false)
  const creditsError = ref<string | null>(null)
  const creditsResult = ref<CreditsResponse | null>(null)

  // ---- Diff ----
  const diffLoading = ref(false)
  const diffError = ref<string | null>(null)
  const diffResult = ref<DiffResponse | null>(null)

  // ---- Write ----
  const writeLoading = ref(false)
  const writeError = ref<string | null>(null)
  const writeResult = ref<WriteResponse | null>(null)

  // ---- 字段映射清单（语义字段名→各容器 mutagen key，供前端构建反向映射）----
  const fieldMap = ref<FieldMapResponse | null>(null)

  // ---- 统一拉取 ----
  const fetchAllLoading = ref(false)
  const fetchAllPhase = ref<"idle" | "apple" | "credits" | "done">("idle")

  // ---- 来源级状态（独立于字段级，用于展示"拉取失败可重试"等） ----
  const appleSourceStatus = ref<FieldStatusKind>("ok")
  const creditsSourceStatus = ref<FieldStatusKind>("ok")

  // ---- 合并字段表（带状态标记） ----
  const fieldStatusMap = ref<Record<string, FieldWithStatus>>({})

  /**
   * 重置某个阶段的状态（切 track / 重试时用）。
   * 不传 phase = 全部重置。
   */
  function reset(phase?: "apple" | "credits" | "diff" | "write" | "fetch-all" | "all"): void {
    const targets: Array<"apple" | "credits" | "diff" | "write" | "fetch-all"> =
      !phase || phase === "all"
        ? ["apple", "credits", "diff", "write", "fetch-all"]
        : [phase]
    for (const p of targets) {
      if (p === "apple") {
        appleLoading.value = false
        appleError.value = null
        appleResult.value = null
        appleSourceStatus.value = "ok"
      } else if (p === "credits") {
        creditsLoading.value = false
        creditsError.value = null
        creditsResult.value = null
        creditsSourceStatus.value = "ok"
      } else if (p === "diff") {
        diffLoading.value = false
        diffError.value = null
        diffResult.value = null
      } else if (p === "write") {
        writeLoading.value = false
        writeError.value = null
        writeResult.value = null
      } else if (p === "fetch-all") {
        fetchAllLoading.value = false
        fetchAllPhase.value = "idle"
        fieldStatusMap.value = {}
        appleSourceStatus.value = "ok"
        creditsSourceStatus.value = "ok"
      }
    }
  }

  /** 拉取 Apple 元数据 */
  async function loadApple(
    trackId: string,
    storefront = "us",
    lang = "zh-Hans",
  ): Promise<AppleResponse | null> {
    appleLoading.value = true
    appleError.value = null
    try {
      const res = await fetchApple(trackId, storefront, lang)
      appleResult.value = res
      return res
    } catch (err: unknown) {
      appleError.value = extractErrorMessage(err, "拉取 Apple 元数据失败")
      appleResult.value = null
      return null
    } finally {
      appleLoading.value = false
    }
  }

  /** 拉取 Credits 元数据 */
  async function loadCredits(
    trackId: string,
    storefront = "us",
  ): Promise<CreditsResponse | null> {
    creditsLoading.value = true
    creditsError.value = null
    try {
      const res = await fetchCredits(trackId, storefront)
      creditsResult.value = res
      return res
    } catch (err: unknown) {
      creditsError.value = extractErrorMessage(err, "拉取 Credits 失败")
      creditsResult.value = null
      return null
    } finally {
      creditsLoading.value = false
    }
  }

  /**
   * 生成 before/after 对比。
   * authoritativeFields 来源：组件可从 apple/credits 结果或手动编辑传入。
   */
  async function loadDiff(
    trackId: string,
    authoritativeFields: AuthoritativeFields,
  ): Promise<DiffResponse | null> {
    diffLoading.value = true
    diffError.value = null
    try {
      const res = await computeDiff(trackId, authoritativeFields)
      diffResult.value = res
      // 进入新 diff 流程时清掉旧 write 结果，避免展示陈旧成功提示
      writeResult.value = null
      writeError.value = null
      return res
    } catch (err: unknown) {
      diffError.value = extractErrorMessage(err, "生成对比失败")
      diffResult.value = null
      return null
    } finally {
      diffLoading.value = false
    }
  }

  /** 拉取字段映射清单（语义→mutagen key，失败不阻塞主流程） */
  async function loadFieldMap(): Promise<FieldMapResponse | null> {
    try {
      const res = await fetchFields()
      fieldMap.value = res
      return res
    } catch (err: unknown) {
      // 字段清单是辅助展示，失败不阻塞主流程，只记日志
      console.error("[meta] loadFieldMap failed:", extractErrorMessage(err, "unknown"))
      return null
    }
  }

  /**
   * 写入标签。不可逆操作——调用方必须在 UI 二次确认后才调用此方法。
   */
  async function doWrite(
    trackId: string,
    afterFields: AuthoritativeFields,
  ): Promise<WriteResponse | null> {
    writeLoading.value = true
    writeError.value = null
    try {
      const res = await writeMeta(trackId, afterFields)
      writeResult.value = res
      return res
    } catch (err: unknown) {
      writeError.value = extractErrorMessage(err, "写入标签失败")
      writeResult.value = null
      return null
    } finally {
      writeLoading.value = false
    }
  }

  /**
   * 根据 appleResult / creditsResult 重建合并字段表（带状态标记）。
   * 合并策略：同字段 Credits 值覆盖 Apple 值（Credits 网页角色信息更细，
   * 是 Apple WebAPI ©wrt 的扩展来源）。
   */
  function _rebuildFieldStatusMap(): void {
    const map: Record<string, FieldWithStatus> = {}

    // Apple 字段先入
    const appleFields = appleResult.value?.authoritative_fields
    if (appleFields) {
      for (const [field, values] of Object.entries(appleFields)) {
        map[field] = { field, values, source: "apple", status: "ok" }
      }
    }

    // Credits 字段覆盖（同 key 以 Credits 为准）
    const creditsFields = creditsResult.value?.authoritative_fields
    if (creditsFields) {
      for (const [field, values] of Object.entries(creditsFields)) {
        map[field] = { field, values, source: "credits", status: "ok" }
      }
    }

    // Credits 永久无哨兵：无 authoritative_fields 但 no_credits=true
    // 此时无字段可标记，但 creditsSourceStatus 已设为 missing_permanent

    // 来源级状态已由 fetchAllMeta 设置，fieldStatusMap 只含实际字段级数据
    fieldStatusMap.value = map
  }

  /**
   * 统一拉取元数据：串行 Apple → Credits。
   * 某源失败不中断另一源。Apple 先（结构化字段，快），Credits 后（网页爬取，慢）。
   */
  async function fetchAllMeta(
    trackId: string,
    storefront = "us",
    lang = "zh-Hans",
  ): Promise<void> {
    fetchAllLoading.value = true
    fetchAllPhase.value = "apple"
    appleSourceStatus.value = "ok"
    creditsSourceStatus.value = "ok"
    fieldStatusMap.value = {}

    // Phase 1: Apple
    const appleRes = await loadApple(trackId, storefront, lang)
    if (!appleRes) {
      appleSourceStatus.value = "failed_retryable"
    }

    // Phase 2: Credits
    fetchAllPhase.value = "credits"
    const creditsRes = await loadCredits(trackId, storefront)
    if (!creditsRes) {
      // 区分永久无 vs 临时失败
      if (creditsResult.value?.no_credits === true) {
        creditsSourceStatus.value = "missing_permanent"
      } else {
        creditsSourceStatus.value = "failed_retryable"
      }
    }

    fetchAllPhase.value = "done"
    fetchAllLoading.value = false

    // 重建合并字段表
    _rebuildFieldStatusMap()
  }

  /** 清空 diffResult（勾选变化时调用，修复 P0 diff 失效 bug） */
  function clearDiff(): void {
    diffResult.value = null
  }

  /** 重试单个失败来源 */
  async function retrySource(
    trackId: string,
    source: "apple" | "credits",
    storefront = "us",
    lang = "zh-Hans",
  ): Promise<void> {
    if (source === "apple") {
      appleSourceStatus.value = "ok"
      const res = await loadApple(trackId, storefront, lang)
      if (!res) {
        appleSourceStatus.value = "failed_retryable"
      }
    } else {
      creditsSourceStatus.value = "ok"
      const res = await loadCredits(trackId, storefront)
      if (!res) {
        if (creditsResult.value?.no_credits === true) {
          creditsSourceStatus.value = "missing_permanent"
        } else {
          creditsSourceStatus.value = "failed_retryable"
        }
      }
    }
    _rebuildFieldStatusMap()
  }

  return {
    // state
    appleLoading,
    appleError,
    appleResult,
    creditsLoading,
    creditsError,
    creditsResult,
    diffLoading,
    diffError,
    diffResult,
    writeLoading,
    writeError,
    writeResult,
    fieldMap,
    fetchAllLoading,
    fetchAllPhase,
    appleSourceStatus,
    creditsSourceStatus,
    fieldStatusMap,
    // actions
    reset,
    loadApple,
    loadCredits,
    loadDiff,
    loadFieldMap,
    doWrite,
    fetchAllMeta,
    clearDiff,
    retrySource,
  }
})
