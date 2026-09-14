# 状态层协议

> **定位**：规定三份状态文件的分工、写入格式与维护时机。状态层回答"项目现在到哪了"，
> 与指令层（`AGENTS.md`）和验证层（`VERIFICATION.md`）正交。
>
> **方法论**：state 落盘而非 context —— 可变状态必须写磁盘为机器可读 / 可 diff 的文件，**禁止依赖 Agent 记忆或对话历史**。

---

## 1. 三文件分工

| 文件 | 角色 | 回答的问题 | 强制 |
|---|---|---|---|
| `progress.md` | 项目状态 + 一行式历史索引 | 完成度？阻塞？Bug？最近变更？ | hook **强制必更** |
| `feature_list.json` | 功能粒度实现状态 | 每个 spec 条目实现了没有？ | hook 通用检查 |
| `session-handoff.md` | 会话交接 | 上次干了什么？下一步？ | 约定（会话结束必更） |

**分工铁律**：内容不重复。一条变更 → progress 记一行索引 / handoff 记摘要 / feature_list 翻状态，各司其职。

---

## 2. 会话生命周期（8 步）

```
① 读 progress.md → feature_list.json → session-handoff.md   （知道到哪了）
② 读目标模块 AGENTS.md                                        （知道要改哪）
③ 读任务对应的 spec / AC                                       （知道完成标准）
④ 跑 scripts/init.py                                          （确认环境健康）
⑤ 干活（每完成一个小步就跑测试，不要攒到最后）
⑥ 更新三份状态文件 + 坑表（若踩坑）
⑦ 走 DoD 八项自查（.harness/delivery/DoD-TEMPLATE.md）
⑧ commit（代码 + harness 同一 commit），更新 handoff 为下一会话准备
```

---

## 3. 抗损坏规则

1. **用工具/脚本写 JSON，禁止手拼**；写后必须能通过 JSON.parse
2. **并发写要串行**：并行会话只改自己的条目；改前 `git status` 确认该文件未被并行会话暂存
3. 提交前 `git diff --cached .harness/state/feature_list.json` 确认仍是合法 JSON
4. **只翻转状态，禁止删条目**：`missing → partial → completed`；废弃用 `deprecated` + notes 说明
5. **状态去虚标**：只有 evidence 指向真实存在的文件路径时，才允许标 `completed`

---

## 4. 生命周期与归档（最容易被忽略的一节）

> **核心认识**：状态文件**只增不减**，最终会变成 Agent 读不动也读不完的档案。
> **这与 harness 要治的 context rot 是同一个病，只是发生在磁盘上。**

**实测教训（2026-09 三个真实项目）**：

| 项目 | feature_list.json | progress.md | AGENTS.md |
|---|---|---|---|
| A | **192 KB** | **122 KB** | 144 行 |
| B | 34 KB | 59 KB | **540 行** |
| C | 22 KB | 45 KB | 66 行 |

192 KB 的 JSON ≈ **50K token** —— Agent 光读状态就烧掉半个上下文，而且读完还抓不住重点。
根因不是"写得不规范"，而是**只规定了怎么写（一行式），没规定留多久（生命周期）**。

### 4.1 体积上限（硬性）

| 文件 | 上限 | 超限动作 |
|---|---|---|
| `AGENTS.md` | 16 KB / **150 行** | 外推内容到 skills / memory |
| `progress.md` | 32 KB / 300 行 | 归档变更日志（保留最近 120 行） |
| `session-handoff.md` | 16 KB / 200 行 | 人工精简（它是"当前会话"语义，不自动归档） |
| `feature_list.json` | 64 KB / 150 条目 | 归档超配额的 completed 条目（保留最近 60 条） |

### 4.2 归档机制

```bash
python scripts/state_health.py                          # 检查是否超限
python scripts/state_health.py --dry-run --archive      # 预览会归档什么（先看）
python scripts/state_health.py --archive                # 执行
```

归档去向：`.harness/state/archive/`
- `progress-log-<YYYY-MM>.md` —— 变更日志的历史部分
- `feature_list-<YYYY-MM>.json` —— 已完成的旧条目

**归档 ≠ 删除**：git 完整保留历史，需要追溯时去归档文件；**Agent 不再读归档区**，这才是省 token 的关键。

### 4.3 与「禁止删条目」规则的关系

`feature_list.json` 的规则是「**禁止删条目，只翻转状态**」——
这条规则保住了可追溯性，但也导致了无限膨胀（旧条目永远占着 Agent 的上下文）。

**正确的完整表述**：
> 禁止**删除**条目；但 `completed` 状态且**超出保留配额的条目应当归档**。
> 归档是移动，不是删除——git 历史与归档文件都还在。

### 4.4 状态层分裂检测

状态层**只允许 `state/` 三件**。以下信号说明出现了"第二套状态"（两套并存必然漂移）：

- 根目录出现 `harness-progress.txt` / `harness-tasks.json` / `*-progress.log` 之类
- 出现 `.harness-active` 之类的空标记文件
- 多个文件都在记"进度"

`state_health.py` 会自动检测并报警。历史流水请归档，空文件请删除。

---

## 5. 写入格式速查

| 文件 | 格式 |
|---|---|
| progress.md §10 | `| YYYY-MM-DD | 做了什么 + 验证结果 + commit hash |`（一行，禁止长段落） |
| feature_list.json | 条目：`id` / `title` / `spec` / `status` / `evidence` / `notes`；`id` 命名 `<子系统>-P<级别>-<序号>` |
| session-handoff.md | 3-5 条摘要 + 下一步优先任务 + 需要人决定的问题 |
