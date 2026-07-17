<template>
  <div class="flex flex-col gap-6">
    <!-- section head -->
    <div class="flex items-baseline justify-between gap-4">
      <div>
        <h3 class="text-xl font-semibold tracking-tight text-primary">元数据</h3>
        <p class="mt-0.5 text-sm text-secondary">对照当前标签与权威值，勾选差异写入音频标签</p>
      </div>
      <span class="text-xs tracking-wide text-tertiary">已选 {{ selectedFieldCount }} 字段</span>
    </div>

    <!-- 统一卡片：工具栏 + 字段表 + 其他本地标签 -->
    <section class="card overflow-hidden">
      <!-- 表头工具栏：storefront/lang + 拉取 + 对比 + 写入 -->
      <div class="flex flex-wrap items-end justify-between gap-3 border-b border-line-subtle p-4">
        <div class="flex flex-wrap items-end gap-2.5">
          <label class="flex flex-col gap-1">
            <span class="text-xs text-secondary">storefront</span>
            <BaseInput v-model="storefront" placeholder="us" :disabled="fetchAllLoading" class="w-20" />
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-xs text-secondary">lang</span>
            <BaseInput v-model="lang" placeholder="zh-Hans" :disabled="fetchAllLoading" class="w-28" />
          </label>
          <BaseButton
            variant="primary"
            icon="Search"
            :disabled="fetchAllLoading || !trackId"
            @click="onFetchAll"
          >
            {{ fetchAllLoading ? fetchPhaseLabel : "拉取" }}
          </BaseButton>
        </div>
        <div class="flex flex-wrap items-end gap-2.5">
          <BaseButton
            variant="secondary"
            icon="Check"
            :disabled="diffLoading || !hasSelection"
            @click="onCompute"
          >
            {{ diffLoading ? "对比中…" : "对比" }}
          </BaseButton>
          <BaseButton
            variant="primary"
            danger
            icon="Edit3"
            :disabled="!canWrite"
            :title="!canWrite ? '请先对比 before/after' : ''"
            @click="showConfirm = true"
          >
            写入标签
          </BaseButton>
        </div>
      </div>

      <!-- 来源级状态 -->
      <div v-if="appleSourceStatus === 'failed_retryable' || creditsSourceStatus !== 'ok'" class="flex flex-col gap-2 px-4 pt-3">
        <div v-if="appleSourceStatus === 'failed_retryable'" class="flex items-center justify-between gap-3 rounded-sm border border-danger/30 bg-danger-subtle px-3 py-2">
          <span class="text-sm text-danger">结构化信息拉取失败，可重试</span>
          <BaseButton variant="ghost" size="sm" icon="RefreshCw" :disabled="fetchAllLoading" @click="onRetrySource('apple')">重试</BaseButton>
        </div>
        <div v-if="creditsSourceStatus === 'missing_permanent'" class="flex items-center justify-between gap-3 rounded-sm border border-line px-3 py-2">
          <span class="text-sm text-secondary">该曲目暂无制作人员信息</span>
        </div>
        <div v-if="creditsSourceStatus === 'failed_retryable'" class="flex items-center justify-between gap-3 rounded-sm border border-danger/30 bg-danger-subtle px-3 py-2">
          <span class="text-sm text-danger">制作人员信息拉取失败，可重试</span>
          <BaseButton variant="ghost" size="sm" icon="RefreshCw" :disabled="fetchAllLoading" @click="onRetrySource('credits')">重试</BaseButton>
        </div>
      </div>

      <!-- diff/写入 错误与成功提示 -->
      <div v-if="diffError" class="mx-4 mt-3 rounded-sm bg-danger-subtle px-3 py-2 text-sm text-danger">{{ diffError }}</div>
      <div v-if="writeError" class="mx-4 mt-3 rounded-sm bg-danger-subtle px-3 py-2 text-sm text-danger">{{ writeError }}</div>
      <div v-if="writeResult" class="mx-4 mt-3 rounded-sm bg-success-subtle px-3 py-2 text-sm text-success">
        写入成功：{{ writeResult.fields_written }} 个字段（{{ writeResult.format }}）
      </div>

      <!-- 统一字段表 -->
      <div v-if="unifiedRows.length > 0">
        <div class="table-head">
          <div class="truncate text-sm font-medium text-primary">字段</div>
          <div class="min-w-0 break-words text-sm text-secondary">当前值</div>
          <div class="min-w-0 flex flex-col gap-0.5 text-[13px] text-primary">权威值</div>
          <div class="text-center">状态</div>
          <div class="text-center">选</div>
        </div>
        <label
          v-for="row in unifiedRows"
          :key="row.field"
          class="table-row"
          :class="rowClass(row)"
        >
          <div class="truncate text-sm font-medium text-primary">{{ row.label }}</div>
          <div class="min-w-0 break-words text-sm text-secondary">
            <span v-if="row.currentValues.length > 0">{{ row.currentValues.join("; ") }}</span>
            <span v-else class="text-tertiary">—</span>
          </div>
          <div class="min-w-0 flex flex-col gap-0.5 text-[13px] text-primary">
            <template v-if="row.hasAuth">
              <span class="break-words">{{ row.authValues.join("; ") }}</span>
              <!-- diff 内联：before 小字（仅 hasDiff 且已对比） -->
              <span v-if="row.diffBefore" class="break-words text-xs text-tertiary">原: {{ row.diffBefore }}</span>
            </template>
            <span v-else-if="hasFetched" class="text-tertiary">—</span>
            <span v-else class="text-xs text-tertiary">未拉取</span>
          </div>
          <div class="text-center">
            <span v-if="!row.hasAuth" class="inline-flex items-center rounded-sm bg-subtle px-1.5 py-0.5 text-[11px] font-medium text-tertiary">本地</span>
            <span v-else-if="row.status === 'missing_permanent'" class="inline-flex items-center rounded-sm bg-subtle px-1.5 py-0.5 text-[11px] font-medium text-tertiary">暂无</span>
            <span v-else-if="row.status === 'failed_retryable'" class="inline-flex items-center rounded-sm bg-danger-subtle px-1.5 py-0.5 text-[11px] font-medium text-danger">失败</span>
            <span v-else class="inline-flex items-center rounded-sm bg-success-subtle px-1.5 py-0.5 text-[11px] font-medium text-success">就绪</span>
          </div>
          <div class="text-center">
            <input
              v-model="selected"
              type="checkbox"
              :value="row.field"
              :disabled="!row.hasAuth || row.status !== 'ok'"
              class="cb"
            >
          </div>
        </label>
      </div>
      <div v-else class="p-5 text-sm text-tertiary">
        该曲目无可读标签字段。
      </div>

      <!-- 其他本地标签（未映射到语义字段） -->
      <details v-if="otherLocalRows.length > 0" class="border-t border-line-subtle">
        <summary class="other-summary list-none px-4 py-2.5 text-xs text-secondary cursor-pointer hover:text-primary">
          其他本地标签（{{ otherLocalRows.length }}）
        </summary>
        <div class="grid grid-cols-2 max-sm:grid-cols-1 px-4 pb-3">
          <div v-for="row in otherLocalRows" :key="row.key" class="grid grid-cols-[96px_1fr] items-baseline gap-3 border-b border-line-subtle py-1.5">
            <div class="font-mono text-[11px] text-tertiary overflow-hidden text-ellipsis whitespace-nowrap" :title="row.key">{{ row.label }}</div>
            <div class="break-words text-xs text-secondary">{{ row.values.join("; ") }}</div>
          </div>
        </div>
      </details>
    </section>

    <!-- 写入二次确认弹窗（迁自 DiffView） -->
    <Teleport to="body">
      <div
        v-if="showConfirm"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
        role="dialog"
        aria-modal="true"
        @click.self="showConfirm = false"
      >
        <div class="card-elevated max-w-md w-full p-5">
          <h4 class="mb-2 text-base font-semibold text-primary">确认写入标签？</h4>
          <p class="mb-4 text-sm text-secondary">
            写操作不可逆（无 Ctrl+Z，无自动备份）。将写入
            <span class="text-primary">{{ diffSummaryText }}</span>。请确认上方对比无误后再继续。
          </p>
          <div v-if="writeError" class="mb-3 rounded-md border border-line-subtle bg-danger-subtle px-3 py-2 text-sm text-danger">
            {{ writeError }}
          </div>
          <div class="flex justify-end gap-2">
            <BaseButton variant="secondary" :disabled="writeLoading" @click="showConfirm = false">取消</BaseButton>
            <BaseButton variant="primary" danger :disabled="writeLoading" @click="onWrite">
              {{ writeLoading ? "写入中…" : "确认写入" }}
            </BaseButton>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import BaseButton from "@/components/ui/BaseButton.vue"
