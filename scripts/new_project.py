#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_project.py — 从 harness-template 初始化一个新项目

用途
----
把本模板变成你的项目骨架：复制结构 → 替换占位符 → 配 git hooks → 生成配置
→ 校验六层完整 → 打印「下一步该填什么」清单。

用法
----
    # 方式 A：模板已 clone 到目标位置，原地初始化
    git clone <template-url> my-project && cd my-project
    python scripts/new_project.py --name "MyProject" --stack next-ts --in-place

    # 方式 B：从模板目录生成到别处
    python scripts/new_project.py --name "MyProject" --stack python --target ../

参数
----
    --name      项目名（必需）
    --stack     技术栈预设：generic | next-ts | python | tauri   （默认 generic）
    --in-place  在当前目录初始化（复制结构但跳过已存在的 harness 文件）
    --target    目标父目录（生成 <target>/<name>）
    --yes       跳过交互确认

退出码
------
    0  成功（打印下一步清单）
    2  参数错误 / 目标已存在 / 复制失败
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date

VERSION = "1.1.0"

# 模块归属从共享清单读（单一真相源）—— init.py / new_project.py / harness_lint.py
# 必须认识同一份模块表，否则"关不干净"或"关掉还被判死链"。详见 module_manifest.py。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from module_manifest import (  # noqa: E402
    ALWAYS_FILES as _MANIFEST_ALWAYS,
    EXCLUDE_FILES as _MANIFEST_EXCLUDE,
    MODULES as _MANIFEST_MODULES,
    PRESETS,
    module_deps,
    module_paths,
    norm_rel,
)

# 复制时排除
EXCLUDE_TOP = {"_selftest", ".git", "__pycache__", "node_modules", ".venv"}
EXCLUDE_EXT = {".pyc", ".pyo"}
# 模板维护者自己的文件，不随项目生成（审核稿/临时分析）
# 注意要写**完整相对路径**：早先只写 basename 时，memory 子目录下的同名文件
# 因为路径比较不匹配而逃过过滤，被复制进了新项目（交付泄漏，已修）。
EXCLUDE_FILES = {f.replace("\\", "/") for f in _MANIFEST_EXCLUDE} | {
    "_REVIEW-候选清单.md",
    # 模板仓库自身标记：生成的项目不是模板仓库，绝不能继承它。
    # 一旦泄漏，新项目的 pre-commit 会误判"我是模板"，从而不去强制 progress.md 更新。
    ".harness/TEMPLATE-REPO",
}

# ── 模块 → 它拥有的文件（关闭该模块则不复制这些文件）──
# 铁律：**关掉的模块不留残骸** —— 生成后删除会漏（人和 Agent 都会漏），
# 残留文件会误导接手者「以为那层检查还在跑」。详见 .harness/MODULES.md
MODULE_PATHS = module_paths()
MODULE_DEPS = module_deps()

# 技术栈预设：code_root + commands
STACKS = {
    "generic": {
        "code_root": "src",
        "commands": {},
    },
    "next-ts": {
        "code_root": ".",
        "commands": {
            "typecheck": "npm run typecheck",
            "lint": "npm run lint",
            "test": "npx vitest run",
        },
        "tech_stack": "Next.js + React + TypeScript + Vitest",
    },
    "python": {
        "code_root": "src",
        "commands": {
            "lint": "ruff check .",
            "test": "pytest -q",
        },
        "tech_stack": "Python + pytest + ruff",
    },
    "tauri": {
        "code_root": "src",
        "commands": {
            "typecheck": "npm run typecheck",
            "test": "npx vitest run",
        },
        "tech_stack": "Tauri 2 + React + TypeScript + Rust",
    },
}

# 占位符 → 自动填充值（未列出的保留，最后汇总成"待填清单"）  guard:allow
AUTO_FILL_KEYS = {"PROJECT_NAME", "DATE", "BRANCH", "TECH_STACK", "CODE_ROOT", "TEST_COMMAND"}

PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

TEXT_EXT = {".md", ".json", ".py", ".sh", ".ps1", ".yml", ".yaml", ".toml", ".txt"}


