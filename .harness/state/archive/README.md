# 归档区（archive）

> **本目录的内容：Agent 不需要读。**

---

## 为什么会有这个目录

状态文件（`progress.md`、`feature_list.json`）只增不减，最终会变成 Agent 读不动也读不完的档案。
实测三个真实项目：`feature_list.json` 最大到 **192 KB**（≈50K token），`progress.md` 到 **122 KB**。

**这与 harness 要治的 context rot 是同一个病，只是发生在磁盘上。**

归档机制把"历史"从"当前状态"里分离出来：
- **当前状态**留在 `state/` 下，Agent 每次都要读 → 必须小
- **历史**移到这里，Agent 不读 → 需要时可查

---

## 归档 ≠ 删除

| | 位置 | Agent 读吗 | 可追溯吗 |
|---|---|---|---|
| 当前状态 | `state/*` | ✅ 每次读 | ✅ |
| 归档内容 | `state/archive/*` | ❌ 不读 | ✅ 这里 + git 历史 |

**信息一条没丢**，只是不再占用 Agent 的上下文。

---

## 文件命名

| 文件 | 内容 |
|---|---|
| `progress-log-<YYYY-MM>.md` | `progress.md` §10 变更日志的历史部分 |
| `feature_list-<YYYY-MM>.json` | `feature_list.json` 中已完成的旧条目 |

同月多次归档会追加到同一文件（带归档时间戳分节）。

---

## 怎么触发归档

```bash
python scripts/state_health.py                      # 检查是否超限
python scripts/state_health.py --dry-run --archive  # 先看会归档什么
python scripts/state_health.py --archive            # 执行
```

节律建议：**每次发布/里程碑结束时跑一次**，或 `state_health.py` 报 ERROR 时立即处理。

---

## 保留配额（可在 `.harness/config.json` 覆盖）

```json
{
  "limits": {
    "progress.md":       { "keep_log_lines": 120 },
    "feature_list.json": { "keep_completed": 60 }
  }
}
```

- 变更日志保留最近 **120 行**（约两个月的活跃记录）
- `feature_list.json` 保留最近 **60 条** completed 条目

配额调大 = 单次读得多；调小 = 需要更频繁归档。默认值按"能覆盖一个季度的工作记忆"设定。

---

## 什么时候该去翻归档

- 要追溯"某个功能是什么时候做的、为什么那么改" → `progress-log-*.md`
- 要找"某个已完成功能的 evidence 路径" → `feature_list-*.json`
- 复盘历史决策 → 先看归档，再顺着 commit hash 用 `git show` 看细节

**日常开发不要打开本目录。**
