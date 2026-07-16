/**
 * useLyricSync — 歌词同步引擎（composable）
 *
 * 职责：
 * - parseTtmlTime：HH:MM:SS.mmm → 毫秒（对齐后端 _TIME_RE）
 * - parseTtml：DOMParser 解析 TTML `<p>` 的 text + begin/end → LyricLine[]
 * - useLyricSync(currentTimeMs, ttml)：返回 {lines, currentIndex}
 *   - ttml 变化时解析一次（不每帧重解析）
 *   - currentTimeMs 变化时二分查找当前行，只在 currentIndex 真变时赋值（避免重渲染）
 *
 * 约束：
 * - timeupdate ~250ms 触发 watch，够歌词同步，不引入 RAF。
 * - composable 保持框架无关，不做 DOM 滚动（消费组件 watch currentIndex 调 scrollIntoView）。
 */
import type { ComputedRef, Ref } from "vue"

/** 单行歌词：文本 + 起止毫秒。 */
export interface LyricLine {
  text: string
  beginMs: number
  endMs: number
}

/** HH:MM:SS.mmm → 毫秒。容错：无毫秒部分按 0；非法返回 0。 */
export function parseTtmlTime(v: string | null | undefined): number {
  if (!v) return 0
  const m = v.trim().match(/^(?<h>\d{1,3}):(?<m>\d{1,2}):(?<s>\d{1,2})(?:\.(?<ms>\d{1,3}))?$/)
  if (!m || !m.groups) return 0
  const g = m.groups
  return (
    Number(g.h) * 3600000 +
    Number(g.m) * 60000 +
    Number(g.s) * 1000 +
    (g.ms ? Number(g.ms) : 0)
  )
}

/** 解析 TTML 字符串成 LyricLine[]。解析失败抛 Error（调用方 try/catch）。 */
export function parseTtml(ttml: string): LyricLine[] {
  const doc = new window.DOMParser().parseFromString(ttml, "application/xml")
  const parserError = doc.querySelector("parsererror")
  if (parserError) throw new Error("XML 格式错误")
  const nodes = Array.from(doc.getElementsByTagName("p"))
  return nodes
    .map((p) => ({
      text: p.textContent?.trim() ?? "",
      beginMs: parseTtmlTime(p.getAttribute("begin")),
      endMs: parseTtmlTime(p.getAttribute("end")),
    }))
    .filter((l) => l.text)
}

/** 二分查找：最后一个 beginMs <= t 的索引，全 > t 返回 -1。 */
function findCurrentLineIndex(lines: LyricLine[], tMs: number): number {
  let lo = 0
  let hi = lines.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (lines[mid].beginMs <= tMs) {
      ans = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return ans
}

/**
 * 歌词同步引擎。
 * @param currentTimeMs 当前播放时间（毫秒，来自 audioManager.currentTime×1000 或 wavesurfer）
 * @param ttml TTML 字符串（Ref 或 ComputedRef，可为 null）
 * @returns { lines, currentIndex, parseError }
 */
export function useLyricSync(
  currentTimeMs: Ref<number> | ComputedRef<number>,
  ttml: Ref<string | null> | ComputedRef<string | null>,
) {
  const lines = ref<LyricLine[]>([])
  const currentIndex = ref(-1)
  const parseError = ref<string | null>(null)

  function refresh(t: string | null): void {
    if (!t) {
      lines.value = []
      parseError.value = null
      return
    }
    try {
      lines.value = parseTtml(t)
      parseError.value = null
    } catch (e: unknown) {
      lines.value = []
      parseError.value = e instanceof Error ? e.message : "未知解析错误"
    }
    currentIndex.value = -1
  }

  watch(ttml, (v) => refresh(v), { immediate: true })

  watch(currentTimeMs, (t) => {
    if (lines.value.length === 0) return
    if (t < 0) {
      currentIndex.value = -1
      return
    }
    const i = findCurrentLineIndex(lines.value, t)
    // 只在变化时写，避免高频 timeupdate 触发重渲染
    if (i !== currentIndex.value) {
      currentIndex.value = i
    }
  })

  return { lines, currentIndex, parseError }
}
