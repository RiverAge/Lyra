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
  FieldMap,
  WriteResponse,
} from "@/apis/meta"

/**
 * 元数据 Store（M6-B）
 *
 * 职责：
 * - 编排 Apple / Credits 拉取、diff 对比、写入流程的会话状态
 * - 暴露 loading / error / 结果数据 ref，供组件 storeToRefs 消费
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

  // ---- 字段映射清单（用于展示字段名→标签映射，可选懒载） ----
  const fieldMap = ref<FieldMap | null>(null)

  /**
   * 重置某个阶段的状态（切 track / 重试时用）。
   * 不传 phase = 全部重置。
   */
  function reset(phase?: "apple" | "credits" | "diff" | "write" | "all"): void {
    const targets: Array<"apple" | "credits" | "diff" | "write"> =
      !phase || phase === "all"
        ? ["apple", "credits", "diff", "write"]
        : [phase]
    for (const p of targets) {
      if (p === "apple") {
        appleLoading.value = false
        appleError.value = null
        appleResult.value = null
      } else if (p === "credits") {
        creditsLoading.value = false
        creditsError.value = null
        creditsResult.value = null
      } else if (p === "diff") {
        diffLoading.value = false
        diffError.value = null
        diffResult.value = null
      } else if (p === "write") {
        writeLoading.value = false
        writeError.value = null
        writeResult.value = null
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

  /** 拉取字段映射清单（可选） */
  async function loadFieldMap(): Promise<FieldMap | null> {
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
    // actions
    reset,
    loadApple,
    loadCredits,
    loadDiff,
    loadFieldMap,
    doWrite,
  }
})
