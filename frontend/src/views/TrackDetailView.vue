<template>
  <div class="mx-auto max-w-6xl px-6 py-6">
    <!-- 返回链接 -->
    <button
      class="mb-4 text-xs text-secondary transition-colors hover:text-primary"
      @click="router.back()"
    >
      ← 返回曲库
    </button>

    <!-- 加载中 -->
    <div v-if="loading" class="rounded-md border border-default bg-surface p-8 text-center shadow-sm">
      <p class="text-sm text-secondary">
        正在加载 track 信息…
      </p>
    </div>

    <!-- 加载失败 -->
    <div v-else-if="loadError" class="rounded-md border border-default bg-surface p-8 text-center shadow-sm">
      <p class="mb-2 text-sm font-medium text-danger">
        加载失败
      </p>
      <p class="mb-3 text-xs text-secondary">
        {{ loadError }}
      </p>
      <button
        class="rounded-md border border-default px-3 py-1.5 text-xs text-primary transition-colors hover:bg-hover"
        @click="loadTrack"
      >
        重试
      </button>
    </div>

    <!-- track 详情壳 -->
    <template v-else-if="track">
      <div class="animate-fade-in">
        <!-- 顶部：基本信息 -->
        <div class="mb-4 rounded-md border border-default bg-surface p-5 shadow-sm">
          <h1 class="text-xl font-semibold text-primary">
            {{ track.title || "（无标题）" }}
          </h1>
          <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-secondary">
            <span>{{ track.artist || "—" }}</span>
            <span class="text-tertiary">·</span>
            <span>{{ track.album || "—" }}</span>
            <span class="text-tertiary">·</span>
            <span class="font-mono text-tertiary">{{ formatMs(track.duration) }}</span>
            <span class="text-tertiary">·</span>
            <span class="font-mono text-tertiary uppercase">{{ track.codec || "—" }}</span>
          </div>
          <p class="mt-2 truncate font-mono text-xs text-tertiary" title="path">
            {{ track.path }}
          </p>
        </div>

        <!-- 播放器 -->
        <div class="mb-4">
          <AudioPlayer />
        </div>

        <!-- tab 切换 -->
        <div class="mb-4 border-b border-default">
          <nav class="flex gap-1">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              class="border-b-2 px-4 py-2 text-sm transition-colors"
              :class="
                activeKey === tab.key
                  ? 'border-accent font-medium text-primary'
                  : 'border-transparent text-secondary hover:text-primary'
              "
              @click="activeKey = tab.key"
            >
              {{ tab.label }}
            </button>
          </nav>
        </div>

        <!-- tab 内容（M6-B MetaTab / M6-C LyricsTab，defineAsyncComponent 动态加载） -->
        <div class="animate-fade-in">
          <component
            :is="activeTab.component"
            :track-id="trackId"
          />
        </div>

        <!-- 底部：进入逐字编辑器入口 -->
        <div class="mt-6 flex items-center justify-end gap-3 border-t border-default pt-4">
          <button
            class="rounded-md bg-accent-subtle px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent hover:text-surface"
            @click="goLyricsEditor"
          >
            进入逐字编辑器 →
          </button>
        </div>
      </div>
    </template>

    <!-- id 不存在（已尝试加载但 track 仍为 null） -->
    <div v-else class="rounded-md border border-default bg-surface p-8 text-center shadow-sm">
      <p class="text-sm text-secondary">
        未找到该 track（id: <span class="font-mono text-tertiary">{{ trackId }}</span>）
      </p>
      <button
        class="mt-3 rounded-md border border-default px-3 py-1.5 text-xs text-primary transition-colors hover:bg-hover"
        @click="router.push('/library')"
      >
        返回曲库
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Component } from "vue"
import type { TrackItem } from "@/apis/library"
import { fetchTrackById } from "@/apis/library"
import { usePlayerStore } from "@/stores/player"
import AudioPlayer from "@/components/player/AudioPlayer.vue"

const MetaTab = defineAsyncComponent(() => import("@/components/meta/MetaTab.vue"))
const LyricsTab = defineAsyncComponent(() => import("@/components/lyrics/LyricsTab.vue"))

/**
 * Track 详情页壳
 *
 * 设计：
 * - 顶部：基本信息 + 路径 + codec + duration
 * - 中部：AudioPlayer（共享 playerStore，进入时若 currentTrack != this 则切到此 track）
 * - tab 容器：meta / lyrics（M6-B/M6-C 合流：defineAsyncComponent 动态加载）
 * - 底部：进入逐字编辑器按钮 → /track/:id/lyrics-editor（M6-D）
 */
interface TabEntry {
  key: "meta" | "lyrics"
  label: string
  component: Component
}

// tab 注册表：M6-B MetaTab + M6-C LyricsTab
const tabs: TabEntry[] = [
  { key: "meta", label: "元数据", component: MetaTab },
  { key: "lyrics", label: "歌词", component: LyricsTab },
]

const activeKey = ref<"meta" | "lyrics">("meta")
const activeTab = computed(
  () => tabs.find((t) => t.key === activeKey.value) ?? tabs[0],
)

const route = useRoute()
const router = useRouter()
const playerStore = usePlayerStore()

const trackId = computed(() => String(route.params.id || ""))
const track = ref<TrackItem | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)

onMounted(() => {
  void loadTrack()
})

// 路由 id 变化时重新加载
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
  try {
    track.value = await fetchTrackById(trackId.value)
    // 同步到播放器 store（若当前播放的不是此 track）
    if (!playerStore.currentTrack || playerStore.currentTrack.id !== track.value.id) {
      // 注意：此处不自动播放，仅设置 currentTrack，避免页面一加载就响声
      playerStore.playTrack(track.value)
      // 设置后立刻暂停，保持「已加载但未播放」状态
      playerStore.setPlaying(false)
    }
  } catch (e: unknown) {
    track.value = null
    loadError.value = normalizeError(e)
  } finally {
    loading.value = false
  }
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
  const mm = String(m).padStart(2, "0")
  const ss = String(s).padStart(2, "0")
  if (m >= 60) {
    const h = Math.floor(m / 60)
    return `${h}:${String(m % 60).padStart(2, "0")}:${ss}`
  }
  return `${mm}:${ss}`
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
/* TrackDetailView 无额外 scoped 样式 */
</style>