import BaseInput from "@/components/ui/BaseInput.vue"
import { useMetaStore } from "@/stores/meta"
import { fetchTrackTags } from "@/apis/meta"
import type { AuthoritativeFields } from "@/apis/meta"
import type { TrackItem } from "@/apis/library"

/**
 * 元数据 tab（单一字段表重构）
 *
 * 范式：从"当前标签/拉取/对比/写入"四卡纵向罗列，改为一张统一字段表。
 * 行 = 语义字段名（FIELD_MAP 的 18 个，来自 /meta/fields）。
 * 列 = 字段 / 当前值(tag_map 经 mutagen→semantic 反向映射) / 权威值(fieldStatusMap) / 状态 / 勾选。
 * 拉取前只显当前值列，拉取后权威值列亮出，diff 内联（权威列下方 before 小字）。
 * 对比/写入融入表头工具栏，写入二次确认弹窗内联（迁自 DiffView）。
 *
 * 约束：auto-import 已注入 ref/computed/onMounted/watch/storeToRefs。
 */
const props = defineProps<{
  trackId: string
  track?: TrackItem | null
}>()

const emit = defineEmits<{
  /** 写入成功，通知父组件（父可刷新 track 基础列；tag_map 不再入库，本组件自行 reload） */
  (e: "written"): void
}>()

