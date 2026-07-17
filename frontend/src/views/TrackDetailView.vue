<template>
  <div class="mx-auto max-w-4xl px-6 py-8">
    <!-- 面包屑/返回 -->
    <div class="flex items-center gap-2 text-sm text-secondary">
      <button class="inline-flex items-center gap-1.5 border-none bg-transparent py-0.5 font-inherit text-secondary transition-colors hover:text-primary" @click="goBack">
        <Icon name="ArrowLeft" :size="14" />
        曲库
      </button>
      <span class="text-tertiary">/</span>
      <span class="text-primary">曲目详情</span>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="mt-6 flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <div class="mb-3 grid h-12 w-12 place-items-center rounded-full bg-subtle text-tertiary">
        <Icon name="Loader2" :size="20" spin />
      </div>
      <p class="text-sm text-secondary">
        正在加载 track 信息…
      </p>
    </div>

    <!-- 加载失败 -->
    <div v-else-if="loadError" class="mt-6 flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <div class="mb-3 grid h-12 w-12 place-items-center rounded-full bg-danger-subtle text-danger">
        <Icon name="AlertCircle" :size="20" />
      </div>
      <p class="mb-2 text-sm font-medium text-danger">
        加载失败
      </p>
      <p class="mb-4 text-xs text-secondary">
        {{ loadError }}
      </p>
      <BaseButton variant="secondary" size="sm" icon="RefreshCw" @click="loadTrack">
        重试
      </BaseButton>
    </div>

    <!-- track 不存在 -->
    <div v-else-if="!track" class="mt-6 flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <div class="mb-3 grid h-12 w-12 place-items-center rounded-full bg-subtle text-tertiary">
        <Icon name="AlertCircle" :size="20" />
      </div>
      <p class="text-sm text-secondary">
        未找到该 track(id: <span class="font-mono text-tertiary">{{ trackId }}</span>)
      </p>
      <div class="mt-4">
        <BaseButton variant="secondary" size="sm" icon="ArrowLeft" @click="router.push('/library')">
          返回曲库
        </BaseButton>
      </div>
    </div>

    <!-- track 详情 -->
    <template v-else>
      <!-- Hero：紧凑单行——封面 48px + 标题·艺术家 + 徽章 + 编辑器；文件路径折叠 -->
      <section class="mt-4 flex items-center gap-3 pb-4">
        <div class="hero-cover h-12 w-12 shrink-0 overflow-hidden rounded-md bg-subtle">
          <img
            v-if="track.has_cover && !coverError"
            :src="`/api/library/${track.id}/artwork`"
            :alt="track.title"
            @error="coverError = true"
          >
          <div v-else class="grid h-full w-full place-items-center text-tertiary">
            <Icon name="Music" :size="18" />
          </div>
        </div>

        <div class="min-w-0 flex-1">
          <!-- 标题 + 艺术家同一行 -->
          <h1 class="truncate text-lg font-semibold leading-tight tracking-tight text-primary">
            {{ track.title || "（无标题）" }}
            <span class="font-normal text-secondary"> · {{ track.artist || "—" }}</span>
          </h1>
          <!-- 徽章行 inline -->
          <div class="mt-1 flex flex-wrap items-center gap-1.5">
            <span class="badge">{{ formatMs(track.duration) }}</span>
            <span v-if="track.codec" class="badge uppercase">{{ track.codec }}</span>
            <span v-if="track.year" class="badge">{{ track.year }}</span>
            <details class="hero-details">
              <summary class="hero-summary">详情 ›</summary>
              <p class="mt-1 max-w-full truncate font-mono text-xs text-tertiary" :title="track.path">{{ track.path }}</p>
            </details>
          </div>
        </div>

        <!-- 编辑器入口（播放转交歌词区 SyncControls） -->
        <BaseButton variant="secondary" size="sm" icon="Edit3" class="shrink-0" @click="goLyricsEditor">
          逐字编辑器
        </BaseButton>
      </section>

      <!-- tab 栏 -->
      <nav class="mb-6 flex gap-1 border-b border-line">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="tab"
          :class="{ active: activeKey === tab.key }"
          @click="activeKey = tab.key"
        >
          {{ tab.label }}
        </button>
      </nav>

      <!-- tab 内容 -->
      <div class="min-h-[200px]">
        <component :is="activeTab.component" :track-id="trackId" :track="track" @written="onMetaWritten" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { Component } from "vue"
import type { TrackItem } from "@/apis/library"
import { fetchTrackById } from "@/apis/library"
import { useAudioManager } from "@/lib/audioManager"
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"

