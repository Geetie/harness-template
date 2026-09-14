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
  "modules": {
    "instructions": true, "state": true, "verification": true,
    "memory": true, "delivery": true, "routing": false,
    "decisions": true, "planning": true,
    "placeholder-guard": true, "integration-check": false
  },
  "code_root": "src",
  "commands": {
    "typecheck": "npm run typecheck",
    "lint": "npm run lint",
    "test": "npx vitest run"
  },
  "baseline": { "test": "0 failed" }
}

模块可插拔
----------
modules 里某项为 false → 该模块负责的检查被跳过，并**打印 [SKIP] 原因**。
未出现的模块视为 true（向后兼容）。
依赖关系见 .harness/MODULES.md。

用法
----
    python scripts/init.py                 # 全部检查
    python scripts/init.py --skip-commands # 只查结构与状态（快）
    python scripts/init.py --modules       # 打印当前模块开关表
    python scripts/init.py --preset full   # 按档位检查（不写配置，仅本次生效）
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

# ── 模块定义（可插拔）──
# 为什么需要：模板此前是焊死的六层，小项目被迫背全套餐。
# 现在每个模块可独立启停，缺失时**显式降级、不报错**。
# 模块归属只从共享清单读（单一真相源），三个脚本必须认识同一份模块表。
# 详见 .harness/MODULES.md 与 scripts/module_manifest.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from module_manifest import (  # noqa: E402
    PRESETS,
    always_files,
    module_deps,
    module_layers,
    module_required,
    resolve_modules as _resolve_from_manifest,
)

# 版本来自单一真相源（此前各脚本各写一份，实测已漂移：lint 1.1.1 / init 1.1.0）
from harness_version import TEMPLATE_VERSION as VERSION  # noqa: E402

MODULE_DEPS = module_deps()
MODULE_LAYERS = module_layers()
_MODULE_REQUIRED = module_required()

# 模块 → 它负责的必需文件（关闭该模块则这些文件不检查）
MODULE_FILES: dict[str, list[tuple[str, str]]] = {
    mod: [(MODULE_LAYERS[mod], f) for f in files]
    for mod, files in _MODULE_REQUIRED.items()
}

# 模块 → 它负责的脚本（单独列出只为在报告中归组；实际文件来自 REQUIRED）
MODULE_SCRIPTS: dict[str, list[str]] = {
    "verification": ["scripts/init.py", "scripts/harness_lint.py"],
    "state": ["scripts/state_health.py"],
    "placeholder-guard": ["scripts/no_placeholder_guard.py"],
    "integration-check": ["scripts/check_integration.py"],
}

# 总是检查的（不属于任何可关模块的总览文件）
ALWAYS_FILES = always_files()


def resolve_modules(cfg: dict | None) -> tuple[dict[str, bool], list[str]]:
    """从 config 解析模块开关，隐式补齐依赖。

    返回 (开关表, 告警列表)。
    **依赖自动补齐但必须告警** —— 静默补齐会让配置与实际行为不一致。
    实际逻辑委托给 module_manifest.resolve_modules（单一真相源），
    这里只负责把 config 形态转成它要的入参。
    """
    explicit = (cfg or {}).get("modules")
    if explicit is None:
        # 老项目无 modules 字段 → 全开（向后兼容）
        return {m: True for m in MODULE_DEPS}, []
    off = {m for m in MODULE_DEPS if not bool(explicit.get(m, True))}
    on, warns = _resolve_from_manifest(enabled_off=off)
    return on, warns


# 状态文件体积上限（与 state_health.py 保持一致；超限 → 状态文件正在变成 Agent 读不完的档案）
STATE_LIMITS = {
    "AGENTS.md": (16 * 1024, 150),
    ".harness/state/progress.md": (32 * 1024, 300),
    ".harness/state/session-handoff.md": (16 * 1024, 200),
    ".harness/state/feature_list.json": (64 * 1024, None),
}


