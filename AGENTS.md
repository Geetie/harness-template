# AGENTS.md — {{PROJECT_NAME}} 开发指南

> **本文件是所有 AI 编码代理的项目入口（指令宪法）。开始任何工作前，先读完本文件。**
>
> Harness 工程六层总览与维护规则见 `.harness/README.md`。本文件只留**铁律与指针**，细节一律外推。

---

## 1. 项目概述

**{{PROJECT_NAME}}** — {{PROJECT_ONE_LINER}}

- **目标用户**：{{TARGET_USERS}}
- **核心用户旅程**（产品可用 = 这条路径跑得通）：{{CORE_JOURNEY}}
- **技术栈**：{{TECH_STACK}}
- **代码主目录**：{{CODE_ROOT}}

---

## 2. 启动路径（Orient — 严格按序，禁止通读）

> 目标：**用最少的 token 达到可开工状态**。每一步都只读指定文件。

| # | 读什么 | 为什么 |
|---|--------|--------|
| 1 | 本文件 §4 铁律 + §5 工作流 | 知道红线 |
| 2 | `.harness/ROUTER.md`（L0 路由） | 判定本次任务需要开哪张能力卡 |
| 3 | 按 ROUTER 指示加载 ≤2 张 `capabilities/*.md` | 省 token 的关键，**不要跳过这层直接翻文档** |
| 4 | `.harness/state/progress.md` → `feature_list.json` → `session-handoff.md` | 项目到哪了、上次停在哪 |
| 5 | `.harness/memory/lessons.md` | 坑表，避免重复踩 |
| 6 | 目标模块的 `**/AGENTS.md` | 要改的目录全貌（约 20 行） |
| 7 | 任务对应的 spec（`.harness/planning/` 或 `docs/`） | 验收标准在这里 |
| 8 | `python scripts/init.py` + `git status && git log --oneline -10` | 环境健康 + 基线 |

**开工前自检**（任一缺失 → 回头补读）：
- [ ] 我知道 §4 铁律
- [ ] 我知道当前测试基线和分支
- [ ] 我知道要改哪个模块，读过它的 AGENTS.md
- [ ] 我知道这个任务的验收标准（AC）在哪

---

## 3. 架构总览

```
{{ARCH_TREE}}
```

**层间依赖铁律**：{{DEPENDENCY_RULES}}

---

## 4. 不可违反的约束（铁律）

> 铁律只记 **Agent 会犯错的规则**。格式：编号 + 一句话 + 违反后果。新增铁律时同步更新本表序号。

### 4.1 交付铁律（最高优先级，详见 `.harness/delivery/README.md`）

- **D1 完成的定义**：一个功能完成 = ① 用户在界面上**能真实走到** ② 数据**真的落库** ③ 有测试证明。三者缺一不可。只写了 API 但 UI 点不到 = 未完成。
- **D2 禁止占位实现**：不写 TODO / FIXME / 占位符 / `NotImplementedError` / 空函数体。缺依赖时**显式报错**，不要静默兜底返回默认值。
- **D3 禁止假数据冒充真实源**：不用 mock / fake / 硬编码常量充当真实数据源。
- **D4 错误处理必须具体**：说明预期什么错、为什么、怎么恢复。禁止 `except: pass` 和「log 后原样重抛」。
- **D5 错误路径与边界必测**：每个任务至少 1 条错误路径 + 1 条边界条件，不能只测 happy path。
- **D6 集成是任务的一部分**：新模块交付时必须已接入主流程调用链，不是孤立可用。
- **D7 禁止无证据的完成声明**：交付报告固定四段（改了什么 / 测了什么附输出 / 每条 AC 的证据 / 剩余不确定性）。无法验证的标 **UNKNOWN**，不得记为通过。

### 4.2 项目专属铁律

> 由项目维护者填写。示例（按实际情况增删）：

- **P1 {{RULE_1}}**
- **P2 {{RULE_2}}**

### 4.3 Git 规范

