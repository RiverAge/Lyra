import js from '@eslint/js'
import fs from 'node:fs'
import path from 'node:path'
import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import vuePlugin from 'eslint-plugin-vue'
import vueParser from 'vue-eslint-parser'
import { fileURLToPath } from 'node:url'

const rootDir = path.dirname(fileURLToPath(import.meta.url))
const autoImportGlobalsPath = path.join(rootDir, '.eslintrc-auto-import.json')
const autoImportGlobals = fs.existsSync(autoImportGlobalsPath)
  ? JSON.parse(fs.readFileSync(autoImportGlobalsPath, 'utf8')).globals ?? {}
  : {}

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'src/auto-imports.d.ts',
      '.eslintrc-auto-import.json',
    ],
  },
  js.configs.recommended,
  ...vuePlugin.configs['flat/essential'],
  {
    files: ['src/**/*.{ts,vue}'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tsParser,
        ecmaVersion: 'latest',
        sourceType: 'module',
        extraFileExtensions: ['.vue'],
      },
      globals: {
        window: 'readonly',
        document: 'readonly',
        console: 'readonly',
        localStorage: 'readonly',
        navigator: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
        ...autoImportGlobals,
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
      }],
      'max-lines': ['error', {
        max: 700,
        skipBlankLines: true,
        skipComments: true,
      }],
      'vue/block-order': ['error', {
        order: ['template', 'script', 'style'],
      }],
      'vue/multi-word-component-names': 'off',

      // 合并为单条 error（camping 原版双写导致 auto-import 提示是死代码，此处修复）
      'no-restricted-imports': ['error', {
        paths: [
          {
            name: 'vue',
            importNames: ['ref', 'computed', 'watch', 'watchEffect', 'reactive', 'onMounted', 'onUnmounted', 'nextTick', 'h', 'readonly', 'shallowRef', 'toRef', 'toRefs', 'unref'],
            message: '这些 API 已通过 auto-import 提供，请直接使用，不要手动 import。',
          },
          {
            name: 'vue-router',
            importNames: ['useRoute', 'useRouter', 'onBeforeRouteLeave', 'onBeforeRouteUpdate'],
            message: '这些 API 已通过 auto-import 提供，请直接使用，不要手动 import。',
          },
          {
            name: 'pinia',
            importNames: ['defineStore', 'storeToRefs', 'createPinia', 'acceptHMRUpdate'],
            message: '这些 API 已通过 auto-import 提供，请直接使用，不要手动 import。',
          },
          {
            name: 'axios',
            message: '禁止直接导入 axios。请使用 src/apis/http.ts 中的统一请求客户端（http.get / http.post 等）。',
          },
          {
            name: 'axios/unsafe/*',
            message: '禁止直接导入 axios。请使用 src/apis/http.ts 中的统一请求客户端。',
          },
        ],
      }],

      // 项目基线禁则：catch 必须 unknown、禁 reactive（优先 ref）、禁 setInterval（走 SSE/WS）、禁 fetch/XMLHttpRequest（走统一客户端）
      'no-restricted-syntax': ['error',
        {
          selector: 'CatchClause[param.typeAnnotation.typeAnnotation.type="TSAnyKeyword"]',
          message: 'Catch parameter must use `unknown`, not `any`. Use `catch (e: unknown)` and handle via getErrorMessage/normalizeError.',
        },
        {
          selector: "CallExpression[callee.name='reactive']",
          message: '默认使用 `ref(...)` 声明状态（包括对象、表单、过滤器、分页等）。仅当"代理式对象访问"能带来明确收益时才使用 `reactive`，并在该行加 `// eslint-disable-next-line no-restricted-syntax -- 原因：...` 显式说明理由。',
        },
        {
          selector: "CallExpression[callee.name='setInterval']",
          message: '项目基线禁止使用 `setInterval` 轮询。推送场景必须使用 SSE/WS，并在断线时提供明确重连或刷新引导。',
        },
        {
          selector: "CallExpression[callee.object.name='window'][callee.property.name='setInterval']",
          message: '项目基线禁止使用 `setInterval` 轮询。推送场景必须使用 SSE/WS，并在断线时提供明确重连或刷新引导。',
        },
        {
          selector: "CallExpression[callee.name='fetch']",
          message: '禁止直接使用 fetch()。请使用 src/apis/http.ts 中的统一请求客户端（http.get / http.post 等），以确保 token 注入、错误处理和 401 拦截生效。',
        },
        {
          selector: "NewExpression[callee.name='XMLHttpRequest']",
          message: '禁止直接使用 XMLHttpRequest。请使用 src/apis/http.ts 中的统一请求客户端（http.get / http.post 等），以确保 token 注入、错误处理和 401 拦截生效。',
        },
      ],
    },
  },
  // 白名单：http.ts 是统一请求封装，是唯一允许 import axios 的文件
  {
    files: ['src/apis/http.ts'],
    rules: {
      'no-restricted-imports': 'off',
    },
  },
]