def build_required(root: str, modules: dict[str, bool]) -> tuple[list, list[str]]:
    """按模块开关生成必需文件清单。

    返回 ([(层, 路径)], [跳过说明])。
    **每个被跳过的模块都要留下可打印的原因** —— 静默跳过等于假装检查过。

    去重：MODULE_FILES（来自 module_manifest.MODULE_REQUIRED）与 MODULE_SCRIPTS
    会有交集（脚本既在模块必需清单里、又在脚本分组里），叠加后同一文件会被检查两次，
    输出里出现重复的 ✅ 行（真实事故）。按路径去重，保持首次出现的顺序。
    """
    files: list[tuple[str, str]] = list(ALWAYS_FILES)
    seen: set[str] = {rel for _, rel in files}
    skipped: list[str] = []

    for mod, on in modules.items():
        entries = list(MODULE_FILES.get(mod, [])) + [
            (MODULE_LAYERS.get(mod, "③验证层"), s) for s in MODULE_SCRIPTS.get(mod, [])
        ]
        entries = [(layer, rel) for layer, rel in entries if rel not in seen]
        if not entries:
            continue
        if on:
            for layer, rel in entries:
                if rel in seen:
                    continue
                seen.add(rel)
                files.append((layer, rel))
        else:
            skipped.append(f"{mod}（{len(entries)} 项检查）")

    return files, skipped


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


def check_structure(root: str, required: list) -> list[tuple[str, str, bool, str]]:
    """返回 [(层, 文件, 是否存在, 说明)]"""
    out = []
    for layer, rel in required:
        p = os.path.join(root, rel)
        ok = os.path.isfile(p)
        out.append((layer, rel, ok, "" if ok else "缺失"))
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
            out.append(
                ("feature_list.json 合法 JSON", False, f"已损坏（并发写常见）: {e}")
            )
    else:
        out.append(("feature_list.json 合法 JSON", False, "文件不存在"))
    return out


def check_hooks(root: str) -> list[tuple[str, bool, str]]:
    out = []
    try:
        r = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        val = r.stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        out.append(("git hooksPath 已配置", False, f"无法读取 git 配置: {e}"))
        return out
    if val == ".githooks":
        out.append(("git hooksPath 已配置", True, ".githooks"))
    else:
        out.append(
            (
                "git hooksPath 已配置",
                False,
                f"当前为 {val or '(未设置)'}，强制机制全部失效。"
                f"执行: git config core.hooksPath .githooks",
            )
        )
    return out


def check_state_limits(root: str) -> list[tuple[str, bool, str]]:
    """状态文件是否膨胀超限。

    只增不减的状态文件最终会变成 Agent 读不动也读不完的档案——
    那是发生在磁盘上的 context rot。这里做最轻量的体积/行数把关。
    """
    over: list[str] = []
    for rel, (max_bytes, max_lines) in STATE_LIMITS.items():
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        size = os.path.getsize(p)
        if size > max_bytes:
            over.append(f"{rel} {size // 1024}KB>{max_bytes // 1024}KB")
            continue
        if max_lines:
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    n = sum(1 for _ in f)
            except OSError:
                continue
            if n > max_lines:
                over.append(f"{rel} {n}行>{max_lines}行")

    if over:
        return [
            (
                "状态文件未超限",
                False,
                "；".join(over) + " → 跑 python scripts/state_health.py --archive",
            )
        ]
    return [("状态文件未超限", True, "")]


def run_commands(root: str, cfg: dict) -> list[tuple[str, bool, str]]:
    out = []
    cmds = (cfg or {}).get("commands", {})
    if not cmds:
        out.append(
            ("质量命令", True, "未配置（跳过）—— 在 .harness/config.json 里配 commands")
        )
        return out
    for name, cmd in cmds.items():
        try:
            r = subprocess.run(
                cmd, cwd=root, shell=True, capture_output=True, text=True, timeout=900
            )
            ok = r.returncode == 0
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


