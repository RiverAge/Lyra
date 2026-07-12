# AI 协作模式规范

> 适用范围:通用(agent 协作纪律,与具体技术栈无关)。示例中的 Python/FastAPI 术语可按栈替换。
> 来源:从 camping 项目 `AI协作模式规范.md` 改写,适配 Lyra(Python FastAPI + Vue3,自用单用户)。

---

## 1. 角色分工

| 角色 | 承担方 | 职责 |
|---|---|---|
| 架构师 | 人工 + AI(主对话) | 全局理解、问题诊断、方案讨论、输出提示词、审计结果 |
| 执行者 | Agent(子会话) | 按提示词执行代码修改,不自行决策、不扩大范围 |

边界:架构师不直接写代码或指定行号;执行者不参与方案讨论和优先级决策。

---

## 2. 工作流

```
讨论 → 方案 → 提示词 → agent 执行 → 审计 → 通过 / 退回
  ↑__________________________________________________|
```

5 步:讨论优先级 → 输出一段自包含提示词 → 用户交给 agent 执行 → 架构师审计 → 通过进下一项 / 不通过退回修复。

---

## 3. 提示词撰写原则

好的提示词四属性:**自包含、可执行、可审计、可收口**(约束不扩 scope、不顺手重构、不改变既有行为)。

### 3.1 提示词 9 段结构

```
1. 目标
   - 一句话说明:要解决什么问题,达到什么结果

2. 前置阅读
   - agent 执行前必须读取的文档列表
   - 只列文档,不在提示词里重写文档内容

3. 背景与已确认问题
   - 当前行为是什么
   - 为什么这是错误的
   - 哪些 commit / 文件导致了问题
   - 哪些事实已经确认,哪些不要再重新讨论

4. 你的任务
   - 要达到什么结果
   - 优先级顺序(先做什么,后做什么)
   - 每一项的完成标准

5. 关键约束
   - 最小闭环、不改变行为、不扩 scope
   - 不要顺手重构、不要添加未要求功能
   - 哪些边界绝对不能碰
   - 哪些少量连带修改是允许的

6. 关键场景
   - 正向场景:什么必须成功
   - 负向场景:什么必须失败 / 不能被放开
   - 回归场景:什么旧行为必须保持

7. 实施提示(可选)
   - 可列关键文件、关键模块、关键脚本
   - 可列建议检查入口
   - 允许给"关键上下文",但不要把实现步骤写成执行手册

8. 验证要求
   - 必须运行的命令(Python 侧:`ruff check`、`mypy`、`pytest`;前端侧:`pnpm run lint`、`pnpm run typecheck`)
   - 关键断言:什么行为必须恢复、什么行为不能破坏
   - 如果有 guard/lint/CI,也要要求执行

9. 输出要求
   - 修复了什么
   - 为什么这能恢复正确行为
   - 跑了哪些验证
   - 还有没有剩余风险
```

### 3.2 不能做(禁止项)

- 把实现步骤写成逐行执行手册
- 指定具体代码片段让 agent 照抄
- 在提示词里重述文档内容(让 agent 自己去读)
- 将多个不相关的改动塞进同一个提示词
- 让 agent 参与架构决策
- 用模糊表达替代验收标准,例如「优化一下」「顺手整理」「看着改」

补充:可以列关键文件路径(已确认有问题的文件、高风险入口、优先检查模块);不要指定行号、补丁内容、伪代码(除非机械替换);可以给实现边界,不要给实现剧本。

### 3.3 目标驱动 vs 指令驱动

| 指令驱动(旧) | 目标驱动(新) |
|---|---|
| 「修改 `routes.py`,在 `get_song` 上加 `Depends(require_ownership)`」 | 「这 3 个端点缺少 ownership 校验,恢复越权访问的旧行为」 |
| 在提示词里列出所有权限规则 | agent 自己从现有依赖项推导 |
| 「不要改 X、不要动 Y」 | 「最小闭环修复,不扩 scope,不改变原有行为」 |
| 提示词 = 执行手册 | 提示词 = 问题 + 约束 |

目标驱动不等于不给上下文(复杂任务应给关键文件/提交/风险点/验证场景);不指定方案不等于不设边界(可要求优先低风险高收益项、不大重构、不改现有行为);高质量提示词 = 问题定义 + 风险边界 + 验证标准 + 非目标。

### 3.4 Agent 输出格式(强制)

```
1. 修复了什么
   - 高层说明做了哪些改动
   - 必要时列关键文件(不是机械 changelog)

2. 为什么这能恢复正确行为
   - 说明方案与问题之间的因果关系

3. 验证结果
   - 运行的检查(ruff / mypy / pytest / pnpm lint / pnpm typecheck)
   - 不能只写"通过",要说明实际执行了什么

4. 剩余风险
   - 还有没有未覆盖的端点、未验证的场景、需要人工确认的点

5. 疑点与决策
   - 执行过程中遇到的模糊点及处理方式
```

