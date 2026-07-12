# Quality Gate

统一的本地门禁入口，按快慢分层：

## 1. pre-commit（快门）

- `node scripts/quality-gate/pre-commit.mjs`
- 执行：增量 bypass 注释检查（`check-disable`）、前端 `style-guard`、`lint-staged`、前端 `typecheck`
- 仅在暂存区触及 `frontend/` 时才跑 style-guard / typecheck

## 2. pre-push（慢门）

- `node scripts/quality-gate/pre-push.mjs`
- 执行：前端全量 `lint` / `typecheck` / `build`

## Frontend Guard

- `scripts/quality-gate/frontend/style-guard.mjs`
- 约束：`frontend/src` 禁止 `!important`、`:deep` / `::v-deep`、以及 Tailwind `!` 重要性修饰符
- 接入：
  - `frontend/package.json` `lint`
  - `scripts/quality-gate/pre-commit.mjs`

## Hook 绑定

- `.husky/pre-commit` -> `pre-commit.mjs`
- `.husky/pre-push` -> `pre-push.mjs`

> 后端 guard（time/id/role）暂缓，Python 栈需重新设计禁则，见 `AGENTS.md`。
