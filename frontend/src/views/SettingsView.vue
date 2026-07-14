<template>
  <div class="mx-auto max-w-3xl px-6 py-6">
    <!-- 页头 -->
    <div class="mb-6">
      <BaseButton variant="ghost" size="sm" icon="ArrowLeft" @click="router.push('/library')">
        返回曲库
      </BaseButton>
      <h1 class="mt-3 text-xl font-semibold text-primary">
        设置
      </h1>
      <p class="mt-1 text-xs text-secondary">
        应用运行期配置（持久化在 SQLite，修改即时生效）
      </p>
    </div>

    <!-- 加载中 -->
    <div
      v-if="settingsStore.loading"
      class="card p-8 text-center"
    >
      <p class="text-sm text-secondary">
        正在加载配置…
      </p>
    </div>

    <!-- 加载失败 -->
    <div
      v-else-if="settingsStore.error && !settingsStore.settings"
      class="card p-8 text-center"
    >
      <p class="mb-2 text-sm font-medium text-danger">
        加载失败
      </p>
      <p class="mb-3 text-xs text-secondary">
        {{ settingsStore.error }}
      </p>
      <BaseButton variant="secondary" size="sm" @click="settingsStore.load()">
        重试
      </BaseButton>
    </div>

    <!-- 主体：配置表单 -->
    <template v-else>
      <!-- Credits 代理配置 -->
      <section class="card mb-6 p-5">
        <header class="mb-4">
          <h2 class="text-base font-semibold text-primary">
            Credits 爬取代理
          </h2>
          <p class="mt-1 text-xs text-secondary">
            Apple Music 制作人员信息爬取用的 CF Worker 代理根地址。
            留空则直连官方域名 music.apple.com（可能因 geo 重定向拿不到目标区数据）。
          </p>
        </header>

        <!-- 输入框 -->
        <div class="space-y-3">
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-secondary">
              代理地址（Base URL）
            </span>
            <BaseInput
              v-model="creditsBaseUrl"
              type="url"
              placeholder="https://your-proxy.workers.dev"
              class="w-full"
              :disabled="settingsStore.saving"
            />
            <span class="mt-1 block text-xs text-tertiary">
              形如 <span class="font-mono">https://xxx.workers.dev</span>。留空 = 直连 music.apple.com
            </span>
          </label>
        </div>

        <!-- 操作区 -->
        <div class="mt-4 flex items-center gap-3">
          <BaseButton
            variant="primary"
            :disabled="settingsStore.saving"
            @click="onSave"
          >
            {{ settingsStore.saving ? "保存中…" : "保存" }}
          </BaseButton>
          <BaseButton
            v-if="hasChange"
            variant="secondary"
            :disabled="settingsStore.saving"
            @click="resetForm"
          >
            撤销修改
          </BaseButton>
        </div>

        <!-- 成功/错误提示 -->
        <div
          v-if="settingsStore.saved"
          class="mt-3 rounded-sm border border-subtle bg-success-subtle px-3 py-2 text-sm text-success"
        >
          已保存。后端下次 credits 请求即用新地址。
        </div>
        <div
          v-if="settingsStore.error"
          class="mt-3 rounded-sm border border-subtle bg-danger-subtle px-3 py-2 text-sm text-danger"
        >
          {{ settingsStore.error }}
        </div>
      </section>

      <!-- 直连说明 -->
      <section class="card p-5">
        <h2 class="mb-2 text-base font-semibold text-primary">
          关于直连
        </h2>
        <p class="text-xs text-secondary leading-relaxed">
          留空代理地址时，Lyra 直连 <span class="font-mono text-primary">music.apple.com</span>。
          从中国大陆 IP 访问会被 geo 重定向到 <span class="font-mono">music.apple.com/cn</span>，
          拿到的是中文区 credits 而非目标 region——可能不符预期。
          建议配置一个反代（如 Cloudflare Worker）出口在目标 region 的代理地址。
        </p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { useSettingsStore } from "@/stores/settings"
import BaseButton from "@/components/ui/BaseButton.vue"
import BaseInput from "@/components/ui/BaseInput.vue"

/**
 * 设置页
 * - 进入时自动 load 当前配置
 * - credits_base_url 输入框 + 保存按钮
 * - 撤销修改按钮（恢复到已保存值）
 * - saved/error 提示
 */
const router = useRouter()
const settingsStore = useSettingsStore()

// 本地编辑态（与 store 已保存值分离，支持"撤销修改"）
const creditsBaseUrl = ref("")
const initialValue = ref("")

const hasChange = computed(() => creditsBaseUrl.value !== initialValue.value)

onMounted(async () => {
  await settingsStore.load()
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
    // 保存成功后同步初始值
    initialValue.value = creditsBaseUrl.value
  }
}
</script>

<style scoped>
/* 全部通过 Tailwind token 类名控制 */
</style>