def is_text(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in TEXT_EXT


def resolve_modules(preset_name: str | None, extra_off: list[str] | None = None
                    ) -> tuple[dict[str, bool], list[str]]:
    """按档位解析模块开关，自动补齐依赖。

    返回 (开关表, 说明列表)。依赖被自动启用时会记入说明（不静默）。
    """
    if preset_name:
        on = set(PRESETS[preset_name])
    else:
        on = set(PRESETS["full"])
    for m in (extra_off or []):
        on.discard(m)

    raw = {m: (m in on) for m in MODULE_DEPS}
    notes: list[str] = []
    changed = True
    while changed:
        changed = False
        for m, v in list(raw.items()):
            if not v:
                continue
            for dep in MODULE_DEPS.get(m, []):
                if not raw.get(dep, True):
                    raw[dep] = True
                    notes.append(f"{m} 依赖 {dep} → 自动启用 {dep}")
                    changed = True

    # 关掉的模块要提示（这些都是"少了那道保险"）
    for m, v in sorted(raw.items()):
        if not v:
            notes.append(f"已关闭模块 {m}（其检查与文件都不生成）")
    return raw, notes


def should_copy(rel_path: str, modules: dict[str, bool]) -> bool:
    """按模块开关决定某个相对路径是否复制。

    路径写法见 module_manifest.norm_rel —— 用 lstrip("./") 会把 `.harness`
    的前导点吃掉，导致所有点目录匹配失败（真实事故，勿重犯）。
    """
    norm = norm_rel(rel_path)
    for mod, paths in MODULE_PATHS.items():
        if not modules.get(mod, True):
            for p in paths:
                pn = norm_rel(p)
                if pn.endswith("/"):
                    if norm.startswith(pn) or ("/" + pn) in ("/" + norm):
                        return False
                elif norm == pn or norm.endswith("/" + pn):
                    return False
    return True


def copy_tree(src: str, dst: str, modules: dict[str, bool] | None = None) -> tuple[int, int]:
    """复制模板结构，返回 (复制的文件数, 跳过的文件数)。"""
    count = 0
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(src):
        rel_dir = os.path.relpath(dirpath, src)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_TOP]
        else:
            dirnames[:] = [d for d in dirnames
                           if d not in EXCLUDE_TOP and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in EXCLUDE_EXT:
                continue
            s = os.path.join(dirpath, fn)
            rel = os.path.relpath(s, src).replace("\\", "/")
            # 排除比对用**完整相对路径**：早先用 basename 比对时，
            # `.harness/memory/_REVIEW-候选清单.md` 这种子目录下的评审稿
            # 因路径不匹配而逃过过滤，被复制进新项目（交付泄漏，已修）。
            if rel in EXCLUDE_FILES or fn in EXCLUDE_FILES:
                continue
            if modules is not None and not should_copy(rel, modules):
                skipped += 1
                continue
            d = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(s, d)
            count += 1
    return count, skipped


def substitute(root: str, mapping: dict) -> tuple[int, dict]:
    """替换占位符。返回 (替换次数, 剩余占位符 -> 出现的文件列表)。"""
    replaced = 0
    remaining: dict[str, list] = {}
    # 本脚本源码里含有占位符字面量（用作提示文案），扫描时必须跳过自己，  guard:allow
    # 否则"待填清单"里会混入自身，制造噪音。
    self_name = os.path.basename(__file__)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_TOP and not d.startswith(".")]
        for fn in filenames:
            if fn == self_name:
                continue
            p = os.path.join(dirpath, fn)
            if not is_text(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            if "{{" not in content:
                continue

            def repl(m):
                nonlocal replaced
                key = m.group(1)
                # {{XXX}} 是"元语法"——文档里用它表示"占位符长什么样"，  guard:allow
                # 不是待填项。漏掉这层过滤会让待填清单混进噪音。
                if re.fullmatch(r"X+", key):
                    return m.group(0)
                if key in mapping:
                    replaced += 1
                    return mapping[key]
                rel = os.path.relpath(p, root).replace("\\", "/")
                remaining.setdefault(key, [])
                if rel not in remaining[key]:
                    remaining[key].append(rel)
                return m.group(0)

            new = PLACEHOLDER_RE.sub(repl, content)
            if new != content:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new)
    return replaced, remaining