反例(不合格):「测试通过。修改完成。」
正例(合格):「修复了 ownership 校验缺失。在 `meta/credits.py` 和 `meta/apple.py` 补充了 `Depends(verify_song_ownership)`,依赖项复用现有 `verify_song_ownership`。运行了 `ruff check && mypy && pytest tests/meta/`。剩余风险:`play/stream.py` 的 Range 端点未覆盖,需后续补。」

### 3.5 架构师自检表(6 项)

1. 问题是否已经收敛为一个明确任务(还在讨论方案就不要下发执行提示词)
2. 提示词是否给出了足够上下文(复杂任务是否列关键文件、关键提交、关键风险点)
3. 是否写清了非目标(agent 是否会因提示词模糊而顺手扩大范围)
4. 是否写清了验证标准(执行完成后能否客观判断「做完了」)
5. 是否区分了「必须达成」和「建议优先」(避免 agent 把建议项当硬要求,或把硬要求当可选项)
6. 提示词是否足够可执行(agent 读完后能否直接开工,而不是反问「从哪开始」「看哪些文件」「跑哪些验证」)

### 3.6 何时适合给更多上下文

应主动给关键文件/提交/测试入口的场景:
- 跨切面重构(FastAPI 中间件、依赖项、装饰器替换)
- 资源 ownership 校验变更
- 历史回归修复
- 需要保持原有行为不变的结构重构
- 需要补 guard / lint / 测试的治理类任务

可保持提示词简短的场景:单文件修复、机械替换、明确无争议的小范围测试补充。

---

## 4. 审计流程

1. **读代码**:逐文件审查变更,确认与提示词一致(见 `代码审计规则.md` §3.9 审计方法约束)
2. **跑验证**:执行 `ruff check`、`mypy`、受影响模块的 `pytest`,前端 `pnpm run lint && pnpm run typecheck`
3. **判通过**:确认无偏离、无副作用、测试口径一致
4. **记录结论**:结构化输出审计结果(见 `代码审计规则.md` §5 审计分级 + §6 交付模板)

---

## 5. 何时进入此模式

激活场景:
- 涉及 3 个以上文件的批量重构
- 跨切面机制替换(中间件、依赖项、统一封装)
- 资源 ownership / 认证策略调整
- 消除反模式、向 engineering 原则收敛的改动
- 用户明确要求

单文件小修小补或纯咨询不适用。

### 5.1 激活确认块(强制)

进入此模式时必须输出:

```
已进入 AI 协作模式。

审计将使用:
- docs/engineering/governance/代码审计规则.md(§3.9 审计方法约束 + §5 审计分级)

提示词将遵循:
- docs/engineering/governance/AI协作模式规范.md §3(目标驱动,不指定实现方案)

Agent 输出要求:
- 修复了什么 + 为什么能恢复行为 + 验证结果 + 剩余风险(§3.4)

当前阶段:<讨论 / 出提示词 / 审计>
```

当前阶段根据实际工作流位置填写。

---

## 6. 多 agent 并行模式

§1-§5 是默认的串行模式(架构师 → 单执行者 agent → 审计)。§6 是可选增强:当有多个无依赖任务时,用 git worktree 隔离工作目录,多 agent 并行执行,rebase + ff merge 合回主分支。

### 6.1 适用场景

适合并行:
- 多个无依赖任务可同时下发(如:前端组件 A + 前端组件 B + 后端接口 C)
- 长任务并行(一个 agent 跑扫描实现,另一个 agent 跑歌词编辑器骨架)

不适合并行:
- 有文件依赖的任务(B 要改 A 刚写的文件)
- 需要看前一个任务结果才能继续的任务
- 单文件小修(串行更简单,开 worktree 的成本不划算)

### 6.2 任务拆分约束(架构师职责)

架构师拆分并行任务时必须保证:

- **文件级零重叠**:列出每个任务会改的文件集,任两个任务的文件集取交集必须为空
- 若两任务都要改同一文件 → 合并为单任务串行,或重新拆分边界使文件不重叠
- 每个任务必须自包含:读自己的前置文档,不依赖另一个 agent 的中间产物
- 任务命名:短横线分隔英文小写,如 `scan-debounce` / `lyric-editor-skeleton`
- 文件集包含新增文件时,新增路径也不能与其他任务重叠(含目录前缀)

### 6.3 worktree 创建流程(架构师执行)

