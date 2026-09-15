#!/usr/bin/env python3
"""模板版本 —— 单一真相源。

为什么单独一个文件：
--------------
此前 `harness_lint.py` / `init.py` / `new_project.py` 各自维护一个 `VERSION`，
结果三份互相漂移（实测：lint 已是 1.1.1，另两个还停在 1.1.0）。
版本号漂移在同步场景下是**致命**的 —— `sync_template.py` 要靠它判断
"项目用的是哪一版模板、有没有可用的更新"，版本错了判断就全错。

**发版规程（改这里就够了）**：
1. 改 `TEMPLATE_VERSION`
2. 改 `.harness/MAINTENANCE.md` §5 维护史加一行
3. `git tag v<TEMPLATE_VERSION>` 并 push
"""

from __future__ import annotations

# 语义化版本：MAJOR.MINOR.PATCH
#   MAJOR — 架构级变更，旧项目无法自动同步（需人工迁移）
#   MINOR — 新增模块/规则，旧项目可安全同步
#   PATCH — 修复与措辞，可安全同步
TEMPLATE_VERSION = "1.9.0"

# 生成的项目在同步时，若模板 MAJOR 与本项目 MAJOR 不同 → 拒绝自动同步（需人工迁移）
SYNC_ALLOW_CROSS_MAJOR = False