- 提交格式：`<type>(<scope>): <description>`，type: `feat|fix|refactor|docs|test|chore`
- **代码 + harness 文件必须同一个 commit**（`.githooks/pre-commit` 强制）
- 并行会话：只 `git add` 自己的文件；**禁止**对共享分支执行 `reset --hard` / `rebase` / `commit --amend`

---

## 5. 开发工作流

### 5.1 DoD（Definition of Done，逐条打勾才算完成）

```
□ AC-01 走通：<动作> → <可观察结果>
□ AC-02 持久化：关掉 → 重开 → 数据还在（write-read-reload）
□ AC-03 集成：在 UI 上能点到，不是只能靠 curl / 单测调用
□ AC-04 错误路径：<异常输入> → 明确提示，不 500、不静默、不吞异常
□ AC-05 边界：<空/超大/非法> → 明确拒绝，不崩溃
□ AC-06 测试：≥1 条走真实依赖的集成测试（真实 DB / 文件 / 网络），不全是 mock
□ AC-07 无占位：`python scripts/no_placeholder_guard.py {{CODE_ROOT}}` 通过
□ AC-08 类型检查 / lint / 测试全绿，贴出真实输出与退出码
```

模板与填写指南 → `.harness/delivery/DoD-TEMPLATE.md`

### 5.2 计划骨架（新功能开工前）

1. **Phase 0 必须是 Walking Skeleton** —— 用假数据打通一条**最薄但每一层都真实**的端到端路径并跑起来。不是先搭数据层。
2. 任务按**用户旅程纵向切**，不按技术模块横向切。
3. 计划末尾**固定**有 `Phase N: Integration & Hardening`，占 20–30% 工时预算。

模板 → `.harness/planning/SPEC-TEMPLATE.md`

### 5.3 Harness 同步协议（强制）

每次代码 commit 必须同步更新 harness 文件，**同一个 commit**：

| 场景 | 必更 |
|---|---|
| 任何代码变更 | `.harness/state/progress.md`（一行式）、`.harness/memory/lessons.md`（踩坑时） |
| 功能状态变化 | `feature_list.json` |
| 会话结束 | `session-handoff.md` |
| 架构/铁律变化 | 本文件 |
| 基线变化 | `scripts/init.py` |

豁免（纯格式化/纯测试数据）：`HARNESS_SKIP=1 git commit ...`

完整规则 → `.harness/MAINTENANCE.md`

---

## 6. 验证

```bash
python scripts/init.py                                   # 环境健康检查 + 基线
{{TEST_COMMAND}}                                         # 测试
python scripts/no_placeholder_guard.py {{CODE_ROOT}}     # 反占位符
python scripts/check_integration.py {{CODE_ROOT}}        # 集成检查
```

提交前三项全绿；完整规范 → `.harness/VERIFICATION.md`

---

## 7. 文档导航

| 位置 | 内容 | 何时读 |
|---|---|---|
| `.harness/README.md` | 六层总览 + 维护规则 | 每次开发前 |
| `.harness/ROUTER.md` | L0 能力路由 | 每次任务开始（判定开哪张卡） |
| `.harness/delivery/` | 交付铁律 · DoD · 收尾清单 · 审计 | 交付前 / 被质疑"是不是 demo"时 |
| `.harness/planning/` | 宪法 + spec/plan/tasks 模板 | 新功能开工前 |
| `.harness/memory/lessons.md` | 坑表 | 开发前 |
| `.harness/memory/failure-modes.md` | 交付失败模式库 | 交付前自查 |
| `.harness/skills/` | 固定流程手册 | 触发式 |
| `docs/README.md` | 设计文档索引 | 找设计文档时 |

---

## 8. 常见陷阱

完整坑表 → `.harness/memory/lessons.md`（踩坑后**必须**回写，hook 强制）。

**交付类失败模式**（专治"看着完成其实没完成"）→ `.harness/memory/failure-modes.md`：
幽灵订阅（注册了从不触发）· 空执行（触发了没产出）· 伪造输出（写了没算）· 单调化（输出收敛成一条线）
