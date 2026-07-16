<template>
  <section class="card overflow-hidden">
    <!-- 顶部工具栏（跨左右栏） -->
    <header class="flex items-center justify-between gap-2 border-b border-line-subtle px-4 py-3">
      <div class="flex items-baseline gap-2">
        <h3 class="text-base font-semibold text-primary">在线匹配</h3>
        <span v-if="store.candidates.length > 0" class="text-xs text-tertiary">· {{ store.candidates.length }} 候选</span>
      </div>
      <BaseButton
        variant="primary"
        size="sm"
        :disabled="store.matching"
        @click="onMatch"
      >
        {{ store.matching ? "匹配中..." : "在线匹配" }}
      </BaseButton>
    </header>

    <!-- 播放控件条（匹配结果出现后显示，横跨左右栏；与 Hero 播放按钮共享 audioManager 单例） -->
    <div
      v-if="store.matchResult && !store.matchError"
      class="border-b border-line-subtle px-4 py-2"
    >
      <SyncControls />
    </div>

    <!-- 未匹配过：引导（纯文字，无 Search 图标） -->
    <div v-if="store.matchError" class="flex items-start gap-2 px-4 py-3 text-sm leading-normal text-danger">
      <Icon name="AlertCircle" :size="14" />
      <span>{{ store.matchError }}</span>
    </div>
    <div v-else-if="!store.matchResult" class="px-4 py-3 text-sm leading-normal text-tertiary">
      点击「在线匹配」从网易云 / QQ 音乐拉取候选歌词，自动选出最佳结果。
    </div>

    <!-- 匹配结果：左右主从布局 -->
    <div v-else class="mp-split">
      <!-- 左栏：候选列表（选择器） -->
      <aside class="mp-candidates">
        <ul v-if="store.candidates.length > 0" class="flex flex-col gap-0.5 px-2 py-2">
          <li
            v-for="(c, idx) in store.candidates"
            :key="idx"
            class="relative flex cursor-pointer items-center gap-1.5 rounded-sm px-2.5 py-1.5 transition-colors hover:bg-hover"
            :class="isSelected(c) ? 'cand-selected bg-accent-subtle' : ''"
            @click="onSelect(c)"
          >
            <SourceIcon v-if="hasLogo(c.source)" :source="c.source" :size="14" class="shrink-0" />
            <span v-else class="inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 text-[11px] font-medium" :class="sourceBadgeClass(c.source)">
              {{ sourceLabel(c.source) }}
            </span>
            <span class="min-w-0 flex-1 truncate text-sm text-primary" :class="isSelected(c) ? 'font-medium' : ''">{{ c.title }}</span>
            <span class="shrink-0 font-mono text-xs text-secondary tabular-nums">{{ c.score.toFixed(1) }}</span>
          </li>
        </ul>
        <p v-else class="px-4 py-2 text-sm text-tertiary">未找到候选</p>
      </aside>

      <!-- 右栏：歌词主体（固定可见） -->
      <div class="min-w-0 p-4">
        <!-- not_found 提示 -->
        <div v-if="store.decision === 'not_found'" class="mt-3 text-sm leading-normal text-tertiary">
          未找到匹配歌词，可尝试切换关键词或稍后重试。
        </div>

        <template v-else-if="store.selectedCandidate">
          <!-- 预览加载/错误/主体 -->
          <div v-if="store.previewing" class="flex items-center gap-1.5 py-6 text-sm text-tertiary">
            <Icon name="Loader2" :size="14" spin />
            <span>拉取歌词中…</span>
          </div>
          <div v-else-if="store.previewError" class="mt-3 flex items-start gap-2 text-sm leading-normal text-danger">
            <Icon name="AlertCircle" :size="14" />
            <span>{{ store.previewError }}</span>
          </div>
          <template v-else>
            <TtmlPreview
              :ttml="store.previewTtml"
              :current-time-ms="currentTimeMs"
              max-height="480px"
              class="mt-2"
            />
          </template>
          <p v-if="!store.previewing && !store.previewTtml && !store.previewError" class="mt-2 text-xs text-tertiary">
            该候选无可用的逐字歌词。
          </p>

          <!-- 采纳 -->
          <div class="mt-3 flex items-center gap-2.5">
            <BaseButton
              variant="ghost"
              size="sm"
              icon="Save"
              :disabled="!store.canAdopt || store.previewing || store.writing"
              @click="onAdopt"
            >
              {{ store.writing ? "写入中..." : "采纳为歌词" }}
            </BaseButton>
            <span class="text-xs text-tertiary">
              将写入 <span class="font-medium text-secondary">{{ sourceLabel(store.selectedCandidate.source) }}</span> sidecar
            </span>
          </div>
          <p v-if="store.lastMessage" class="mt-1 text-xs text-success">
            {{ store.lastMessage }}
          </p>
          <p v-if="store.writeError" class="mt-1 text-xs text-danger">
            {{ store.writeError }}
          </p>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { Candidate } from "@/apis/lyrics"
