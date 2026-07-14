<template>
  <div class="mx-auto max-w-6xl px-6 py-6">
    <!-- 返回链接 -->
    <BaseButton variant="ghost" size="sm" icon="ArrowLeft" @click="router.back()">
      返回
    </BaseButton>

    <!-- 顶部：trackId + source 选择器 + 全量保存 -->
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <h1 class="text-xl font-semibold text-primary">
          逐字歌词编辑器
        </h1>
        <span class="font-mono text-xs text-tertiary">
          track {{ trackId || "—" }}
        </span>
      </div>
      <div class="flex items-center gap-2">
        <label class="text-xs text-secondary">source</label>
        <select
          v-model="sourceSel"
          class="input-ring rounded-sm border border-subtle bg-surface px-2 py-1.5 text-sm text-primary"
          :disabled="store.loading || store.saving"
          @change="onSourceChange"
        >
          <option value="apple">apple</option>
          <option value="netease">netease</option>
          <option value="qq">qq</option>
        </select>
        <BaseButton
          variant="primary"
          size="sm"
          icon="Save"
          :disabled="store.saving || !store.doc"
          @click="onSave"
        >
          {{ store.saving ? "保存中..." : "全量保存" }}
        </BaseButton>
      </div>
    </div>

    <!-- 缺少 track id -->
    <div v-if="!trackId" class="card p-8 text-center">
      <p class="text-sm text-secondary">
        缺少 track id
      </p>
    </div>

    <!-- 加载中 -->
    <div v-else-if="store.loading" class="card p-8 text-center">
      <p class="text-sm text-secondary">
        正在加载歌词文档…
      </p>
    </div>

    <!-- 加载失败 -->
    <div v-else-if="store.loadError" class="card p-8 text-center">
      <p class="mb-2 text-sm font-medium text-danger">
        加载失败
      </p>
      <p class="mb-3 text-xs text-secondary">
        {{ store.loadError }}
      </p>
      <BaseButton variant="secondary" size="sm" @click="reload">
        重试
      </BaseButton>
    </div>

    <!-- 主布局：波形 + 时间轴 + 编辑面板 -->
    <div v-else-if="store.doc" class="flex flex-col gap-4">
      <!-- 波形 -->
      <WaveformView
        ref="waveformRef"
        :track-id="trackId"
        @timeupdate="onTimeUpdate"
        @seek="onSeek"
      />

      <!-- span 时间轴 -->
      <SpanTimeline
        :lines="store.lines"
        :current-time-ms="currentTimeMs"
        @select="onSelectSpan"
      />

      <!-- 编辑面板 -->
      <SpanEditor :track-id="trackId" />
    </div>

    <!-- 文档为空（无行） -->
    <div v-else class="card p-8 text-center">
      <p class="text-sm text-secondary">
        该 source 无歌词文档
      </p>
    </div>

    <!-- 全量保存反馈 -->
    <p v-if="store.lastSavePath" class="mt-3 text-xs text-success">
      已写入：{{ store.lastSavePath }}
    </p>
    <p v-if="store.saveError" class="mt-3 text-xs text-danger">
      {{ store.saveError }}
    </p>
  </div>
</template>

<script setup lang="ts">
import type { EditorSource } from "@/apis/editor"
import WaveformView from "@/components/editor/WaveformView.vue"
import SpanEditor from "@/components/editor/SpanEditor.vue"
import SpanTimeline from "@/components/editor/SpanTimeline.vue"
import BaseButton from "@/components/ui/BaseButton.vue"
import { useEditorStore } from "@/stores/editor"

/**
 * 逐字歌词编辑器页（LyricsEditorView）
 *
 * 职责：
 * - 从 useRoute().params.id 取 trackId（string）
 * - source 选择器（apple/netease/qq，默认 apple）
 * - 选 source → store.loadDoc(trackId, source) → 传给 SpanTimeline
 * - 布局：上方波形 + 下方 span 时间轴 + 底部编辑面板
 * - 「全量保存」入口 → store.saveDoc(trackId)
 *
 * 设计：
 * - currentTimeMs 由 WaveformView 的 timeupdate/seek 推动本地 ref，
 *   再下传给 SpanTimeline 做当前 span 高亮
 * - onSelectSpan（来自 SpanTimeline）→ store.select(...)
 *   → SpanEditor 通过 store.selection 消费
 * - waveformRef 持有 WaveformView 暴露的 play/pause/seek（defineExpose）
 *
 * 约束：
 * - auto-import 已注入 ref / computed / onMounted / watch
 * - 不直接调 apis，全走 store
 */

const route = useRoute()
const router = useRouter()
const store = useEditorStore()

const trackId = computed(() => String(route.params.id || ""))
const sourceSel = ref<EditorSource>("apple")
const currentTimeMs = ref(0)

// WaveformView 实例引用（用于调用暴露的 play/pause/seek）
const waveformRef = ref<InstanceType<typeof WaveformView> | null>(null)

onMounted(() => {
  if (trackId.value) {
    void store.loadDoc(trackId.value, sourceSel.value)
  }
})

// 切换 source → 重新加载
function onSourceChange(): void {
  if (!trackId.value) return
  currentTimeMs.value = 0
  void store.loadDoc(trackId.value, sourceSel.value)
}

/** 重试加载（保留当前 sourceSel）。 */
function reload(): void {
  if (!trackId.value) return
  void store.loadDoc(trackId.value, sourceSel.value)
}

/** 波形播放进度更新。 */
function onTimeUpdate(ms: number): void {
  currentTimeMs.value = ms
}

/** 波形拖动 seek。 */
function onSeek(_ms: number): void {
  // currentTimeMs 由 onTimeUpdate 同步推进，这里无需重复
}

/** 时间轴点击 span/line → 写入 store.selection。 */
function onSelectSpan(payload: {
  lineIndex: number
  spanIndex: number | null
  span: { text: string; begin_ms: number; end_ms: number } | null
  line: { begin_ms: number; end_ms: number }
}): void {
  // span 级用 span 的 begin/end，行级用 line 的 begin/end
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

/** 全量保存。 */
async function onSave(): Promise<void> {
  if (!trackId.value) return
  await store.saveDoc(trackId.value)
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
