---
name: orientation
description: 新 Agent / 新任务上手。触发场景：刚进项目 / 新会话 / 接手他人工作 / 不知道从哪开始。按八步渐进式读取必要文件，用最少 token 达到可开工状态，禁止通读整个 docs。
---

# Orient（新任务上手）

> **目标**：用最少 token 达到可开工状态。**禁止通读** —— 通读会烧光上下文还抓不住重点。

## 八步（严格按序）

| # | 动作 |
|---|------|
| 1 | 读根 `AGENTS.md` §4 铁律 + §5 工作流 |
| 2 | 读 `.harness/routing/ROUTER.md` → 判定本次要开哪张 capability 卡 |
| 3 | 按 ROUTER 加载 **≤2 张** `capabilities/*.md` |
| 4 | 读 `.harness/state/`：`progress.md` → `feature_list.json` → `session-handoff.md` |
| 5 | 读 `.harness/memory/lessons.md`（坑表） |
| 6 | 读目标模块的 `**/AGENTS.md` |
| 7 | 读任务对应的 spec（`.harness/planning/` 或按 `docs/README.md` 索引定位） |
| 8 | `python scripts/init.py` + `git status && git log --oneline -10` |

## 开工前自检

```
□ 我知道项目铁律
□ 我知道当前测试基线与分支
□ 我知道要改哪个模块，读过它的 AGENTS.md
□ 我知道这个任务的 AC 在哪
```
任一缺失 → 回头补读，不要硬上。

## 接手他人 / 他 Agent 的工作（额外三步）

1. `git log` 看最近改动 + 跑一次测试确认当前是绿的
2. `python scripts/no_placeholder_guard.py <dir>` —— 前人可能留了 TODO
3. `python scripts/check_integration.py <dir>` —— 前人可能写了没接的模块

> 直接在前人半成品上继续，最容易把已知问题变成未知问题。

## 常见误判

| 误判 | 后果 | 正确做法 |
|---|---|---|
| 通读整个 `docs/` | 烧 token 且抓不住重点 | 按索引定位，只读相关的 |
| 跳过 ROUTER 直接翻文档 | 加载了不需要的知识 | 先判意图，再开卡 |
| 不读坑表就动手 | 重复踩坑 | 坑表 2 分钟，省 2 小时 |
| 不确认基线就改 | 无法判断回归 | 改前先跑一遍 |
