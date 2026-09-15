# 模块清单（MODULES）

> **解决的问题**：模板此前是**焊死的六层** —— 小项目被迫背全套餐。
> 本文件定义：**每个模块可独立启停，缺失时显式降级、不报错。**
>
> **单一真相源**：`scripts/module_manifest.py` 的 `MODULES` 常量。
> 生成侧（`new_project.py`）、体检侧（`init.py`）、检查侧（`harness_lint.py`）
> **全部 import 它** —— 三份各写一份必然漂移。
>
> **开关表**：`.harness/config.json` 的 `modules` 字段 · **校验**：`scripts/init.py`

---

## 0. 设计原则（三条铁律）

| 铁律 | 含义 | 为什么 |
|---|---|---|
| **① 关掉的模块不留残骸** | 由 `new_project.py` 按 `enabled` **生成**，不是生成后删除 | 生成后删除会漏（人-Agent 都会漏），且残留文件会误导接手者 |
| **② 依赖缺失必须显式降级** | `requires` 未满足时，脚本打印 `[SKIP] xxx 模块未启用，跳过 yyy`，**不静默、不报错** | 静默跳过 = 以为检查了其实没检查（违背 `GLOBAL-LESSONS.md` M0） |
| **③ 降级不阻塞** | 任何模块关掉，其余功能照常，只是少了那道保险 | 可插拔的代价必须是"少一层保险"，不是"跑不起来" |

> **补充铁律 ④（v1.1.0 新增，来自实测事故）**：
> **检查规则本身必须认识"模块已关闭"这个状态。**
> 关掉 delivery 后，`MAINTENANCE.md` 里对 `acceptance.md` 的引用**必然**变成死链 ——
> 靠"删除文档里的引用"消死链是治标（文档还要说明这个模块存在）。
> 正确做法：`harness_lint.py` 读同一份模块表，跳过属于已关闭模块的引用。
> 实测：这一条把最小档位的 L001 噪音从 33 条降到 0 条。

---

## 1. 模块清单

| 模块 | ID | 依赖 | 提供什么 | 关掉的代价 |
|---|---|---|---|---|
| **指令层** | `instructions` | — | `AGENTS.md` / `CLAUDE.md` / 分层 AGENTS 规范 | **无** —— 这是地基，不可关 |
| **状态层** | `state` | `instructions` | `progress.md` / `feature_list.json` / `session-handoff.md` / `STATE-PROTOCOL.md` | 跨会话失忆；无进度追踪 |
| **验证层** | `verification` | — | `init.py` / `harness_lint.py` / `state_health.py` / git hooks | **失去全部自动检查** |
| **记忆层** | `memory` | `instructions` | `lessons.md` / `GLOBAL-LESSONS.md` / `failure-modes.md` / 反模式库 / 晋升协议 | 重复踩坑 |
| **交付层** | `delivery` | `verification` | DoD 模板 / 验收清单 / 收尾清单 / 审计 prompt | **回到"交付塌方"状态** —— 模块没集成、占位符没人管 |
| **路由层** | `routing` | — | `.harness/routing/ROUTER.md` + 能力卡（三级加载） | 无法按需加载，全量读文档 |
| **技能层** | `skills` | `instructions` | `.harness/skills/*/SKILL.md`（Orientation / 交付门禁 / 收敛审计 / 提交同步） | Agent 缺少固定动作手册，每轮重新摸索 |
| **决策层** | `decisions` | — | `DECISION-PROTOCOL.md` / `DECISIONS.md` / ADR / 失效水位（L008-L011） | 决策变更后文档静默过时 |
| **规划层** | `planning` | — | `CONSTITUTION.md` / `SPEC-TEMPLATE.md` | 需求/设计/任务无结构 |
| **反占位门禁** | `placeholder-guard` | `verification` | `no_placeholder_guard.py` | TODO/桩实现混入提交 |
| **接线体检** | `integration-check` | `verification` | `check_integration.py`（孤儿模块检测） | 写完的模块没接上 |
| **升级层** | `upgrade` | `verification` | `sync_template.py` + `sync_lib.py`（三向合并拉模板更新） | 项目与模板脱钩，模板改进永远拿不到 |
| **代码规范层** | `code-quality` | `verification` | `quality.py`（ESLint/Prettier/ruff 接线）+ `CODE-QUALITY.md` | 风格问题不再被拦，只能靠 review 兜 |
| **设计层** | `design` | — | `design_smell.py`（技术债信号）+ `DESIGN-PRINCIPLES.md`（SOLID 判据/模式选择） | 缺"写代码前的设计判断"，债靠事后还 |
| **测试治理层** | `testing` | `verification` | `test_runner.py`（智能选测/分层/进度）+ `test_audit.py`（oracle 有效性审计）+ `TEST-STRATEGY.md` | 每次跑全量、有效性不明、假绿测试不删 |