const store = useMetaStore()
const {
  fetchAllLoading,
  fetchAllPhase,
  appleSourceStatus,
  creditsSourceStatus,
  fieldStatusMap,
  fieldMap,
  diffLoading,
  diffError,
  diffResult,
  writeLoading,
  writeError,
  writeResult,
} = storeToRefs(store)

const storefront = ref("us")
const lang = ref("zh-Hans")
const selected = ref<string[]>([])
const showConfirm = ref(false)

// 现读的 tag_map（B 方案：不入库，调 /meta/{id}/tags 拿）。
// 文本 tag 经白名单过滤，不含 covr 等二进制。加载失败为空 {}（表显空）。
const tagMap = ref<Record<string, unknown>>({})
const tagMapLoading = ref(false)

// ---------- 语义字段反向映射 ----------

/** codec → mutagen key 列名（FIELD_MAP 各容器列） */
function codecColumn(codec: string | undefined): "mp4" | "flac" | "mp3" {
  // alac/m4a → MP4 容器；flac → flac；mp3 → mp3
  const c = (codec || "").toLowerCase()
  if (c === "flac") return "flac"
  if (c === "mp3") return "mp3"
  return "mp4" // alac / m4a / mp4 / 未知都走 MP4
}

/** 语义字段 → 中文标签（FIELD_MAP 的 18 个 semantic 名） */
const SEMANTIC_LABELS: Record<string, string> = {
  title: "标题", artist: "艺人", album_artist: "专辑艺人", album: "专辑",
  composer: "作曲", lyricist: "作词", producer: "制作人", mixer: "混音师",
  engineer: "工程师", remixer: "混音师(remix)", arranger: "编曲", conductor: "指挥",
  djmixer: "DJ混音", performer: "表演者", genre: "流派", copyright: "版权",
  record_company: "厂牌", isrc: "ISRC", barcode: "条码",
}

