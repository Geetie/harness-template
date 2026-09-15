#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pre-commit.py — harness 强制闸门（确定性层）

强制两件事：
  1. **harness 同步**：有代码变更时，progress.md 与 lessons.md 必须同步更新且同一 commit
  2. **反占位符**：提交的代码里不得有 TODO / 桩实现 / 假数据

由 `.githooks/pre-commit` 调用（bash 包装，负责找到 Python 解释器）。
豁免：`HARNESS_SKIP=1 git commit ...`（仅限纯格式化 / 纯测试数据等无功能逻辑的变更）

退出码：0 放行 / 1 阻断 / 2 内部错误（也阻断，不静默）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# 有代码变更时【强制必更】的文件（相对仓库根）
MANDATORY_ON_CODE = [
    ".harness/state/progress.md",
    ".harness/memory/lessons.md",
]

# 模板仓库特殊模式：本仓库是**被复制出去的源头**，其 state/lessons 文件必须保持
# 未填写的脚手架原样（否则新项目一生成就带着本仓库的历史日志）。
# 因此在这里改成强制更新 MAINTENANCE.md —— 模板自身的变更史记在维护规范里。
#
# 识别方式：存在 .harness/TEMPLATE-REPO 标记文件（只在本仓库有，new_project 不复制它）。
TEMPLATE_MARKER = ".harness/TEMPLATE-REPO"
MANDATORY_ON_CODE_TEMPLATE = [
    ".harness/MAINTENANCE.md",
]

# 判定为"非代码"的前缀/后缀（这些变更不触发强制）
NON_CODE_PREFIXES = (".harness/", "docs/", ".githooks/", "scripts/")
NON_CODE_SUFFIXES = (".md", ".lock", "-lock.json")


def git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[!] git 调用失败: {e}", file=sys.stderr)
        return 2, ""


def repo_root() -> str | None:
    code, out = git("rev-parse", "--show-toplevel")
    return out.strip() if code == 0 and out.strip() else None


def load_code_root(root: str) -> str | None:
    return (load_config(root) or {}).get("code_root")


def load_config(root: str) -> dict | None:
    """读 .harness/config.json。失败返回 None（调用方须显式处理，不静默）。"""
    cfg = os.path.join(root, ".harness", "config.json")
    if not os.path.isfile(cfg):
        return None
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def is_code_file(rel: str) -> bool:
    if any(rel.startswith(p) for p in NON_CODE_PREFIXES):
        return False
    if rel.endswith(NON_CODE_SUFFIXES):
        return False
    return True


