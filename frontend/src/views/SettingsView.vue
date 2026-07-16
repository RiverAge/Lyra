<template>
  <div class="mx-auto max-w-3xl px-6 py-8">
    <!-- 页头 -->
    <div class="mb-7">
      <h1 class="mb-2 text-3xl font-semibold tracking-tight text-primary">设置</h1>
      <p class="text-sm text-secondary">应用运行期配置（持久化在 SQLite，修改即时生效）</p>
    </div>

    <!-- 加载中 -->
    <div v-if="settingsStore.loading" class="flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <p class="text-sm text-secondary">正在加载配置…</p>
    </div>

    <!-- 加载失败（可写配置加载失败，但只读区仍可展示） -->
    <div v-else-if="settingsStore.error && !settingsStore.settings" class="flex flex-col items-center rounded-lg border border-line bg-surface p-12 text-center">
      <p class="mb-2 text-sm font-medium text-danger">加载失败</p>
      <p class="mb-3 text-xs text-secondary">{{ settingsStore.error }}</p>
      <BaseButton variant="secondary" size="sm" @click="settingsStore.load()">重试</BaseButton>
    </div>

    <template v-else>
      <!-- 曲库区 -->
      <section class="mb-5 rounded-lg border border-line bg-surface p-5 shadow-card">
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 class="text-xl font-semibold tracking-tight text-primary">曲库</h3>
            <p class="mt-0.5 text-sm text-secondary">音乐库根目录与扫描状态</p>
          </div>
          <span class="pill" :class="scannerPillClass">{{ scannerPillText }}</span>
        </div>

        <div class="info-grid mb-5 flex flex-col gap-0.5">
          <div class="info-row">
            <span class="info-k">库根目录</span>
            <span class="info-v font-mono text-xs">{{ scannerStore.libraryRoot || "未配置" }}</span>
          </div>
          <div class="info-row">
            <span class="info-k">上次扫描</span>
            <span class="info-v">{{ formatTime(scannerStore.lastScannedAt) }}</span>
          </div>
          <div v-if="scannerStore.isScanning" class="info-row">
            <span class="info-k">扫描进度</span>
            <span class="info-v font-mono text-xs">{{ scannerStore.count }} / {{ scannerStore.totalFiles }}</span>
          </div>
          <div v-if="scannerStore.errorMessage" class="info-row">
            <span class="info-k">错误</span>
            <span class="info-v text-danger">{{ scannerStore.errorMessage }}</span>
          </div>
        </div>

        <div class="flex items-center gap-2.5">
          <BaseButton
            variant="primary"
            icon="RefreshCw"
            :disabled="scannerStore.isScanning || scannerStore.triggering || !scannerStore.libraryConfigured"
            @click="onTriggerScan"
          >
            {{ scannerStore.triggering ? "触发中…" : (scannerStore.isScanning ? "扫描中…" : "扫描曲库") }}
          </BaseButton>
          <BaseButton variant="secondary" icon="RefreshCw" :disabled="scannerStore.isScanning" @click="scannerStore.refreshStatus()">
            刷新状态
          </BaseButton>
        </div>

        <div v-if="scannerStore.triggerError" class="alert alert-fail">{{ scannerStore.triggerError }}</div>
        <div v-if="!scannerStore.libraryConfigured" class="alert alert-neutral">
          库根目录未配置（LYRA_MUSIC_LIBRARY_ROOT 未设置），扫描不可用。
        </div>
      </section>

      <!-- 元数据爬取代理区 -->
      <section class="mb-5 rounded-lg border border-line bg-surface p-5 shadow-card">
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 class="text-xl font-semibold tracking-tight text-primary">元数据爬取代理</h3>
            <p class="mt-0.5 text-sm text-secondary">Apple Music 制作人员信息爬取用的 CF Worker 代理根地址</p>
          </div>
        </div>

        <label class="mb-4 flex flex-col gap-1.5">
          <span class="text-xs font-medium text-secondary">代理地址（Base URL）</span>
          <BaseInput
            v-model="creditsBaseUrl"
            type="url"
            placeholder="https://your-proxy.workers.dev"
            class="w-full"
            :disabled="settingsStore.saving"
          />
          <span class="text-xs leading-normal text-tertiary">形如 <span class="font-mono">https://xxx.workers.dev</span>。留空 = 直连 music.apple.com（中国大陆 IP 会被 geo 重定向到中文区）</span>
        </label>

        <div class="flex items-center gap-2.5">
          <BaseButton variant="primary" :disabled="settingsStore.saving" @click="onSave">
            {{ settingsStore.saving ? "保存中…" : "保存" }}
          </BaseButton>
          <BaseButton v-if="hasChange" variant="secondary" :disabled="settingsStore.saving" @click="resetForm">
            撤销修改
          </BaseButton>
        </div>

        <div v-if="settingsStore.saved" class="alert alert-success">
          已保存。后端下次 credits 请求即用新地址。
        </div>
        <div v-if="settingsStore.error" class="alert alert-fail">{{ settingsStore.error }}</div>
      </section>

      <!-- 环境信息区（只读） -->
      <section class="mb-5 rounded-lg border border-line bg-surface p-5 shadow-card">
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 class="text-xl font-semibold tracking-tight text-primary">环境信息</h3>
            <p class="mt-0.5 text-sm text-secondary">运行期环境配置（LYRA_* 环境变量，只读）</p>
          </div>
          <BaseButton variant="ghost" size="sm" icon="RefreshCw" :disabled="settingsStore.configLoading" @click="settingsStore.loadConfig()">
            刷新
          </BaseButton>
        </div>

        <div v-if="settingsStore.configLoading" class="py-2 text-sm text-tertiary">加载中…</div>
        <div v-else-if="settingsStore.configError" class="alert alert-fail">{{ settingsStore.configError }}</div>
        <div v-else-if="settingsStore.config" class="info-grid flex flex-col gap-0.5">
          <div class="info-row">
            <span class="info-k">库根目录</span>
            <span class="info-v font-mono text-xs">{{ settingsStore.config.music_library_root || "未配置" }}</span>
          </div>
          <div class="info-row">
            <span class="info-k">数据库路径</span>
            <span class="info-v font-mono text-xs">{{ settingsStore.config.db_path }}</span>
          </div>
          <div class="info-row">
            <span class="info-k">日志目录</span>
            <span class="info-v font-mono text-xs">{{ settingsStore.config.log_dir || "未配置（仅 stdout）" }}</span>
          </div>
          <div class="info-row">
            <span class="info-k">日志级别</span>
            <span class="info-v font-mono text-xs">{{ settingsStore.config.log_level }}</span>
          </div>
          <div class="info-row">
            <span class="info-k">日志 rotate</span>
            <span class="info-v font-mono text-xs">{{ formatBytes(settingsStore.config.log_max_bytes) }} · 保留 {{ settingsStore.config.log_backup_count }} 份</span>
          </div>
          <div class="info-row">
            <span class="info-k">静态目录</span>
            <span class="info-v font-mono text-xs">{{ settingsStore.config.static_dir || "未配置" }}</span>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { useSettingsStore } from "@/stores/settings"
