import type { AppSettings } from "@/apis/settings"
import { fetchSettings, saveSettings } from "@/apis/settings"

/**
 * Settings Store
 *
 * 职责：
 * - 维护应用配置状态（credits_base_url 等）
 * - load：进入配置页时拉取当前值
 * - save：用户保存时写入后端
 *
 * 设计：
 * - loading/saving/error 三件套（照 meta.ts 范式）
 * - credits_base_url 空串=直连 music.apple.com（后端语义）
 */

export const useSettingsStore = defineStore("settings", () => {
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)
  const settings = ref<AppSettings | null>(null)
  const saved = ref(false)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      settings.value = await fetchSettings()
    } catch (e: unknown) {
      error.value = normalizeError(e)
      settings.value = null
    } finally {
      loading.value = false
    }
  }

  async function save(creditsBaseUrl: string): Promise<boolean> {
    saving.value = true
    error.value = null
    saved.value = false
    try {
      settings.value = await saveSettings({ credits_base_url: creditsBaseUrl })
      saved.value = true
      return true
    } catch (e: unknown) {
      error.value = normalizeError(e)
      return false
    } finally {
      saving.value = false
    }
  }

  function reset(): void {
    settings.value = null
    error.value = null
    saved.value = false
  }

  return { loading, saving, error, settings, saved, load, save, reset }
})

function normalizeError(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { status?: number; data?: unknown } }).response
    if (resp?.status === 503) return "数据库未初始化，无法保存配置"
  }
  if (e instanceof Error) return e.message
  return "请求失败"
}
