#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init.py — 环境健康检查

用途
----
每次开发前跑一次，确认三件事：**结构完整 / 状态可读 / 基线是绿的**。
对应 harness 第三层（验证层）。新 Agent 上手第 8 步、提交前、接手他人工作时都要跑。

检查项
------
1. 结构：harness 六层必需文件是否齐全（缺哪个打印哪个）
2. 状态：feature_list.json 是否仍是合法 JSON（抗损坏规则）
3. 钩子：git core.hooksPath 是否指向 .githooks（否则强制机制全部失效）
4. 命令：类型检查 / lint / 测试（从 .harness/config.json 读取，逐条跑并报告退出码）

配置 .harness/config.json（可选，不存在则跳过第 4 项）
------------------------------------------------------
{
  "code_root": "src",
  "commands": {
    "typecheck": "npm run typecheck",
    "lint": "npm run lint",
    "test": "npx vitest run"
  },
  "baseline": { "test": "0 failed" }
}

用法
----
    python scripts/init.py                 # 全部检查
    python scripts/init.py --skip-commands # 只查结构与状态（快）
    python scripts/init.py --json

退出码
------
    0  全部通过
    1  有检查项未通过 → 先修再开工
    2  配置错误（config.json 非法 JSON 等）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

VERSION = "1.0.0"

# 六层必需文件（相对仓库根）
REQUIRED_FILES = [
    ("①指令层", "AGENTS.md"),
    ("⑥交付层", ".harness/delivery/README.md"),
    ("⑥交付层", ".harness/delivery/DoD-TEMPLATE.md"),
    ("⑥交付层", ".harness/delivery/acceptance.md"),
    ("⑥交付层", ".harness/delivery/hardening-checklist.md"),
    ("②状态层", ".harness/state/progress.md"),
    ("②状态层", ".harness/state/feature_list.json"),
    ("②状态层", ".harness/state/session-handoff.md"),
    ("④记忆层", ".harness/memory/lessons.md"),
    ("④记忆层", ".harness/memory/failure-modes.md"),
    ("⑤技能层", ".harness/routing/ROUTER.md"),
    ("①计划", ".harness/planning/CONSTITUTION.md"),
    ("①计划", ".harness/planning/SPEC-TEMPLATE.md"),
    ("总览", ".harness/README.md"),
    ("维护", ".harness/MAINTENANCE.md"),
]

REQUIRED_SCRIPTS = [
    "scripts/no_placeholder_guard.py",
    "scripts/check_integration.py",
    "scripts/init.py",
]


def find_repo_root() -> str:
    """从脚本位置反推仓库根（scripts/ 的上一级）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def load_config(root: str) -> tuple[dict | None, str | None]:
    cfg_path = os.path.join(root, ".harness", "config.json")
    if not os.path.isfile(cfg_path):
        return None, None
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f".harness/config.json 不是合法 JSON: {e}"


def check_structure(root: str) -> list[tuple[str, str, bool, str]]:
    """返回 [(层, 文件, 是否存在, 说明)]"""
    out = []
    for layer, rel in REQUIRED_FILES:
        p = os.path.join(root, rel)
        ok = os.path.isfile(p)
        out.append((layer, rel, ok, "" if ok else "缺失"))
    for rel in REQUIRED_SCRIPTS:
        p = os.path.join(root, rel)
        ok = os.path.isfile(p)
        out.append(("③验证层", rel, ok, "" if ok else "缺失"))
    return out


def check_state(root: str) -> list[tuple[str, bool, str]]:
    out = []
    fl = os.path.join(root, ".harness", "state", "feature_list.json")
    if os.path.isfile(fl):
        try:
            with open(fl, "r", encoding="utf-8") as f:
                json.load(f)
            out.append(("feature_list.json 合法 JSON", True, ""))
        except json.JSONDecodeError as e:
            out.append(("feature_list.json 合法 JSON", False,
                        f"已损坏（并发写常见）: {e}"))
    else:
        out.append(("feature_list.json 合法 JSON", False, "文件不存在"))
    return out


def check_hooks(root: str) -> list[tuple[str, bool, str]]:
    out = []
    try:
        r = subprocess.run(["git", "config", "--get", "core.hooksPath"],
                           cwd=root, capture_output=True, text=True, timeout=15)
        val = r.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        out.append(("git hooksPath 已配置", False, f"无法读取 git 配置: {e}"))
        return out
    if val == ".githooks":
        out.append(("git hooksPath 已配置", True, ".githooks"))
    else:
        out.append(("git hooksPath 已配置", False,
                    f"当前为 {val or '(未设置)'}，强制机制全部失效。"
                    f"执行: git config core.hooksPath .githooks"))
    return out


def run_commands(root: str, cfg: dict) -> list[tuple[str, bool, str]]:
    out = []
    cmds = (cfg or {}).get("commands", {})
    if not cmds:
        out.append(("质量命令", True, "未配置（跳过）—— 在 .harness/config.json 里配 commands"))
        return out
    for name, cmd in cmds.items():
        try:
            r = subprocess.run(cmd, cwd=root, shell=True,
                               capture_output=True, text=True, timeout=900)
            ok = (r.returncode == 0)
            tail = (r.stdout or r.stderr or "").strip().splitlines()
            detail = f"exit={r.returncode}"
            if tail:
                detail += " | " + tail[-1][:160]
            out.append((f"{name}: {cmd}", ok, detail))
        except subprocess.TimeoutExpired:
            out.append((f"{name}: {cmd}", False, "超时（900s）"))
        except OSError as e:
            out.append((f"{name}: {cmd}", False, f"执行失败: {e}"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="harness 环境健康检查")
    ap.add_argument("--root", default=None, help="仓库根（默认自动推断）")
    ap.add_argument("--skip-commands", action="store_true", help="跳过质量命令（快检）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else find_repo_root()
    if not os.path.isdir(root):
        print(f"[!] 仓库根不存在: {root}", file=sys.stderr)
        return 2

    cfg, cfg_err = load_config(root)
    if cfg_err:
        print(f"[!] {cfg_err}", file=sys.stderr)
        return 2

    results = []
    results += [(c, n, ok, d) for (c, n, ok, d) in check_structure(root)]
    results += [( "②状态层", n, ok, d) for (n, ok, d) in check_state(root)]
    results += [("③验证层", n, ok, d) for (n, ok, d) in check_hooks(root)]
    if not args.skip_commands:
        results += [("③验证层", n, ok, d) for (n, ok, d) in run_commands(root, cfg or {})]

    failures = [r for r in results if not r[2]]
    exit_code = 1 if failures else 0

    if args.json:
        print(json.dumps({
            "version": VERSION, "root": root.replace("\\", "/"),
            "total": len(results), "failed": len(failures),
            "exit_code": exit_code,
            "checks": [{"category": c, "name": n, "ok": ok, "detail": d}
                       for (c, n, ok, d) in results],
        }, ensure_ascii=False, indent=2))
        return exit_code

    print(f"\nharness 环境健康检查 — {root}\n" + "=" * 60)
    cur = None
    for cat, name, ok, detail in results:
        if cat != cur:
            print(f"\n[{cat}]")
            cur = cat
        mark = "✅" if ok else "❌"
        line = f"  {mark} {name}"
        if detail:
            line += f"  — {detail}"
        print(line)

    print("\n" + "=" * 60)
    if failures:
        print(f"❌ {len(failures)}/{len(results)} 项未通过 —— 先修再开工。")
        print("\n最常见的一条：hooksPath 没配 → git config core.hooksPath .githooks")
    else:
        print(f"✅ 全部 {len(results)} 项通过。可以开工。")
    print(f"\n退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
