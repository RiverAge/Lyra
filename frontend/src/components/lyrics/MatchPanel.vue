<template>
  <section class="card overflow-hidden">
    <!-- 顶部工具栏（跨左右栏） -->
    <header class="flex items-center justify-between gap-2 border-b border-line-subtle px-4 py-3">
      <div class="flex items-center gap-2.5">
        <h3 class="text-base font-semibold text-primary">在线匹配</h3>
        <BaseButton
          variant="secondary"
          size="sm"
          icon="Edit3"
          @click="onEditor"
        >
          逐字编辑器
        </BaseButton>
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
        <div class="flex items-center gap-1 px-4 pb-2 text-xs uppercase tracking-wide text-tertiary">
          候选 <span class="font-mono text-secondary">{{ store.candidates.length }}</span>
        </div>
        <ul v-if="store.candidates.length > 0" class="flex flex-col gap-0.5 px-2 pb-2">
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
            <span class="min-w-0 flex-1 truncate text-sm text-primary">{{ c.title }}</span>
            <span class="shrink-0 font-mono text-xs text-secondary tabular-nums">{{ c.score.toFixed(1) }}</span>
          </li>
        </ul>
        <p v-else class="px-4 py-2 text-sm text-tertiary">未找到候选</p>
      </aside>

      <!-- 右栏：歌词主体（固定可见） -->
      <div class="min-w-0 p-4">
        <!-- 决策徽章 + reason -->
        <div class="flex flex-wrap items-center gap-2.5 mb-3">
          <span class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium" :class="decisionBadgeClass">
            <Icon :name="decisionIcon" :size="13" />
            {{ decisionLabel }}
          </span>
          <span class="text-sm text-secondary">{{ friendlyReason }}</span>
        </div>

        <!-- not_found 提示 -->
        <div v-if="store.decision === 'not_found'" class="mt-3 text-sm leading-normal text-tertiary">
          未找到匹配歌词，可尝试切换关键词或稍后重试。
        </div>

        <template v-else-if="store.selectedCandidate">
          <!-- 选中候选信息 -->
          <div class="flex items-center justify-between gap-3 rounded-md bg-subtle px-3 py-2.5">
            <div class="flex min-w-0 items-center gap-2">
              <SourceIcon v-if="hasLogo(store.selectedCandidate.source)" :source="store.selectedCandidate.source" :size="16" class="shrink-0" />
              <span v-else class="inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 text-[11px] font-medium" :class="sourceBadgeClass(store.selectedCandidate.source)">
                {{ sourceLabel(store.selectedCandidate.source) }}
              </span>
              <span class="truncate text-sm font-medium text-primary">{{ store.selectedCandidate.title }}</span>
              <span class="shrink-0 text-xs text-tertiary">{{ store.selectedCandidate.artists.join("、") }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <div class="h-1 w-[60px] overflow-hidden rounded-full bg-hover">
                <div class="h-full rounded-full" :class="scoreClass(store.selectedCandidate.score)" :style="{ width: store.selectedCandidate.score + '%' }" />
              </div>
              <span class="font-mono text-xs text-secondary tabular-nums">{{ store.selectedCandidate.score.toFixed(1) }}</span>
            </div>
          </div>

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
            <!-- 歌词校对播放控件（调 audioManager 单例，与 TtmlPreview 共享 currentTime） -->
            <SyncControls class="mt-3" />
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
import type { IconName } from "@/components/ui/icons/paths"
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

function onEditor(): void {
  void useRouter().push(`/track/${props.trackId}/lyrics-editor`)
}

/** 当前候选是否选中：按 id + source */
function isSelected(c: Candidate): boolean {
  const s = store.selectedCandidate
  if (!s) return false
  return s.id === c.id && s.source === c.source
}

/** 决策徽章配色：accept=success / review=accent / reject=danger / neutral=subtle+tertiary */
const decisionBadgeClass = computed(() => {
  switch (store.decision) {
    case "accept":
      return "bg-success-subtle text-success"
    case "review":
      return "bg-accent-subtle text-accent"
    case "reject":
      return "bg-danger-subtle text-danger"
    default:
      return "bg-subtle text-tertiary"
  }
})

const decisionIcon = computed<IconName>(() => {
  switch (store.decision) {
    case "accept":
      return "Check"
    case "review":
      return "AlertCircle"
    case "reject":
      return "X"
    default:
      return "Search"
  }
})

const decisionLabel = computed(() => {
  switch (store.decision) {
    case "accept":
      return "可直接采用"
    case "review":
      return "需人工复核"
    case "reject":
      return "低可信度"
    case "not_found":
      return "未找到"
    default:
      return "—"
  }
})

/** reason 友好化 */
const friendlyReason = computed(() => {
  const r = store.reason
  if (!r) return ""
  const scoreMatch = r.match(/score\s+([\d.]+)/i)
  const gapMatch = r.match(/gap\s+([\d.]+)/i)
  const score = scoreMatch ? scoreMatch[1] : null
  const gap = gapMatch ? gapMatch[1] : null
  if (/ambiguous/i.test(r)) {
    return `有多个相近候选，最佳得分 ${score ?? "—"}，与次选差距仅 ${gap ?? "—"}，建议人工确认`
  }
  if (/placeholder artist/i.test(r)) {
    return `标题/专辑/时长三强匹配（艺人缺失），得分 ${score ?? "—"}，可直接采用`
  }
  if (/medium confidence/i.test(r)) {
    return `中等可信度，最佳得分 ${score ?? "—"}，建议核对后再采纳`
  }
  if (/low confidence/i.test(r)) {
    return `可信度较低，最佳得分 ${score ?? "—"}，可能不是同一首歌`
  }
  if (score && gap) return `最佳得分 ${score}，领先次选 ${gap}`
  return r
})

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

/** score 进度条配色：用中性墨色梯度，避免与来源徽章（绿/黄/红/彩 logo）撞色。
 * accept=深墨黑 / review=中灰 / reject=浅灰，自成体系不抢来源色。 */
function scoreClass(score: number): string {
  if (score >= 86) return "bg-accent"
  if (score >= 74) return "bg-secondary"
  return "bg-tertiary"
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

/* 选中候选项左 2px ::before 色条（tw 无法表达伪元素色条；底色已用 bg-accent-subtle） */
.cand-selected::before {
  content: "";
  position: absolute;
  left: 0;
  top: 5px;
  bottom: 5px;
  width: 2px;
  border-radius: 1px;
  background-color: var(--theme-accent);
}
</style>
