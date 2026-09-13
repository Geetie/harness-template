# harness-template

> 一套开箱即用的 **AI 编码 Agent Harness 工程模板**。新项目直接 clone 下来跑一次脚手架，Agent 立刻知道项目是什么、自己该做什么、什么算"做完"。
>
> 设计目标只有一个：**让 Agent 稳定交付可用产品，而不是交付一个跑得起来的 demo。**

---

## 1. 为什么需要它

AI 辅助开发最典型的失败不是写不出代码，而是：

> 计划顺利跑完 → 每个模块"完成" → 交到你手上却是一个充斥占位符、模块互不相连的简陋 demo。

根因是三件事（业界已有正式命名）：

| 症状 | 命名 | 根因 |
|---|---|---|
| TODO / 占位符 | **Incomplete Implementation** | 没有 Definition of Done，Agent 自己定义"完成"，且倾向"看起来完成" |
| 模块没集成 | **Wiring Failure** | 计划**横向切模块**，验收**纵向走用户旅程**，两者正交 |
| 整体是 demo | **Production-Readiness Cliff** | Agent 的奖励信号偏可见层（UI/截图），不可见层（持久化/鉴权/并发/可观测）被跳过 |

本模板把这三类失败的防线**固化进工程结构**，而不是写进 prompt 让 Agent 自觉遵守。

---

## 2. 六层架构

```
┌─────────────────────────────────────────────────────────────┐
│ ⑥ 交付层  .harness/delivery/      交付门禁·DoD·集成·审计     │  ← 本模板新增，专治最后一公里
├─────────────────────────────────────────────────────────────┤
│ ① 指令层  AGENTS.md + **/AGENTS.md    宪法·铁律·分层规则      │
│ ② 状态层  progress/feature_list/handoff   跨会话落盘          │
│ ③ 验证层  scripts/ + .harness/hooks/     环境·基线·闸门        │
│ ④ 记忆层  .harness/memory/               坑表·失败模式库      │
│ ⑤ 技能层  .harness/skills/ + routing/    固定流程·按需加载    │
└─────────────────────────────────────────────────────────────┘
        强制金字塔：advisory(规则) → tool(脚本) → deterministic(hook)
```

**前五层**来自 UGSimulator / SylvaPPT / AI投股工作台三个项目的实战沉淀；
**第六层（交付层）**是把"打通最后一公里"的方法论固化成门禁。

---

## 3. 三条设计原则

1. **指令文件是宪法，不是百科全书** —— 只记 Agent 会犯错的规则，其余用指针外推
2. **State 落盘，不进 context** —— 一切跨会话状态写磁盘（JSON 抗损坏），不依赖 Agent 记忆
3. **强制金字塔** —— 关键标准必须靠 hook 保证，不能靠 Agent 自觉（advisory < tool < deterministic）

配套两条省 token 机制：
- **渐进式披露**：静态（根 AGENTS）→ 半动态（模块 AGENTS / harness 各层）→ 全动态（skills）
- **ROUTER 三级加载**：L0 路由常驻（~1K token）→ L1 能力卡按需（2-5K/张）→ L2 深度原文（按需）

---

## 4. 快速开始

```bash
# 1. 克隆（或 fork 到你自己的账号）
git clone <your-repo-url> my-project && cd my-project

# 2. 用脚手架初始化（替换占位符、配置 git hooks、生成状态文件）
python scripts/new_project.py --name "MyProject" --stack "next-ts" --target ..

# 或直接在本目录内初始化
python scripts/new_project.py --name "MyProject" --in-place

# 3. 环境健康检查
python scripts/init.py

# 4. 把 AGENTS.md 交给你的 Agent，说一句："读 AGENTS.md，按 §2 启动路径 Orient"
```

脚手架会做四件事：
- 把 `{{PROJECT_NAME}}` 等占位符替换成真实值
- 配置 `git config core.hooksPath .githooks`
- 生成 `.harness/state/` 下三份状态文件实例
- 校验六层结构完整、打印「下一步该填什么」清单

