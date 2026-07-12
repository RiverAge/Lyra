import axios from 'axios'

/**
 * Lyra 统一请求客户端
 *
 * 职责：
 * 1. 请求拦截器：注入 Bearer token（若 localStorage 有）
 * 2. 响应拦截器：401 防抖 + 可注册外部 handler（解耦 token 失效处理与请求层）
 *
 * 约束：本文件是 eslint no-restricted-imports axios 白名单的唯一文件，
 * 其余模块禁止直接 import axios，必须用 `http.get / http.post`。
 *
 * Lyra 后端是 FastAPI，响应不套 envelope，直接用 response.data。
 * 若后续需要统一错误格式，在响应拦截器里加，不要在业务层各自处理。
 */

export interface UnauthorizedContext {
  url: string
  statusCode: number
}

type UnauthorizedHandler = (ctx: UnauthorizedContext) => void | Promise<void>

let unauthorizedHandler: UnauthorizedHandler | null = null
let isHandling401 = false

/**
 * 注册 401 处理器（如跳转登录、刷新 token）。
 * 防抖：并发的 401 只触发一次 handler，其余静默 reject。
 */
export function registerUnauthorizedHandler(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler
}

export const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url: string = error.config?.url || ''
      if (!isHandling401 && unauthorizedHandler) {
        isHandling401 = true
        const ctx: UnauthorizedContext = { url, statusCode: 401 }
        void Promise.resolve(unauthorizedHandler(ctx))
          .catch((handlerError) => { console.error('[http] unauthorized handler failed:', handlerError) })
          .finally(() => { isHandling401 = false })
      }
    }
    return Promise.reject(error)
  },
)
