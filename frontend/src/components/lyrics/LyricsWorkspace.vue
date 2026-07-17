<template>
  <section class="card overflow-hidden">
    <!-- 顶部工具栏（跨左右栏） -->
    <header class="flex items-center justify-between gap-2 border-b border-line-subtle px-4 py-3">
      <div class="flex items-baseline gap-2">
        <h3 class="text-base font-semibold text-primary">歌词</h3>
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

    <!-- 匹配错误 -->
    <div v-if="store.matchError" class="flex items-start gap-2 border-b border-line-subtle px-4 py-3 text-sm leading-normal text-danger">
      <Icon name="AlertCircle" :size="14" />
      <span>{{ store.matchError }}</span>
    </div>

    <!-- 主从布局：左来源选择器 + 右统一预览 -->
    <div class="mp-split">
      <!-- 左栏：来源选择器（已有 sidecar + 在线候选） -->
      <aside class="mp-candidates">
        <!-- 已有 sidecar 组 -->
        <div v-if="store.sidecars.length > 0 || store.loadingSidecars" class="src-group-head">已有</div>
        <p v-if="store.loadingSidecars && store.sidecars.length === 0" class="px-4 py-1.5 text-xs text-tertiary">加载中...</p>
        <p v-else-if="store.sidecarsError" class="px-4 py-1.5 text-xs text-danger">{{ store.sidecarsError }}</p>
        <ul v-if="store.sidecars.length > 0" class="flex flex-col gap-0.5 px-2 py-1">
          <li
            v-for="item in store.sidecars"
            :key="`sc-${item.source}`"
            class="src-row"
            :class="isSidecarSelected(item.source) ? 'src-selected bg-accent-subtle' : ''"
            @click="onSelectSidecar(item.source)"
          >
            <SourceIcon v-if="hasLogo(item.source)" :source="item.source" :size="14" class="shrink-0" />
            <span v-else class="inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 text-[11px] font-medium" :class="sourceBadgeClass(item.source)">
              {{ sourceLabel(item.source) }}
            </span>
            <span class="min-w-0 flex-1 truncate text-sm" :class="isSidecarSelected(item.source) ? 'font-medium text-primary' : 'text-primary'">{{ sidecarRowLabel(item.source) }}</span>
            <button
              class="grid h-5 w-5 shrink-0 place-items-center rounded-sm border-none bg-transparent text-tertiary transition-colors hover:bg-hover hover:text-danger disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-tertiary"
              :disabled="item.source === 'apple' || store.deleting === item.source"
              :title="item.source === 'apple' ? 'Apple 官方歌词不可删除' : (store.deleting === item.source ? '删除中' : '删除')"
              @click.stop="confirmRemove(item.source)"
            >
              <Icon name="Trash2" :size="12" />
            </button>
          </li>
        </ul>

        <!-- 在线候选组 -->
        <div v-if="store.candidates.length > 0" class="src-group-head">在线候选</div>
        <ul v-if="store.candidates.length > 0" class="flex flex-col gap-0.5 px-2 py-1">
          <li
            v-for="(c, idx) in store.candidates"
            :key="`cand-${idx}`"
            class="relative flex cursor-pointer items-center gap-1.5 rounded-sm px-2.5 py-1.5 transition-colors hover:bg-hover"
            :class="isCandidateSelected(c) ? 'cand-selected bg-accent-subtle' : ''"
            @click="onSelectCandidate(c)"
          >
            <SourceIcon v-if="hasLogo(c.source)" :source="c.source" :size="14" class="shrink-0" />
            <span v-else class="inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 text-[11px] font-medium" :class="sourceBadgeClass(c.source)">
              {{ sourceLabel(c.source) }}
            </span>
            <span class="min-w-0 flex-1 truncate text-sm text-primary" :class="isCandidateSelected(c) ? 'font-medium' : ''">{{ c.title }}</span>
            <span class="shrink-0 font-mono text-xs text-secondary tabular-nums">{{ c.score.toFixed(1) }}</span>
          </li>
        </ul>

        <!-- 空态：无 sidecar 无候选 -->
        <p
          v-if="store.sidecars.length === 0 && store.candidates.length === 0 && !store.loadingSidecars && !store.sidecarsError"
          class="px-4 py-3 text-sm leading-normal text-tertiary"
        >
          点击「在线匹配」从网易云 / QQ 音乐拉取候选歌词。
        </p>
      </aside>

      <!-- 右栏：统一预览区 -->
      <div class="flex min-w-0 flex-col p-4">
        <!-- 预览主体 -->
        <div class="min-h-0 flex-1">
          <!-- 选中候选：预览 + 采纳 -->
          <template v-if="selectedKind === 'candidate' && store.selectedCandidate">
            <div v-if="store.previewing" class="flex items-center gap-1.5 py-6 text-sm text-tertiary">
              <Icon name="Loader2" :size="14" spin />
              <span>拉取歌词中…</span>
            </div>
            <div v-else-if="store.previewError" class="flex items-start gap-2 text-sm leading-normal text-danger">
              <Icon name="AlertCircle" :size="14" />
              <span>{{ store.previewError }}</span>
            </div>
            <template v-else>
              <TtmlPreview
                :ttml="store.previewTtml"
                :current-time-ms="currentTimeMs"
                max-height="480px"
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
          </template>

          <!-- 选中 sidecar：只读内容 -->
          <template v-else-if="selectedKind === 'sidecar' && selectedSidecar">
            <TtmlPreview
              v-if="selectedSidecar.format === 'ttml'"
              :ttml="selectedSidecar.content"
              :current-time-ms="currentTimeMs"
              max-height="480px"
            />
            <pre v-else class="max-h-[480px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-line-subtle bg-surface p-3 text-xs text-secondary">{{ truncateContent(selectedSidecar.content, 2000) }}</pre>
            <p class="mt-2 break-all font-mono text-[11px] text-tertiary">{{ selectedSidecar.path }}</p>
          </template>

          <!-- 未选中：引导 -->
          <p v-else class="py-6 text-sm leading-normal text-tertiary">
            点左侧来源查看歌词内容，或「在线匹配」拉取候选。
          </p>
        </div>

        <!-- 操作反馈 -->
        <p v-if="store.lastMessage" class="mt-2 text-xs text-success">{{ store.lastMessage }}</p>
        <p v-if="store.writeError" class="mt-2 text-xs text-danger">{{ store.writeError }}</p>

        <!-- SyncControls 常驻底部（进页即可点播放，audioManager 单例） -->
        <div class="mt-3 border-t border-line-subtle pt-3">
          <SyncControls />
        </div>
      </div>
    </div>

    <!-- 删除二次确认 -->
    <Teleport to="body">
      <div
        v-if="pendingDelete"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
        role="dialog"
        aria-modal="true"
        @click.self="pendingDelete = null"
      >
        <div class="card-elevated w-full max-w-sm p-4">
          <h4 class="mb-2 text-base font-medium text-primary">确认删除 sidecar</h4>
          <p class="mb-4 text-sm text-secondary">
            将删除 <span class="font-medium text-primary">{{ sourceLabel(pendingDelete) }}</span> sidecar。此操作不可撤销。
          </p>
          <div class="flex justify-end gap-2">
            <BaseButton variant="secondary" @click="pendingDelete = null">取消</BaseButton>
            <BaseButton
              variant="primary"
              danger
              :disabled="store.deleting !== null"
              @click="doRemove"
            >
              {{ store.deleting !== null ? "删除中" : "删除" }}
            </BaseButton>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import type { Candidate, LyricSource, SidecarItem } from "@/apis/lyrics"
