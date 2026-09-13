# 验证层

> **定位**：环境健康 + 测试基线 + 提交闸门。对应 harness 第三层。
> **方法论**：强制金字塔 `advisory（规则）→ tool（脚本）→ deterministic（hook）`。
> 关键标准必须靠 **hook** 保证——写在文档里让 Agent 自觉遵守的规则，等于没有规则。

---

## 1. 三条命令（开发前 / 提交前）

```bash
python scripts/init.py                                    # 环境健康检查（结构+状态+钩子+命令）
python scripts/no_placeholder_guard.py <code_root>         # 反占位符
python scripts/check_integration.py <code_root>            # 集成检查（孤儿模块）
```

> ⚠️ **扫描范围只写 `code_root`，不要写 `.`**
> `.harness/` 与 `docs/` 里大量**讨论**占位符、TODO、失败模式——那正是它们存在的意义。
> 把门禁指向仓库根会让这些治理文档刷屏（实测 26 个文档命中 38 条），
> 结果是**误报淹没真警报 → 门禁被关掉 → 等于没有门禁**。
> 门禁永远只指向真实代码目录（`.harness/config.json` 的 `code_root`）。

`init.py` 检查什么：
1. **结构**：六层必需文件是否齐全
2. **状态**：`feature_list.json` 是否仍是合法 JSON（并发写易损坏）
3. **钩子**：`git config core.hooksPath` 是否指向 `.githooks`（**这一项失效 = 所有强制机制失效**）
4. **命令**：按 `.harness/config.json` 跑类型检查 / lint / 测试，报告退出码

---

## 2. 提交闸门（pre-commit）

`.githooks/pre-commit`（bash 包装）→ `.githooks/pre-commit.py`（实际逻辑）

强制两项：

| 检查 | 内容 | 阻断条件 |
|---|---|---|
| **harness 同步** | 有代码变更时，`progress.md` + `lessons.md` 必须同步更新 | 两者未在暂存区 |
| **反占位符** | 对 `code_root` 跑 `no_placeholder_guard.py --fail-on error` | 发现 ERROR |

**启用**（脚手架自动做，手动执行）：
```bash
git config core.hooksPath .githooks
```

**豁免**（纯格式化 / 纯测试数据等无功能逻辑的变更）：
```bash
HARNESS_SKIP=1 git commit -m "chore: format"
```

> ⚠️ **不要用 `--no-verify` 绕过**。绕过的每一次，都会让下一次绕过更容易。

---

## 3. 测试基线（防漂移）

**基线漂移是最常见的隐性 bug**：测试数量变了，但记录基线的三处没同步 → 之后所有"全绿了吗"的判断都是错的。

基线变化时必须**同时**更新三处：

| 位置 | 内容 |
|---|---|
| `scripts/init.py` → `.harness/config.json` 的 `baseline` | 测试命令与期望结果 |
| 根 `AGENTS.md` §6 | 测试命令与基线数字 |
| `.harness/state/progress.md` 头部 | `测试基线` 字段 |

---

## 4. 配置（`.harness/config.json`）

```json
{
  "project": "MyProject",
  "stack": "next-ts",
  "code_root": ".",
  "commands": {
    "typecheck": "npm run typecheck",
    "lint": "npm run lint",
    "test": "npx vitest run"
  },
  "baseline": { "test": "0 failed" }
}
```

- `code_root` 决定反占位符与集成检查的扫描范围
- `commands` 里的每条会被 `init.py` 实际执行并报告退出码
- 增删命令后跑一次 `init.py` 确认配置有效

---

## 5. 钩子扩展

复杂钩子（如 SylvaPPT 的 5px 坐标规则检查）用声明式配置管理 → `.harness/hooks/hooks.json`。
模板默认只启用提交闸门；项目需要时按同样结构追加。