```
# 1. 确保 master 干净且最新
cd <Lyra主仓>
git checkout master

# 2. 为任务创建分支 + worktree(仓外目录)
git worktree add ../Lyra-worktrees/<任务名> -b agent/<任务名>

# 3. 进入 worktree,装依赖(worktree 不共享 node_modules)
cd ../Lyra-worktrees/<任务名>
pnpm --dir frontend install --frozen-lockfile
```

约定:
- worktree 物理路径固定:`<Lyra主仓父目录>/Lyra-worktrees/<任务名>`(即 `C:\Users\Mercury\Desktop\src\media\Lyra-worktrees\<任务名>`)
- 分支名 `agent/<任务名>`,worktree 目录名同 `<任务名>`
- `pnpm install` 是必须步骤:worktree 是独立工作树,node_modules 不共享(见 §6.5)
- `--frozen-lockfile` 加速:lockfile 已在主仓固化,worktree 复用

### 6.4 agent 执行约束(在 worktree 内)

- agent 在 worktree 目录内工作,所有 commit 落在 `agent/<任务名>` 分支
- agent 只改本任务文件集内的文件,不碰其他文件(架构师已在 §6.2 保证零重叠)
- agent 完成后跑验证(Python 侧 `ruff`/`mypy`/`pytest`;前端侧 `pnpm run lint`/`pnpm run typecheck`),全过后通知架构师
- **agent 不做 rebase,不 merge,不自解冲突**——这些是架构师职责(见 §6.6)

### 6.5 worktree 下的 hooks/依赖工程现实(重要)

worktree 是独立物理目录,有两个工程问题必须知晓:

1. **husky hooks 不触发**:`core.hooksPath=.husky/` 是相对路径,git 在 worktree 根找 `.husky/`,但 `.husky/` 只在主仓根。worktree 里 commit 时 pre-commit/pre-push **不会触发**。
   - 这是预期行为:worktree 内的 commit 是 agent 中间产物,质量门禁在 merge 回 master 时由架构师在主仓重跑(见 §6.6 步骤 5)
   - 等价于:worktree 内 commit 无门禁,master 合并前架构师手动跑完整质量门禁做审计

2. **node_modules 不共享**:worktree 是独立工作树,没有 node_modules。必须在 §6.3 步骤 3 跑 `pnpm --dir frontend install`
   - 不装依赖则 `lint`/`typecheck`/`build` 全跑不起来

### 6.6 合并流程(架构师执行,rebase + ff merge)

```
# 1. 确认 agent 已完成,进入主仓
cd <Lyra主仓>
git checkout master

# 2. rebase agent 分支到 master 最新
git rebase master agent/<任务名>

# 3a. 若 rebase 无冲突 → 切回 master,ff merge
git checkout master
git merge --ff-only agent/<任务名>

# 3b. 若 rebase 冲突 → 架构师仲裁(见下方"冲突处理")

# 4. 清理 worktree + 分支(合并成功后立即执行)
git worktree remove ../Lyra-worktrees/<任务名>
git branch -d agent/<任务名>

# 5. 在主仓跑完整质量门禁(merge 后的 master)
pnpm --dir frontend run lint
pnpm --dir frontend run typecheck
```

冲突处理(架构师仲裁,agent 不自解):
- **轻冲突**(注释/格式/import 顺序):架构师手动 `git rebase --continue` 解,继续 merge
- **重冲突**(逻辑互斥/同函数不同改法):`git rebase --abort`,退回让 agent 在新 worktree 基于最新 master 重做
- 原则:agent 不碰冲突文件——避免 agent 静默覆盖另一个 agent 的改动

### 6.7 多 worktree 状态查询

```
git worktree list        # 查看所有 worktree + 当前 HEAD
git worktree prune       # 清理已删目录但元数据残留的 worktree
```

- 任何时刻 `git worktree list` 的输出 = 正在进行的并行任务清单
- 废弃 worktree(目录已删但未 remove)一眼可见,prune 可清

### 6.8 与串行模式的关系

- §1-§5 的串行工作流是默认模式,适用于绝大多数任务
- §6 多 agent 并行是可选增强:仅当有多个无依赖任务且开 worktree 的成本划算时启用
- 并行模式下,每个 agent 仍遵循 §3.4 输出格式 + §4 审计流程
- 并行模式的审计点:**rebase 成功后** + **ff merge 前**——架构师在主仓审计 agent 分支 rebase 后的最终 diff(`git diff master...agent/<任务名>`)
- 多个 agent 串行合入:若 A、B 两个 agent 同时完成,先合 A(rebase A → ff merge → 清理),再合 B(rebase B → 此时 B 基于 A 合入前的 master,rebase 会把 A 的改动叠上 → ff merge → 清理)
