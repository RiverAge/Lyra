<template>
  <div class="card overflow-hidden">
    <!-- 表头 -->
    <div class="track-row track-head">
      <div class="col-idx text-xs uppercase tracking-wide text-tertiary">#</div>
      <div class="text-xs uppercase tracking-wide text-tertiary">标题</div>
      <div class="text-xs uppercase tracking-wide text-tertiary">专辑</div>
      <div class="text-xs uppercase tracking-wide text-tertiary">艺人</div>
      <div class="col-dur text-xs uppercase tracking-wide text-tertiary">时长</div>
      <div class="col-fmt text-xs uppercase tracking-wide text-tertiary">格式</div>
      <div class="col-play" />
    </div>

    <!-- 加载态：骨架行 -->
    <template v-if="loading">
      <div
        v-for="i in skeletonCount"
        :key="`sk-${i}`"
        class="track-row"
      >
        <div class="col-idx"><div class="skel skel-idx" /></div>
        <div class="ttl">
          <div class="skel skel-cov" />
          <div class="skel skel-ttl" />
        </div>
        <div class="skel skel-cell" />
        <div class="skel skel-cell" />
        <div class="skel skel-dur" />
        <div class="skel skel-fmt" />
        <div />
      </div>
    </template>

    <!-- 空态 -->
    <div
      v-else-if="empty"
      class="flex flex-col items-center justify-center px-6 py-20 text-center"
    >
      <div class="mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-subtle text-tertiary">
        <Icon name="Music" :size="24" />
      </div>
      <p class="mb-1 text-sm font-medium text-primary">
        {{ hasFilters ? "没有匹配的曲目" : "曲库为空" }}
      </p>
      <p class="text-xs text-secondary">
        {{ hasFilters ? "试试调整或清空筛选条件" : "请先扫描音乐库根目录" }}
      </p>
    </div>

    <!-- 错误态 -->
    <div
      v-else-if="error"
      class="flex flex-col items-center justify-center px-6 py-20 text-center"
    >
      <div class="mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-danger-subtle text-danger">
        <Icon name="AlertCircle" :size="24" />
      </div>
      <p class="mb-1 text-sm font-medium text-danger">
        加载失败
      </p>
      <p class="mb-4 text-xs text-secondary">
        {{ error }}
      </p>
      <BaseButton variant="secondary" size="sm" icon="RefreshCw" @click="$emit('retry')">
        重试
      </BaseButton>
    </div>

    <!-- 数据行 -->
    <template v-else>
      <div
        v-for="(track, i) in tracks"
        :key="track.id"
        class="track-row group"
        @click="$emit('navigate', track.id)"
      >
        <div class="col-idx">
          <span class="num text-sm group-hover:hidden">{{ rowIndex(i) }}</span>
          <button
            class="play-mini hidden group-hover:grid"
            title="播放"
            @click.stop="play(track)"
          >
            <Icon name="Play" :size="11" />
          </button>
        </div>
        <div class="ttl">
          <div class="ttl-cov">
            <img
              v-if="track.has_cover && !imgError[track.id]"
              :src="`/api/library/${track.id}/artwork`"
              :alt="track.title"
              loading="lazy"
              @error="imgError[track.id] = true"
            >
            <Icon v-else name="Music" :size="16" class="text-tertiary" />
          </div>
          <div class="min-w-0">
            <div class="truncate text-sm text-primary">{{ track.title || "（无标题）" }}</div>
            <div class="truncate text-xs text-secondary">{{ track.artist || "—" }}</div>
          </div>
        </div>
        <div class="truncate text-sm text-secondary">{{ track.album || "—" }}</div>
        <div class="truncate text-sm text-secondary">{{ track.artist || "—" }}</div>
        <div class="col-dur text-sm text-secondary tabular-nums">{{ formatMs(Number(track.duration) || 0) }}</div>
        <div class="col-fmt font-mono text-xs uppercase text-tertiary">{{ codecLabel(track.codec) }}</div>
        <div class="col-play" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { TrackItem } from "@/apis/library"
