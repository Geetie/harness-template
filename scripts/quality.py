#!/usr/bin/env python3
"""代码质量统一入口 —— lint / format / typecheck 的接线层。

为什么需要它
------------
此前 `config.json.commands` 是个平铺 dict，`init.py` 逐个 `shell=True` 跑，
在真实项目里会踩三个坑：

1. **工具没装 vs 工具报错，现象一样**（都是非零退出码）。
   → 于是"ESLint 没装"被显示成"质量命令失败"，新人以为自己代码有问题。
   **降级路径必须满足主契约**（S9）：没装要显式说"未安装，已跳过"，不是报错。
2. **lint 与 format 混为一谈**。`--fix` 会改文件，`--check` 不该改。
   平铺 dict 分不清哪个能自动修，于是 CI 里误跑 `--fix` 改掉别人的代码。
3. **pre-commit 全量跑 lint 太慢**，会被人 `--no-verify` 绕过去（门禁自我否定，S13）。
   → 提交时只跑**暂存文件**。

配置
----
写在 `.harness/config.json` 的 `quality` 段（由 `new_project.py` 按 stack 生成）：

    "quality": {
      "typecheck":    "npm run typecheck",
      "lint":         "npm run lint",
      "lint_fix":     "npm run lint -- --fix",
      "format_check": "npx prettier --check .",
      "format_fix":   "npx prettier --write ."
    }

用法
----
    python scripts/quality.py --doctor     # 体检：工具装没装、配置齐不齐
    python scripts/quality.py --check      # 只检查，不改任何文件（CI / 日常）
    python scripts/quality.py --fix        # 自动修复（本地用）
    python scripts/quality.py --staged     # 只对 git 暂存文件（pre-commit 用）
    python scripts/quality.py --json       # 机器可读

退出码
------
    0  通过 / 全部跳过（且跳过原因已打印）
    1  有问题（lint 不过 / 格式不对）
    2  配置错误

**不静默原则**：每一条结果都要带原因。
"跳过"必须说明是**未配置**还是**工具未安装**——这两者对用户的含义完全不同。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness_version import TEMPLATE_VERSION as VERSION  # noqa: E402

# 每步的超时（秒）。pre-commit 里要快，否则人们会 --no-verify 绕开（S13）。
TIMEOUT_STAGED = 120
TIMEOUT_FULL = 600

# --fix 才会跑的键（会改文件，绝不能在 check/预提交里跑）
FIX_ONLY_KEYS = ("lint_fix", "format_fix")
# --check 跑的键（只读）
CHECK_KEYS = ("typecheck", "lint", "format_check")

TOOL_HINT = {
    "eslint": "npm i -D eslint  （或 npx eslint --init 生成配置）",
    "prettier": "npm i -D prettier",
    "ruff": "pip install ruff",
    "black": "pip install black",
    "tsc": "npm i -D typescript",
    "golangci-lint": "https://golangci-lint.run/usage/install/",
    "checkstyle": "需要 Java + checkstyle jar",
}


def load_cfg(root: str) -> tuple[dict, str]:
    p = os.path.join(root, ".harness", "config.json")
    if not os.path.isfile(p):
        return {}, f"找不到 {p}"
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        return {}, f"config.json 不是合法 JSON: {e}"
    except OSError as e:
        return {}, f"config.json 读取失败: {e}"
    if not isinstance(cfg, dict):
        return {}, "config.json 顶层不是对象"
    return cfg, ""


def first_tool(cmd: str) -> str:
    """从命令里猜主程序名，用于"是否安装"的判断与提示。"""
    parts = (cmd or "").split()
    for tok in parts:
        if tok in ("npx", "npm", "yarn", "pnpm", "run", "--", "-m"):
            continue
        base = os.path.basename(tok)
        if base:
            return base
    return ""


def tool_available(cmd: str) -> tuple[bool, str]:
    """判断命令的主程序是否可用。

    `npx xxx` 这类不能只看 `shutil.which("npx")` —— npx 存在不代表包已装。
    所以：命令以 npx 开头时，额外用 `npx --no-install xxx --version` 探测。
    """
    if not cmd:
        return False, "命令为空"
    parts = cmd.split()
    if not parts:
        return False, "命令为空"

    if parts[0] in ("npx", "npm", "yarn", "pnpm"):
        # 取包体名（npx <pkg> ... / npm run <script>）
        if parts[0] == "npm" and len(parts) > 1 and parts[1] == "run":
            # npm run <script> —— 脚本是否存在取决于 package.json，直接认为可用
            return True, ""
        pkg = parts[1] if len(parts) > 1 else ""
        if not pkg:
            return False, "无法解析包名"
        try:
            r = subprocess.run(
                [parts[0], "--no-install", pkg, "--version"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode == 0:
                return True, ""
        except subprocess.TimeoutExpired:
            # 不写 `except: pass` —— 那会把"探测超时"和"确实没装"混成同一种结果，
            # 用户看到的都是"未安装"，真实原因被吞掉（S14）。
            return False, f"{pkg} 探测超时（60s）"
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"{pkg} 探测失败: {e.__class__.__name__}"
        return False, f"{pkg} 未安装"

    exe = parts[0]
    if shutil.which(exe):
        return True, ""
    return False, f"{exe} 不在 PATH 中"


def run_one(cmd: str, root: str, timeout: int) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            cmd, cwd=root, shell=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"超时（{timeout}s）—— 命令太慢，考虑缩小范围"
    except OSError as e:
        return False, f"执行失败: {e}"
    tail = ""
    lines = (r.stdout or r.stderr or "").strip().splitlines()
    if lines:
        tail = lines[-1][:200]
    return (r.returncode == 0), f"exit={r.returncode}" + (f" | {tail}" if tail else "")


def staged_files(root: str, exts: tuple[str, ...]) -> list[str]:
    """git 暂存区里、且仍存在的文件（过滤到指定扩展名）。"""
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[!] 读取 git 暂存区失败: {e}", file=sys.stderr)
        return []
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        f = line.strip().replace("\\", "/")
        if not f or not os.path.isfile(os.path.join(root, f)):
            continue
        if exts and not f.lower().endswith(exts):
            continue
        out.append(f)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="代码质量统一入口（lint/format/typecheck）"
    )
    ap.add_argument("--root", default=None, help="项目根（默认当前目录）")
    ap.add_argument(
        "--doctor", action="store_true", help="体检：工具装没装、配置齐不齐"
    )
    ap.add_argument("--check", action="store_true", help="只检查，不改文件")
    ap.add_argument("--fix", action="store_true", help="自动修复（会改文件）")
    ap.add_argument(
        "--staged", action="store_true", help="只对 git 暂存文件（pre-commit）"
    )
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or os.getcwd())
    cfg, err = load_cfg(root)
    if err:
        print(f"[!] {err}", file=sys.stderr)
        return 2

    quality = cfg.get("quality") or {}
    if not isinstance(quality, dict) or not quality:
        msg = (
            "未配置 quality 段 —— 代码规范工具没接进来。\n"
            "  在 .harness/config.json 里加:\n"
            '    "quality": {"lint": "...", "format_check": "...", "format_fix": "..."}\n'
            "  或重新生成项目时选一个技术栈（--stack next-ts / python 等）。"
        )
        print(f"[!] {msg}", file=sys.stderr)
        return 2

    results: list[dict] = []

    # ── 体检 ──
    if args.doctor:
        print(f"\n代码质量体检 — {os.path.basename(root)}")
        print("=" * 60)
        for key in ("typecheck", "lint", "lint_fix", "format_check", "format_fix"):
            cmd = quality.get(key)
            if not cmd:
                print(f"  ⚪ {key:<14} 未配置")
                results.append({"step": key, "status": "unconfigured"})
                continue
            ok, why = tool_available(cmd)
            tool = first_tool(cmd)
            if ok:
                print(f"  ✅ {key:<14} {cmd}")
                results.append({"step": key, "status": "ok", "cmd": cmd})
            else:
                hint = TOOL_HINT.get(tool, "")
                print(f"  ⚠️  {key:<14} 跳过 — {why}")
                if hint:
                    print(f"      安装: {hint}")
                results.append(
                    {
                        "step": key,
                        "status": "missing_tool",
                        "cmd": cmd,
                        "reason": why,
                        "hint": hint,
                    }
                )
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    # ── 执行 ──
    if args.staged:
        keys = ("lint", "format_check")
        timeout = TIMEOUT_STAGED
        files = staged_files(
            root, (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".java")
        )
        if not files:
            if not args.json:
                print("暂存区没有需要检查的源码文件 —— 跳过。")
            return 0
    elif args.fix:
        keys = FIX_ONLY_KEYS
        timeout = TIMEOUT_FULL
        files = []
    else:
        keys = CHECK_KEYS
        timeout = TIMEOUT_FULL
        files = []

    any_fail = False
    for key in keys:
        cmd = quality.get(key)
        if not cmd:
            if not args.json:
                print(f"  ⚪ {key}: 未配置（跳过）")
            results.append({"step": key, "status": "unconfigured"})
            continue

        ok, why = tool_available(cmd)
        if not ok:
            # 降级必须显式（铁律②）：没装 ≠ 代码有问题
            if not args.json:
                print(f"  ⚠️  {key}: 跳过 — {why}（工具未安装，不等于代码有问题）")
            results.append({"step": key, "status": "skipped", "reason": why})
            continue

        real = cmd
        if files:
            # 只喂暂存文件；命令里若已含 "." 就替换掉，否则追加
            quoted = " ".join(f'"{f}"' for f in files)
            real = cmd.replace(" .", " " + quoted) if " ." in cmd else f"{cmd} {quoted}"

        ok, detail = run_one(real, root, timeout)
        mark = "✅" if ok else "❌"
        if not args.json:
            print(f"  {mark} {key}: {real[:80]}")
            if not ok:
                print(f"      {detail}")
        results.append(
            {
                "step": key,
                "status": "pass" if ok else "fail",
                "cmd": real,
                "detail": detail,
            }
        )
        if not ok:
            any_fail = True

    if args.json:
        print(
            json.dumps(
                {"root": root, "results": results, "exit_code": 1 if any_fail else 0},
                ensure_ascii=False,
                indent=2,
            )
        )
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
