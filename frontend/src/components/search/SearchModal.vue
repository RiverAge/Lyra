<template>
  <Teleport to="body">
    <Transition name="search-modal">
      <div
        v-if="searchStore.open"
        class="search-overlay"
        @click.self="close"
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-label="搜索曲库"
          class="search-panel"
        >
          <!-- 输入区 -->
          <div class="search-input-row">
            <Icon name="Search" :size="18" class="shrink-0 text-tertiary" />
            <input
              ref="inputEl"
              :value="searchStore.query"
              type="text"
              placeholder="搜索歌曲、艺人、专辑…"
              class="search-input"
              autocomplete="off"
              spellcheck="false"
              @input="onInput"
              @keydown="onKeydown"
            >
            <kbd class="kbd">ESC</kbd>
          </div>

          <!-- 结果列表 -->
          <div class="search-results">
            <!-- 加载中（首次搜 + 无旧结果时显示） -->
            <div
              v-if="searchStore.loading && searchStore.results.length === 0"
              class="search-empty"
            >
              搜索中…
            </div>

            <!-- 空状态：有 query 但无结果且非加载中 -->
            <div
              v-else-if="searchStore.query.trim() && searchStore.results.length === 0"
              class="search-empty"
            >
              未找到匹配 " {{ searchStore.query.trim() }} " 的曲目
            </div>

            <!-- 初始提示：还没输入 -->
            <div v-else-if="searchStore.results.length === 0" class="search-empty">
              输入关键词搜索曲库
            </div>

            <!-- 结果列表 -->
            <ul v-else>
              <li
                v-for="(item, i) in searchStore.results"
                :key="item.id"
                :class="['search-item', { active: i === searchStore.activeIndex }]"
                @mousemove="searchStore.activeIndex = i"
                @click="select(item.id)"
              >
                <div class="item-cov">
                  <img
                    v-if="item.has_cover && !imgError[item.id]"
                    :src="`/api/library/${item.id}/artwork`"
                    :alt="item.title"
                    loading="lazy"
                    @error="imgError[item.id] = true"
                  >
                  <Icon v-else name="Music" :size="16" class="text-tertiary" />
                </div>
                <div class="item-text">
                  <span class="item-title">{{ item.title || "（无标题）" }}</span>
                  <span class="item-meta">{{ item.artist || "未知艺人" }} · {{ item.album || "未知专辑" }}</span>
                </div>
              </li>
            </ul>
          </div>

          <!-- 底部提示 -->
          <div class="search-footer">
            <span class="footer-hint">
              <kbd class="kbd">↑</kbd><kbd class="kbd">↓</kbd> 选择
              <kbd class="kbd ml">↵</kbd> 打开
            </span>
            <span class="footer-count">
              {{ searchStore.results.length }} 条结果
            </span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { useSearchStore } from "@/stores/search"
import Icon from "@/components/ui/icons/Icon.vue"

/* global HTMLInputElement, Event, KeyboardEvent */

/**
 * 全局搜索 Modal（⌘K / Ctrl+K 触发）
 *
 * - Teleport 到 body，遮罩 + 居中面板
 * - 输入 debounce 200ms（store 内）→ /api/library/search
 * - 键盘：↑↓ 选择、↵ 打开、ESC 关闭
 * - 打开时自动 focus 输入框
 *
 * 触发快捷键 + ESC 监听在 App.vue 注册（全局），这里只处理面板内交互。
 */

const searchStore = useSearchStore()
const router = useRouter()
const inputEl = ref<HTMLInputElement | null>(null)

// 封面加载失败回退：按 track.id 记录（与 TrackTable 同模式）
const imgError = ref<Record<string, boolean>>({})

// 打开时 focus 输入框
watch(
  () => searchStore.open,
  (v) => {
    if (v) {
      // nextTick：等 DOM 渲染（Transition 入场后）
      void nextTick(() => {
        inputEl.value?.focus()
      })
    }
  },
)

function onInput(e: Event): void {
  const value = (e.target as HTMLInputElement).value
  searchStore.onInput(value)
}

function onKeydown(e: KeyboardEvent): void {
  switch (e.key) {
    case "ArrowDown":
      e.preventDefault()
      searchStore.moveActive(1)
      break
    case "ArrowUp":
      e.preventDefault()
      searchStore.moveActive(-1)
      break
    case "Enter":
      e.preventDefault()
      void selectActive()
      break
    case "Escape":
      e.preventDefault()
      close()
      break
  }
}

function close(): void {
  searchStore.setOpen(false)
}

async function selectActive(): Promise<void> {
  const item = searchStore.activeItem()
  if (item) await select(item.id)
}

async function select(id: string): Promise<void> {
  searchStore.setOpen(false)
  await router.push(`/track/${id}`)
}
</script>

<style scoped>
/* 遮罩：半透明黑 + backdrop blur */
.search-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
  background-color: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
}

/* 居中面板：max-w 限制宽度，圆角 + 阴影 */
.search-panel {
  width: 100%;
  max-width: 560px;
  margin: 0 16px;
  background-color: var(--theme-bg-surface);
  border: 1px solid var(--theme-border-default);
  border-radius: var(--radius-lg);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

/* 输入区 */
.search-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--theme-border-subtle);
}
.search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 16px;
  color: var(--theme-text-primary);
}
.search-input::placeholder {
  color: var(--theme-text-tertiary);
}

/* 结果区 */
.search-results {
  max-height: 360px;
  overflow-y: auto;
}
.search-empty {
  padding: 32px 16px;
  text-align: center;
  font-size: 14px;
  color: var(--theme-text-tertiary);
}

/* 结果项 */
.search-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  cursor: pointer;
  transition: background-color var(--animate-duration-hover) ease;
}
.search-item.active {
  background-color: var(--theme-bg-hover);
}
.item-cov {
  width: 36px;
  height: 36px;
  border-radius: 4px;
  background-color: var(--theme-bg-subtle);
  flex-shrink: 0;
  overflow: hidden;
  display: grid;
  place-items: center;
}
.item-cov img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.item-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.item-title {
  font-size: 14px;
  color: var(--theme-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-meta {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 底部 */
.search-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-top: 1px solid var(--theme-border-subtle);
  font-size: 12px;
  color: var(--theme-text-tertiary);
}
.footer-hint {
  display: flex;
  align-items: center;
  gap: 4px;
}
.footer-hint .ml {
  margin-left: 8px;
}
.footer-count {
  font-variant-numeric: tabular-nums;
}

/* kbd 键帽 */
.kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--theme-border-default);
  background-color: var(--theme-bg-subtle);
  font-size: 11px;
  font-family: var(--font-mono, ui-monospace, monospace);
  color: var(--theme-text-secondary);
}

/* Transition：遮罩淡入 + 面板上滑 */
.search-modal-enter-active,
.search-modal-leave-active {
  transition: opacity 0.18s ease;
}
.search-modal-enter-active .search-panel,
.search-modal-leave-active .search-panel {
  transition: opacity 0.18s ease, transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.search-modal-enter-from,
.search-modal-leave-to {
  opacity: 0;
}
.search-modal-enter-from .search-panel,
.search-modal-leave-to .search-panel {
  opacity: 0;
  transform: translateY(-12px) scale(0.98);
}
/* 关闭动画时由 tokens.css 的 html.no-anim * 全局兜底压成瞬时，此处不重复 */
</style>