const MetaTab = defineAsyncComponent(() => import("@/components/meta/MetaTab.vue"))
const LyricsTab = defineAsyncComponent(() => import("@/components/lyrics/LyricsTab.vue"))

/**
 * Track 详情页壳（紧凑 Hero + tab）
 *
 * 设计：
 * - Hero：紧凑单行（封面48px + 标题·艺术家 + 徽章 + 编辑器；文件路径折叠进「详情」）
 * - tab：元数据 / 歌词（defineAsyncComponent 动态加载），默认进歌词 tab
 * - 播放：audioManager 单例（跨页面共享），Hero 无播放钮，播放控件在歌词区 SyncControls 常驻
 * - 进页 loadTrack → fetchTrackById + audioManager.loadTrack(track, query.play==='1')
 *   同 track 不重载（跨页面跳转保留进度）；?play=1 则自动播
 */

interface TabEntry {
  key: "meta" | "lyrics"
  label: string
  component: Component
}

const tabs: TabEntry[] = [
  { key: "meta", label: "元数据", component: MetaTab },
  { key: "lyrics", label: "歌词", component: LyricsTab },
]

const activeKey = ref<"meta" | "lyrics">("lyrics")
const activeTab = computed(
  () => tabs.find((t) => t.key === activeKey.value) ?? tabs[0],
)

const route = useRoute()
const router = useRouter()
const audio = useAudioManager()

const trackId = computed(() => String(route.params.id || ""))
const track = ref<TrackItem | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)
const coverError = ref(false)

onMounted(() => {
  void loadTrack()
})

watch(
  () => trackId.value,
  (next, prev) => {
    if (next && next !== prev) {
      void loadTrack()
    }
  },
)

async function loadTrack(): Promise<void> {
  if (!trackId.value) {
    loadError.value = "缺少 track id"
    return
  }
  loading.value = true
  loadError.value = null
  coverError.value = false
  try {
    track.value = await fetchTrackById(trackId.value)
    // audioManager.loadTrack：同 track 不重载（跨页面保留进度）；
    // ?play=1（从曲库点播放按钮跳来）则自动播
    const autoplay = route.query.play === "1"
    void audio.loadTrack(track.value, autoplay)
  } catch (e: unknown) {
    track.value = null
    loadError.value = normalizeError(e)
  } finally {
    loading.value = false
  }
}

/** 元数据写入成功：重新拉 track 刷新基础列（title/artist 等可能被写改；
 * tag_map 不再入库，MetaTab 自行 reload 现读文件） */
function onMetaWritten(): void {
  void loadTrack()
}

function goBack(): void {
  router.back()
}

function goLyricsEditor(): void {
  void router.push(`/track/${trackId.value}/lyrics-editor`)
}

function formatMs(ms: number): string {
  const v = Number(ms) || 0
  if (!v) return "--:--"
  const totalSec = Math.floor(v / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  const ss = String(s).padStart(2, "0")
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, "0")}:${ss}`
  }
  return `${String(m).padStart(2, "0")}:${ss}`
}

function normalizeError(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { status?: number; data?: unknown } }).response
    if (resp?.status === 404) return "track 不存在"
    if (resp?.status === 503) return "曲库尚未初始化"
  }
  if (e instanceof Error) return e.message
  return "请求失败"
}
</script>

<style scoped>
/* hero 封面 img 子元素选择器（tw 难表达 .hero-cover img） */
.hero-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* 徽章 */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background-color: var(--theme-bg-subtle);
  border: 1px solid var(--theme-border-default);
  font-size: 11px;
  color: var(--theme-text-secondary);
}

/* tab 栏：active 用 border-bottom-color（动态 class） */
.tab {
  padding: 10px 16px;
  font-size: 14px;
  color: var(--theme-text-secondary);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color var(--animate-duration-hover) ease, border-color var(--animate-duration-hover) ease;
  margin-bottom: -1px;
}
.tab:hover {
  color: var(--theme-text-primary);
}
.tab.active {
  color: var(--theme-text-primary);
  border-bottom-color: var(--theme-accent);
  font-weight: 500;
}

/* Hero 详情折叠：隐藏原生三角，summary 当文字链接 */
.hero-details summary {
  list-style: none;
}
.hero-details summary::-webkit-details-marker {
  display: none;
}
.hero-summary {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  cursor: pointer;
  padding: 2px 4px;
}
.hero-summary:hover {
  color: var(--theme-text-secondary);
}
</style>
