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

### 4.1 先理解一件事：模板是**工具箱**，不是项目骨架

clone 下来的这个目录是**工具箱**（用来生成新项目、以及给已有项目拉更新），
**它本身不是你的项目**。你的项目由它**生成到别处**，是独立的 git 仓库。

推荐把工具箱放在固定位置长期保留 —— 这样模板改进了，`git pull` 就能拿到：

```bash
# 1. clone 工具箱（放在你习惯的位置）
git clone <this-repo-url> ~/tools/harness

# 2. 到你想放项目的地方，生成项目（--target 必填）
cd ~/projects
python ~/tools/harness/scripts/new_project.py --name "MyProject" --stack python --target .

# 3. 进项目
cd MyProject
python scripts/init.py          # 体检：结构/配置/hooks 是否就位
```

生成的 `MyProject/` 是**全新 git 仓库**（已 `git init`、无 remote、无提交）——
直接 `git remote add origin <你的仓库>` 再 push 即可，与工具箱无关。

> ⚠️ **不要** clone 完就在那个目录里 `--in-place`：脚手架会拒绝
> （检测到 `.harness/TEMPLATE-REPO`，防止把模板占位符就地写死，模板就废了）。
> 若确实想那样做，见 §4.5。

### 4.2 填三个核心占位符（决定项目质量的部分）

脚手架会打印一份待填清单。**最关键的三个**在 `AGENTS.md`：

| 占位符 | 填什么 | 为什么它是核心 |
|---|---|---|
| `PROJECT_ONE_LINER` | 一句话说清项目是什么 | Agent 判断"这个需求该不该做"的依据 |
| `CORE_JOURNEY` | 核心用户旅程 | **产品可用 = 这条路径跑得通**；验收按它纵向走，与"横向按模块切"正交 |
| `ARCH_TREE` | 代码目录骨架 | Agent 知道新文件该放哪，不会乱建目录 |

其余（`progress.md` 的测试基线数字、`CONSTITUTION.md` 的技术约束等）可以边做边填。

### 4.3 选技术栈与档位

```bash
--stack  generic | python | next-ts | tauri | java
```

| stack | code_root | 测试命令 | 备注 |
|---|---|---|---|
| `python` | `src` | `pytest -q` | 会额外生成 `pytest.ini`（排除 harness 工具脚本，见 §8） |
| `next-ts` | `.` | `npx vitest run` | 含 ESLint / Prettier |
| `tauri` | `src` | `npx vitest run` | 前端侧 ESLint / Prettier |
| `java` | `src/main/java` | `mvn -q test` | 含 Checkstyle / Spotless |
| `generic` | `src` | （无） | 未定栈时用 |

```bash
--preset minimal | standard | full     # 默认 full
```

| preset | 层数 | 适合 |
|---|---|---|
| `minimal` | 4（指令/状态/验证/记忆） | 小工具、试验性项目 |
| `standard` | 12（+交付/规划/占位守卫/技能/代码规范/设计/测试/集成检查） | 常规项目 |
| `full` | 15（+路由/决策/升级） | 长期演进、需要决策台账的项目 |

不确定就先用 `--stack generic --preset minimal`，需要时再加。

### 4.4 把 AGENTS.md 交给你的 Agent

```
读 AGENTS.md，按 §2 启动路径 Orient。
```

### 4.5 想改造 clone 的那个目录本身？

```bash
rm .harness/TEMPLATE-REPO      # 摘掉"我是模板本体"的标记
git remote remove origin       # ⚠️ clone 后 remote 指向模板，不改会 push 回模板
git remote add origin <你的仓库>
python scripts/new_project.py --name "MyProject" --stack python --in-place
```

### 4.6 已经有项目，想拉模板的后续改进？

```bash
cd 你的项目
python scripts/sync_template.py --check     # 只看差异，不写文件
python scripts/sync_template.py --apply     # 应用"可安全更新"的部分
```

三向合并（模板基线 / 你的改动 / 模板当前）：你改过的文件**不会被覆盖**，
冲突项会列出来让你裁决。基线记在 `.harness/config.json` 里，不用额外维护。

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

## 7. 常见坑（首次使用会遇到的）

### `.py` 文件里的占位符形态是"描述"，不是待填项

模板脚本的注释里会写类似「模板里是占位符形态、项目里是实值」这种**说明文字**。
脚手架**不会**替换 `.py` 文件里的占位符形态，也不会把它们列进待填清单 ——
否则「模板里是占位符字面」这种说明会被改写成「模板里是 <你的项目名>」，
语义完全反了（这是实测踩到并修掉的）。

### `pytest.ini` 为什么会被生成

harness 自带 `scripts/test_runner.py` / `scripts/test_audit.py`，
它们文件名匹配 pytest 的 `test_*.py` 收集规则。不排除的话，**任何**项目跑
`pytest` 都会去收集它们，并因为里面的业务函数（如 `test_command(cfg)`）
报 `fixture 'cfg' not found`。

所以 `--stack python` 会生成一份 `pytest.ini`：

```ini
[pytest]
norecursedirs = scripts .git __pycache__ node_modules .venv
```

如果你有自己的 `pytest.ini` / `pyproject.toml` 配置，**保留自己的**，
只要确保 `norecursedirs` 里有 `scripts` 即可。

### pre-commit 会拦你的提交 —— 那是在工作

改代码后提交，如果 `progress.md` / `lessons.md` 没跟着更新，会被拦。
这是设计（见 §3 强制金字塔）：

```
harness 未同步：以下文件必须与代码在同一个 commit 中更新
      · .harness/state/progress.md
      · .harness/memory/lessons.md
```

修法就是照做：`progress.md` 追加一行变更日志，`lessons.md` 写一条教训
（本次没有新教训就写「本次无新教训」，但别留空不改）。

纯格式化 / 纯测试数据的提交可以 `HARNESS_SKIP=1 git commit` 跳过
（**仅限这类**，跳过会失去全部五道检查）。

### `.harness/` 不是临时文件

它是 harness 的状态与规则本体（Agent 每次开工都要读），
也是 pre-commit 检查的对象。不要加进 `.gitignore`、不要手动删。

### 报告里出现"未做运行时验证"是什么意思

证据门禁（`evidence_gate.py`）验证"标完成的功能是否真做完"时，
只有证据命令形如 `python xxx.py` 才能做**运行时**验证（追踪函数是否真被调用、
返回值是否真出现在输出里）。其他形式（`pytest`、`node`、`go test`）
会降级为静态检查，并在输出里**明确标注**：

```
⚠️ 未做运行时验证（证据命令非 `python xxx.py` 形式）—— 本次仅静态检查
```

**这是诚实标注，不是失败** —— 但你知道该信到什么程度。

---

## 8. 许可与来源

模板方法论来源：
- 前五层：UGSimulator / SylvaPPT / AI投股工作台 实战沉淀（2026-07 至今）
- 第六层：[Production-Readiness Cliff](https://aipatternbook.com/production-readiness-cliff) · [Acceptance Criteria](https://aipatternbook.com/acceptance-criteria) · [AI Smell](https://aipatternbook.com/ai-smell) · [Addy Osmani: The 70% Problem](https://addyosmani.com/agentic-engineering/the-70-percent-problem) · [GitHub Spec Kit](https://github.com/github/spec-kit)