def main() -> int:
    if os.environ.get("HARNESS_SKIP"):
        print("[harness] HARNESS_SKIP=1 —— 已豁免本次检查。")
        return 0

    root = repo_root()
    if not root:
        print("[!] 不是 git 仓库，无法执行 harness 检查。", file=sys.stderr)
        return 2

    code, out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    if code != 0:
        return 2
    staged = [ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()]
    if not staged:
        return 0

    code_files = [f for f in staged if is_code_file(f)]
    if not code_files:
        return 0  # 纯 harness / 文档变更，放行

    problems: list[str] = []

    # ── 检查 1：harness 强制必更 ──
    # 模板仓库走特殊清单（见 MANDATORY_ON_CODE_TEMPLATE 的说明），
    # 否则会逼着模板去污染它自己的脚手架文件。
    if os.path.isfile(os.path.join(root, TEMPLATE_MARKER)):
        mandatory = MANDATORY_ON_CODE_TEMPLATE
        hint = "（模板仓库模式：本次变更请在 MAINTENANCE.md §变更史记一行）"
    else:
        mandatory = MANDATORY_ON_CODE
        hint = "（progress.md 追加一行变更日志；若本次踩了新坑则更新 lessons.md）"

    missing = [m for m in mandatory if m not in staged]
    if missing:
        problems.append(
            "harness 未同步：以下文件必须与代码在同一个 commit 中更新\n"
            + "".join(f"      · {m}\n" for m in missing)
            + "      "
            + hint
        )

    # ── 检查 2：反占位符 ──
    code_root = load_code_root(root)
    if code_root:
        target = os.path.join(root, code_root)
        if os.path.isdir(target):
            guard = os.path.join(root, "scripts", "no_placeholder_guard.py")
            if os.path.isfile(guard):
                try:
                    r = subprocess.run(
                        [sys.executable, guard, code_root, "--fail-on", "error"],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    if r.returncode not in (0,):
                        tail = (r.stdout or r.stderr or "").strip()
                        problems.append(
                            "反占位符检查未通过（no_placeholder_guard）\n"
                            + (tail[-1200:] if tail else f"      退出码 {r.returncode}")
                        )
                except (OSError, subprocess.SubprocessError) as e:
                    problems.append(f"反占位符检查执行失败（视为未通过）: {e}")
            else:
                problems.append("缺少 scripts/no_placeholder_guard.py —— 门禁不完整")
        else:
            problems.append(
                f"config.json 的 code_root 指向的目录不存在: {code_root}\n"
                f"      请修正 .harness/config.json"
            )
    else:
        print(
            "[harness] 提示：未配置 .harness/config.json 的 code_root，跳过反占位符检查。"
        )

    # ── 检查 3：代码规范（只跑暂存文件）──
    # 为什么不跑全量：全量 lint 动辄几十秒，人会用 --no-verify 绕开，
    # 门禁就自我否定了（S13：降噪即有效性）。只查暂存文件，通常 <10s。
    # 工具没装时 quality.py 会显式跳过（不是报错），所以这里只关心它是否"失败"。
    quality = os.path.join(root, "scripts", "quality.py")
    if os.path.isfile(quality):
        try:
            r = subprocess.run(
                [sys.executable, quality, "--staged"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if r.returncode not in (0,):
                tail = (r.stdout or r.stderr or "").strip()
                problems.append(
                    "代码规范检查未通过（quality.py --staged）\n"
                    + (tail[-1200:] if tail else f"      退出码 {r.returncode}")
                    + "\n      自动修复: python scripts/quality.py --fix"
                )
        except subprocess.TimeoutExpired:
            problems.append("代码规范检查超时（180s）—— 请缩小改动范围后重试")
        except (OSError, subprocess.SubprocessError) as e:
            problems.append(f"代码规范检查执行失败（视为未通过）: {e}")
    # 脚本不存在 = code-quality 模块未启用，静默跳过（可插拔：关掉的模块不该打扰）

    # ── 检查 4：证据门禁（防"只声明完成"）──
    # 触发条件精准：只在 status 文件被改动时跑。
    # 因为"把功能标成 completed"这个动作必然改 feature_list.json ——
    # 此时不校验证据，等于门禁形同虚设（此前就是这个状态：字段存在但没人核）。
    # 平时（改代码不改状态）不跑，避免每次提交都执行一遍证据命令。
    STATE_FILE = ".harness/state/feature_list.json"
    if STATE_FILE in staged:
        gate = os.path.join(root, "scripts", "evidence_gate.py")
        if os.path.isfile(gate):
            try:
                r = subprocess.run(
                    [sys.executable, gate, "--json"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if r.returncode != 0:
                    tail = (r.stdout or r.stderr or "").strip()
                    problems.append(
                        "证据门禁未通过（标记 completed 必须有可执行证据）\n"
                        + (tail[-1500:] if tail else f"      退出码 {r.returncode}")
                        + "\n      用法见 scripts/evidence_gate.py 头部说明"
                    )
            except subprocess.TimeoutExpired:
                problems.append(
                    "证据门禁超时（300s）—— 证据命令应当很快，请检查它是否在跑全套测试"
                )
            except (OSError, subprocess.SubprocessError) as e:
                problems.append(f"证据门禁执行失败（视为未通过）: {e}")
        else:
            # 模块未启用 → 但要提醒"状态文件被改了却没人核证据"这个事实
            print(
                "[harness] 提示：feature_list.json 已改动，但未启用证据门禁"
                "（scripts/evidence_gate.py 不存在）"
            )

    # ── 检查 5：接线检查（防"写了但没接上"）──
    # **默认就跑** —— 不再要求先配 entry。
    # 理由（实测）：原实现探测不到入口就退出 2，而新项目默认没配 entry，
    # 于是这个门禁**从不生效**，未集成的代码畅行无阻。
    # 现在 check_integration 在无入口时自动降级为「入度=0」判定，可以直接跑。
    # 配了 entry 就传（可达性分析更精确），没配就用降级模式。
    ci = os.path.join(root, "scripts", "check_integration.py")
    if os.path.isfile(ci):
        cfg_all = load_config(root) or {}
        integ = cfg_all.get("integration") or {}
        entry = integ.get("entry") if isinstance(integ, dict) else None
        allow = integ.get("allow_orphans") if isinstance(integ, dict) else None
        code_root_i = cfg_all.get("code_root") or "src"
        cmd_i = [sys.executable, ci, code_root_i]
        for e in entry if isinstance(entry, list) else ([entry] if entry else []):
            cmd_i += ["--entry", str(e)]
        for a in allow or []:
            cmd_i += ["--allow", str(a)]
        try:
            r = subprocess.run(
                cmd_i, cwd=root, capture_output=True, text=True, timeout=180
            )
            if r.returncode != 0:
                tail = (r.stdout or r.stderr or "").strip()
                problems.append(
                    "接线检查未通过（有模块写了但没被任何地方调用）\n"
                    + (tail[-1200:] if tail else f"      退出码 {r.returncode}")
                    + "\n      每个孤儿模块：接进调用链 / 删掉 / "
                    "或用 config.json 的 integration.allow_orphans 显式豁免"
                )
        except subprocess.TimeoutExpired:
            problems.append("接线检查超时（180s）")
        except (OSError, subprocess.SubprocessError) as e:
            problems.append(f"接线检查执行失败（视为未通过）: {e}")

    if not problems:
        print(
            "[harness] ✅ 检查通过（harness 已同步 + 无占位 + 代码规范 + 证据 + 接线）"
        )
        return 0

    print("\n" + "╔" + "═" * 62 + "╗")
    print("║" + " " * 14 + "harness 提交闸门 — 未通过" + " " * 22 + "║")
    print("╠" + "═" * 62 + "╣")
    for i, p in enumerate(problems, 1):
        print(f"║ {i}. ", end="")
        lines = p.split("\n")
        print(lines[0])
        for ln in lines[1:]:
            print("║    " + ln)
    print("╠" + "═" * 62 + "╣")
    print("║ 修复：补齐上面列出的项 → git add → 重新 commit           ║")
    print("║ 合法豁免（纯格式化/纯测试数据）：                        ║")
    print("║   HARNESS_SKIP=1 git commit ...                          ║")
    print("╚" + "═" * 62 + "╝\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
