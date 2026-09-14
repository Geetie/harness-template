# Harness 维护规范

> **一句话**：把 harness 当代码管理。每个文件都有明确的**角色 / 触发更新的事件 / 格式约束 / 强制机制**。
> 本文件是「哪个文件该在什么时候改」的唯一权威。任何不确定 → 查本文件，不要猜。

---

## 0. 三条不可协商的硬规则

1. **代码 + harness 同一个 commit** —— `.githooks/pre-commit` 强制。代码改了但 harness 没动 = 提交被拦。
2. **踩坑必回写坑表** —— `.harness/memory/lessons.md` 是 hook 强制必更项（与 progress 同级）。
3. **状态落盘不进 context** —— 任何跨会话需要记住的东西，写进 `state/`，不许只留在对话里。
4. **状态文件有体积上限** —— `AGENTS.md` ≤150 行、`progress.md` ≤32 KB、`feature_list.json` ≤64 KB。
   超限执行 `python scripts/state_health.py --archive` 归档。
   > 只增不减的状态文件最终会变成 Agent 读不完的档案——**那是发生在磁盘上的 context rot**。

豁免（纯格式化 / 纯测试数据等不涉及功能逻辑的变更）：`HARNESS_SKIP=1 git commit ...`

---

## 1. 维护总表（按文件）

### ① 指令层

| 文件 | 角色 | 何时更新 | 格式约束 | 强制 |
|---|---|---|---|---|
| `AGENTS.md`（根） | 宪法：项目概述 / 铁律 / 工作流 / 导航 | 架构变化、新增铁律、基线变化、导航失效 | 只留**铁律与指针**；细节外推到本目录；**总长控制在 150 行内** | — |
| `**/AGENTS.md`（模块） | 该目录职责 / 关键文件 / 约束 / 测试 | 新增或修改该目录代码 | **~20 行**，四段式，见 `instructions/AGENTS-guidelines.md` | — |
| `instructions/AGENTS-guidelines.md` | 模块 AGENTS.md 的书写规范 | 规范本身演进 | — | — |

**AGENTS.md 的瘦身纪律**（违者等于让所有规则一起失效）：
前沿模型可靠跟随的指令上限约 **150–200 条**，而 Agent 工具自身的系统提示已占约 50 条。
→ 规则越多，遵循率**整体**下降（不是只忽略后面的）。**新增规则前先删一条旧规则。**

### ② 状态层

| 文件 | 角色 | 何时更新 | 格式约束 | 强制 |
|---|---|---|---|---|
| `state/progress.md` | 项目状态 + 一行式变更日志 | **任何代码变更的 commit** | §10 变更日志**一行式**：`| 日期 | 做了什么 + 验证结果 + commit |`；**禁止长段落** | hook **强制必更** |
| `state/feature_list.json` | 功能粒度实现状态 | 功能实现 / 降级 / 阻塞 / 废弃 | 用工具写，写后必须能 JSON.parse；**只翻转状态，禁止删条目** | hook 通用检查 |
| `state/session-handoff.md` | 会话交接（3-5 条摘要 + 下一步） | 每次会话结束 | 短；写"上次停在哪 / 下次优先做什么" | 约定（每次会话结束必更） |

**三文件分工铁律**：内容**不重复**。
- 一条变更 → progress 记一行索引，handoff 记摘要，feature_list 翻状态，各司其职。
- progress = 状态与历史索引；handoff = 会话细节；feature_list = 功能状态。

**feature_list.json 抗损坏规则**（并发写曾导致重复 id 与裸换行 JSON 损坏）：
1. 用工具/脚本写入，**禁止手拼 JSON**；写后必须能通过 JSON.parse
2. 并行会话只改自己的条目；改前 `git status` 确认该文件没被并行会话暂存
3. 提交前 `git diff --cached state/feature_list.json` 确认仍是合法 JSON
4. 状态档位：`missing → partial → completed`，废弃用 `deprecated` 并在 notes 标注原因

### ③ 验证层

| 文件 | 角色 | 何时更新 | 强制 |
|---|---|---|---|
| `scripts/init.py` | 环境健康检查 + 测试基线 | 基线变化、新增依赖、命令变化 | 与 AGENTS.md §6、VERIFICATION.md **同步校准**（防漂移） |
| `.githooks/pre-commit` | 确定性闸门 | 强制项变化 | — |
| `hooks/hooks.json` | 钩子声明式配置 | 增/删钩子 | — |
| `VERIFICATION.md` | 验证层说明 | 基线变化 | — |

**基线漂移是最常见的隐性 bug**：测试数量变了但三处基线没同步 → 后面所有判断都错。
基线变化时必须同时改：`scripts/init.py` + 根 `AGENTS.md` §6 + `VERIFICATION.md`。

### ④ 记忆层