/** 从 fieldMap 构建 mutagen key → semantic 反向映射（按 codec 选列） */
const mutagenToSemantic = computed<Record<string, string>>(() => {
  const col = codecColumn(props.track?.codec as string | undefined)
  const out: Record<string, string> = {}
  for (const f of fieldMap.value?.fields ?? []) {
    const k = f[col]
    if (k) out[k] = f.semantic
  }
  return out
})

/** 是否已拉取过权威值（决定权威列显示"未拉取"还是"—"） */
const hasFetched = computed(() => Object.keys(fieldStatusMap.value).length > 0)

// ---------- tag_map（现读 /meta/{id}/tags） ----------

/** 异步加载当前 track 的 tag_map（现读文件，B 方案不入库） */
async function loadTagMap(): Promise<void> {
  if (!props.trackId) return
  tagMapLoading.value = true
  try {
    const res = await fetchTrackTags(props.trackId)
    tagMap.value = (res.tag_map && typeof res.tag_map === "object")
      ? res.tag_map as Record<string, unknown>
      : {}
  } catch {
    tagMap.value = {}
  } finally {
    tagMapLoading.value = false
  }
}

/** 当前 tag_map（现读缓存，供 unifiedRows / otherLocalRows 取值） */
function parseTagMap(): Record<string, unknown> {
  return tagMap.value
}

/** 二进制/非文本 tag key（封面/编码工具，不当文本展示） */
const BINARY_KEYS = new Set<string>([
  "covr", "©cov", "©too", "@too", "tool", "encoder", "encodersettings",
])

function toStringArray(v: unknown): string[] {
  const arr = Array.isArray(v) ? v : [v]
  return arr.map((x) => String(x)).filter(Boolean)
}

// ---------- 统一字段表行 ----------

interface UnifiedRow {
  field: string
  label: string
  currentValues: string[]
  authValues: string[]
  source: "apple" | "credits" | null
  status: "ok" | "missing_permanent" | "failed_retryable"
  hasAuth: boolean
  hasDiff: boolean
  /** diff 对比后的 before 文本（仅 hasDiff 且已 loadDiff） */
  diffBefore: string | null
}

/** 行级动态 class：差异行 accent-subtle 底；权威存在但状态非 ok 的行半透明 */
function rowClass(row: UnifiedRow): string {
  const cls: string[] = []
  if (row.hasDiff) cls.push("bg-accent-subtle")
  if (row.hasAuth && row.status !== "ok") cls.push("opacity-50")
  return cls.join(" ")
}

/** 统一字段表：以语义字段为行，合并当前值 + 权威值 + diff before */
const unifiedRows = computed<UnifiedRow[]>(() => {
  const tagMap = parseTagMap() ?? {}
  // 语义字段集合：优先用 fieldMap（18 个），降级用 SEMANTIC_LABELS
  const semanticList =
    fieldMap.value?.fields.map((f) => f.semantic) ?? Object.keys(SEMANTIC_LABELS)
  // 反向：semantic → tag_map 里的 mutagen key（取反向映射命中的 key）
  const semToMutagenKey: Record<string, string> = {}
  for (const [mKey, sem] of Object.entries(mutagenToSemantic.value)) {
    semToMutagenKey[sem] = mKey
  }

  const rows: UnifiedRow[] = []
  for (const sem of semanticList) {
    // 当前值：从 tag_map 按 mutagen key 取
    const mKey = semToMutagenKey[sem]
    const currentRaw = mKey ? tagMap[mKey] : undefined
    const currentValues = currentRaw != null && currentRaw !== "" ? toStringArray(currentRaw) : []

    // 权威值：从 fieldStatusMap 取
    const auth = fieldStatusMap.value[sem]
    const hasAuth = !!auth
    const authValues = auth?.values ?? []
    const status = auth?.status ?? "ok"
    const source = auth?.source ?? null

    // diff before（仅当已 loadDiff）
    const diffEntry = diffResult.value?.diffs?.find((d) => d.field === sem)
    const hasDiff = hasAuth && currentValues.length > 0 &&
      JSON.stringify(currentValues) !== JSON.stringify(authValues)
    const diffBefore = diffEntry && diffEntry.before != null
      ? formatBefore(diffEntry.before)
      : null

    rows.push({
      field: sem,
      label: SEMANTIC_LABELS[sem] ?? sem,
      currentValues,
      authValues,
      source,
      status,
      hasAuth,
      hasDiff,
      diffBefore,
    })
  }
  return rows
})

