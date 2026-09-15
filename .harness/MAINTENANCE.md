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
| 2026-09-16 | R23 | **首次走查"用户第一天"路径**（峰宝问"该怎么用这个模板"）：真跑 clone→生成→init 全流程，**发现 5 个第一天就踩的问题** —— ① **pytest 误收集**（`scripts/test_*.py` 被当测试，报 fixture not found）→ 生成 pytest.ini 排除 scripts/；② **`.py` 注释被机械替换**（"模板里是 {{PROJECT_NAME}}" → "模板里是 FreshApp"，语义荒谬）→ `.py` 不参与替换；③ 待填清单混入描述性文本 → 同 ② 修复；④ init 报错信息不明（stdout/stderr 短路 + 不分"未安装"与"失败"）；⑤ `.cm14.tmp` 脏数据泄漏进生成物 | 修后空项目 init **38/38 全绿**（原 1/38 红）|
| 2026-09-15 | R22 | **第十二批自查（阈值校准）**：所有阈值首次用**数据**校准 —— 统计模板自身 16 个脚本的真实分布，目标"只抓最极端 ~10%"。`MAX_LINES` 500→**800**（原值让 8/16 文件含中位数全超限=纯噪音）· `MAX_NESTING` 4→**6**（样本 P90=6）· state `AGENTS.md max_lines` 150→**200**（原值**正好等于模板行数**，零余量）| 效果：模板自身 smell 信号 **27→4 条**（噪音降 85%，剩下的是真极端）· 双向验证 6/6 · 未校准项（MAX_CLASS_METHODS 样本无类）已标注为盲区 |
| 2026-09-15 | R21 | **第十一批自查（非 Python 栈的**行为**验证）**：造 TS/Java 真占位实现实测 → 发现**两个跨语言覆盖缺口** ① `not-implemented` 只认 Python 的 NotImplementedError，TS 的 `throw new Error("not implemented")`、Java 的 `UnsupportedOperationException`、Go 的 `panic(...)` **全部漏过** → 已补跨语言形态；② `design_smell` 只支持 .py/.ts，Java 项目直接 exit=2 且只说"没找到源码文件" → 已改为明确说明"本目录含 .java，当前仅支持 …" | 规则双向 10/10 · TS/Java guard 实抓 6/6 · 回归 lint 0E/0W · ruff 全过 |
| 2026-09-15 | R20 | **第十一批自查（统一清单不变式）**：先证伪了我自己的说法 —— 上轮报告称「owned 与 MODULE_REQUIRED 内容已不一致」是**误判**（两者语义本就不同：owned=模块拥有的全部文件，required=体检红线关键子集），实测 `required ⊆ owned` 全部满足。正确动作不是合并而是**加机器校验**：新增 `module_manifest.self_check()`（5 类不变式）+ lint 规则 **L012 清单自洽** | 端到端 5/5（基线0报/双归属检出/required⊄owned检出/幽灵路径检出/恢复归零）· ruff 全过 · init 42/42 |
| 2026-09-15 | R19 | **第十批自查（档位 × 语言栈 交叉矩阵 3×3）**：9 个组合全部生成成功；**发现系统性问题** —— `new_project.py` 在 minimal/standard 档一跑就 `ModuleNotFoundError: No module named sync_lib`（sync_lib 归 upgrade 模块=仅 full 档，但它是 new_project 的必需依赖，而 new_project 在每个档位都有）→ **模块归属错误**。已把 sync_lib 移到 verification | 修后 9 组合 × 全部脚本 **0 崩溃** |
| 2026-09-15 | R18 | **第九批自查（evidence_gate 残留 + pre-commit 检查 1）**：A 结构防线 5/5（evidence 是数字/数组/缺 cmd/expect_stdout 是字符串/touches 是字符串 全拦）· B 强度锁 2/2 · C 命令异常 2/2 · D feature_list 损坏 → exit 2 · E **发现真问题**：检查 1 的 `hint` 文字说 lessons.md 是"若踩了新坑则更新"（条件性），但代码**无条件**要求它进 staged —— **说明与实现矛盾**，用户按提示以为可以不改、只会觉得门禁莫名。已修 hint 对齐实现 | 提示一致性双向验证 3/3 · 超时机制实测 331s 返回 exit=1（阈值 300s）**正常** |
| 2026-09-15 | R17 | **第八批自查（state_health + sync_template）**：state_health 双向实测通过（551 行 → 报超限；正常 → 不报）；sync_template 六向对照通过（一致/可更新/apply生效/**保护本地改动**/不自动删模板已删文件/错误不静默）。**本批无需修复** | （又踩两次方法论坑：sync_template 属 upgrade 模块，standard 档没有该脚本；基线实为 config.json 里的哈希而非独立文件 —— 两次都是我的测试假设错）|
| 2026-09-15 | R16 | **第七批自查（quality + test_runner）修 3 处**：① `quality.first_tool` 把 `npx @scope/pkg` 的 basename 截成 `pkg` → 探测失败 → **误判"未安装"**；② `tool_available` 在 Windows 下直接 spawn `npx`（实为 `npx.cmd`）→ FileNotFoundError → 同样误判未装（改用 `shutil.which`）；③ **`test_runner` 选测只做一层映射** → "测试→wrapper→base"间接引用漏选 → 降级跑全量（正是最初抱怨的"改一点跑全量"）。已加**反向依赖传递闭包** | 间接引用实测选中 · 直接引用回归正常 · lint 0E/0W · ruff 全过 |
| 2026-09-15 | R15 | **第五+六批自查（L004/L006/init）**：L008-L011 决策演进 11 项、L004/L006 共 7 项 —— **全部通过**（这批实现扎实）。**init 发现真漏报**：`load_config` 在 config.json 不存在时返回 `(None, None)`，被当成"正常默认"→ init 报"全部通过"，但实际 code_root/quality/commands 全缺失，**多道门禁已静默失效**（与 L003 同族：缺配置与配置正常同形）。已加 ①验证层 `config.json 缺失` 显式检查项 | 双向验证 failed 1→2 且无重复 · lint 0E/0W · ruff All checks passed |
| 2026-09-15 | R14 | **harness_lint 逐条自查（峰宝追问"100+ 检查点怎么就这些"）**：修正测试方法（复制模板+差值法，此前没控制基线）后发现 4 个真问题 —— ① **L003 完全不工作**（`\b` 在中文后永不成立，静默失效）② **L002/L007 不跳围栏**（代码块示例被当真内容）③ **L001 误报包基建文件名**（一行列举产生 7 条误报）④ **系统性**：`iter_lines_skip_fence` 只有 L010 用，4 条规则全没接 | 逐条对照 17 项（16 符合预期 + 1 项为设计如此） · 模板 lint 0E/0W |
| 2026-09-15 | R13 | **逐条刁钻自查**（峰宝要求"每个检查点能防住吗"）：第一批证据门禁深度攻击 8 种（**发现真漏洞 E1/E4**：调用但丢弃结果 + 硬编码输出 → 加"返回值必须出现在输出里"防线，修后 8/8）；第二批 guard 11 条规则逐条双向对照 35 样本（**修 3 处**：NotImplemented 合法用法误报、mockup 词边界误报、get_mock_data 漏报 → 35/35）；第三批其他模块 6 项（循环引用/动态 import/自定义断言/分支断言/空期望串 全 PASS） | 对抗套件回归 12/12 · 模板 lint 0E/0W · ruff All checks passed |
| 2026-09-15 | R12 | **能力清单 `CAPABILITIES.md`**：从各脚本**代码里抽取**（非凭记忆）全部门禁与规则，逐项标注「防什么 / 前提 / **验证状态**」，并专设 §11「已知的洞」。关键区分：把「逐条验证过」与「只跑过整体」分开标 —— guard 11 条里仅 2 条经过修正验证、harness_lint 11 条未逐条验证、smell/lint 的阈值均未校准 | lint 0E/0W · init 42/42 |
| 2026-09-15 | R11 | **接线检查真正生效**：实测发现「未集成接线」此前**根本拦不住** —— ① 脚本属 integration-check 模块，standard 档没有 ② 探测不到入口就退出 2，而新项目默认没配 entry → 门禁从不执行。修：新增「入度=0」降级判定（不依赖入口）；`--allow` 白名单；公共排除清单（修 __init__.py 误报）；integration-check 进 standard 档；pre-commit 检查 5 改默认执行 | 实测：真实项目未集成模块被拦 · 误报 5→2 · 入口模式与降级模式均验证 |
| 2026-09-15 | R10 | **证据门禁加运行时验证**：对抗测试发现 `touches` 的静态文本匹配可被「import 但不调用 + 硬编码答案」绕过 → 新增 `_evidence_probe.py`（sys.settrace 记录「文件::函数名」，<module> 不算数）；artifacts 加执行前后指纹比对（防复用旧文件） | 对抗测试 14 种手法：**13 拦 1 放过**（唯一放过是真边界：行为正确但实现硬编码） |
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