| 文件 | 角色 | 何时更新 | 强制 |
|---|---|---|---|
| `memory/lessons.md` | 通用坑表（踩过的坑 + 黄金原则） | **踩了新坑的那一刻** | hook **强制必更** |
| `memory/failure-modes.md` | 交付失败模式库 | 发现新的"看着完成其实没完成"模式 | 交付前必读 |

**坑表写法**：`现象 → 根因 → 正确做法`。只记**会重复犯**的坑，一次性环境问题不记。

### ⑤ 技能层

| 文件 | 角色 | 何时更新 |
|---|---|---|
| `routing/ROUTER.md` | L0 常驻路由（~1K token） | 新增/删除能力卡时同步注册表 |
| `routing/capabilities/*.md` | L1 能力卡（2-5K token/张） | 该领域知识演进 |
| `skills/*/SKILL.md` | 固定流程手册 | 流程变化 |

**新增能力卡/技能后必须在 ROUTER.md 注册表加一行**，否则 Agent 找不到它（等于不存在）。

### ⑥ 交付层

| 文件 | 角色 | 何时更新 | 强制 |
|---|---|---|---|
| `delivery/README.md` | 交付铁律总纲 | 铁律演进 | — |
| `delivery/DoD-TEMPLATE.md` | Task 级验收模板 | 模板改进 | 每个任务开工前套用 |
| `delivery/acceptance.md` | 项目级 Definition of Done | 项目标准变化 | 所有任务共用 |
| `delivery/hardening-checklist.md` | Phase N 收尾清单 | 清单改进 | **交付前必须走完** |
| `delivery/audit-prompt.md` | 独立 verifier 审计 prompt | — | 交付前跑一次 |

---

## 2. 场景 → 改哪些文件（速查）

| 场景 | 必改 | 按需 |
|---|---|---|
| 实现了一个功能 | `state/progress.md` 一行、`state/feature_list.json` 状态、`session-handoff.md` | 模块 `AGENTS.md` |
| 踩了新坑 | `memory/lessons.md` | `state/progress.md` |
| 基线变了（测试数/命令） | `scripts/init.py`、根 `AGENTS.md` §6、`VERIFICATION.md` | `state/progress.md` 头部 |
| 新增模块/目录 | 该目录 `AGENTS.md` | `docs/README.md` 索引 |
| 新增固定流程 | `skills/<name>/SKILL.md` + `ROUTER.md` 注册 | `.harness/README.md` §5 |
| 架构决策 | ADR 到 `docs/adr/`，根 `AGENTS.md` §3/§4 | `docs/README.md` |
| **准备交付** | `delivery/hardening-checklist.md` 全项 + 独立审计 | `memory/failure-modes.md` 自查 |
| 每季度 | 修剪：AGENTS 瘦身、坑表去重、feature_list 核对 | 本文件回顾 |

---

## 3. 季度修剪清单

> **stale rules 比 missing rules 更有害** —— 过期规则会让 Agent 做错事，且你不知道它在遵循过期规则。
> **先跑工具，再靠人眼**：能自动检测的不要人审（人眼审不出漂移）。对照 `.harness/memory/harness-antipatterns.md`（12 条实测反模式）。

```bash
python scripts/state_health.py    # 体积/行数/条目超限、第二套状态（AP-01/02/04）
python scripts/harness_lint.py    # 漂移：死链/绝对路径/基线/注册表/过期/清单（AP-08~12）
```

- [ ] 跑上面两条，处理全部 ERROR
- [ ] 根 `AGENTS.md`：删掉不再适用的铁律；总长是否仍 ≤150 行（AP-04）
- [ ] 对比「元规范行数 vs 宪法行数」——元规范不该比宪法还长（AP-05）
- [ ] 模块 `AGENTS.md`：删除已废弃目录的；核对"关键文件"是否仍存在
- [ ] `memory/lessons.md`：合并重复条目；删掉已不适用的（框架升级后失效的坑）
- [ ] `state/feature_list.json`：核对 `completed` 条目的 evidence 路径是否仍存在
- [ ] `routing/ROUTER.md`：能力卡是否都还有用；注册表与磁盘文件是否一致（L004）
- [ ] `delivery/acceptance.md`：项目级 DoD 是否还符合当前阶段
- [ ] `state/progress.md`：§10 变更日志是否过长（过长则归档）
- [ ] 扫描"已废止规则表"是否还留在宪法里（AP-07）——它该在 memory 或归档
- [ ] 检查空洞件与模糊标注（AP-12）：0 字节文件、"部分有效"这类状态词

---

## 4. 新增文件的三条规则

1. **新治理文档一律进 `.harness/`**，不在根目录或 `docs/` 其他位置新增散件（否则归口失效）
2. **新建即注册**：在相应索引（本文件、`ROUTER.md`、`.harness/README.md` §5）加一行
3. **能写成 skill 的流程不要写成规则**：流程 → `skills/`；只有"红线"才进 `AGENTS.md`
