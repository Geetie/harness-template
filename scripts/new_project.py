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

VERSION = "1.0.0"

# 复制时排除
EXCLUDE_TOP = {"_selftest", ".git", "__pycache__", "node_modules", ".venv"}
EXCLUDE_EXT = {".pyc", ".pyo"}

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

# 占位符 → 自动填充值（未列出的保留，最后汇总成"待填清单"）
AUTO_FILL_KEYS = {"PROJECT_NAME", "DATE", "BRANCH", "TECH_STACK", "CODE_ROOT", "TEST_COMMAND"}

PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

TEXT_EXT = {".md", ".json", ".py", ".sh", ".ps1", ".yml", ".yaml", ".toml", ".txt"}


def is_text(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in TEXT_EXT


def copy_tree(src: str, dst: str) -> int:
    """复制模板结构，返回复制的文件数。"""
    count = 0
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
            rel = os.path.relpath(s, src)
            d = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(s, d)
            count += 1
    return count


def substitute(root: str, mapping: dict) -> tuple[int, dict]:
    """替换占位符。返回 (替换次数, 剩余占位符 -> 出现的文件列表)。"""
    replaced = 0
    remaining: dict[str, list] = {}
    # 本脚本源码里含有占位符字面量（用作提示文案），扫描时必须跳过自己，
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
    ap.add_argument("--in-place", action="store_true", help="在当前目录原地初始化")
    ap.add_argument("--target", default=None, help="目标父目录（生成 <target>/<name>）")
    ap.add_argument("--yes", action="store_true", help="跳过确认")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    template_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
        n = copy_tree(template_root, dst)
        print(f"复制 {n} 个文件 → {dst}")

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
        "code_root": preset["code_root"],
        "commands": preset["commands"],
        "baseline": {"test": ""},
    }
    cfg_path = os.path.join(cfg_dir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"生成 .harness/config.json（stack={args.stack}）")

    for m in setup_git(dst):
        print(f"  {m}")

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
