# Engineering Rules

可复用的技术约束与实现规范。跨项目通用,Lyra 在此落地。

## 分类目录

### governance/ — 治理
- [`AI协作模式规范.md`](./governance/AI协作模式规范.md) — 架构师/执行者角色分工、工作流、提示词 9 段结构、输出格式 5 段、自检表
- [`代码审计规则.md`](./governance/代码审计规则.md) — 审计入口、强制规则、P0/P1/P2 分级、交付模板

## 新文档写入规则

1. 新文档按"领域"而非"文件名"归类(如 `governance/`、`frontend/`、`backend/`)
2. 文件名用中文短语,反映规则内容(如 `AI协作模式规范.md` 而非 `rules.md`)
3. 每篇文档首句声明适用范围(通用 / Python 后端 / Vue3 前端)
