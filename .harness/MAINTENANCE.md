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

---

## 5. 模板仓库维护史（仅本仓库）

> **本仓库是模板源头，不是模板生成出来的项目。** 因此强制必更项不是
> `state/progress.md`（它要保持脚手架原样），而是**本文件的这一节**。
> 机制见 `.githooks/pre-commit.py` 的 `MANDATORY_ON_CODE_TEMPLATE`，
> 由 `.harness/TEMPLATE-REPO` 标记文件触发。

| 日期 | 轮次 | 内容 | 验证 |
|---|---|---|---|
| 2026-09-14 | R1 | 状态层生命周期：体积上限 + 归档 + `state_health.py` | lint 通过 |
| 2026-09-14 | R2 | 一致性检查 `harness_lint.py`（L001-L007） | 0 ERROR |
| 2026-09-14 | R3 | 反模式库 `harness-antipatterns.md`（12 条）+ 工具收尾 | 通过 |
| 2026-09-14 | R4 | **决策演进层**：决策三件套（台账/指针/失效水位）+ L008-L011 + 可插拔架构（11 模块/3 档位）+ 单一真相源 `module_manifest.py` + GLOBAL-LESSONS 57 条 | lint 0E/0W · init 30/30 · 死链 33→0 |
| 2026-09-14 | R5 | **自审修复**（4 处）：①移除臆想路径 `.githooks/hooks.json` ②L004 加模块关闭豁免 ③L010 跳过围栏代码块（`iter_lines_skip_fence`）④`read()` 失败留痕 + `--explain-skip`。新增教训 S14/P23/P24。新增模板仓库模式（`TEMPLATE-REPO` 标记） | 三档位 lint 全 0E · init 19/27/31 · L010 双向对照 3/3 PASS |
| 2026-09-15 | R9 | **证据门禁 `evidence_gate.py`**：把 feature_list 的 `evidence` 从「字符串声明」升级为「可执行契约」（cmd/expect_stdout/artifacts/touches），标 completed 必须跑通内容校验。pre-commit 加检查 4（证据）与检查 5（接线，读 config.integration.entry）。修正 guard 的 log-and-rethrow 规则（包装重抛误报）；修模板自身 9 个 ruff lint 问题 | 红队：垃圾 demo 端到端 3/3 拦住 · 证据门禁双向对照 5/5 · guard 规则对照 4/4 |
| 2026-09-15 | R8 | **测试治理层 `testing`**：`test_runner.py`（默认只跑受改动影响，`--all` 才全量；分层 `--layer`；进度可见）+ `test_audit.py`（实现 arXiv:2606.18168 的 8 类 oracle 信号分类法 + 孤儿测试检测）+ `TEST-STRATEGY.md`（分层模型/汇报模板/测试删除纪律）。`design` 进 standard 档。新增 1 个模块共 15 个 | AP: oracle 分类器逐类对照 **8/8** · 智能选测 3 场景 PASS · 三档位 0E · 模板 lint 0E/0W |
| 2026-09-15 | R7 | **代码规范层 + 设计层**：`quality.py`（ESLint/Prettier/ruff 接线，工具未装=跳过不算失败）+ `design_smell.py`（SM001-SM005 技术债信号）+ `DESIGN-PRINCIPLES.md`（SOLID 判据/模式选择反向清单）+ SPEC「设计决策四问」。新增 2 个模块共 14 个。顺带 ruff format 模板自身 12 个脚本 | lint 0E/0W · init 38/38 · 三档位 0E · 噪音 363→31 |
| 2026-09-15 | R6-doc | 候选清单同步至 **64 条**（28 条可机器检查）；GLOBAL-LESSONS 增至 64 条（UG 29 / TPL 18 / AI 7 / SY 7 / 个人铁律 3） | lint 0E/0W |
| 2026-09-15 | R6 | **升级层 `upgrade`**：`sync_template.py` + `sync_lib.py` 三向合并（base/ours/theirs）；`config.json.template_sync` 记录基线与替换映射；`--check/--apply/--force/--adopt-now`。**顺带修 3 个老 bug**：①`substitute` 用 `startswith(".")` 把 `.harness/` 整个跳过 → 占位符从未替换 ②文本模式写文件把 LF 转成 CRLF ③版本号 5 处漂移 → 统一到 `harness_version.py`。新增教训 S15/S16/P25/P26 | 五向对照全 PASS（已是最新/可更新/保护本地/无基线保守/错误边界）· 三档位 0E · init 33/33 |

### 模板仓库特有的三条纪律

1. **脚手架文件保持未填写**：`state/progress.md`、`memory/lessons.md`、
   `planning/SPEC-TEMPLATE.md` 等随项目生成的文件，在本仓库里**永远不填**。
   需要记录模板自身的历史 → 记在上表。
2. **验证必须覆盖"生成出来的项目"**：本仓库自己 lint 通过 ≠ 生成的骨架能用。
   每次改动都要跑 `new_project.py --preset {minimal,standard,full}` 并在产物里
   各跑一遍 `init.py` / `harness_lint.py`（这是可插拔的真实验收面）。
3. **版本号只改一处**：所有脚本的版本都从 `scripts/harness_version.py` 导入。
   发版三步：①改 `TEMPLATE_VERSION` ②本表加一行 ③`git tag v<版本>` + push。
   跨 MAJOR 时生成的项目会拒绝自动同步（需人工迁移）。

### 升级层使用说明（给已生成的项目）

```bash
python scripts/sync_template.py --check              # 只看差异（默认，不写文件）
python scripts/sync_template.py --apply              # 应用"可安全更新 + 新增"，冲突跳过
python scripts/sync_template.py --apply --force      # 连冲突一起覆盖（丢本地改动）
python scripts/sync_template.py --adopt-now          # 旧项目补基线（不复制文件）
python scripts/sync_template.py --template <路径>     # 手动指定模板仓库
```
判定依据是 **三向合并**（见 `scripts/sync_lib.py` 顶部说明）：
模板改了而项目没动 → 覆盖；项目改过 → 保护；两边都改 → 冲突，人工裁决。
