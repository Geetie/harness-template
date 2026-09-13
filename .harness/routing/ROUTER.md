# 能力路由（L0 常驻）

> **三级加载，省 token 的核心机制**：
> - **L0** = 本文件，常驻（~1K token）—— 只做一件事：判意图，选卡
> - **L1** = `capabilities/<卡>.md`，按需加载（2-5K token/张）—— **单次任务 ≤2 张**
> - **L2** = 深度原文（`docs/` 下），按需 —— 单次 ≤3 篇
>
> **铁律：先判意图，再开卡。禁止直接翻原始文档或遍历整个 docs/。**

---

## 能力卡注册表

| # | 卡名 | 触发条件（看到这些就开这张卡） | 文件 |
|---|---|---|---|
| 1 | **orientation** | 新任务 / 新会话 / 不知道从哪开始 / 接手别人的工作 | `capabilities/orientation.md` |
| 2 | **delivery-audit** | 要交付 / 被问"做完了吗" / 怀疑是 demo / 收尾阶段 | `capabilities/delivery-audit.md` |
| 3 | **integration-check** | 模块写完了要接入 / 怀疑没接上 / handler 没反应 / 数据没落库 | `capabilities/integration-check.md` |

### 技能（固定流程，与能力卡的区别：技能是"步骤"，能力卡是"知识"）

| 技能 | 触发场景 | 文件 |
|---|---|---|
| `delivery-gate` | 准备交付 | `../skills/delivery-gate/SKILL.md` |
| `converge-audit` | 计划跑完后的收尾对拍 | `../skills/converge-audit/SKILL.md` |
| `submit-and-harness-sync` | 准备 commit / 被 hook 拦下 | `../skills/submit-and-harness-sync/SKILL.md` |

---

## 意图路由示例

- 「帮我看看这个新项目」→ orientation（1）
- 「这功能做完了吗 / 能交付吗」→ delivery-audit（2）
- 「我加了个模块但没反应 / 数据没存住」→ integration-check（3）
- 「准备 commit」→ submit-and-harness-sync（技能）
- 「计划跑完了，收个尾」→ converge-audit（技能）+ delivery-audit（2）

**复合任务**：先判主意图选主卡，再按需要联动第二张（总数 ≤2）。

---

## 通用红线（每次必守，无论开哪张卡）

1. **不编造**：不知道就说不知道；缺数据返回缺失，绝不脑补
2. **不写占位实现**：TODO / 桩 / 假数据一律禁止，缺依赖就显式报错
3. **不无证据声明完成**：交付必须有命令输出 / 查询 / 日志；无法验证标 UNKNOWN
4. **不顺手改范围外的代码**：发现相邻问题单独报告
5. **不确定先问**：先问再做，优于做完再改

---

## 维护

- 新增能力卡后**必须在上表注册**，否则 Agent 找不到它（等于不存在）
- 卡片超过 5K token 就该拆分
- 季度修剪：删掉不再使用的卡
