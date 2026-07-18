/**
 * 动画偏好（纯前端偏好，localStorage 持久化，不走后端）
 *
 * 设计：
 * - 默认开动画（无视系统 prefers-reduced-motion）——自用工具，动画常驻
 * - 关闭 → 给 <html> 打 .no-anim class，全局 transition/animation 压成瞬时
 *   （tokens.css 的 .no-anim 规则兜底）
 * - 模块级单例 ref（多组件共享同一状态，import 即同步）
 *
 * localStorage key: lyra-anim，值 "1"=开 / "0"=关。默认（无 key）= 开。
 */

const STORAGE_KEY = "lyra-anim"

/** <html> class 名：打上后 tokens.css 压所有动画/过渡为瞬时 */
const NO_ANIM_CLASS = "no-anim"

function readInitial(): boolean {
  if (typeof window === "undefined") return true
  const v = localStorage.getItem(STORAGE_KEY)
  // 默认开（无 key 或非法值都视为开）
  return v !== "0"
}

const enabled = ref<boolean>(readInitial())

/** 把当前 enabled 同步到 <html> class（开→移除 no-anim，关→打上 no-anim） */
function syncHtmlClass(v: boolean): void {
  if (typeof document === "undefined") return
  const el = document.documentElement
  if (v) el.classList.remove(NO_ANIM_CLASS)
  else el.classList.add(NO_ANIM_CLASS)
}

/** 启动时应用一次（App.vue onMounted 调，SSR 安全守卫已含） */
function applyOnBoot(): void {
  syncHtmlClass(enabled.value)
}

/** 设开关：写 localStorage + 同步 <html> class + 更新 ref */
function setEnabled(v: boolean): void {
  enabled.value = v
  if (typeof window !== "undefined") {
    localStorage.setItem(STORAGE_KEY, v ? "1" : "0")
  }
  syncHtmlClass(v)
}

export function useAnimationPref() {
  return { enabled, applyOnBoot, setEnabled }
}
