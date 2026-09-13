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

## 4. 写入格式速查

| 文件 | 格式 |
|---|---|
| progress.md §10 | `| YYYY-MM-DD | 做了什么 + 验证结果 + commit hash |`（一行，禁止长段落） |
| feature_list.json | 条目：`id` / `title` / `spec` / `status` / `evidence` / `notes`；`id` 命名 `<子系统>-P<级别>-<序号>` |
| session-handoff.md | 3-5 条摘要 + 下一步优先任务 + 需要人决定的问题 |
