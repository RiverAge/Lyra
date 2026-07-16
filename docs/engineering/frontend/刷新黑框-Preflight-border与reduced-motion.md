# Preflight `border: 0 solid` × reduced-motion 刷新黑框

> 适用范围:Vue3 前端。任何用 Tailwind v4 Preflight + `transition: border-color` + `prefers-reduced-motion` 的项目都可能复现。本文档记录 Lyra 实测的一次定位全过程,供后人遇同类症状时快速收敛,避免重走 focus outline 的弯路。
> 代码真源:`frontend/src/styles/tokens.css` 的 `@media (prefers-reduced-motion: reduce)` 段。

---

## 0. 一句话结论

**刷新瞬时黑框的根因不是浏览器 focus outline,是 Tailwind v4 Preflight 的 `border: 0 solid` 让所有元素 `border-style: solid` 就位后,某元素 `transition: border-color` 在 `prefers-reduced-motion` 下被压成瞬时的过渡中间帧(墨黑)露了出来。修复:reduce 段加 `transition-property: none`,掐掉过渡帧本身。**

---

## 1. 症状

- F5 刷新页面时,视口**上、左、右**三边出现约 2-5px 的**墨黑色边框**
- 持续约 0.3s,之后**自行消失**,页面恢复正常
- 去 Tailwind 全量 `*:focus-visible { outline: none }`、去根元素 `:focus` 兜底**均无效**
- 去 `App.vue` 的 `<Transition mode="out-in">` **无效**
- 去掉 `<script src="/src/main.ts">`(整个 Vue 挂载)→ 黑框消失
- 去掉 `@media (prefers-reduced-motion: reduce)` 段 → 黑框消失
- DevTools 全量 `* { outline:none !important; box-shadow:none !important }` → **黑框仍在**
- DevTools 全量 `* { ... border:none !important }` → **黑框消失**

> 关键判据:**全量关 outline+box-shadow 仍在,全量关 border 才消失** → 框是 `border`(或被渲染成 border-like 的东西),不是 focus 轮廓。前面所有 focus 方向的修复都无效,是因为根因不在 focus。

---

## 2. 根因:三个条件叠加,缺一不可

### 条件 A:Tailwind v4 Preflight 的 `border: 0 solid`

Tailwind v4 Preflight(`@layer base`)注入:

```css
*, ::after, ::before, ::backdrop, ::file-selector-button {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  border: 0 solid;  /* ← 关键 */
}
```

`border: 0 solid` 拆开:
- `border-width: 0`(默认 width 为 0)
- `border-style: solid`(**所有元素 style:solid 就位**)
- `border-color: currentcolor`(简写不写 color 时默认取当前文字色——Lyra 文字色是墨黑 `#18181b`)

设计意图:让 `border` / `border-line` 这类工具类只需写 `border-width` + `color` 就出边框,不用每次补 `border-style`。

**陷阱**:`border-width: 0` 只设"默认值",一旦元素被加了 `border`(= `border-width:1px`)类,width 就非 0;而 `border-style: solid` 已就位 → 边框可被渲染。`0` 不等于"没有 border"。

### 条件 B:某元素 `transition: border-color`

Lyra 里 `.card-hover` / `.input-ring` 等都声明 `transition: ... border-color ...`。这些元素带 `border`(width:1px)类,正常状态下 border-color 是浅灰(`#e8e8ec`),hover/focus 时过渡到墨黑(`#18181b`)或加深色。过渡期间,border-color 会**经历墨黑那一帧**。

### 条件 C:`prefers-reduced-motion` 把 transition 压成瞬时

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
    transition-duration: 0.01ms;  /* ← 只压时长,不关属性 */
  }
}
```

reduce 偏好(用户开了系统级"减少动态"或 Firefox `ui.prefersReducedMotion`)触发此段。`transition-duration: 0.01ms` 把 border-color 过渡**压成近乎瞬时**——但仍是"一帧过渡"。这一帧:

- `border-style: solid` 就位(A)
- `border-width: 1px`(元素带 `border` 类)
- `border-color` 处于过渡中间值(墨黑 `#18181b`)(B)
- 过渡被压成 0.01ms,这一帧瞬显(C)

→ 墨黑 1px 实线边框**瞬显**,视觉上就是"刷新黑框"。挂载稳定、过渡结束后 border-color 回到目标值(浅灰或墨黑但稳定),黑框消失 → 对应"0.3s 后消失"。

