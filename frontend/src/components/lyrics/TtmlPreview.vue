<template>
  <div class="rounded-md border border-default bg-subtle p-3">
    <!-- 头部：行数统计 -->
    <div class="mb-2 flex items-center justify-between">
      <span class="text-sm font-medium text-primary">TTML 预览</span>
      <span class="text-xs text-tertiary">{{ lineCount }} 行</span>
    </div>

    <!-- 无内容 -->
    <p v-if="!ttml" class="text-sm text-tertiary">
      无内容
    </p>

    <!-- 解析失败 -->
    <p v-else-if="parseError" class="text-sm text-danger">
      解析失败：{{ parseError }}
    </p>

    <!-- 解析成功：逐行纯文本 -->
    <div v-else class="max-h-80 overflow-auto">
      <p
        v-for="(line, idx) in lines"
        :key="idx"
        class="whitespace-pre-wrap break-words py-0.5 text-sm text-primary"
      >
        {{ line }}
      </p>
      <p v-if="lines.length === 0" class="text-sm text-tertiary">
        未提取到歌词行
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * TTML 渲染预览
 *
 * 职责：
 * - 接收 TTML 字符串 prop，纯文本逐行展示（不渲染时间轴）
 * - 解析失败时给出错误提示而非崩
 *
 * 约束：
 * - 用 DOMParser（浏览器原生 XML 解析），不引入第三方依赖
 * - 不直接 fetch / XMLHttpRequest（style-guard + eslint 双重禁止）
 * - auto-import 已注入 ref / computed / watch
 */
const props = defineProps<{ ttml: string | null }>()

const lines = ref<string[]>([])
const parseError = ref<string | null>(null)

const lineCount = computed(() => lines.value.length)

/** 从 TTML 字符串里抽 `<p>` 标签的文本内容，逐行返回。 */
function parseTtml(ttml: string): string[] {
  // 通过 window.DOMParser 访问（DOMParser 不在 eslint globals 白名单，
  // window 已允许；浏览器原生 XML 解析，无第三方依赖）
  const parser = new window.DOMParser()
  const doc = parser.parseFromString(ttml, "application/xml")
  // parseFromString 对坏 XML 会返回含 <parsererror> 的文档
  const parserError = doc.querySelector("parsererror")
  if (parserError) {
    throw new Error("XML 格式错误")
  }
  // TTML 结构：<tt><body><div><p>...</p>...</div></body></tt>
  // 兼容：直接取所有 <p>（无论嵌套层级）
  const nodes = Array.from(doc.getElementsByTagName("p"))
  if (nodes.length === 0) return []
  const result: string[] = []
  for (const node of nodes) {
    // textContent 取所有后代文本节点拼接，包含 <span> 内的文字
    const text = node.textContent?.trim() ?? ""
    if (text) result.push(text)
  }
  return result
}

function refresh(ttml: string | null): void {
  if (!ttml) {
    lines.value = []
    parseError.value = null
    return
  }
  try {
    lines.value = parseTtml(ttml)
    parseError.value = null
  } catch (e: unknown) {
    lines.value = []
    parseError.value = e instanceof Error ? e.message : "未知解析错误"
  }
}

watch(
  () => props.ttml,
  (val) => refresh(val),
  { immediate: true },
)
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
