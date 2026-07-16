/**
 * useLyricSync — 歌词同步引擎（composable）
 *
 * 职责：
 * - parseTtmlTime：HH:MM:SS.mmm → 毫秒（对齐后端 _TIME_RE）
 * - parseTtml：DOMParser 解析 TTML `<p>` 的 text + begin/end + 内嵌 `<span>` → LyricLine[]
 *   （逐字行 spans 非空，纯文本行 spans 为空）
 * - useLyricSync(currentTimeMs, ttml)：返回 {lines, currentIndex, currentSpanIndex}
 *   - ttml 变化时解析一次（不每帧重解析）
 *   - currentTimeMs 变化时二分查找当前行 + 行内当前 span，只在真变时赋值（避免重渲染）
 *
 * 约束：
 * - timeupdate ~250ms 触发 watch，够歌词同步，不引入 RAF。
 * - composable 保持框架无关，不做 DOM 滚动（消费组件 watch currentIndex 调 scrollIntoView）。
 */
import type { ComputedRef, Ref } from "vue"

/* global Document, Element */

/** 单个逐字 span：文本 + 起止毫秒。 */
export interface LyricSpan {
  text: string
  beginMs: number
  endMs: number
}

/** 单行歌词：文本 + 起止毫秒 + 逐字 spans（纯文本行为空数组）。
 *
 * key：行 key（TTML <p key="L1">），用于配对 translation/transliteration 行。
 * translation：整行翻译文本（逐行，无逐字）。
 * transliteration：注音/罗马音 spans（逐字=多 span；逐行=单 span 整行）。
 * 三者皆可选——无翻译/注音的行对应字段 undefined。
 */
