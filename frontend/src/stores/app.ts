/**
 * 全局应用状态 Store（占位）
 *
 * 职责：
 * - 预留全局状态位（如侧边栏折叠、toast 队列等），按需扩展
 *
 * 约束：
 * - 本任务为占位实现，不预建业务状态
 * - 主题已废弃（固定浅色，见 tokens.css 单一 :root）
 * - auto-import 已注入 defineStore，不要手动 import
 */

export const useAppStore = defineStore("app", () => {
  return {}
})
