<template>
  <div class="mx-auto max-w-6xl px-6 py-6">
    <!-- 返回链接 -->
    <BaseButton variant="ghost" size="sm" icon="ArrowLeft" @click="router.back()">
      返回曲库
    </BaseButton>

    <!-- 加载中 -->
    <div v-if="loading" class="card mt-4 p-12 text-center">
      <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-subtle">
        <Icon name="Loader2" :size="20" spin />
      </div>
      <p class="text-sm text-secondary">
        正在加载 track 信息…
      </p>
    </div>

    <!-- 加载失败 -->
    <div v-else-if="loadError" class="card mt-4 p-12 text-center">
      <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-danger-subtle text-danger">
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

    <!-- track 详情壳 -->
    <template v-else-if="track">
      <div class="mt-4">
        <!-- Hero 区：大封面 + 信息（合并原顶部 info card，消除与 dock 的重复） -->
        <div class="card mb-6 p-6">
          <div class="flex flex-col gap-6 sm:flex-row">
            <!-- 封面 -->
            <div class="flex-shrink-0">
              <img
                v-if="track.has_cover && !coverError"
                :src="`/api/library/${track.id}/artwork`"
                :alt="track.title"
                class="h-40 w-40 rounded-lg object-cover shadow-md"
                @error="coverError = true"
              >
              <div
                v-else
                class="flex h-40 w-40 items-center justify-center rounded-lg bg-subtle text-tertiary shadow-md"
              >
                <Icon name="Music" :size="48" />
              </div>
            </div>

            <!-- 信息 -->
            <div class="min-w-0 flex-1">
              <h1 class="text-2xl font-semibold text-primary">
                {{ track.title || "（无标题）" }}
              </h1>
              <div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
                <span class="text-secondary">{{ track.artist || "—" }}</span>
                <span class="text-tertiary">·</span>
                <span class="text-secondary">{{ track.album || "—" }}</span>
              </div>

              <!-- 元数据徽章 -->
              <div class="mt-4 flex flex-wrap items-center gap-2">
                <span class="rounded-sm bg-subtle px-2 py-1 font-mono text-xs text-tertiary">
                  {{ formatMs(track.duration) }}
                </span>
                <span
                  v-if="track.codec"
                  class="rounded-sm bg-subtle px-2 py-1 font-mono text-xs uppercase text-tertiary"
                >{{ track.codec }}</span>
              </div>

              <!-- 路径 -->
              <p class="mt-4 truncate font-mono text-xs text-tertiary" title="path">
                {{ track.path }}
              </p>
            </div>
          </div>
        </div>

        <!-- tab 切换 -->
        <div class="mb-4 border-b border-subtle">
          <nav class="flex gap-1">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              class="border-b-2 px-4 py-2.5 text-sm transition-colors"
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
        <div>
          <component
            :is="activeTab.component"
            :track-id="trackId"
          />
        </div>

        <!-- 底部：进入逐字编辑器入口 -->
        <div class="mt-6 flex items-center justify-end gap-3 border-t border-subtle pt-4">
          <BaseButton variant="secondary" icon="Edit3" @click="goLyricsEditor">
            进入逐字编辑器
          </BaseButton>
        </div>
      </div>
    </template>

    <!-- id 不存在（已尝试加载但 track 仍为 null） -->
    <div v-else class="card mt-4 p-12 text-center">
      <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-subtle text-tertiary">
        <Icon name="AlertCircle" :size="20" />
      </div>
      <p class="text-sm text-secondary">
        未找到该 track（id: <span class="font-mono text-tertiary">{{ trackId }}</span>）
      </p>
      <div class="mt-4">
        <BaseButton variant="secondary" size="sm" icon="ArrowLeft" @click="router.push('/library')">
          返回曲库
        </BaseButton>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Component } from "vue"
import type { TrackItem } from "@/apis/library"
import { fetchTrackById } from "@/apis/library"
import { usePlayerStore } from "@/stores/player"
import BaseButton from "@/components/ui/BaseButton.vue"
import Icon from "@/components/ui/icons/Icon.vue"

const MetaTab = defineAsyncComponent(() => import("@/components/meta/MetaTab.vue"))
const LyricsTab = defineAsyncComponent(() => import("@/components/lyrics/LyricsTab.vue"))

/**
 * Track 详情页壳
 *
 * 设计：
 * - Hero 区：大封面 + 标题/艺人/专辑/时长/codec/路径（合并原顶部 info card）
 * - 播放器已全局化为 PlayerDock（App.vue 挂载），此处不再渲染独立播放器
 * - tab 容器：meta / lyrics（M6-B/M6-C 合流：defineAsyncComponent 动态加载）
 * - 底部：进入逐字编辑器按钮 → /track/:id/lyrics-editor（M6-D）
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
const coverError = ref(false)

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
  coverError.value = false
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
