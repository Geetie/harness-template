---
name: submit-and-harness-sync
description: 提交与 harness 同步。触发场景：准备 git commit / 被 pre-commit hook 拦下 / 需要更新 progress、feature_list、session-handoff、坑表。确保代码与 harness 文件在同一个 commit，且状态文件符合写入规范。
---

# 提交 + harness 同步

> **铁律**：代码 + harness 文件**同一个 commit**（`.githooks/pre-commit` 强制）。
> 代码改了但 harness 没动 = 提交被拦。这是设计意图，不是 bug。

## 提交前清单

```
□ 类型检查 / lint / 测试全绿（贴出真实输出与退出码）
□ scripts/no_placeholder_guard.py <code_root> 通过
□ .harness/state/progress.md §10 追加一行（一行式！）
□ .harness/state/feature_list.json 状态已翻转（若功能状态变化）
□ .harness/state/session-handoff.md 已更新（本次做了什么 / 下一步）
□ .harness/memory/lessons.md 已追加（若踩了新坑）
□ 目标模块的 **/AGENTS.md 已更新（若目录内容变化）
□ 只 add 自己的文件（并行会话纪律）
```

## 一行式变更日志格式

```markdown
| 2026-09-14 | feat(auth): 登录持久化（write-read-reload 通过，128 passed / 0 failed，commit abc1234） |
```

规则：
- 一行写**发生了什么 + 验证结果 + commit hash**
- **细节禁止写在这里** —— 细节去 `session-handoff.md`，经验去 `lessons.md`
- 禁止长段落（历史教训：长段落会让 progress 迅速膨胀且无人读）

## feature_list.json 写入纪律

1. **用工具/脚本写，禁止手拼**；写后必须能 JSON.parse
2. **只翻转 status，禁止删条目**：`missing → partial → completed`，废弃用 `deprecated` + notes
3. 只有 evidence 指向**真实存在的文件路径**时才允许标 `completed`（状态去虚标）
4. 同步更新顶部 `last_updated` 与底部 `summary` 计数

## 被 hook 拦下时

hook 会明确告诉你缺哪个文件。按提示补齐后重新 `git add` + `git commit`。
**不要用 `--no-verify` 绕过** —— 除非你确认这是合法豁免。

合法豁免（纯格式化 / 纯测试数据等不涉及功能逻辑的变更）：
```bash
HARNESS_SKIP=1 git commit -m "chore: format"
```

## 提交信息格式

```
<type>(<scope>): <description>
```
type: `feat|fix|refactor|docs|test|chore`

## 提交后

```
□ git log --oneline -1 确认提交成功（不要只信退出码）
□ 更新 session-handoff.md 的"最后 commit"
```