---

## 5. 目录结构

```
harness-template/
├── AGENTS.md                    # ① 指令宪法（模板，含占位符）
├── CLAUDE.md                    # 跨工具兼容入口（指向 AGENTS.md）
├── README.md                    # 本文件
├── .gitignore
├── .githooks/
│   └── pre-commit               # ③ 确定性闸门：harness 同步 + 反占位符
├── .harness/
│   ├── README.md                # harness 总览（六层 + 启动路径 + 维护规则）
│   ├── MAINTENANCE.md           # ★ 维护规范总表：哪个文件何时更新、谁更新
│   ├── STATE-PROTOCOL.md        # ② 状态三件的分工与写入规范
│   ├── VERIFICATION.md          # ③ 验证层：init/基线/hook 机制
│   ├── instructions/
│   │   └── AGENTS-guidelines.md # 分层 AGENTS.md 书写规范
│   ├── state/                   # ② 状态三件（模板实例，脚手架复制）
│   │   ├── progress.md
│   │   ├── feature_list.json
│   │   └── session-handoff.md
│   ├── memory/
│   │   ├── lessons.md           # ④ 坑表（hook 强制必更）
│   │   └── failure-modes.md     # ④ ★ 交付失败模式库
│   ├── delivery/                # ⑥ ★ 交付层
│   │   ├── README.md            #    交付铁律总纲
│   │   ├── DoD-TEMPLATE.md      #    Task 级验收模板
│   │   ├── acceptance.md        #    项目级 Definition of Done
│   │   ├── hardening-checklist.md  # Phase N 收尾清单
│   │   └── audit-prompt.md      #    独立 verifier 审计 prompt
│   ├── planning/                # ① 计划骨架（Spec-Driven）
│   │   ├── CONSTITUTION.md      #    项目宪法（不可协商原则）
│   │   └── SPEC-TEMPLATE.md     #    spec/plan/tasks 三段式模板
│   ├── routing/
│   │   ├── ROUTER.md            # ⑤ L0 常驻路由（省 token 关键）
│   │   └── capabilities/        # ⑤ L1 能力卡（按需加载）
│   ├── skills/                  # ⑤ 固定流程外化
│   │   ├── orientation/         #    新 Agent 上手
│   │   ├── delivery-gate/       #    ★ 交付门禁
│   │   ├── converge-audit/      #    ★ 收尾对拍审计
│   │   └── submit-and-harness-sync/  # 提交 + harness 同步
│   └── hooks/
│       └── hooks.json           # ③ 钩子声明式配置
├── scripts/
│   ├── init.py                  # 环境健康检查
│   ├── no_placeholder_guard.py  # ⑥ 反占位符门禁
│   ├── check_integration.py     # ⑥ 集成检查（模块真的被接进主流程了吗）
│   └── new_project.py           # 脚手架
└── docs/
    └── README.md                # 设计文档索引（渐进式披露唯一入口）
```

---

## 6. 维护

**把 harness 当代码管理。** 所有维护规则集中在 → [`.harness/MAINTENANCE.md`](.harness/MAINTENANCE.md)

三条硬规则：
1. **代码 + harness 同一个 commit**（pre-commit hook 强制）
2. **踩坑必回写坑表**（hook 强制必更）
3. **每季度修剪一次** —— stale rules 比 missing rules 更有害

---

## 7. 许可与来源

模板方法论来源：
- 前五层：UGSimulator / SylvaPPT / AI投股工作台 实战沉淀（2026-07 至今）
- 第六层：[Production-Readiness Cliff](https://aipatternbook.com/production-readiness-cliff) · [Acceptance Criteria](https://aipatternbook.com/acceptance-criteria) · [AI Smell](https://aipatternbook.com/ai-smell) · [Addy Osmani: The 70% Problem](https://addyosmani.com/agentic-engineering/the-70-percent-problem) · [GitHub Spec Kit](https://github.com/github/spec-kit)