import { useLyricsStore } from "@/stores/lyrics"
import { useAudioManager } from "@/lib/audioManager"
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"
import SourceIcon from "@/components/ui/icons/SourceIcon.vue"
import SyncControls from "./SyncControls.vue"
import TtmlPreview from "./TtmlPreview.vue"

/**
 * LyricsWorkspace — 歌词工作台（左来源选择器 + 右统一预览 + SyncControls 常驻）
 *
 * 合并自 MatchPanel + SidecarList：
 * - 左栏：已有 sidecar 组（apple/已采纳 netease·qq）+ 在线候选组，点哪条右栏显哪条
 * - 右栏：候选→预览 TTML + 采纳；sidecar→只读内容；未选→引导
 * - SyncControls 进页常驻底部（不依赖 matchResult），播放统一在此
 *
 * 选中态：候选走 store.selectedCandidate；sidecar 走本地 selectedKind/selectedSidecarSource
 * （sidecar 无"选中"概念，本地维护）。两者互斥：选 sidecar 清候选，选候选清 sidecar。
 *
 * 约束：auto-import 已注入 ref/computed/onMounted；不直接调 apis，走 store。
 */
const props = defineProps<{ trackId: string }>()

const store = useLyricsStore()
const audio = useAudioManager()
/** 当前播放时间（毫秒），喂给 TtmlPreview 同步高亮。 */
const currentTimeMs = computed(() => Math.round(audio.currentTime.value * 1000))

// ---- 选中态：sidecar（候选走 store.selectedCandidate）----
type SelectedKind = "sidecar" | "candidate" | null
const selectedKind = ref<SelectedKind>(null)
const selectedSidecarSource = ref<LyricSource | null>(null)

