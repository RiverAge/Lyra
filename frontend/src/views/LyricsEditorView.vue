<template>
  <div class="mx-auto max-w-6xl px-6 py-8 max-sm:px-4">
    <!-- 面包屑/返回 -->
    <div class="mb-5 flex items-center gap-2 text-sm text-secondary">
      <button class="inline-flex items-center gap-1.5 border-none bg-transparent py-0.5 font-inherit text-secondary transition-colors hover:text-primary" @click="goBack">
        <Icon name="ArrowLeft" :size="14" />
        曲目
      </button>
      <span class="text-tertiary">/</span>
      <span class="text-primary">逐字歌词编辑器</span>
    </div>

    <!-- 顶部工具条：标题 + source + 全量保存 -->
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
      <div class="flex items-baseline gap-3">
        <h1 class="text-2xl font-semibold tracking-tight text-primary max-sm:text-xl">逐字歌词编辑器</h1>
        <span class="font-mono text-xs text-tertiary">track {{ trackId || "—" }}</span>
      </div>

      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2">
          <span class="text-xs text-secondary">source</span>
          <div class="relative flex items-center">
            <select
              v-model="sourceSel"
              class="select-bare input-ring w-[140px] max-sm:w-[120px] cursor-pointer rounded-sm border border-line bg-surface py-1.5 pl-3 pr-7 text-[13px] text-primary hover:not-disabled:border-line-strong disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="store.loading || store.saving"
              @change="onSourceChange"
            >
              <option value="apple">apple</option>
              <option value="netease">netease</option>
              <option value="qq">qq</option>
            </select>
            <Icon name="ChevronDown" :size="14" class="pointer-events-none absolute right-2.5 text-tertiary" />
          </div>
        </label>
        <BaseButton
          variant="primary"
          size="md"
          icon="Save"
          :disabled="store.saving || !store.doc"
          @click="onSave"
        >
          {{ store.saving ? "保存中…" : "全量保存" }}
        </BaseButton>
      </div>
    </div>

    <!-- 缺少 track id -->
    <div v-if="!trackId" class="flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <p class="text-sm text-secondary">缺少 track id</p>
    </div>

    <!-- 加载中 -->
    <div v-else-if="store.loading" class="flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <div class="mb-3 grid h-12 w-12 place-items-center rounded-full bg-subtle text-tertiary">
        <Icon name="Loader2" :size="20" spin />
      </div>
      <p class="text-sm text-secondary">正在加载歌词文档…</p>
    </div>

    <!-- 加载失败 -->
    <div v-else-if="store.loadError" class="flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <div class="mb-3 grid h-12 w-12 place-items-center rounded-full bg-danger-subtle text-danger">
        <Icon name="AlertCircle" :size="20" />
      </div>
      <p class="mb-2 text-sm font-medium text-danger">加载失败</p>
      <p class="mb-4 text-xs text-secondary">{{ store.loadError }}</p>
      <BaseButton variant="secondary" size="sm" icon="RefreshCw" @click="reload">重试</BaseButton>
    </div>

    <!-- 文档为空 -->
    <div v-else-if="!store.doc" class="flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <div class="mb-3 grid h-12 w-12 place-items-center rounded-full bg-subtle text-tertiary">
        <Icon name="AlertCircle" :size="20" />
      </div>
      <p class="text-sm text-secondary">该 source 无歌词文档</p>
    </div>

    <!-- 主布局：波形 + span 时间轴 + 同步预览 + 编辑面板 -->
    <div v-else class="flex flex-col gap-4">
      <WaveformView
        ref="waveformRef"
        :track-id="trackId"
        @timeupdate="onTimeUpdate"
        @seek="onSeek"
        @playing="onWaveformPlaying"
      />
      <SpanTimeline
        :lines="store.lines"
        :current-time-ms="currentTimeMs"
        @select="onSelectSpan"
      />
      <SyncPreview />
      <SpanEditor :track-id="trackId" />
    </div>

    <!-- 保存反馈 -->
    <div v-if="store.lastSavePath" class="mt-3.5 rounded-md border border-success/30 bg-success-subtle px-3 py-2 text-[13px] leading-normal text-success">
      已写入：<span class="font-mono">{{ store.lastSavePath }}</span>
    </div>
    <div v-if="store.saveError" class="mt-3.5 rounded-md border border-danger/30 bg-danger-subtle px-3 py-2 text-[13px] leading-normal text-danger">{{ store.saveError }}</div>
  </div>
</template>

