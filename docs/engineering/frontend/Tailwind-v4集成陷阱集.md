# Tailwind v4 集成陷阱集

> 适用范围:Vue3 前端。Lyra 用 Tailwind v4(`@tailwindcss/postcss` + `tailwindcss@4.x`),CSS-first 配置(`@import "tailwindcss"` + `@theme` 块)。本文档汇总 Lyra 踩过的三类 v4 集成陷阱,供后人遇同类症状时按图索骥。
> 三类陷阱的共同根:**Tailwind v4 自动注入的底层规则(Preflight / @theme 生成 / 自动内容检测)与项目代码(残留 v3 config / scoped var / transition border-color)叠加产生隐蔽副作用**——配置层、命名层、渲染层各一处。

---

## 陷阱目录

| # | 陷阱 | 层 | 一句话 |
|---|---|---|---|
| 1 | v3 config 残留 | 配置层 | v4 项目留着空壳 `tailwind.config.js`,真源在 `@theme` 但 config 误导后人重复定义 |
| 2 | theme 双源冲突 | 命名层 | `@theme` 生成的工具类 与 scoped 里 `var()`/hex 并行,改一处另一处不跟 |
| 3 | Preflight `border:0 solid` × reduce-motion 刷新黑框 | 渲染层 | 详见独立文档 [`刷新黑框-Preflight-border与reduced-motion.md`](./刷新黑框-Preflight-border与reduced-motion.md) |

---

## 陷阱 1:v3 config 残留(配置层)

### 症状

`frontend/tailwind.config.js` 是 v3 风格配置文件,内容空壳:

```js
export default {
  content: ["./index.html", "./src/**/*.{vue,js,ts,jsx,tsx}"],  // v3 概念
  theme: { extend: {} },   // 空壳
  plugins: [],
}
```

### 根因

- **v4 是 CSS-first**:`@import "tailwindcss"` + `@theme` 块就是全部配置,真源在 `tokens.css`
- **v3 的 `content` 数组在 v4 空跑**:v4 用自动内容检测 + `@source` 指令,`@tailwindcss/postcss` 为兼容才读 config 的 `content`(行为等价于默认扫 `index.html`+`src/**`)
- **v3 的 `theme.extend` 在 v4 由 `@theme` 块替代**:config 里的 `extend` 是死代码

### 危害(不是无害的"留着自己看")

**误导性**——让后人以为配置在 config 文件里,可能在 config 里加东西造成与 `@theme` **重复定义**(就是陷阱 2 的成因)。空壳 config 是陷阱 2 的温床,留着等于留坑。

### 修复

**删掉 `tailwind.config.js`**。v4 不需要它。删后 `@tailwindcss/postcss` 走默认内容检测(覆盖 `index.html`+`src/**`),工具类照常生成,行为不变。

### 验证

```bash
cd frontend && pnpm build   # 工具类照常生成、无 class 丢失即确认
```

### 历史

- `d89e9d6`(前端骨架)引入:同时有 v4 的 `@import "tailwindcss"` + v3 的 `tailwind.config.js`(含 `theme.extend.fontFamily`,与 `@theme` 重复)
- `8f9920f`(设计系统重构)清理:把 config 里 `fontFamily` 清空,留注释「fontFamily 真源在 @theme 块,此处留空避免冗余覆盖」——但**只清内容、没删文件**
- 本次:删整个空壳 config

---

## 陷阱 2:theme 双源冲突(命名层)

### 症状

改 token 后视觉不一致——`@theme` 生成的工具类(`bg-surface`/`text-primary`)变了,但部分组件 scoped style 里直接写 `var(--theme-xxx)` 或硬编码 hex 没跟着变,同色名两套来源并行。

### 根因

存在**两套色源**:
1. `tokens.css @theme` 块 → Tailwind 自动生成 `bg-*`/`text-*`/`border-*` 工具类(真源)
2. 各 `.vue` scoped style 里直接写 `var(--theme-xxx)` 或 hex(旁路源)

改 token 时(1)变了、(2)没跟,视觉不一致。这是「theme 跟 tailwind 冲突」体感最强的来源。

### 子陷阱:`bg-bg-*` 错位命名

`8f9920f` 时 `@theme` 块把背景色 token 注册成 `--color-bg-base`/`--color-bg-surface`(多一层 `bg`),Tailwind v4 据此生成工具类 `bg-bg-base`(**两个 bg**:`bg-` 前缀 + `bg-base` 色名),全项目写成 `bg-bg-surface` 这种绕口名。

`a93fb61` 改成 `--color-base`/`--color-surface`(去多余层级),工具类变正常 `bg-surface`,清理 5 文件的 `bg-bg-*`→`bg-*`、`text-white`→`text-on-accent`。

### 子陷阱:`data-theme` 双主题

`a93fb61` 时 tokens.css 是 `:root[data-theme="dark"]`/`[data-theme="light"]` 双主题 + `app.ts` 默认 dark。`7e746c8` 改成**单一浅色主题、去 `data-theme` 分支**(`--theme-accent` 从靛蓝 `#6366f1` 改墨黑 `#18181b`)。

### 修复

`7e746c8`(TW 全项目收口)消灭旁路源:scoped style 清空、全用 tw 工具类。commit message 原话「删除文件内重复定义的语义色类(@theme 已生成)」——删 scoped 里手写的 `.text-primary {color:var(...)}` 等与 `@theme` 同名重复的定义。

`f5c41ea`(收尾)把剩余 scoped 里 tw 无法表达的规则集中到 `tokens.css @layer utilities`(全局工具类),scoped 只留 tw 硬约束(grid/伪元素/v-bind/keyframes/accent-color)。

### 教训

**单一真源**:`@theme` 是 token 唯一真源,组件只用 tw 工具类(`bg-surface`/`text-primary`),不在 scoped 里写 `var(--theme-xxx)` 或 hex。必须写 `var()` 时(如 keyframes / `accent-color` / `v-bind`),集中在 `tokens.css @layer utilities` 的全局工具类里,不散落组件。

> 关联记忆:`lyra-tw-scoped-shrink` 记了 scoped 收口的 6 类必须保留规则。

---

## 陷阱 3:Preflight × reduce-motion 刷新黑框(渲染层)

详见独立文档:[`刷新黑框-Preflight-border与reduced-motion.md`](./刷新黑框-Preflight-border与reduced-motion.md)

**一句话**:Preflight `border:0 solid` 让所有元素 `border-style:solid` 就位,某元素 `transition:border-color` 在 `prefers-reduced-motion` 下被压成瞬时的过渡中间帧(墨黑 `#18181b`)瞬显成黑框。修复:reduce 段加 `transition-property:none` 掐过渡帧。

---

## 共性教训

1. **v4 是 CSS-first**:配置真源在 `tokens.css @theme`,不要留 v3 的 `tailwind.config.js`(即使是空壳——空壳是坑不是无害)
2. **单一真源**:组件只用 tw 工具类,不旁路写 `var()`/hex;必须写时集中到全局工具类
3. **底层规则 × 项目代码叠加**:v4 自动注入的 Preflight / @theme 生成 / 自动检测是"底层规则",它们和项目代码(transition border-color / scoped var)叠加才产生陷阱。遇怪现象先想"哪条底层规则在起作用",不要从"焦点""重渲染"先入为主
4. **症状像什么不重要,二分法关掉哪类属性才消失才重要**(见陷阱 3 文档 §5 checklist)