def prune_module_refs(root: str, modules: dict[str, bool]) -> int:
    """清理"被关闭模块"在存活文档里的引用行。

    为什么必须做：关掉模块后，MAINTENANCE.md / README.md / AGENTS.md 里
    仍会引用那些被删掉的文件 —— 实测产生 **44 条死链警告**，新项目一开工
    就被噪音淹没（这正是模板要避免的"降噪即有效性"反面）。

    策略（保守，只动明确指向已关闭模块文件的行）：
      · 表格行：整行删除
      · 列表行（`- [xxx](path)`）：整行删除
      · 其他行含引用：加行内 `lint-ignore` 并追加注记，不删（避免破坏上下文）
    """
    targets: set[str] = set()
    for mod, on in modules.items():
        if on:
            continue
        for p in MODULE_PATHS.get(mod, []):
            if p.endswith("/"):
                targets.add(p.rstrip("/") + "/")
            else:
                targets.add(p)
    if not targets:
        return 0

    # 只处理"活文档"（harness 治理文档 + 根 AGENTS/README），不碰归档区
    scan = []
    for rel in ("AGENTS.md", "README.md"):
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            scan.append(p)
    for sub in (".harness", "docs"):
        base = os.path.join(root, sub)
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in {"archive", "decisions"}]
            for f in fn:
                if f.lower().endswith((".md", ".markdown")):
                    scan.append(os.path.join(dp, f))

    changed_files = 0
    for p in scan:
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.read().splitlines(keepends=True)
        except (OSError, UnicodeDecodeError):
            continue

        out: list[str] = []
        removed = 0
        for ln in lines:
            hit = any(t in ln for t in targets)
            if not hit:
                out.append(ln)
                continue
            stripped = ln.lstrip()
            is_row = stripped.startswith("|")
            is_list_item = stripped.startswith(("-", "*", "+"))
            if is_row or is_list_item:
                # 表格行/列表项：整行移除（这是"引用已关闭模块"的常规形态）
                removed += 1
                continue
            # 行内引用：加豁免标记并注明，不删（保留上下文可读性）
            if "lint-ignore" not in ln:
                out.append(ln.rstrip("\n") + "  <!-- lint-ignore: 对应模块未启用 -->\n")
            else:
                out.append(ln)

        if removed:
            new = "".join(out)
            # 连续空行压缩（删行后常见）
            new = re.sub(r"\n{3,}", "\n\n", new)
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new)
                changed_files += 1
            except OSError as e:
                # 不静默：清理失败会让文档残留指向已关闭模块的引用（死链），
                # 必须让用户知道哪个文件没清理成功。
                print(f"[!] 引用清理失败（该文件仍可能含死链）: "
                      f"{os.path.relpath(p, root)} — {e}", file=sys.stderr)
    return changed_files