<script setup lang="ts">
/* global queueMicrotask */
import type { EditorSource } from "@/apis/editor"
import { fetchTrackById } from "@/apis/library"
import { useAudioManager } from "@/lib/audioManager"
import WaveformView from "@/components/editor/WaveformView.vue"
import SpanEditor from "@/components/editor/SpanEditor.vue"
import SpanTimeline from "@/components/editor/SpanTimeline.vue"
import SyncPreview from "@/components/editor/SyncPreview.vue"
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"
import { useEditorStore } from "@/stores/editor"

/**
 * 逐字歌词编辑器页（B 布局重写外壳）
 *
 * 职责：
 * - trackId（route.params.id）
 * - source 选择器（apple/netease/qq，默认 apple）→ store.loadDoc
 * - 布局：波形 + span 时间轴 + 编辑面板
 * - 全量保存 → store.saveDoc
 *
 * 设计（保留）：
 * - currentTimeMs 由 WaveformView timeupdate/seek 推动 → SpanTimeline 当前 span 高亮
 * - onSelectSpan → store.select → SpanEditor 经 store.selection 消费
 * - waveformRef 持有 WaveformView 暴露的 play/pause/seek
 *
 * 子组件（WaveformView/SpanTimeline/SpanEditor）保持不动——token 驱动已浅色化，
 * 交互密集工作台不硬套 B 表格语言。
 */

const route = useRoute()
const router = useRouter()
const store = useEditorStore()
const audio = useAudioManager()

const trackId = computed(() => String(route.params.id || ""))
const sourceSel = ref<EditorSource>("apple")
const currentTimeMs = ref(0)

const waveformRef = ref<InstanceType<typeof WaveformView> | null>(null)

onMounted(async () => {
  if (!trackId.value) return
  // 加载歌词文档 + audioManager 载入 track（同 track 不重载，从详情页跳来进度保留）
  void store.loadDoc(trackId.value, sourceSel.value)
  try {
    const track = await fetchTrackById(trackId.value)
    void audio.loadTrack(track, false)
  } catch {
    // track 加载失败不阻塞歌词编辑
  }
})

/**
 * 互斥：audioManager 播放时 pause wavesurfer；wavesurfer 播放时 pause audioManager。
 * 避免 audioManager（听音+歌词同步）与 wavesurfer（波形校对）两套音频同时响。
 * 用标志防递归（一方 pause 不触发另一方）。
 */
let mutex = false
function onWaveformPlaying(isPlaying: boolean): void {
  if (mutex) return
  if (isPlaying && audio.playing.value) {
    mutex = true
    audio.pause()
    queueMicrotask(() => { mutex = false })
  }
}
// audioManager 开始播放 → pause wavesurfer
watch(
  () => audio.playing.value,
  (ap) => {
    if (mutex) return
    if (ap) {
      const ws = waveformRef.value
      if (ws && (ws as unknown as { playing?: boolean }).playing !== undefined) {
        // 通过 expose 的 pause 方法
        mutex = true
        ;(ws as unknown as { pause: () => void }).pause?.()
        queueMicrotask(() => { mutex = false })
      }
    }
  },
)

function goBack(): void {
  router.back()
}

function onSourceChange(): void {
  if (!trackId.value) return
  currentTimeMs.value = 0
  void store.loadDoc(trackId.value, sourceSel.value)
}

function reload(): void {
  if (!trackId.value) return
  void store.loadDoc(trackId.value, sourceSel.value)
}

function onTimeUpdate(ms: number): void {
  currentTimeMs.value = ms
}

function onSeek(_ms: number): void {
  // currentTimeMs 由 onTimeUpdate 同步推进
}

function onSelectSpan(payload: {
  lineIndex: number
  spanIndex: number | null
  span: { text: string; begin_ms: number; end_ms: number } | null
  line: { begin_ms: number; end_ms: number }
}): void {
  if (payload.spanIndex !== null && payload.span) {
    store.select({
      lineIndex: payload.lineIndex,
      spanIndex: payload.spanIndex,
      beginMs: payload.span.begin_ms,
      endMs: payload.span.end_ms,
    })
  } else {
    store.select({
      lineIndex: payload.lineIndex,
      spanIndex: null,
      beginMs: payload.line.begin_ms,
      endMs: payload.line.end_ms,
    })
  }
}

async function onSave(): Promise<void> {
  if (!trackId.value) return
  await store.saveDoc(trackId.value)
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名 + 全局 .select-bare/.input-ring 控制 */
</style>
