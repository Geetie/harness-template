# 代码规范层（CODE-QUALITY）

> **一句话**：把 ESLint / Prettier / ruff 这类代码规范工具接进 harness，
> 让"风格与规范"和"测试"一样，成为**提交前会被拦下来的东西**，而不是靠自觉。

---

## 0. 为什么要单独一层

放进 `config.json.commands` 平铺跑也能跑，但会踩三个坑：

| 坑 | 现象 | 后果 |
|---|---|---|
| **工具没装 = 命令失败** | `ruff` 没装时 `ruff check .` 返回非零 | 显示成"质量命令失败"，新人以为自己代码有问题 |
| **lint 与 format 混为一谈** | 平铺 dict 分不清哪个会改文件 | CI 里误跑 `--fix`，改掉别人的代码 |
| **全量跑太慢** | 提交时全量 lint 动辄几十秒 | 人用 `--no-verify` 绕开 → **门禁自我否定**（S13） |

所以单独一层，专门处理这三件事：**降级要说人话**、**区分只读与改写**、**提交时只查暂存文件**。

---

## 1. 配置在哪

`.harness/config.json` 的 `quality` 段（由 `new_project.py --stack <栈>` 自动生成）：

```json
"quality": {
  "typecheck":    "npm run typecheck",
  "lint":         "npx eslint .",
  "lint_fix":     "npx eslint . --fix",
  "format_check": "npx prettier --check .",
  "format_fix":   "npx prettier --write ."
}
```

**键的语义**（名字决定行为，别乱起）：

| 键 | 会改文件? | 什么时候跑 |
|---|---|---|
| `typecheck` | 否 | `--check` |
| `lint` | 否 | `--check` / `--staged` |
| `lint_fix` | **是** | 仅 `--fix` |
| `format_check` | 否 | `--check` / `--staged` |
| `format_fix` | **是** | 仅 `--fix` |

> 只配一部分也没关系：没配的键会显示"⚪ 未配置（跳过）"，**不会**被当成失败。

---

## 2. 四个用法

```bash
python scripts/quality.py --doctor    # 体检：哪些工具装了、哪些没装、怎么装
python scripts/quality.py --check     # 只检查，不改任何文件（CI / 日常）
python scripts/quality.py --fix       # 自动修复（本地用，会改文件）
python scripts/quality.py --staged    # 只查 git 暂存文件（pre-commit 自动跑）
```

### `--doctor` 输出示例

```
  ✅ lint          npx eslint .
  ⚠️  format_check  跳过 — prettier 未安装
      安装: npm i -D prettier
  ⚪ typecheck     未配置
```

**三种状态的区分很重要**：
- ✅ 装了且配置好 → 会真的跑
- ⚠️ **没装 → 跳过**（不等于你的代码有问题）
- ⚪ 没配 → 跳过（这个项目不需要这一项）

---

## 3. 预置技术栈

| stack | lint | format | typecheck |
|---|---|---|---|
| `next-ts` | ESLint | Prettier | `tsc` |
| `python` | ruff check | ruff format | — |
| `tauri` | ESLint（前端侧） | Prettier | `tsc` |
| `java` | Checkstyle | Spotless | — |
| `generic` | — | — | — |

用 `new_project.py --stack python` 生成时会自动写入对应配置。

---

## 4. 加一个新栈 / 改配置

直接改 `.harness/config.json` 的 `quality` 段即可，不用动代码。
若想让后续项目也默认带上，改 `scripts/new_project.py` 的 `STACKS`。

**注意**：`lint` 命令里带 `.`（如 `npx eslint .`）时，`--staged` 会把 `.` 替换成暂存文件列表；
不带 `.` 的会追加。写命令时尽量带 `.`，这样两种模式都对。

---

## 5. 与其他层的关系

| 层 | 管什么 | 例子 |
|---|---|---|
| **本层（code-quality）** | **怎么写**（风格、规范） | 缩进、未使用变量、命名 |
| `placeholder-guard` | **有没有写完** | TODO、桩实现、`NotImplementedError` |
| `integration-check` | **有没有接上** | 写了模块但没人调用 |
| `verification` → `harness_lint.py` | **harness 文档自身** 是否漂移 | 死链、绝对路径 |

四者**不重叠**：风格归本层，完工度归 guard，接线归 integration-check，文档归 lint。

---

## 6. 关掉这个模块

在 `.harness/config.json` 设 `"code-quality": false`。
此时 `scripts/quality.py` 与本文档都不会生成，**pre-commit 也会自动跳过质量检查**
（脚本不存在即跳过，不会报错 —— 关掉的模块不该打扰你，铁律③）。

代价：**风格问题不再被拦**，只能靠 code review 兜。
