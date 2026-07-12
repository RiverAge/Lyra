import App from "./App.vue"
import router from "./router"

// 全局样式（含设计系统 token）
import "@/styles/tokens.css"

const app = createApp(App)

app.use(router)

// Pinia（store 在组件内 lazy-import，这里只挂实例）
// auto-import 已注入 createPinia，无需手动 import
app.use(createPinia())

app.mount("#app")