/** 未映射到语义字段的本地 tag key（其他本地标签） */
interface LocalRow {
  key: string
  label: string
  values: string[]
}

const OTHER_LABELS: Record<string, string> = {
  "©day": "年份", date: "年份", TDRC: "年份", "©cmt": "注释", comment: "注释",
  COMM: "注释", "©lyr": "内嵌歌词", lyrics: "内嵌歌词", USLT: "内嵌歌词",
  tracknumber: "音轨号", TRCK: "音轨号", discnumber: "碟号", TPOS: "碟号",
}

const otherLocalRows = computed<LocalRow[]>(() => {
  const tagMap = parseTagMap() ?? {}
  const mapped = new Set(Object.keys(mutagenToSemantic.value))
  return Object.entries(tagMap)
    .filter(([key, v]) => {
      if (mapped.has(key)) return false
      if (v === null || v === undefined || v === "") return false
      if (BINARY_KEYS.has(key)) return false
      return true
    })
    .map(([key, v]) => {
      const values = toStringArray(v).map((s) => (s.length > 200 ? s.slice(0, 200) + "…" : s))
      return { key, label: OTHER_LABELS[key] ?? key, values }
    })
    .filter((r) => r.values.length > 0)
    .sort((a, b) => a.label.localeCompare(b.label))
})

// ---------- 选择 / diff / 写入（迁自 DiffView） ----------

/** 当前勾选的权威字段（仅 ok 状态选中项） */
const mergedFields = computed<AuthoritativeFields>(() => {
  const out: AuthoritativeFields = {}
  for (const k of selected.value) {
    const entry = fieldStatusMap.value[k]
    if (entry && entry.status === "ok") out[k] = entry.values
  }
  return out
})

const selectedFieldCount = computed(() => Object.keys(mergedFields.value).length)
const hasSelection = computed(() => Object.keys(mergedFields.value).length > 0)
const canWrite = computed(() => Boolean(diffResult.value) && hasSelection.value)

/** diff 摘要文案（确认框用） */
const diffSummaryText = computed(() => {
  const diffs = diffResult.value?.diffs
  if (!diffs || diffs.length === 0) return `${selectedFieldCount.value} 个字段的权威值`
  const counts = { added: 0, modified: 0, removed: 0 }
  for (const d of diffs) {
    const kind = normalizeKind(d.kind, d.before, d.after)
    if (kind in counts) counts[kind as keyof typeof counts]++
  }
  const parts: string[] = []
  if (counts.added > 0) parts.push(`${counts.added} 新增`)
  if (counts.modified > 0) parts.push(`${counts.modified} 修改`)
  if (counts.removed > 0) parts.push(`${counts.removed} 删除`)
  const total = counts.added + counts.modified + counts.removed
  if (parts.length === 0) return `${selectedFieldCount.value} 个字段（无变更）`
  return `${total} 个字段（${parts.join("、")}）`
})

