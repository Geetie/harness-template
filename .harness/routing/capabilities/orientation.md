# 能力卡：orientation（新任务上手）

> **触发**：新任务 / 新会话 / 接手别人的工作 / 不知道从哪开始
> **目标**：用最少 token 达到可开工状态

---

## 八步（严格按序，禁止通读）

| # | 动作 | 产出 |
|---|------|------|
| 1 | 读根 `AGENTS.md` §4 铁律 + §5 工作流 | 知道红线 |
| 2 | 读 `.harness/ROUTER.md` | 判定本次要开哪张卡 |
| 3 | 按 ROUTER 加载 ≤2 张 capability 卡 | 拿到领域知识 |
| 4 | 读 `.harness/state/` 三件：progress → feature_list → session-handoff | 知道项目到哪了 |
| 5 | 读 `.harness/memory/lessons.md` | 知道坑在哪 |
| 6 | 读目标模块的 `**/AGENTS.md` | 知道要改的目录 |
| 7 | 读任务对应的 spec（`.harness/planning/` 或 `docs/`） | 知道验收标准 |
| 8 | `python scripts/init.py` + `git status && git log --oneline -10` | 环境与基线 |

## 开工前自检（任一缺失 → 回头补读）

- [ ] 我知道项目铁律
- [ ] 我知道当前测试基线与分支
- [ ] 我要改哪个模块，读过它的 AGENTS.md
- [ ] 我知道这个任务的 AC 在哪

---

## 接手他人/他 Agent 的工作（额外三步）

1. **先审计再动手** —— `git log` 看最近改动；跑一次测试确认当前是绿的
2. **确认没有隐藏债务** —— 跑 `scripts/no_placeholder_guard.py <dir>`，前人可能留了 TODO
3. **确认集成状态** —— 跑 `scripts/check_integration.py <dir>`，前人可能写了没接的模块

> 直接在前人半成品上继续，是最容易把已知问题变成未知问题的方式。

---

## 常见误判

| 误判 | 后果 | 正确做法 |
|---|---|---|
| 通读整个 `docs/` | 烧光 token 还抓不住重点 | 按 `docs/README.md` 索引定位，只读相关的 |
| 跳过 ROUTER 直接翻文档 | 加载了不需要的知识 | 先判意图，再开卡 |
| 不读坑表就动手 | 重复踩坑 | 坑表通常 2 分钟读完，省 2 小时 |
| 不确认基线就改 | 无法判断回归 | 改前先跑一遍，知道"原来是对的" |
