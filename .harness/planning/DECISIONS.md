# 决策台账（DECISIONS）

> ★ **这是本项目决策状态的唯一权威源。**
> 判断"某条决策现在什么状态"，**只查本表**；需要"为什么这么定"时才展开读 `decisions/ADR-NNN-*.md`。
> **协议**：`.harness/DECISION-PROTOCOL.md` · **机器校验**：`harness_lint.py` 的 L008/L009/L010/L011

---

## 1. 状态表（每新增/变更决策必须更新本表）

| 编号 | 标题 | 状态 | 日期 | 取代关系 | 落地证据 | 文件 |
|---|---|---|---|---|---|---|
| ADR-000 | 采用"决策台账+状态机+失效水位"管理决策演进 | `accepted` | 2026-09-14 | — | `.harness/DECISION-PROTOCOL.md` | `decisions/ADR-000-decision-ledger.md` |

**状态取值**（五态之一，详见协议 §2）：
`proposed` \| `accepted` \| `partial` \| `superseded` \| `rejected` \| `deprecated`

**取代关系写法**：
- 本决策取代了旧的 → `supersedes ADR-010`
- 本决策被新的取代 → `superseded by ADR-015`

---

## 2. 欠账清单（`partial` 决策集中于此）

> **为什么要单列**：`partial`（已决未落地）是最危险的状态 —— 看起来已经定了，实际没做，新 Agent 会以为已生效。
> **本表由 `harness_lint.py` 的 L011 校验**：状态为 `partial` 但 gap 为空 → 报 ERROR。

| 编号 | 还差什么（gap） | 为何没做（blocked_by） | 预期时机 |
|---|---|---|---|
| — | *（暂无欠账）* | — | — |

**还清后**：把该决策在 §1 的状态改为 `accepted`，填上落地证据，并从本表删除。

---

## 3. 失效决策集合（供 L010 引用检测）

> 此表由脚本自动核对，**不需要手工维护**——脚本从 §1 中筛出 `superseded` / `deprecated` 的编号。
> 用途：任何文档若 `depends-on` 了这里的编号，会被标 STALE（L010）。

| 编号 | 失效原因 | 取代者 | 失效日期 |
|---|---|---|---|
| — | *（暂无失效决策）* | — | — |

---

## 4. 维护规则

| 时机 | 动作 |
|---|---|
| 新做架构决策 | 新建 `decisions/ADR-NNN-*.md` → 本表 §1 加一行 |
| 决策被推翻 | 新 ADR 写 `supersedes` → 旧 ADR 改 `superseded` + `superseded_by` → 本表两侧都更新 |
| 决定但没做完 | 状态标 `partial` → **§2 欠账清单必须写 gap 与 blocked_by** |
| 欠账还清 | 状态改 `accepted` + 补落地证据 → 从 §2 删除 |
| 提交前 | 跑 `python scripts/harness_lint.py --only L008,L009,L010,L011` 确认无断裂 |

> ⚠️ **pre-commit 强制**：若本次提交改动了代码或架构文档，但 `DECISIONS.md` 未更新 → 按项目配置可能被拦截。