import { useLyricsStore } from "@/stores/lyrics"
import { useAudioManager } from "@/lib/audioManager"
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"
import SourceIcon from "@/components/ui/icons/SourceIcon.vue"
import SyncControls from "./SyncControls.vue"
import TtmlPreview from "./TtmlPreview.vue"

/**
 * 在线匹配面板（主从布局）
 *
 * 左栏候选列表（选择器）+ 右栏歌词预览（主体固定可见）。
 * 点左栏候选 → store.selectCandidate → 右栏 previewTtml 切换，视线不跳。
 *
 * - 选中候选 = store.selectedCandidate（默认 best）
 * - 预览 = store.previewTtml（best 短路用 match 返回的 best_ttml，否则调 preview 端点）
 * - 采纳 = store.adoptSelected
 *
 * 约束：auto-import 已注入 ref / computed；不直接调 apis，走 store。
 */
const props = defineProps<{ trackId: string }>()

const store = useLyricsStore()
const audio = useAudioManager()
/** 当前播放时间（毫秒），喂给 TtmlPreview 同步模式高亮。 */
const currentTimeMs = computed(() => Math.round(audio.currentTime.value * 1000))

async function onMatch(): Promise<void> {
  await store.runMatch(props.trackId, "netease,qq")
}

async function onSelect(c: Candidate): Promise<void> {
  await store.selectCandidate(props.trackId, c)
}

async function onAdopt(): Promise<void> {
  await store.adoptSelected(props.trackId)
}

/** 当前候选是否选中：按 id + source */
function isSelected(c: Candidate): boolean {
  const s = store.selectedCandidate
  if (!s) return false
  return s.id === c.id && s.source === c.source
}

/** 来源是否有品牌 logo（netease/qq 有，apple/未知降级文字徽章） */
function hasLogo(source: string): boolean {
  return source === "netease" || source === "qq"
}

/** 来源徽章配色 + 标签（仅 apple/未知用文字徽章；netease/qq 用 SourceIcon） */
function sourceBadgeClass(source: string): string {
  switch (source) {
    case "netease":
      return "bg-success-subtle text-success"
    case "qq":
      return "bg-warning-subtle text-warning"
    case "apple":
      return "bg-accent-subtle text-accent"
    default:
      return "bg-surface text-secondary"
  }
}

function sourceLabel(source: string): string {
  switch (source) {
    case "netease":
      return "网易云"
    case "qq":
      return "QQ音乐"
    case "apple":
      return "Apple"
    default:
      return source
  }
}
</script>

<style scoped>
/* 主从布局：2 列定宽 grid（280px 侧栏） + @media 响应式（tw grid-cols-[280px_1fr] 可转但保留可读性） */
.mp-split {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 0;
}
@media (max-width: 767px) {
  .mp-split {
    grid-template-columns: 1fr;
  }
  .mp-candidates {
    border-right: none;
    border-bottom: 1px solid var(--theme-border-subtle);
    max-height: 220px;
  }
}

/* 左栏：右边框分隔 + 可滚动 */
.mp-candidates {
  border-right: 1px solid var(--theme-border-subtle);
  overflow: auto;
}

/* 选中候选项左 3px ::before 色条（tw 无法表达伪元素色条；底色已用 bg-accent-subtle） */
.cand-selected::before {
  content: "";
  position: absolute;
  left: 0;
  top: 5px;
  bottom: 5px;
  width: 3px;
  border-radius: 1px;
  background-color: var(--theme-accent);
}
</style>