### 为什么是"上、左、右"三边

底部那一边通常被 sticky header 下面的内容流 / 滚动条 / 主内容遮住,所以只看到三边——这是**整个根级容器(或大块组件)被描了一道边**的特征,不是某个居中小元素(居中元素会是四边)。

### 为什么去掉 `border: 0 solid` 黑框就消失

去掉后没有 `border-style: solid` 兜底 → 元素 border 默认 `style: none` → **`border-style: none` 时,无论 width 多少、color 是什么,边框都不渲染** → 过渡那一帧的墨黑色画不出来 → 黑框消失。

但这不是正解:删 Preflight 的 `border: 0 solid` 会让所有 `border-*` 工具类失效(border-style 没了)。

---

## 3. 修复

在 `prefers-reduced-motion` 段加 `transition-property: none`:

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
    transition-duration: 0.01ms;
    transition-property: none;  /* ← 掐掉过渡帧本身 */
  }
}
```

**为什么是 `transition-property: none` 而非仅 `transition-duration: 0.01ms`**:`duration: 0.01ms` 只是让过渡"快",但 border-color **仍会经历那一帧**(0.01ms 也是一帧,reduce 下被冻结/瞬显);`transition-property: none` 直接**禁掉所有属性过渡**,border-color 不再有"过渡帧",墨黑中间帧根本不产生 → 黑框根治。

### 不破坏什么

- **不删 Preflight**:`border-*` 工具类照常工作,边框样式正常
- **不破坏无障碍**:reduce 用户本就接受"最低限度动态",关掉过渡是其预期;正常用户(`prefers-reduced-motion: no-preference`)完全不受影响,按钮/输入框/hover 的 border 过渡照常丝滑
- **不影响 focus 可达性**:可交互元素的 `:focus-visible` 走各自 `.input-ring` / `focus-visible`,无障碍不退化

---

## 4. 定位走过的弯路(后人避坑)

| 假设 | 验证 | 结论 |
|---|---|---|
| 浏览器默认 focus outline 落 `<body>` | 去 `*:focus-visible {outline:none}` 无效 | 错 |
| 根元素 focus 轮廓 | `html/body/#app/main:focus{outline:none}` 无效 | 错 |
| `<Transition mode="out-in">` 空窗焦点抖动 | 去 mode 无效 | 错 |
| reduce 段焦点抖动画 focus 轮廓 | reduce 内 `*:focus{outline:none!important}` 无效 | 错 |
| 是 outline / box-shadow | 全量关 outline+box-shadow 仍在 | 错 |
| **是 border** | 全量关 border 才消失 | **对** |

**教训**:CSS 视觉现象的"像 focus 轮廓"和"是 focus 轮廓"之间差一个 DevTools 实证。**症状像什么不重要,二分法关掉哪类属性才消失才重要**。下次遇"瞬时黑框/彩框",直接按 `outline` → `box-shadow` → `border` → Firefox 专有伪元素(`:-moz-focusring` / `::-moz-focus-outer`)的顺序二分,不要从"焦点"先入为主。

---

## 5. 排查 checklist(再遇同类症状)

1. **是不是 reduce-motion 触发?** 关掉系统"减少动态"/改 Firefox `ui.prefersReducedMotion=0`,黑框消失 → 是 reduce 段相关,查 transition/animation
2. **是哪类属性?** DevTools 临时注入:
   - `* { outline:none !important }` → 没了 = outline
   - 追加 `box-shadow:none !important` → 没了 = box-shadow
   - 追加 `border:none !important` → 没了 = border(多半是 Preflight `border:0 solid` + border-color 过渡)
3. **冻结瞬态定位元素**:reduce 段把 `transition-duration` 临时改成 `111110.01ms`,瞬时帧变常驻,DevTools 从容选中看是哪个元素
4. **精准修**:不删 Preflight、不删无障碍段;在 reduce 段 `transition-property: none` 掐过渡帧,或让具体元素不 transition border-color

---

## 6. 环境记录

- 症状复现浏览器:**Firefox**(Chromium 行为不同,Firefox 在 reduce 下对瞬时 transition 的中间帧渲染更易可见)
- 触发偏好:系统级"减少动态"或 Firefox `ui.prefersReducedMotion` = reduce
- 框架:Vue 3 + Tailwind v4 Preflight + `<Transition>`
- 修复 commit:见 git log `tokens.css` 的 `prefers-reduced-motion` 段加 `transition-property: none`