def setup_git(root: str) -> list[str]:
    msgs = []
    try:
        if not os.path.isdir(os.path.join(root, ".git")):
            r = subprocess.run(["git", "init"], cwd=root, capture_output=True,
                               text=True, timeout=60)
            msgs.append("git init: " + ("成功" if r.returncode == 0 else f"失败 {r.stderr.strip()}"))
        r = subprocess.run(["git", "config", "core.hooksPath", ".githooks"],
                           cwd=root, capture_output=True, text=True, timeout=30)
        msgs.append("hooksPath: " + (".githooks 已配置" if r.returncode == 0
                                     else f"配置失败 {r.stderr.strip()}"))
    except (OSError, subprocess.SubprocessError) as e:
        msgs.append(f"git 操作失败（可手动执行）: {e}")
    return msgs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="从 harness-template 初始化新项目")
    ap.add_argument("--name", required=True, help="项目名")
    ap.add_argument("--stack", default="generic", choices=list(STACKS))
    ap.add_argument("--preset", default="full", choices=sorted(PRESETS),
                    help="模块档位: minimal | standard | full（默认 full）")
    ap.add_argument("--disable", default=None,
                    help="额外关闭模块，逗号分隔（如 routing,integration-check）")
    ap.add_argument("--in-place", action="store_true", help="在当前目录原地初始化")
    ap.add_argument("--target", default=None, help="目标父目录（生成 <target>/<name>）")
    ap.add_argument("--yes", action="store_true", help="跳过确认")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    template_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    modules, mod_notes = resolve_modules(
        args.preset, [s.strip() for s in (args.disable or "").split(",") if s.strip()])

    if args.in_place:
        dst = template_root
    else:
        if not args.target:
            print("[!] 非 --in-place 模式必须提供 --target", file=sys.stderr)
            return 2
        dst = os.path.abspath(os.path.join(args.target, args.name))
        if os.path.exists(dst) and os.listdir(dst):
            print(f"[!] 目标目录已存在且非空: {dst}", file=sys.stderr)
            return 2
        os.makedirs(dst, exist_ok=True)
        n, sk = copy_tree(template_root, dst, modules)
        print(f"复制 {n} 个文件 → {dst}" + (f"（按模块开关跳过 {sk} 个）" if sk else ""))

    preset = STACKS[args.stack]
    mapping = {
        "PROJECT_NAME": args.name,
        "DATE": date.today().isoformat(),
        "BRANCH": "main",
        "TECH_STACK": preset.get("tech_stack", "{{TECH_STACK}}"),
        "CODE_ROOT": preset["code_root"],
        "TEST_COMMAND": preset["commands"].get("test", "<你的测试命令>"),
    }

    replaced, remaining = substitute(dst, mapping)
    print(f"替换占位符 {replaced} 处")

    # 生成 config.json
    cfg_dir = os.path.join(dst, ".harness")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg = {
        "project": args.name,
        "stack": args.stack,
        "preset": args.preset,
        "modules": modules,
        "code_root": preset["code_root"],
        "commands": preset["commands"],
        "baseline": {"test": ""},
    }
    cfg_path = os.path.join(cfg_dir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"生成 .harness/config.json（stack={args.stack}, preset={args.preset}）")

    if mod_notes:
        print("\n模块开关说明：")
        for n in mod_notes:
            print(f"  · {n}")

    for m in setup_git(dst):
        print(f"  {m}")

    # 清理被关闭模块在存活文档里的引用（否则产生大量死链警告）
    pruned = prune_module_refs(dst, modules)
    if pruned:
        print(f"  清理 {pruned} 个文档中指向已关闭模块的引用行")

    # 打印结果
    print("\n" + "=" * 60)
    print(f"✅ 项目骨架已就绪：{args.name}  ({dst})")
    print("=" * 60)

    if remaining:
        print("\n⚠️  以下占位符需要你人工填写（这是真正决定项目质量的部分）：\n")
        for key in sorted(remaining):
            files = remaining[key][:3]
            more = "" if len(remaining[key]) <= 3 else f" 等 {len(remaining[key])} 处"
            print(f"  · {{{{{key}}}}}   出现于: {', '.join(files)}{more}")
        print("\n  最关键的三个（填完它们，Agent 才真正知道项目是什么）：")
        print("    1. {{PROJECT_ONE_LINER}} — 一句话说清项目是什么")
        print("    2. {{CORE_JOURNEY}}       — 核心用户旅程（产品可用 = 这条路径跑得通）")
        print("    3. {{ARCH_TREE}}          — 代码目录骨架")
        print("\n  填完跑: python scripts/init.py")

    print("\n下一步：")
    print("  1. 填写上面列出的占位符（至少 PROJECT_ONE_LINER / CORE_JOURNEY / ARCH_TREE）")
    print("  2. python scripts/init.py    确认环境健康")
    print("  3. 把 AGENTS.md 交给 Agent：『读 AGENTS.md，按 §2 启动路径 Orient』")
    print("  4. 第一个任务务必是 Phase 0 Walking Skeleton（见 .harness/planning/SPEC-TEMPLATE.md）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