/** 当前选中的 sidecar 项（从 store.sidecars 按 source 取）。 */
const selectedSidecar = computed<SidecarItem | null>(() => {
  if (selectedKind.value !== "sidecar" || !selectedSidecarSource.value) return null
  return store.sidecars.find((s) => s.source === selectedSidecarSource.value) ?? null
})

onMounted(async () => {
  await store.loadSidecars(props.trackId)
  // 默认选中 apple sidecar（若有），右栏首屏即有内容
  const apple = store.sidecars.find((s) => s.source === "apple")
  if (apple) {
    selectedKind.value = "sidecar"
    selectedSidecarSource.value = "apple"
  }
})

async function onMatch(): Promise<void> {
  await store.runMatch(props.trackId, "netease,qq")
  // 匹配后默认选 best 候选（store.runMatch 已设 selectedCandidate=best）
  if (store.selectedCandidate) {
    selectedKind.value = "candidate"
    selectedSidecarSource.value = null
  }
}

async function onSelectCandidate(c: Candidate): Promise<void> {
  await store.selectCandidate(props.trackId, c)
  selectedKind.value = "candidate"
  selectedSidecarSource.value = null
}

function onSelectSidecar(source: LyricSource): void {
  selectedKind.value = "sidecar"
  selectedSidecarSource.value = source
}

async function onAdopt(): Promise<void> {
  await store.adoptSelected(props.trackId)
  // 采纳后切到该 sidecar 只读视图（已写入 store.sidecars）
  if (store.selectedCandidate) {
    selectedKind.value = "sidecar"
    selectedSidecarSource.value = store.selectedCandidate.source
  }
}

// ---- 删除二次确认（迁自 SidecarList）----
const pendingDelete = ref<LyricSource | null>(null)

function confirmRemove(source: LyricSource): void {
  // apple 官方词不可删（按钮已 disabled，兜底防绕过）
  if (source === "apple") return
  pendingDelete.value = source
}

async function doRemove(): Promise<void> {
  if (!pendingDelete.value) return
  const source = pendingDelete.value
  pendingDelete.value = null
  await store.removeSidecar(props.trackId, source)
  // 删除后若删的是当前选中 sidecar，回退到 apple（若有）或空
  if (selectedSidecarSource.value === source) {
    const apple = store.sidecars.find((s) => s.source === "apple")
    if (apple) {
      selectedSidecarSource.value = "apple"
    } else {
      selectedKind.value = null
      selectedSidecarSource.value = null
    }
  }
}

// ---- 工具函数（合并自 MatchPanel + SidecarList）----
function isCandidateSelected(c: Candidate): boolean {
  if (selectedKind.value !== "candidate") return false
  const s = store.selectedCandidate
  if (!s) return false
  return s.id === c.id && s.source === c.source
}

function isSidecarSelected(source: LyricSource): boolean {
  return selectedKind.value === "sidecar" && selectedSidecarSource.value === source
}

/** 来源是否有品牌 logo（netease/qq 有，apple/未知降级文字徽章） */
function hasLogo(source: string): boolean {
  return source === "netease" || source === "qq"
}

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

function sourceLabel(source: LyricSource): string {
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

/** sidecar 行标签：apple=官方词，netease/qq=已采纳 */
function sidecarRowLabel(source: LyricSource): string {
  switch (source) {
    case "apple":
      return "官方词"
    case "netease":
      return "已采纳"
    case "qq":
      return "已采纳"
    default:
      return source
  }
}

/** 长 json 截断展示（sidecar 非 ttml 格式兜底）。 */
function truncateContent(content: string, max: number): string {
  if (content.length <= max) return content
  return content.slice(0, max) + "\n…（已截断）"
}
</script>

<style scoped>
/* 主从布局：2 列定宽 grid（280px 侧栏） + 响应式 */
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
    max-height: 240px;
  }
}

/* 左栏：右边框分隔 + 可滚动 */
.mp-candidates {
  border-right: 1px solid var(--theme-border-subtle);
  overflow: auto;
}

/* 来源组标题 */
.src-group-head {
  padding: 8px 16px 2px;
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--theme-text-tertiary);
}

/* sidecar 行：可点击 + 删除按钮 */
.src-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background-color var(--animate-duration-hover) ease;
}
.src-row:hover {
  background-color: var(--theme-bg-hover);
}

/* 选中态（sidecar 行 + 候选行通用）：左 3px 色条 */
.src-selected::before,
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
.src-row.src-selected {
  position: relative;
}
</style>
