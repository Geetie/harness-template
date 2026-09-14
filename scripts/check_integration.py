#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_integration.py — 集成检查（Wiring Failure 静态嫌疑犯检测）

用途
----
从主流程入口出发做引用可达性分析，找出**写了但从未被任何地方调用**的模块。
这类"孤儿模块"是 Wiring Failure（模块都写好了但没集成）最典型的静态信号。

⚠️ 能力边界（必须知道，否则会误用本工具）
本工具**只能**发现"完全没被调用"的模块。下面两类必须靠行为验证，本工具抓不到：
  · 注册了但从不触发（幽灵订阅）
  · 触发了但写到没人读的地方（空执行）
配套行为探针见 `.harness/routing/capabilities/integration-check.md` 的三个探针。
**工具 + 探针，缺一不可。**

用法
----
    python scripts/check_integration.py <code_root>
    python scripts/check_integration.py src --entry src/main.tsx --entry src/app
    python scripts/check_integration.py . --alias @=src --json
    python scripts/check_integration.py src --include-tests

退出码（显式声明，绝不静默）
----------------------------
    0  未发现孤儿模块（但可能仍有 WARN，会打印出来）
    1  发现孤儿模块 → 阻断交付，需人工确认每个是"待接入"还是"死代码"
    2  用法错误 / 路径不存在 / 扫不到源文件 / 找不到入口 → 阻断（不静默吞掉）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict, field

VERSION = "1.0.0"

# 忽略目录（与 no_placeholder_guard 保持一致）
IGNORE_DIRS = {
    "node_modules",
    "bower_components",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "out",
    "target",
    "bin",
    "obj",
    "coverage",
    "htmlcov",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".git",
    ".idea",
    ".vscode",
    "site-packages",
    "vendor",
    "third_party",
}

CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
}

# 各语言的 import 语句模式（够用即可，不追求 AST 级精确）
IMPORT_PATTERNS = [
    # JS/TS: import ... from "x" / import "x" / export ... from "x" / require("x") / import("x")
    re.compile(r"""(?:from|import|require)\s*\(?\s*['"]([^'"]+)['"]"""),
    # Python: from x import y / import x
    re.compile(r"^\s*from\s+([\.\w]+)\s+import", re.MULTILINE),
    re.compile(r"^\s*import\s+([\.\w]+)", re.MULTILINE),
    # Go
    re.compile(r"^\s*(?:import\s+)?\"([\w\.\-/]+)\"", re.MULTILINE),
]

# 测试文件判定（默认排除，可用 --include-tests 纳入）
TEST_PATTERNS = [
    re.compile(r"[._-](test|spec)\.[jt]sx?$", re.I),
    re.compile(r"^test_.*\.py$", re.I),
    re.compile(r".*_test\.py$", re.I),
    re.compile(r"(^|[\\/])(__tests__|tests?|conftest)([\\/]|$)", re.I),
]

# 自动探测的入口（按优先级）
AUTO_ENTRY_CANDIDATES = [
    "src/main.tsx",
    "src/main.ts",
    "src/index.tsx",
    "src/index.ts",
    "src/App.tsx",
    "src/App.ts",
    "app/main.py",
    "main.py",
    "app.py",
    "src/app.py",
    "src/main.go",
    "main.go",
    "src/main.rs",
    "src/lib.rs",
    "index.js",
    "index.ts",
    "src/index.js",
    "app/page.tsx",
    "app/layout.tsx",
    "src-tauri/src/main.rs",
    "cmd/main.go",
]


@dataclass
class Orphan:
    file: str
    bytes: int
    reason: str  # 为什么判定为孤儿（显式声明，不静默）
    imported_by: list = field(default_factory=list)  # 反向：谁（本该）引用它


@dataclass
class Result:
    root: str
    entries: list
    scanned: int
    reachable: int
    orphans: list
    warnings: list


def is_test_file(path: str) -> bool:
    norm = path.replace("\\", "/")
    return any(p.search(norm) for p in TEST_PATTERNS)