import Icon from "@/components/ui/icons/Icon.vue"
import BaseButton from "@/components/ui/BaseButton.vue"

/**
 * TrackTable — B 布局表格版曲库列表
 *
 * - grid 列：# / 标题(含封面) / 专辑 / 艺人 / 时长 / 格式 / 播放位
 * - 行 hover 高亮；hover 时序号 → 播放按钮
 * - 点击行 → emit('navigate', id) 跳详情
 * - 点击播放按钮 → 跳详情页带 ?play=1（详情页 audioManager 自动播）
 * - 含 loading 骨架行 / 空态 / 错误态
 */

const props = withDefaults(
  defineProps<{
    tracks: TrackItem[]
    loading?: boolean
    error?: string | null
    page?: number
    pageSize?: number
    hasFilters?: boolean
    skeletonCount?: number
  }>(),
  {
    loading: false,
    error: null,
    page: 1,
    pageSize: 20,
    hasFilters: false,
    skeletonCount: 8,
  },
)

defineEmits<{
  (e: "navigate", id: string): void
  (e: "retry"): void
}>()

const router = useRouter()

const empty = computed(() => !props.loading && props.tracks.length === 0)

// 封面加载失败回退：按 track.id 记录
const imgError = ref<Record<string, boolean>>({})

function rowIndex(i: number): number {
  return (props.page - 1) * props.pageSize + i + 1
}

function play(track: TrackItem): void {
  // 跳详情页带 ?play=1，详情页 audioManager 自动播（首页无全局播放器）
  void router.push({ path: `/track/${track.id}`, query: { play: "1" } })
}

function codecLabel(codec: unknown): string {
  return String(codec || "").toLowerCase()
}

/** ms → mm:ss（超 1h 显示 h:mm:ss）。duration 字段为毫秒。 */
function formatMs(ms: number): string {
  if (!ms || ms < 0) return "--:--"
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  const ss = String(s).padStart(2, "0")
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, "0")}:${ss}`
  }
  return `${String(m).padStart(2, "0")}:${ss}`
}
</script>

<style scoped>
/* 表格行：7 列定宽 grid（tw 难表达多列定宽 fr 混合） */
.track-row {
  display: grid;
  grid-template-columns: 40px 1.4fr 1.2fr 1fr 72px 64px 36px;
  gap: 16px;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid var(--theme-border-subtle);
  cursor: pointer;
  transition: background-color var(--animate-duration-hover) ease;
}
.track-row:last-child {
  border-bottom: none;
}
.track-row:hover {
  background-color: var(--theme-bg-hover);
}

/* 表头 */
.track-head {
  font-weight: 500;
  background-color: var(--theme-bg-subtle);
  cursor: default;
  border-bottom: 1px solid var(--theme-border-default);
}
.track-head:hover {
  background-color: var(--theme-bg-subtle);
}

.col-idx {
  position: relative;
  height: 18px;
  display: flex;
  align-items: center;
}
.play-mini {
  position: absolute;
  inset: 0;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: none;
  background: var(--theme-accent);
  color: var(--theme-on-accent);
  cursor: pointer;
}

/* 标题列：封面容器 */
.ttl {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.ttl-cov {
  width: 36px;
  height: 36px;
  border-radius: 4px;
  background-color: var(--theme-bg-subtle);
  flex-shrink: 0;
  overflow: hidden;
  display: grid;
  place-items: center;
}
.ttl-cov img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.col-play {
  width: 0;
}

/* 骨架（@keyframes + 各块尺寸，tw 难表达） */
.skel {
  background-color: var(--theme-bg-hover);
  border-radius: 4px;
  animation: pulse-skel 1.5s ease-in-out infinite;
}
.skel-idx { width: 16px; height: 12px; }
.skel-cov { width: 36px; height: 36px; border-radius: 4px; }
.skel-ttl { width: 60%; height: 12px; }
.skel-cell { width: 50%; height: 12px; }
.skel-dur { width: 32px; height: 12px; }
.skel-fmt { width: 36px; height: 12px; }
@keyframes pulse-skel {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0.9; }
}
</style>
