import type { EditorSource, LyricDocModel, PatchSpanRequest } from "@/apis/editor"
import {
  getLyricDoc,
  patchSpan,
  postLyricDoc,
} from "@/apis/editor"

/**
 * 逐字歌词编辑器 Store
 *
 * 职责：
 * - 加载某 track 某 source 的 LyricDocModel（getLyricDoc）
 * - 局部 PATCH（改 span / line 的 begin/end）
 * - 全量保存（postLyricDoc）
 * - 维护 loading / patching / saving / error 状态供视图消费
 *
 * 约束：
 * - auto-import 已注入 defineStore / ref / computed，不要手动 import
 * - state 全用 ref，禁 reactive
 * - catch 必须 unknown，错误经 normalizeEditorError 归一化
 * - 只 import 类型和 apis/editor
 */

/** 选中项：span/line 索引 + 该 span/line 的 begin/end 副本（用于编辑面板）。 */
export interface Selection {
  lineIndex: number
  spanIndex: number | null
  beginMs: number
  endMs: number
}

export const useEditorStore = defineStore("editor", () => {
  // ---- 文档状态 ----
  const doc = ref<LyricDocModel | null>(null)
  const source = ref<EditorSource>("apple")
  const loading = ref(false)
  const loadError = ref<string | null>(null)

  // ---- 局部 PATCH ----
  const patching = ref(false)
  const patchError = ref<string | null>(null)
  const lastPatchOk = ref(false)

  // ---- 全量保存 ----
  const saving = ref(false)
  const saveError = ref<string | null>(null)
  const lastSavePath = ref<string | null>(null)

  // ---- 选中项 ----
  const selection = ref<Selection | null>(null)

  /** 当前选中的 line（根据 selection.lineIndex 取，越界返回 null）。 */
  const selectedLine = computed(() => {
    if (!doc.value || !selection.value) return null
    return doc.value.lines[selection.value.lineIndex] ?? null
  })

  /** 当前选中的 span（spanIndex 为 null 表示选的是行级，无 span）。 */
  const selectedSpan = computed(() => {
    const line = selectedLine.value
    const si = selection.value?.spanIndex ?? null
    if (!line || si === null) return null
    return line.spans[si] ?? null
  })

  /** 派生：行列表（便于 SpanTimeline 直接消费）。 */
  const lines = computed(() => doc.value?.lines ?? [])

  /**
   * 加载某 track 某 source 的歌词文档。
   * 成功后清空 selection / error。
   */
  async function loadDoc(trackId: string, src: EditorSource): Promise<void> {
    source.value = src
    loading.value = true
    loadError.value = null
    try {
      doc.value = await getLyricDoc(trackId, src)
      selection.value = null
    } catch (e: unknown) {
      doc.value = null
      loadError.value = normalizeEditorError(e, "load")
    } finally {
      loading.value = false
    }
  }

  /**
   * 局部 PATCH：改某 line 或 span 的 begin/end。
   * 成功后用返回的 doc 覆盖本地，并同步 selection 的 begin/end。
   */
  async function patchSelection(
    trackId: string,
    body: PatchSpanRequest,
  ): Promise<boolean> {
    patching.value = true
    patchError.value = null
    lastPatchOk.value = false
    try {
      const res = await patchSpan(trackId, source.value, body)
      doc.value = res.doc
      // 同步 selection：保持选中索引，但刷新 begin/end 副本
      if (selection.value) {
        const line = res.doc.lines[body.line_index]
        if (line) {
          if (body.span_index !== null) {
            const span = line.spans[body.span_index]
            if (span) {
              selection.value = {
                lineIndex: body.line_index,
                spanIndex: body.span_index,
                beginMs: span.begin_ms,
                endMs: span.end_ms,
              }
            }
          } else {
            selection.value = {
              lineIndex: body.line_index,
              spanIndex: null,
              beginMs: line.begin_ms,
              endMs: line.end_ms,
            }
          }
        }
      }
      lastPatchOk.value = true
      return true
    } catch (e: unknown) {
      patchError.value = normalizeEditorError(e, "patch")
      return false
    } finally {
      patching.value = false
    }
  }

  /**
   * 全量保存：POST 当前 doc（含 source）。路径目标由 body.source 决定。
   */
  async function saveDoc(trackId: string): Promise<boolean> {
    if (!doc.value) return false
    saving.value = true
    saveError.value = null
    lastSavePath.value = null
    try {
      const res = await postLyricDoc(trackId, doc.value)
      doc.value = res.doc
      lastSavePath.value = res.path
      return true
    } catch (e: unknown) {
      saveError.value = normalizeEditorError(e, "save")
      return false
    } finally {
      saving.value = false
    }
  }

  /** 选中某 span/line（来自 SpanTimeline 的点击）。 */
  function select(sel: Selection): void {
    selection.value = { ...sel }
    lastPatchOk.value = false
    patchError.value = null
  }

  /** 清空选中。 */
  function clearSelection(): void {
    selection.value = null
    patchError.value = null
    lastPatchOk.value = false
  }

  function resetAll(): void {
    doc.value = null
    source.value = "apple"
    loading.value = false
    loadError.value = null
    patching.value = false
    patchError.value = null
    lastPatchOk.value = false
    saving.value = false
    saveError.value = null
    lastSavePath.value = null
    selection.value = null
  }

  return {
    // 状态
    doc,
    source,
    loading,
    loadError,
    patching,
    patchError,
    lastPatchOk,
    saving,
    saveError,
    lastSavePath,
    selection,
    // 派生
    selectedLine,
    selectedSpan,
    lines,
    // actions
    loadDoc,
    patchSelection,
    saveDoc,
    select,
    clearSelection,
    resetAll,
  }
})

/**
 * 编辑器错误归一化：把 http 错误转成本地化文案。
 * phase 用于区分加载/打补丁/全量保存阶段，给出更精准的提示。
 */
function normalizeEditorError(e: unknown, phase: "load" | "patch" | "save"): string {
  const verb =
    phase === "load" ? "加载" : phase === "patch" ? "写回此项" : "全量保存"
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { status?: number; data?: unknown } }).response
    if (resp?.status === 400) {
      if (phase === "patch") return "越界索引或不支持的 source"
      return "不支持的 source"
    }
    if (resp?.status === 404) return "track 或 sidecar 不存在"
    if (resp?.status === 422) return "track_id 非数字"
    if (resp?.status === 503) return "store 未初始化"
    if (resp?.status === 500) return "歌词解析失败"
  }
  if (e instanceof Error) return `${verb}失败：${e.message}`
  return `${verb}失败`
}