def collect_sources(root: str, include_tests: bool, exts: set) -> list[str]:
    """收集代码根下的源文件。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")
        ]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in exts:
                continue
            full = os.path.join(dirpath, fn)
            if not include_tests and is_test_file(full):
                continue
            out.append(full)
    return out


def find_entries(root: str, explicit: list[str] | None) -> tuple[list[str], str]:
    """确定入口集合。返回 (入口文件列表, 来源说明)。"""
    if explicit:
        entries = []
        for e in explicit:
            p = e if os.path.isabs(e) else os.path.join(root, e)
            if os.path.isdir(p):
                entries.extend(collect_sources(p, False, CODE_EXTENSIONS))
            elif os.path.isfile(p):
                entries.append(p)
            else:
                print(f"[!] 指定的入口不存在，已跳过: {e}", file=sys.stderr)
        if entries:
            return sorted(set(entries)), "由 --entry 指定"
        return [], "--entry 指定的路径全部无效"

    for cand in AUTO_ENTRY_CANDIDATES:
        p = os.path.join(root, cand.replace("/", os.sep))
        if os.path.isfile(p):
            return [p], f"自动探测到入口 {cand}"
    return [], "未能自动探测到入口（请用 --entry 指定）"


def parse_alias_map(pairs: list[str], root: str) -> list[tuple[str, str]]:
    """解析别名，如 `@=src` → 前缀 `@/` 映射到 <root>/src。"""
    out = []
    for pair in pairs:
        if "=" not in pair:
            print(f"[!] 别名格式应为 <前缀>=<目录>，已忽略: {pair}", file=sys.stderr)
            continue
        prefix, target = pair.split("=", 1)
        prefix = prefix.rstrip("/")
        out.append((prefix, os.path.join(root, target.replace("/", os.sep))))
    # 默认别名：@ -> src（若存在），否则 @ -> root
    if not any(p == "@" for p, _ in out):
        src_dir = os.path.join(root, "src")
        out.append(("@", src_dir if os.path.isdir(src_dir) else root))
    return out


def resolve_spec(
    spec: str, from_file: str, root: str, aliases: list[tuple[str, str]], exts: set
) -> list[str]:
    """把一个 import 说明符解析成候选文件路径（可能多个，也可能解析不到）。"""
    spec = spec.strip()
    if not spec or spec.startswith("data:") or spec.startswith("http"):
        return []

    cands: list[str] = []

    if spec.startswith("."):
        base_dir = os.path.dirname(from_file)
        base = os.path.normpath(os.path.join(base_dir, spec.replace("/", os.sep)))
    else:
        base = None
        # 先试别名
        for prefix, target in aliases:
            if spec == prefix:
                base = target
                break
            if spec.startswith(prefix + "/"):
                base = os.path.join(
                    target, spec[len(prefix) + 1 :].replace("/", os.sep)
                )
                break
        if base is None:
            # 退化为"从根解析"：去 @ 前缀后按相对根处理
            cleaned = spec.lstrip("@~/")
            base = os.path.join(root, cleaned.replace("/", os.sep))

    # 候选：base 本身（带已知扩展） / base + 各扩展 / base/index + 各扩展
    tried = [base]
    for e in exts:
        tried.append(base + e)
    for e in exts:
        tried.append(os.path.join(base, "index" + e))
    # Python 包：base 当成模块路径（点转斜杠）
    if "." in os.path.basename(base) and not os.path.splitext(base)[1]:
        tried.append(base.replace(".", os.sep) + ".py")

    seen = set()
    for t in tried:
        t = os.path.normpath(t)
        if t in seen:
            continue
        seen.add(t)
        if os.path.isfile(t) and os.path.splitext(t)[1].lower() in exts:
            cands.append(t)
    return cands


def extract_imports(filepath: str) -> list[str]:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return []
    specs = []
    for pat in IMPORT_PATTERNS:
        for m in pat.finditer(content):
            s = m.group(1).strip()
            if s:
                specs.append(s)
    return specs


def analyze(
    root: str,
    entries: list[str],
    sources: list[str],
    aliases: list[tuple[str, str]],
    exts: set,
) -> tuple[set, list]:
    """从入口 BFS，返回 (可达文件集合, 未解析的 import 说明符列表)。"""
    source_set = set(os.path.normpath(s) for s in sources)
    reachable: set[str] = set()
    unresolved: list[str] = []
    queue = [os.path.normpath(e) for e in entries if os.path.normpath(e) in source_set]

    # 入口本身算可达
    for e in entries:
        n = os.path.normpath(e)
        if n in source_set:
            reachable.add(n)

    while queue:
        cur = queue.pop()
        for spec in extract_imports(cur):
            targets = resolve_spec(spec, cur, root, aliases, exts)
            if not targets:
                unresolved.append(f"{os.path.basename(cur)} -> {spec}")
                continue
            for t in targets:
                t = os.path.normpath(t)
                if t in source_set and t not in reachable:
                    reachable.add(t)
                    queue.append(t)
    return reachable, unresolved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="集成检查：找出写了但从未被调用的孤儿模块（Wiring Failure 静态嫌疑犯）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="⚠️ 只能发现『完全没被调用』的模块；"
        "『注册了不触发』与『写了没人读』必须靠行为探针，见 integration-check.md",
    )
    ap.add_argument("root", help="代码根目录")
    ap.add_argument(
        "--entry",
        action="append",
        default=[],
        help="主流程入口（文件或目录），可重复；不指定则自动探测",
    )
    ap.add_argument(
        "--alias",
        action="append",
        default=[],
        help="路径别名，格式 <前缀>=<目录>，如 @=src；可重复",
    )
    ap.add_argument(
        "--include-tests", action="store_true", help="把测试文件也纳入分析（默认排除）"
    )
    ap.add_argument(
        "--ext", action="append", default=[], help="额外纳入的扩展名（如 .vue），可重复"
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"[!] 代码根目录不存在: {root}", file=sys.stderr)
        return 2

    exts = set(CODE_EXTENSIONS) | {
        e if e.startswith(".") else "." + e for e in args.ext
    }

    sources = collect_sources(root, args.include_tests, exts)
    if not sources:
        print(
            "[!] 未扫描到任何源文件 —— 这本身就是异常，请检查 root / 扩展名配置。",
            file=sys.stderr,
        )
        return 2

    entries, entry_note = find_entries(root, args.entry or None)
    if not entries:
        print(
            f"[!] 找不到主流程入口（{entry_note}）。"
            f"没有入口就无法判断可达性，请用 --entry 指定。",
            file=sys.stderr,
        )
        return 2

    aliases = parse_alias_map(args.alias, root)
    reachable, unresolved = analyze(root, entries, sources, aliases, exts)

    source_set = set(os.path.normpath(s) for s in sources)
    entry_set = set(os.path.normpath(e) for e in entries)
    orphan_paths = sorted(source_set - reachable - entry_set)

    orphans = []
    for p in orphan_paths:
        try:
            size = os.path.getsize(p)
        except OSError:
            size = -1
        rel = os.path.relpath(p, root).replace("\\", "/")
        orphans.append(
            Orphan(
                file=rel,
                bytes=size,
                reason="从主流程入口出发的引用可达性分析未覆盖到该文件",
            )
        )

    warnings = []
    if unresolved:
        warnings.append(
            f"{len(unresolved)} 个 import 说明符无法解析为本地文件"
            f"（可能是第三方包、动态导入或别名未配置）→ 相关模块可能被误判为孤儿"
        )
    if not args.include_tests:
        warnings.append(
            "测试文件默认排除；若模块只被测试引用，本工具仍会判为孤儿（这通常是真问题）"
        )

    result = Result(
        root=root.replace("\\", "/"),
        entries=[os.path.relpath(e, root).replace("\\", "/") for e in entries],
        scanned=len(sources),
        reachable=len(reachable),
        orphans=[asdict(o) for o in orphans],
        warnings=warnings,
    )

    exit_code = 1 if orphans else 0

    if args.json:
        print(
            json.dumps(
                {
                    **asdict(result),
                    "entry_source": entry_note,
                    "unresolved_count": len(unresolved),
                    "exit_code": exit_code,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"\n代码根: {result.root}")
        print(f"入口来源: {entry_note}")
        print(f"入口: {', '.join(result.entries) if result.entries else '(无)'}")
        print(
            f"扫描源文件: {result.scanned}   可达: {result.reachable}   孤儿: {len(orphans)}\n"
        )

        if warnings:
            print("--- 说明 / 局限 ---")
            for w in warnings:
                print(f"  ⚠️  {w}")
            if unresolved:
                for u in unresolved[:10]:
                    print(f"      · {u}")
                if len(unresolved) > 10:
                    print(f"      · ... 还有 {len(unresolved) - 10} 条")
            print()

        if orphans:
            print(f"--- 孤儿模块（{len(orphans)}）---")
            for o in orphans:
                print(f"  ❌ {o.file}  ({o.bytes} bytes)")
                print(f"      ↳ {o.reason}")
            print("\n处置建议:")
            print("  1) 待接入 → 接入主流程，或明确登记为『待接入』并关联任务")
            print("  2) 死代码 → 删掉（留着会让人误以为功能已存在）")
            print("  3) 确实是入口/动态加载 → 用 --entry 或 --alias 补登记")
        else:
            print("✅ 通过：静态可达性分析未发现孤儿模块。")
            print(
                "   注意：这不等于集成没问题 —— 还需跑行为探针（write-read-reload / 让缺失层响亮失败 / 输出是否真的在变）。"
            )

        print(f"\n退出码: {exit_code}" + ("（阻断交付）" if exit_code else "（放行）"))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
