# Lyra 文档索引

三层文档架构,冲突时项目规则优先于基线规则。

## 文档分层

| 层 | 目录 | 职责 |
|----|------|------|
| Base rules | `AGENTS.md` + `AGENTS.base.md` | 跨项目可复用的工程行为基线 |
| Engineering rules | `docs/engineering/` | 可复用的技术约束与实现规范 |
| Project rules | `docs/` (本目录下非 engineering 子目录) | Lyra 项目特定的需求、接口、交付约束 |

## 当前文档

### 需求规格(project)
- [`requirements.md`](./requirements.md) — Lyra 需求基线(O1-O8 全部定案)

### Engineering
- [`engineering/README.md`](./engineering/README.md) — engineering 层导航
- `engineering/governance/` — 治理文档
  - [`AI协作模式规范.md`](./engineering/governance/AI协作模式规范.md) — agent 角色分工、提示词 9 段结构、输出格式强制
  - [`代码审计规则.md`](./engineering/governance/代码审计规则.md) — 审计分级(P0/P1/P2)、强制规则、交付模板

## 新文档写入规则

1. 跨项目可复用的规则 → `docs/engineering/`
2. Lyra 项目特有的决策 → `docs/`(本目录,与 `engineering/` 平级)
3. 新文档必须在上方索引表登记

## 文档独立性

每篇文档应可独立阅读,不依赖其他文档的上下文。引用其他文档时用"见 `X.md §Y`"格式,不复制内容。
