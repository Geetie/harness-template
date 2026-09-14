# Harness 工程总览（六层）

> **本目录 = 项目全部「工程治理 / 经验 / 技能 / 交付」文档的唯一归口。**
> 设计文档（specs / designs / adr）走 `docs/README.md` 索引，与本目录正交。

---

## 1. 六层架构

| 层 | 作用 | 存放位置 | 强制机制 |
|----|------|---------|---------|
| **① 指令层** | 项目怎么运转、铁律、工作流 | 根 `AGENTS.md`（宪法）+ `**/AGENTS.md`（分层，~20 行）+ `instructions/AGENTS-guidelines.md` | — |
| **② 状态层** | 跨会话落盘：进度 / 功能状态 / 交接 | `state/progress.md` · `state/feature_list.json` · `state/session-handoff.md` + `STATE-PROTOCOL.md` | pre-commit **强制必更** |
| **③ 验证层** | 环境健康 + 测试基线 + 提交闸门 | `scripts/init.py` · `.githooks/pre-commit` · `hooks/hooks.json` + `VERIFICATION.md` | pre-commit **强制** |
| **④ 记忆层** | 踩坑沉淀 + 失败模式 + 审计 | `memory/lessons.md` · `memory/failure-modes.md` | 坑表 **强制必更** |
| **⑤ 技能层** | 固定流程外化 + 按需路由 | `skills/*/SKILL.md` · `routing/ROUTER.md` + `routing/capabilities/*.md` | 触发式读取 |
| **⑥ 交付层** | 交付门禁 · DoD · 集成 · 收尾审计 | `delivery/*` + `scripts/no_placeholder_guard.py` · `scripts/check_integration.py` | Phase N **强制** |

**为什么要有第 ⑥ 层**：前五层保证 Agent"按规范写代码"，但**不保证交付物可用**。
AI 辅助开发最常见的失败是——计划跑完了，交出来却是一个充斥占位符、模块互不相连的 demo。
第 ⑥ 层专治这个：把「完成」从 Agent 的主观判断，变成流程里的客观闸门。

---

## 2. 方法论（六条，写进工程结构而非 prompt）

1. **指令文件是宪法不是百科全书** —— 只记 Agent 会犯错的规则；其余用指针外推
2. **State 落盘而非 context** —— 跨会话状态必须写磁盘（JSON 抗损坏），禁止依赖 Agent 记忆
3. **强制金字塔** —— `advisory`（规则）→ `tool`（脚本）→ `deterministic`（hook）；关键标准必须 hook 保证
4. **知识外推 skills** —— 固定流程写成触发式 skill，不内联在 AGENTS.md
5. **渐进式披露** —— 静态（根 AGENTS）→ 半动态（本目录 / 模块 AGENTS）→ 全动态（skills / capabilities）
6. **季度修剪** —— stale rules 比 missing rules 更有害；harness 当代码管理

### 省 token 的两条硬机制

- **ROUTER 三级加载**：L0 `routing/ROUTER.md` 常驻（~1K token）→ L1 `capabilities/<卡>.md` 按需（2-5K/张，**单次 ≤2 张**）→ L2 深度原文（按需，单次 ≤3 篇）
- **模块 AGENTS.md 就近治理**：每个代码子目录一份 ~20 行，只读目标目录那一份，不全量遍历

---

## 3. 文件地图

```
.harness/
├── README.md                # 本文件
├── MAINTENANCE.md           # ★ 维护规范总表（哪个文件何时更新）
├── STATE-PROTOCOL.md        # 状态三件分工与写入规范
├── VERIFICATION.md          # 验证层：init / 基线 / hook 机制
├── instructions/
│   └── AGENTS-guidelines.md # 分层 AGENTS.md 书写规范
├── state/                   # 状态三件（实例）
├── memory/
│   ├── lessons.md           # 通用坑表（hook 强制必更）
│   ├── failure-modes.md     # ★ 交付失败模式库（幽灵订阅/空执行/伪造输出/单调化）
│   └── harness-antipatterns.md  # ★ harness 自身反模式库（12 条，含实测证据与检测规则）
├── delivery/                # ⑥ 交付层
│   ├── README.md            #    交付铁律总纲
│   ├── DoD-TEMPLATE.md      #    Task DoD 模板
│   ├── acceptance.md        #    项目级 Definition of Done
│   ├── hardening-checklist.md  # Phase N 收尾清单
│   └── audit-prompt.md      #    独立 verifier 审计 prompt
├── planning/
│   ├── CONSTITUTION.md      #    项目宪法（不可协商原则）
│   └── SPEC-TEMPLATE.md     #    spec / plan / tasks 三段式
├── routing/
│   ├── ROUTER.md            #    L0 常驻路由
│   └── capabilities/        #    L1 能力卡
├── skills/                  # 固定流程外化
│   ├── orientation/         #    新 Agent 上手
│   ├── delivery-gate/       #    交付门禁
│   ├── converge-audit/      #    收尾对拍审计
│   └── submit-and-harness-sync/
└── hooks/
    └── hooks.json           # 钩子声明式配置
```

---

## 4. 维护规则（摘要，完整版见 `MAINTENANCE.md`）

| 场景 | 更新文件 | 强制 |
|---|---|---|
| 功能/设计落地 commit | `state/progress.md`（一行式）+ `session-handoff.md` + 相关 `feature_list.json` 条目 | hook **强制**，同一 commit |
| 踩了新坑 | `memory/lessons.md` | hook **强制** |
| 测试基线变化 | `scripts/init.py` + 根 `AGENTS.md` §6 + `VERIFICATION.md` | 同步校准防漂移 |
| 新增/修改模块 | 对应 `**/AGENTS.md` | — |
| 新增固定流程 | 外化 `skills/<name>/SKILL.md` 并在 `ROUTER.md` 注册 | — |
| 架构/铁律变化 | 根 `AGENTS.md` + 本文件 | — |
| 交付前 | 走 `delivery/hardening-checklist.md` Phase N | 项目级 **强制** |
| 每季度 | 修剪：AGENTS 瘦身、坑表去重、feature_list 核对 | — |

**通用规则**
- 变更记一行在 `progress.md`，细节写 `session-handoff.md`，经验写坑表 —— **禁止把长段落堆进 progress**
- 代码 + harness **同一个 commit**
- 根级文件（`AGENTS.md` / `scripts/` / `.githooks/`）被工具硬引用，**不要迁移位置**

---

## 5. 技能注册表

| 技能 | 触发场景 |
|---|---|
| `skills/orientation/SKILL.md` | 新任务 / 新 Agent 接手 |
| `skills/delivery-gate/SKILL.md` | 准备交付 / 被要求"做完了吗" |
| `skills/converge-audit/SKILL.md` | 计划跑完后的收尾对拍 |
| `skills/submit-and-harness-sync/SKILL.md` | 准备 commit / 被 hook 拦下 |