import { useScannerStore } from "@/stores/scanner"
import BaseButton from "@/components/ui/BaseButton.vue"
import BaseInput from "@/components/ui/BaseInput.vue"

/**
 * 设置页（B 布局重写）
 *
 * 三区：曲库（只读状态 + 扫描触发）/ 元数据爬取代理（可写）/ 环境信息（只读）
 * - settingsStore：可写配置 + 只读 config
 * - scannerStore：库根目录/扫描状态/触发扫描
 */

const settingsStore = useSettingsStore()
const scannerStore = useScannerStore()

// 本地编辑态（与 store 已保存值分离，支持"撤销修改"）
const creditsBaseUrl = ref("")
const initialValue = ref("")

const hasChange = computed(() => creditsBaseUrl.value !== initialValue.value)

// 扫描状态 pill
const scannerPillClass = computed(() => {
  if (scannerStore.isScanning) return "pill-active"
  if (scannerStore.isError) return "pill-fail"
  if (scannerStore.libraryConfigured) return "pill-ok"
  return "pill-neutral"
})
const scannerPillText = computed(() => {
  if (scannerStore.isScanning) return "扫描中"
  if (scannerStore.isError) return "错误"
  if (scannerStore.libraryConfigured) return "已就绪"
  return "未配置"
})

onMounted(async () => {
  await settingsStore.load()
  void settingsStore.loadConfig()
  await scannerStore.refreshStatus()
  syncFromStore()
})

function syncFromStore(): void {
  const val = settingsStore.settings?.credits_base_url ?? ""
  creditsBaseUrl.value = val
  initialValue.value = val
}

function resetForm(): void {
  creditsBaseUrl.value = initialValue.value
}

async function onSave(): Promise<void> {
  const ok = await settingsStore.save(creditsBaseUrl.value)
  if (ok) {
    initialValue.value = creditsBaseUrl.value
  }
}

async function onTriggerScan(): Promise<void> {
  await scannerStore.trigger()
}

/** 时间戳（秒/毫秒）→ 本地可读时间；null 显示 — */
function formatTime(ts: number | null): string {
  if (!ts) return "—"
  const ms = ts > 1e12 ? ts : ts * 1000
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleString("zh-CN", { hour12: false })
}

/** 字节数 → 可读（MB/KB） */
function formatBytes(bytes: number): string {
  if (!bytes) return "0B"
  const mb = bytes / (1024 * 1024)
  if (mb >= 1) return `${mb}MB`
  return `${Math.round(bytes / 1024)}KB`
}
</script>

<style scoped>
/* pill 状态徽章配色（scannerPillClass 动态返回） */
.pill {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border-radius: var(--radius-full);
  font-size: 12px;
  border: 1px solid var(--theme-border-default);
  background-color: var(--theme-bg-subtle);
  color: var(--theme-text-secondary);
  flex-shrink: 0;
}
.pill-ok {
  background-color: var(--theme-success-subtle);
  color: var(--theme-success);
  border-color: transparent;
}
.pill-active {
  background-color: var(--theme-accent-subtle);
  color: var(--theme-text-primary);
  border-color: transparent;
}
.pill-fail {
  background-color: var(--theme-danger-subtle);
  color: var(--theme-danger);
  border-color: transparent;
}
.pill-neutral {
  color: var(--theme-text-tertiary);
}

/* 信息表：2 列定宽 grid + :last-child（tw 难表达） */
.info-row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 16px;
  align-items: baseline;
  padding: 10px 0;
  border-bottom: 1px solid var(--theme-border-subtle);
}
.info-row:last-child {
  border-bottom: none;
}
.info-k {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  letter-spacing: 0.02em;
}
.info-v {
  font-size: 13px;
  color: var(--theme-text-primary);
  word-break: break-all;
}

/* 提示条配色（alert-success/fail/neutral 动态） */
.alert {
  margin-top: 14px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--theme-border-default);
  font-size: 13px;
}
.alert-success {
  background-color: var(--theme-success-subtle);
  color: var(--theme-success);
}
.alert-fail {
  background-color: var(--theme-danger-subtle);
  color: var(--theme-danger);
}
.alert-neutral {
  background-color: var(--theme-bg-subtle);
  color: var(--theme-text-tertiary);
}
</style>
