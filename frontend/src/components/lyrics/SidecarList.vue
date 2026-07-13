<template>
  <section class="rounded-md border border-default bg-surface p-4 shadow-sm">
    <header class="mb-3 flex items-center justify-between">
      <h3 class="text-base font-medium text-primary">
        已有 sidecar
      </h3>
      <button
        class="rounded-sm border border-default px-2 py-1 text-xs text-secondary transition-colors hover:bg-hover disabled:opacity-50"
        :disabled="store.loadingSidecars"
        @click="reload"
      >
        刷新
      </button>
    </header>

    <!-- 加载中 -->
    <p v-if="store.loadingSidecars && store.sidecars.length === 0" class="text-sm text-tertiary">
      加载中...
    </p>

    <!-- 错误 -->
    <p v-else-if="store.sidecarsError" class="text-sm text-danger">
      {{ store.sidecarsError }}
    </p>

    <!-- 空 -->
    <p v-else-if="store.sidecars.length === 0" class="text-sm text-tertiary">
      暂无 sidecar，可通过在线匹配采纳生成。
    </p>

    <!-- 列表 -->
    <ul v-else class="flex flex-col gap-2">
      <li
        v-for="item in store.sidecars"
        :key="item.source"
        class="rounded-md border border-subtle bg-subtle p-3"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex flex-col gap-1">
            <div class="flex items-center gap-2">
              <span :class="sourceBadgeClass(item.source)" class="rounded-sm px-2 py-0.5 text-xs font-medium">
                {{ item.source }}
              </span>
              <span class="rounded-sm border border-subtle px-1.5 py-0.5 text-xs text-secondary">
                {{ item.format }}
              </span>
            </div>
            <p class="break-all text-xs text-tertiary">
              {{ item.path }}
            </p>
          </div>
          <div class="flex flex-shrink-0 items-center gap-1">
            <button
              class="rounded-sm border border-default px-2 py-1 text-xs text-primary transition-colors hover:bg-hover"
              @click="toggleExpand(item.source)"
            >
              {{ expanded.has(item.source) ? "收起" : "查看" }}
            </button>
            <button
              class="rounded-sm border border-default px-2 py-1 text-xs text-danger transition-colors hover:bg-hover disabled:opacity-50"
              :disabled="store.deleting === item.source"
              @click="confirmRemove(item.source)"
            >
              {{ store.deleting === item.source ? "删除中" : "删除" }}
            </button>
          </div>
        </div>

        <!-- 展开后的内容预览 -->
        <div v-if="expanded.has(item.source)" class="mt-2 border-t border-subtle pt-2">
          <TtmlPreview v-if="item.format === 'ttml'" :ttml="item.content" />
          <pre v-else class="max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs text-secondary">{{ truncateContent(item.content, 2000) }}</pre>
        </div>

        <!-- 折叠态：内容截断预览 -->
        <p v-else class="mt-2 break-words text-xs text-secondary">
          {{ previewText(item) }}
        </p>
      </li>
    </ul>

    <!-- 操作反馈 -->
    <p v-if="store.lastMessage" class="mt-2 text-xs text-success">
      {{ store.lastMessage }}
    </p>
    <p v-if="store.writeError" class="mt-2 text-xs text-danger">
      {{ store.writeError }}
    </p>

    <!-- 删除确认对话框 -->
    <div
      v-if="pendingDelete"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div class="w-full max-w-sm rounded-md border border-default bg-surface p-4 shadow-md">
        <h4 class="mb-2 text-base font-medium text-primary">
          确认删除 sidecar
        </h4>
        <p class="mb-4 text-sm text-secondary">
          将删除 <span class="font-medium text-primary">{{ pendingDelete }}</span> sidecar。此操作不可撤销。
        </p>
        <div class="flex justify-end gap-2">
          <button
            class="rounded-sm border border-default px-3 py-1.5 text-sm text-primary transition-colors hover:bg-hover"
            @click="pendingDelete = null"
          >
            取消
          </button>
          <button
            class="rounded-sm bg-danger px-3 py-1.5 text-sm text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            :disabled="store.deleting !== null"
            @click="doRemove"
          >
            {{ store.deleting !== null ? "删除中" : "删除" }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { LyricSource, SidecarItem } from "@/apis/lyrics"
import { useLyricsStore } from "@/stores/lyrics"
import TtmlPreview from "./TtmlPreview.vue"

/**
 * 已有 sidecar 列表
 *
 * 职责：
 * - 进入时加载 listSidecars(trackId)
 * - 每条 sidecar：source 徽章 + format + 内容预览（截断）
 * - 查看（展开）/ 删除（确认后 DELETE）
 *
 * 约束：
 * - auto-import 已注入 ref / computed / onMounted
 * - 不直接调 apis，走 store
 * - 删除走二次确认弹窗
 */
const props = defineProps<{ trackId: string }>()

const store = useLyricsStore()

const expanded = ref<Set<LyricSource>>(new Set())
const pendingDelete = ref<LyricSource | null>(null)

onMounted(async () => {
  await store.loadSidecars(props.trackId)
})

async function reload(): Promise<void> {
  await store.loadSidecars(props.trackId)
}

function toggleExpand(source: LyricSource): void {
  const next = new Set(expanded.value)
  if (next.has(source)) next.delete(source)
  else next.add(source)
  expanded.value = next
}

function confirmRemove(source: LyricSource): void {
  pendingDelete.value = source
}

async function doRemove(): Promise<void> {
  if (!pendingDelete.value) return
  const source = pendingDelete.value
  pendingDelete.value = null
  await store.removeSidecar(props.trackId, source)
  // 若该条已展开，收起
  if (expanded.value.has(source)) {
    const next = new Set(expanded.value)
    next.delete(source)
    expanded.value = next
  }
}

/** 折叠态预览文本：ttml 提取首行，json 截断。 */
function previewText(item: SidecarItem): string {
  if (!item.content) return "（空内容）"
  if (item.format === "ttml") {
    // 取首个 <p> 文本兜底，否则截断原文
    const match = item.content.match(/<p[^>]*>([\s\S]*?)<\/p>/)
    if (match) {
      const text = match[1].replace(/<[^>]+>/g, "").trim()
      if (text) return text.slice(0, 200)
    }
  }
  return item.content.slice(0, 200)
}

/** 长 json 截断展示。 */
function truncateContent(content: string, max: number): string {
  if (content.length <= max) return content
  return content.slice(0, max) + "\n…（已截断）"
}

/** source 徽章配色：apple=accent / netease=success / qq=warning。 */
function sourceBadgeClass(source: LyricSource): string {
  switch (source) {
    case "apple":
      return "bg-accent-subtle text-accent"
    case "netease":
      return "bg-accent-subtle text-success"
    case "qq":
      return "bg-accent-subtle text-warning"
    default:
      return "bg-subtle text-secondary"
  }
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
