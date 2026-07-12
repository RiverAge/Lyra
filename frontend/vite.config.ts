import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import AutoImport from "unplugin-auto-import/vite";
import { resolve } from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget =
    env.VITE_API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [
      vue(),
      AutoImport({
        imports: ["vue", "vue-router", "pinia"],
        dts: "src/auto-imports.d.ts",
        eslintrc: {
          enabled: true,
          filepath: "./.eslintrc-auto-import.json"
        }
      }),
    ],
    resolve: {
      alias: {
        "@": resolve(__dirname, "src"),
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    }
  };
});