def check_quality_tools(root: str, cfg: dict) -> list[tuple[str, bool, str]]:
    """代码规范工具是否就位（ESLint/Prettier/ruff…）。

    这里**只体检不执行**（执行交给 `quality.py --check`），
    因为体检要快、要能在没装任何工具的环境里跑。

    **不算失败**：工具没装只是"少一道保险"，不该让 init 报红 ——
    否则新 clone 的仓库永远不健康，人就会忽略这个检查（降噪即有效性）。
    但会明确写清"未安装 + 怎么装"，不允许静默。
    """
    out: list[tuple[str, bool, str]] = []
    quality = (cfg or {}).get("quality") or {}
    if not quality:
        out.append(
            (
                "代码规范工具",
                True,
                "未配置 quality 段（跳过）—— "
                "改 .harness/config.json 或换 --stack 重生成",
            )
        )
        return out

    try:
        import quality as Q
    except ImportError:
        out.append(("代码规范工具", True, "scripts/quality.py 缺失（模块未完整安装）"))
        return out

    missing = []
    configured = 0
    for key in ("typecheck", "lint", "format_check"):
        cmd = quality.get(key)
        if not cmd:
            continue
        configured += 1
        try:
            ok, why = Q.tool_available(cmd)
        except (OSError, subprocess.SubprocessError) as e:
            # 探测本身出错也要说清（不静默），但不算失败
            missing.append(f"{key}: 探测失败 {e.__class__.__name__}")
            continue
        if not ok:
            missing.append(f"{key}（{why}）")

    if not configured:
        out.append(("代码规范工具", True, "quality 段为空（跳过）"))
    elif missing:
        out.append(
            (
                "代码规范工具",
                True,
                f"⚠ {len(missing)} 项工具未安装，提交时会跳过: " + "; ".join(missing),
            )
        )
    else:
        out.append(("代码规范工具", True, f"{configured} 项已就绪"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="harness 环境健康检查")
    ap.add_argument("--root", default=None, help="仓库根（默认自动推断）")
    ap.add_argument("--skip-commands", action="store_true", help="跳过质量命令（快检）")
    ap.add_argument("--modules", action="store_true", help="只打印当前模块开关表")
    ap.add_argument(
        "--preset",
        default=None,
        choices=sorted(PRESETS),
        help="按档位覆盖模块开关（仅本次生效，不写配置）",
    )
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

    if args.preset:
        # 档位覆盖：显式给出全部模块的开关，覆盖配置
        cfg = dict(cfg or {})
        cfg["modules"] = {m: (m in PRESETS[args.preset]) for m in MODULE_DEPS}

    modules, mod_warnings = resolve_modules(cfg)

    if args.modules:
        print(f"\n模块开关表 — {root}\n" + "=" * 50)
        for m in sorted(MODULE_DEPS):
            on = modules.get(m, True)
            deps = ",".join(MODULE_DEPS[m]) or "—"
            print(f"  {'✅ 开' if on else '❌ 关'}  {m:<20} 依赖: {deps}")
        enabled = sum(1 for v in modules.values() if v)
        print(f"\n  {enabled}/{len(modules)} 个模块启用")
        print("  详见 .harness/MODULES.md")
        return 0

    required, skipped = build_required(root, modules)
    for w in mod_warnings:
        print(f"[!] 模块依赖: {w}", file=sys.stderr)
    for s in skipped:
        # 显式声明跳过原因（铁律：静默跳过 = 假装检查过）
        print(f"[SKIP] 模块未启用，跳过检查: {s}", file=sys.stderr)

    results = []
    results += [(c, n, ok, d) for (c, n, ok, d) in check_structure(root, required)]
    if modules.get("state", True):
        results += [("②状态层", n, ok, d) for (n, ok, d) in check_state(root)]
        results += [("②状态层", n, ok, d) for (n, ok, d) in check_state_limits(root)]
    else:
        print("[SKIP] state 模块未启用，跳过状态文件完整性与体积检查", file=sys.stderr)
    results += [("③验证层", n, ok, d) for (n, ok, d) in check_hooks(root)]
    if modules.get("code-quality", True):
        results += [
            ("③验证层", n, ok, d) for (n, ok, d) in check_quality_tools(root, cfg or {})
        ]
    else:
        print("[SKIP] code-quality 模块未启用，跳过代码规范工具检查", file=sys.stderr)
    if not args.skip_commands:
        results += [
            ("③验证层", n, ok, d) for (n, ok, d) in run_commands(root, cfg or {})
        ]

    failures = [r for r in results if not r[2]]
    exit_code = 1 if failures else 0

    if args.json:
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "root": root.replace("\\", "/"),
                    "total": len(results),
                    "failed": len(failures),
                    "exit_code": exit_code,
                    "checks": [
                        {"category": c, "name": n, "ok": ok, "detail": d}
                        for (c, n, ok, d) in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