function normalizeKind(kind: unknown, before: unknown, after: unknown): "added" | "modified" | "removed" | "unchanged" {
  if (kind === "added" || kind === "modified" || kind === "removed" || kind === "unchanged") return kind
  if (before === undefined && after !== undefined) return "added"
  if (before !== undefined && after === undefined) return "removed"
  if (JSON.stringify(before) !== JSON.stringify(after)) return "modified"
  return "unchanged"
}

function formatBefore(v: unknown): string {
  if (v == null) return ""
  if (Array.isArray(v)) return v.length === 0 ? "[]" : v.join("; ")
  if (typeof v === "string") return v
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

const fetchPhaseLabel = computed(() => {
  switch (fetchAllPhase.value) {
    case "apple": return "结构化信息…"
    case "credits": return "制作人员…"
    default: return "拉取中…"
  }
})

// ---------- actions ----------

async function onFetchAll(): Promise<void> {
  selected.value = []
  store.clearDiff()
  await store.fetchAllMeta(props.trackId, storefront.value, lang.value)
  const okFields = Object.values(fieldStatusMap.value).filter((f) => f.status === "ok").map((f) => f.field)
  selected.value = okFields
}

async function onRetrySource(source: "apple" | "credits"): Promise<void> {
  await store.retrySource(props.trackId, source, storefront.value, lang.value)
  const okFields = Object.values(fieldStatusMap.value).filter((f) => f.status === "ok").map((f) => f.field)
  const newSelected = new Set(selected.value)
  for (const f of okFields) newSelected.add(f)
  selected.value = [...newSelected]
}

async function onCompute(): Promise<void> {
  await store.loadDiff(props.trackId, mergedFields.value)
}

async function onWrite(): Promise<void> {
  const res = await store.doWrite(props.trackId, mergedFields.value)
  if (res) {
    showConfirm.value = false
    emit("written")
    // 写入后重新现读 tag_map（文件已改）+ 刷新 diff，让 before 对齐新值
    await loadTagMap()
    await store.loadDiff(props.trackId, mergedFields.value)
  }
}

// 勾选变化时清空 diff（防旧 diff 与新勾选不一致）
watch(selected, () => store.clearDiff(), { deep: true })

// 切换 track 重置 + 重载 tag_map
watch(
  () => props.trackId,
  (next, prev) => {
    if (next !== prev) {
      store.reset("all")
      selected.value = []
      showConfirm.value = false
      tagMap.value = {}
      void loadTagMap()
    }
  },
)

// 进页拉取字段映射（构建反向映射；失败降级）+ 现读 tag_map
onMounted(async () => {
  await store.loadFieldMap()
  await loadTagMap()
})
</script>

<style scoped>
/* 统一字段表：5 列定宽 grid + @media 响应式（tw 难表达多列定宽 + last-child，保留 scoped） */
.table-head,
.table-row {
  display: grid;
  grid-template-columns: 120px 1fr 1fr 64px 40px;
  gap: 12px;
  align-items: center;
  padding: 10px 16px;
}
.table-head {
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--theme-text-tertiary);
  font-weight: 500;
  font-size: 11px;
  background-color: var(--theme-bg-subtle);
  border-bottom: 1px solid var(--theme-border-default);
}
.table-row {
  border-bottom: 1px solid var(--theme-border-subtle);
  transition: background-color var(--animate-duration-hover) ease;
}
.table-row:last-child {
  border-bottom: none;
}
.table-row:hover {
  background-color: var(--theme-bg-hover);
}

/* 复选框：accent-color 无 tw 等价 */
.cb {
  accent-color: var(--theme-accent);
  width: 14px;
  height: 14px;
  cursor: pointer;
}

/* details summary：隐藏原生三角（list-none 在部分浏览器不够，::-webkit 补刀） */
.other-summary::-webkit-details-marker {
  display: none;
}

@media (max-width: 640px) {
  .table-head,
  .table-row {
    grid-template-columns: 100px 1fr 1fr 56px 36px;
    gap: 8px;
    padding: 10px 12px;
  }
}
</style>
