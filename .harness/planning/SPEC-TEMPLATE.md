# Spec / Plan / Tasks 三段式模板

> **方法论**：Spec-Driven Development —— 从 `Prompt → Code` 变成 `Prompt → Spec → Plan → Tasks → Code`。
> 核心收益：**先定义完成，再动手**，让 Agent 的终点线与你的一致。
>
> 三段各自回答：Spec = 做什么与什么算做完；Plan = 怎么做与为什么；Tasks = 按什么顺序做。

---

## 一、Spec（做什么）

```markdown
# Spec: <功能名>

## 用户故事
作为 <角色>，我希望 <动作>，以便 <价值>。

## 核心用户旅程（纵向，不是模块列表）
<起点> → <步骤> → <用户看到的结果>

## 功能需求 FR
- FR-001 <一句话，可验证>
- FR-002

## 成功标准 SC
- SC-001 <可度量的结果，如"上传 5MB PDF 后在 3 秒内看到解析结果">

## 边界与非目标
- 不做：<明确排除的东西>

## 验收标准 AC（详见 .harness/delivery/DoD-TEMPLATE.md）
- [ ] AC-01 … AC-08
```

**Spec 的三条写法要求**
1. AC 必须含**至少 1 条错误处理**与**至少 1 条边界**（否则 Agent 只做 happy path）
2. 每条 SC 都要能被后续 converge 审计追溯（有对应实现或明确标记为未做）
3. **先写 AC 再写代码** —— AC 是终点线，Agent 精确停在你画的线上，不多不少

---

## 二、Plan（怎么做）

```markdown
# Plan: <功能名>

## Constitution Check
- Principle I 交付完整性：☐ 满足
- Principle II 无占位：☐ 满足
- Principle III 可验证性：☐ 满足
- Principle IV 技术栈：☐ 满足
- Principle V 质量闸门：☐ 满足

## 技术方案
<选型 + 关键决策>

## 数据契约 / 接口
| 接口 | 输入 | 输出 | 错误 |
|---|---|---|---|

## 依赖与风险
- 依赖：
- 风险：<最可能出问题的地方 + 应对>
```

**Plan 的硬性要求**：**必须先做 Constitution Check**，不通过就改计划，不要指望实现阶段补救。

---

## 三、Tasks（按什么顺序做）

```markdown
# Tasks: <功能名>

## Phase 0 · Walking Skeleton（必做，不可跳过）
- [ ] T001 打通一条最薄的端到端路径：用最简单的数据，穿过每一层（UI/API/逻辑/存储），产出真实结果
      AC：能在界面上真的走完；数据落库；能跑起来

## Phase 1..N · 按用户旅程切分（不按技术模块横切）
- [ ] T002 <用户能走完的一条路径>
      AC-01 走通 / AC-02 持久化 / AC-03 集成到 UI / AC-04 错误路径 / AC-05 边界
      AC-06 真实依赖集成测试 / AC-07 无占位 / AC-08 质量闸门

## Phase N · Integration & Hardening（固定收尾，占 20-30% 预算）
- [ ] T0xx 全链路走查（手动）
- [ ] T0xx 反占位符扫描 --fail-on warn
- [ ] T0xx 接线体检（每个注册的服务真的触发并产出）
- [ ] T0xx 隐形层六项（持久化/鉴权/密钥/并发/可观测/部署回滚）
- [ ] T0xx converge 审计：拿 spec + tasks 对拍代码库，关闭 gap
- [ ] T0xx 独立 verifier 审计（新会话）
```

### Tasks 的四条规则

1. **Phase 0 必须是 Walking Skeleton** —— 用假数据打通一条**最薄但每一层都真实**的端到端路径并跑起来。
   不是"先搭数据层"。骨架不走路，教它跑步没有意义。
2. **按用户旅程纵向切，不按模块横向切** —— 这是"模块都好了但拼不起来"的根治办法。
3. **tasks 是 append-only** —— converge 发现 gap 时**追加**新任务，不要改已有任务（保可追溯）。
4. **Phase N 固定存在** —— 集成不会自然发生，必须被显式计划。

---

## 四、converge（收尾对拍）

实现完成后，拿 spec / plan / tasks / constitution 对拍代码库：

```
□ 每条 FR 都有对应实现（或明确标记未做）
□ 每条 SC 可被验证
□ 每条 task 被验证关闭
□ 无违反 constitution 的实现
□ 产出 gap 清单 → 追加 gap-closure 任务 → 关闭后再跑一次 converge
```

**实现完 ≠ 完成。** 这一遍对拍才是把"跑完计划"变成"可交付"的关键一步。