**元文档（不属任何模块，始终保留）**：
`README.md` · `.harness/README.md` · `.harness/MAINTENANCE.md` · `.harness/MODULES.md`

---

## 2. 配置方式

`.harness/config.json`：

```json
{
  "project": "我的项目",
  "stack": "next-ts",
  "preset": "standard",

  "modules": {
    "instructions":     true,
    "state":            true,
    "verification":     true,
    "memory":           true,
    "delivery":         true,
    "routing":          false,
    "skills":           true,
    "decisions":        true,
    "planning":         true,
    "placeholder-guard": true,
    "integration-check": false
  },

  "code_root": "src",
  "commands": { "typecheck": "...", "lint": "...", "test": "..." },
  "baseline": { "test": "0 failed" }
}
```

> **未出现的模块视为 `true`**（向后兼容：老项目的 config.json 没有 `modules` 字段时，一切照常）。

---

## 3. 三个预置档位

| 档位 | 开启模块 | 用途 |
|---|---|---|
| **minimal** | `instructions` / `state` / `verification` / `memory` | 小工具、脚本、实验 |
| **standard** | minimal + `delivery` / `planning` / `placeholder-guard` / `skills` / `code-quality` / `design` / `testing` | 常规项目 |
| **full** | standard + `routing` / `decisions` / `integration-check` / `upgrade` / `design` | 长期演进、多模块、多 Agent 协作 |

用 `new_project.py --preset full` 选择；也可在 config.json 里逐个覆盖。

> 档位定义在 `module_manifest.PRESETS`，与上表一一对应。
> 依赖会被**自动补齐**，但补齐时打印告警（铁律 ②）。
>
> `upgrade` 只在 full 档：小项目通常生命周期短，不需要"拉模板更新"这套机制；
> 且它会往 config.json 写入同步基线，给项目增加一点状态。

---

## 4. 降级行为表（关掉后会发生什么）

| 模块关掉 | `init.py` 行为 | `harness_lint.py` 行为 | `new_project.py` 行为 |
|---|---|---|---|
| `state` | 跳过状态文件检查（打印 `[SKIP]`） | 跳过 L003（基线漂移） | 不复制 `state/` 与 `STATE-PROTOCOL.md` |
| `memory` | 跳过 `lessons.md` 存在性 | — | 不复制 memory 层文档 |
| `decisions` | 跳过决策层文件检查 | **跳过 L008-L011**（打印 `[SKIP]`） | 不复制协议/台账/ADR |
| `routing` | 跳过 ROUTER 检查 | 跳过 L004（注册表失配） | 不复制 `routing/` |
| `delivery` | 跳过交付层文件检查 | — | 不复制 `delivery/` |
| `skills` | 跳过技能卡检查 | — | 不复制 `skills/` |
| `placeholder-guard` | — | — | 不复制门禁脚本 |
| `integration-check` | — | — | 不复制体检脚本 |

> **所有跳过都必须打印原因**（铁律 ②）。静默跳过是最危险的形态 —— 你以为检查过了。

---

## 5. 实现位置

| 位置 | 职责 |
|---|---|
| **`scripts/module_manifest.py`** | **单一真相源**：`MODULES`（拥有文件 / 依赖 / 层名）、`PRESETS`、`ALWAYS_FILES`、`EXCLUDE_FILES`、`norm_rel()` |
| `.harness/config.json` | 每个项目自己的 `modules` 开关 |
| `scripts/init.py` | 读开关 → 生成必需文件清单（按路径去重）→ 打印 `[SKIP]` 原因 |
| `scripts/harness_lint.py` | ① 决策组规则按 `decisions` 开关守卫 ② **L001 豁免已关闭模块的引用**（铁律 ④） |
| `scripts/new_project.py` | 按 `--preset` / `--disable` 过滤文件；清理存活文档中指向已关闭模块的引用行 |
| `.githooks/pre-commit.py` | 按 `modules` 决定强制项 |

---

## 6. 反模式

| 反模式 | 为什么错 |
|---|---|
| **AP-M1 关掉模块但留着文件** | 接手者会以为那些检查还在跑（**残留比缺失更危险**） |
| **AP-M2 静默跳过** | 以为检查了其实没检查 —— 与 `GLOBAL-LESSONS.md` M0 同源 |
| **AP-M3 关掉 `verification`** | 等于放弃全部自动护栏，**不建议任何项目这么做** |
| **AP-M4 让模块之间循环依赖** | `requires` 必须是有向无环的 |
| **AP-M5 各处各写一份模块表** | 三份必然漂移：生成侧漏路径 → 关不干净；检查侧漏路径 → 几十条噪音（v1.1.0 实测事故） |
| **AP-M6 用 `lstrip("./")` 规范化路径** | `lstrip` 的参数是**字符集**不是前缀，会吃掉 `.harness` 的前导点，导致所有点目录匹配失效 |
