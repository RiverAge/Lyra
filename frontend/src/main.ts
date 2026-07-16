import App from "./App.vue"
import router from "./router"

// 字体本地托管（@fontsource，字体文件进 bundle，零外部 CDN 依赖）
// 英文 Inter：400/500/600/700（tokens.css --font-sans 用 "Inter"）
import "@fontsource/inter/400.css"
import "@fontsource/inter/500.css"
import "@fontsource/inter/600.css"
import "@fontsource/inter/700.css"
// 等宽 JetBrains Mono：400/500/600（--font-mono 用 "JetBrains Mono"）
import "@fontsource/jetbrains-mono/400.css"
import "@fontsource/jetbrains-mono/500.css"
import "@fontsource/jetbrains-mono/600.css"
// 中文 Noto Sans SC：用 chinese-simplified 单文件子集（一次覆盖常用中文，
// 非默认的多 unicode-range 分包——本地托管不需要按需探测，单文件更稳）
import "@fontsource/noto-sans-sc/chinese-simplified-400.css"
import "@fontsource/noto-sans-sc/chinese-simplified-500.css"
import "@fontsource/noto-sans-sc/chinese-simplified-700.css"

// 全局样式（含设计系统 token）
import "@/styles/tokens.css"

const app = createApp(App)

app.use(router)

// Pinia（store 在组件内 lazy-import，这里只挂实例）
// auto-import 已注入 createPinia，无需手动 import
app.use(createPinia())

app.mount("#app")
