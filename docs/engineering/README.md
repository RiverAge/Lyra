# Engineering Rules

可复用的技术约束与实现规范。跨项目通用,Lyra 在此落地。

## 分类目录

### governance/ — 治理
- [`AI协作模式规范.md`](./governance/AI协作模式规范.md) — 架构师/执行者角色分工、工作流、提示词 9 段结构、输出格式 5 段、自检表、§6 多 agent 并行(worktree+rebase)
- [`代码审计规则.md`](./governance/代码审计规则.md) — 审计入口、强制规则、P0/P1/P2 分级、交付模板

### frontend/ — 前端
- [`设计系统.md`](./frontend/设计系统.md) — 设计 token(色彩/字号/间距/圆角/阴影)、单一浅色主题(墨黑强调色)、标准动画+性能约束、组件视觉规范、Tailwind v4 映射
- [`Tailwind-v4集成陷阱集.md`](./frontend/Tailwind-v4集成陷阱集.md) — 三类 v4 集成陷阱索引:①v3 config 残留 ②theme 双源冲突(bg-bg-*/data-theme) ③Preflight 刷新黑框,每项根因+修复+真源指针
- [`刷新黑框-Preflight-border与reduced-motion.md`](./frontend/刷新黑框-Preflight-border与reduced-motion.md) — F5 刷新瞬时黑框根因(Preflight `border:0 solid` × border-color 过渡 × reduce-motion),定位弯路 + 排查 checklist

## 新文档写入规则

1. 新文档按"领域"而非"文件名"归类(如 `governance/`、`frontend/`、`backend/`)
2. 文件名用中文短语,反映规则内容(如 `AI协作模式规范.md` 而非 `rules.md`)
3. 每篇文档首句声明适用范围(通用 / Python 后端 / Vue3 前端)