export interface LyricLine {
  text: string
  beginMs: number
  endMs: number
  spans: LyricSpan[]
  key?: string
  translation?: string
  transliteration?: LyricSpan[]
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

/** 读单个 <p> 元素 → { text, beginMs, endMs, spans, key }（逐字 span 或纯文本行）。 */
function parseP(p: Element): {
  text: string
  beginMs: number
  endMs: number
  spans: LyricSpan[]
  key: string
} {
  const spans = parseSpans(p)
  return {
    text: p.textContent?.trim() ?? "",
    beginMs: parseTtmlTime(p.getAttribute("begin")),
    endMs: parseTtmlTime(p.getAttribute("end")),
    spans,
    key: p.getAttribute("key") ?? "",
  }
}

/** 读元素内所有 <span begin end> → LyricSpan[]（逐字时间轴）。无文本 span 过滤掉。 */
function parseSpans(el: Element): LyricSpan[] {
  return Array.from(el.getElementsByTagName("span"))
    .map((s) => ({
      text: s.textContent?.trim() ?? "",
      beginMs: parseTtmlTime(s.getAttribute("begin")),
      endMs: parseTtmlTime(s.getAttribute("end")),
    }))
    .filter((s) => s.text)
}

/**
 * 解析 TTML 字符串成 LyricLine[]（多 div track：main + translation + transliteration）。
 *
 * 读 <body> 下所有 <div>，按 role 属性分流：
 * - role="main"（或无 role）：主歌词行
 * - role="translation"：翻译行（逐行纯文本），按 key 配对到主歌词行 .translation
 * - role="transliteration"：注音行（逐字 span 或逐行纯文本），按 key 配对到 .transliteration
 * 兼容老 <head><metadata> 的 <text for="Lx"> 形态：fallback 读 metadata 的
 * translation/transliteration track，按 for 属性配对。
 * 解析失败抛 Error（调用方 try/catch）。
 */
export function parseTtml(ttml: string): LyricLine[] {
  const doc = new window.DOMParser().parseFromString(ttml, "application/xml")
  const parserError = doc.querySelector("parsererror")
  if (parserError) throw new Error("XML 格式错误")

  const body = doc.querySelector("body")
  if (!body) return []

  const mainLines: LyricLine[] = []
  const translationByKey = new Map<string, string>()
  const transliterationByKey = new Map<string, LyricSpan[]>()

  for (const div of Array.from(body.getElementsByTagName("div"))) {
    const role = div.getAttribute("role") ?? ""
    for (const p of Array.from(div.getElementsByTagName("p"))) {
      const parsed = parseP(p)
      if (!parsed.text && parsed.spans.length === 0) continue
      if (role === "translation") {
        if (parsed.key && parsed.text) translationByKey.set(parsed.key, parsed.text)
      } else if (role === "transliteration") {
        if (parsed.key) {
          // 逐字注音=多 span；逐行注音=单 span 整行（parseP 已把纯文本 p 的 spans 置空，
          // 退化成整行文本存为单 span，保留行时间以便逐字高亮逻辑统一）
          const trSpans: LyricSpan[] = parsed.spans.length > 0
            ? parsed.spans
            : [{ text: parsed.text, beginMs: parsed.beginMs, endMs: parsed.endMs }]
          if (parsed.text) transliterationByKey.set(parsed.key, trSpans)
        }
      } else {
        // main（无 role 或 role="main"）
        mainLines.push({
          text: parsed.text,
          beginMs: parsed.beginMs,
          endMs: parsed.endMs,
          spans: parsed.spans,
          key: parsed.key || undefined,
        })
      }
    }
  }

  // fallback：老 metadata <text for="Lx"> 形态（无多 div track 时）
  if (translationByKey.size === 0 && transliterationByKey.size === 0) {
    readMetadataTracks(doc, translationByKey, transliterationByKey)
  }

  // 配对到主歌词行
  for (const line of mainLines) {
    if (line.key) {
      const tr = translationByKey.get(line.key)
      if (tr) line.translation = tr
      const roma = transliterationByKey.get(line.key)
      if (roma) line.transliteration = roma
    }
  }
  return mainLines.filter((l) => l.text)
}

/** 读老式 <head><metadata> 的 translation/transliteration track（<text for="Lx">）作 fallback。 */
function readMetadataTracks(
  doc: Document,
  translationByKey: Map<string, string>,
  transliterationByKey: Map<string, LyricSpan[]>,
): void {
  const metadata = doc.querySelector("head > metadata")
  if (!metadata) return
  for (const track of Array.from(metadata.children)) {
    const tag = track.tagName.toLowerCase()
    const role = tag === "translation" ? "translation"
      : tag === "transliteration" ? "transliteration"
      : ""
    if (!role) continue
    for (const tx of Array.from(track.children)) {
      if (tx.tagName.toLowerCase() !== "text") continue
      const key = tx.getAttribute("for") ?? ""
      if (!key) continue
      if (role === "translation") {
        // 翻译：纯文本整行（LyricLine.translation 是 string，不存逐字）
        const text = tx.textContent?.trim() ?? ""
        if (text) translationByKey.set(key, text)
      } else {
        // 注音：优先读 <text for> 内逐字 <span begin end>（QQ contentroma 逐字罗马音）；
        // 无 span 则纯文本整行存单 span（netease romalrc 逐行，时间 0 由逐字高亮逻辑兜底）
        const spans = parseSpans(tx)
        if (spans.length > 0) {
          transliterationByKey.set(key, spans)
        } else {
          const text = tx.textContent?.trim() ?? ""
          if (text) transliterationByKey.set(key, [{ text, beginMs: 0, endMs: 0 }])
        }
      }
    }
  }
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
 * 行内二分：找当前 span。
 * @returns span 索引；纯文本行(spans 空) 或 当前无活跃 span（已结束未续）返回 -1。
 * 消费方见 -1 即退化为整行高亮。
 */
export function findCurrentSpanIndex(spans: LyricSpan[], tMs: number): number {
  if (spans.length === 0) return -1
  let lo = 0
  let hi = spans.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (spans[mid].beginMs <= tMs) {
      ans = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  // 已结束未续（尾部 span 结束后到下一行 begin 之间的 gap）→ 无活跃 span
  if (ans >= 0 && spans[ans].endMs <= tMs) return -1
  return ans
}

/**
 * 歌词同步引擎。
 * @param currentTimeMs 当前播放时间（毫秒，来自 audioManager.currentTime×1000 或 wavesurfer）
 * @param ttml TTML 字符串（Ref 或 ComputedRef，可为 null）
 * @returns { lines, currentIndex, currentSpanIndex, parseError }
 */
export function useLyricSync(
  currentTimeMs: Ref<number> | ComputedRef<number>,
  ttml: Ref<string | null> | ComputedRef<string | null>,
) {
  const lines = ref<LyricLine[]>([])
  const currentIndex = ref(-1)
  const currentSpanIndex = ref(-1)
  /** 当前行注音 span 索引（逐字注音高亮；无注音/逐行注音返回 -1 整行高亮） */
  const currentTransliterationSpanIndex = ref(-1)
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
    currentSpanIndex.value = -1
    currentTransliterationSpanIndex.value = -1
  }

  watch(ttml, (v) => refresh(v), { immediate: true })

  watch(currentTimeMs, (t) => {
    if (lines.value.length === 0) return
    if (t < 0) {
      currentIndex.value = -1
      currentSpanIndex.value = -1
      currentTransliterationSpanIndex.value = -1
      return
    }
    const i = findCurrentLineIndex(lines.value, t)
    if (i !== currentIndex.value) {
      currentIndex.value = i
    }
    // 行内主歌词 span 索引（纯文本行返回 -1）
    const si = i >= 0 ? findCurrentSpanIndex(lines.value[i].spans, t) : -1
    if (si !== currentSpanIndex.value) {
      currentSpanIndex.value = si
    }
    // 当前行注音 span 索引（逐字注音；逐行注音/无注音返回 -1）
    const trSpans = i >= 0 ? lines.value[i].transliteration : undefined
    const ti = trSpans ? findCurrentSpanIndex(trSpans, t) : -1
    if (ti !== currentTransliterationSpanIndex.value) {
      currentTransliterationSpanIndex.value = ti
    }
  })

  return { lines, currentIndex, currentSpanIndex, currentTransliterationSpanIndex, parseError }
}
