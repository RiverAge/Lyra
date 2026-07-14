<template>
  <section class="card p-4">
    <header class="mb-3 flex items-center justify-between gap-2">
      <h3 class="text-base font-medium text-primary">
        在线匹配
      </h3>
      <BaseButton
        variant="primary"
        size="sm"
        icon="Search"
        :disabled="store.matching"
        @click="onMatch"
      >
        {{ store.matching ? "匹配中..." : "在线匹配" }}
      </BaseButton>
    </header>

    <!-- 错误 -->
    <p v-if="store.matchError" class="text-sm text-danger">
      {{ store.matchError }}
    </p>

    <!-- 未匹配过 -->
    <p v-else-if="!store.matchResult" class="text-sm text-tertiary">
      点击「在线匹配」从网易 / QQ 拉取候选歌词。
    </p>

    <!-- 匹配结果 -->
    <template v-else>
      <!-- 决策徽章 + reason -->
      <div class="mb-3 flex items-center gap-2">
        <span :class="decisionBadgeClass(store.decision)" class="rounded-sm px-2 py-0.5 text-xs font-medium">
          {{ decisionLabel(store.decision) }}
        </span>
        <span class="text-sm text-secondary">{{ store.reason }}</span>
      </div>

      <!-- not_found 提示 -->
      <p v-if="store.decision === 'not_found'" class="text-sm text-tertiary">
        未找到匹配歌词。
      </p>

      <!-- 候选列表 -->
      <div v-else class="flex flex-col gap-2">
        <h4 class="text-sm font-medium text-secondary">
          候选（{{ store.candidates.length }}）
        </h4>
        <ul class="flex flex-col gap-1">
          <li
            v-for="(c, idx) in store.candidates"
            :key="idx"
            :class="store.best && store.best.source === c.source && isSameCandidate(store.best, c) ? 'border-accent bg-accent-subtle' : 'border-subtle bg-subtle'"
            class="rounded-md border p-2"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="rounded-sm bg-surface px-1.5 py-0.5 text-xs font-medium text-primary">
                  {{ c.source }}
                </span>
                <span class="text-sm text-primary">{{ c.title }}</span>
                <span class="text-xs text-tertiary">{{ c.artist }}</span>
              </div>
              <span class="font-mono text-xs text-secondary">
                {{ formatScore(c.score) }}
              </span>
            </div>
            <p class="mt-1 text-xs text-tertiary">
              {{ c.album || "—" }}
            </p>
          </li>
        </ul>
        <p v-if="store.candidates.length === 0" class="text-xs text-tertiary">
          无候选
        </p>
      </div>

      <!-- 最佳 TTML 预览 + 采纳 -->
      <div v-if="store.bestTtml" class="mt-3">
        <TtmlPreview :ttml="store.bestTtml" />
        <div class="mt-2 flex items-center gap-2">
          <BaseButton
            variant="ghost"
            size="sm"
            :disabled="!store.canAdopt || store.writing"
            @click="onAdopt"
          >
            {{ store.writing ? "写入中..." : "采纳" }}
          </BaseButton>
          <span class="text-xs text-tertiary">
            将写入到 <span class="font-medium text-secondary">{{ store.lyricSource ?? "—" }}</span> sidecar
          </span>
        </div>
        <p v-if="store.lastMessage" class="mt-1 text-xs text-success">
          {{ store.lastMessage }}
        </p>
        <p v-if="store.writeError" class="mt-1 text-xs text-danger">
          {{ store.writeError }}
        </p>
      </div>
      <p v-else-if="store.decision && store.decision !== 'not_found'" class="mt-3 text-xs text-tertiary">
        最佳候选无可用 TTML（可能未拉取到歌词）。
      </p>
    </template>
  </section>
</template>

<script setup lang="ts">
import type { Candidate, MatchDecision } from "@/apis/lyrics"
import { useLyricsStore } from "@/stores/lyrics"
import BaseButton from "@/components/ui/BaseButton.vue"
import TtmlPreview from "./TtmlPreview.vue"

/**
 * 在线匹配面板
 *
 * 职责：
 * - 「在线匹配」按钮 → store.runMatch(trackId, "netease,qq")
 * - 展示 decision 徽章（accept 绿 / review 黄 / reject 红 / not_found 灰）+ reason
 * - 候选列表（title/artist/album/score），best 高亮
 * - best_ttml 不为空时：TtmlPreview + 采纳按钮
 * - 采纳 → store.adoptBest(trackId)（source 用 lyric_source，不是 apple）
 *
 * 约束：
 * - auto-import 已注入 ref / computed
 * - 不直接调 apis，走 store
 */
const props = defineProps<{ trackId: string }>()

const store = useLyricsStore()

async function onMatch(): Promise<void> {
  await store.runMatch(props.trackId, "netease,qq")
}

async function onAdopt(): Promise<void> {
  await store.adoptBest(props.trackId)
}

/** decision 徽章配色：accept=success / review=accent / reject=danger / not_found=tertiary。 */
function decisionBadgeClass(d: MatchDecision | null): string {
  switch (d) {
    case "accept":
      return "bg-success-subtle text-success"
    case "review":
      return "bg-accent-subtle text-accent"
    case "reject":
      return "bg-danger-subtle text-danger"
    case "not_found":
      return "bg-surface text-tertiary"
    default:
      return "bg-surface text-tertiary"
  }
}

function decisionLabel(d: MatchDecision | null): string {
  switch (d) {
    case "accept":
      return "可直接采用"
    case "review":
      return "需人工复核"
    case "reject":
      return "低分"
    case "not_found":
      return "未找到"
    default:
      return "—"
  }
}

/** best 与候选是否同一项：source + title + artist + score 四元组近似。 */
function isSameCandidate(a: Candidate, b: Candidate): boolean {
  return (
    a.source === b.source &&
    a.title === b.title &&
    a.artist === b.artist &&
    a.score === b.score
  )
}

function formatScore(score: number): string {
  return score.toFixed(1)
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
