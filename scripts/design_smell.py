#!/usr/bin/env python3
"""技术债信号检测（design smell）。

⚠️ **先读这一段，否则会误用本脚本**
---------------------------------
本脚本**不能**判断代码是否符合 SOLID，也不能判断抽象是否合理。
它只检测**可统计的技术债信号**（文件多大、有没有环、嵌套多深）。

    "这个文件 800 行"  → 是信号（SM001）
    "这个类职责是否单一" → 机器判断不了，只有人能

所以输出一律是 **warn（信号）而非 error（违规）**：
每个信号都可能是合理的（生成代码、配置表、算法密集型文件）。
**看到信号先判断，别无脑改。** —— 无脑改会把设计改坏。

真正让设计变好的是**写代码之前的判断**，见
`.harness/design/DESIGN-PRINCIPLES.md` 与 SPEC 模板的「设计决策四问」。

用法
----
    python scripts/design_smell.py [路径...]        # 默认 src/ 或 code_root
    python scripts/design_smell.py src/ --json
    python scripts/design_smell.py src/ --fail-on warn   # CI 里当门禁（慎用）

退出码
------
    0  没有信号 / 只有信号且不 --fail-on
    1  有信号且 --fail-on 命中
    2  路径不存在 / 无可读文件

**不静默**：解析失败的文件会单独列出（读不到 ≠ 没问题，见 S14）。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness_version import TEMPLATE_VERSION as VERSION  # noqa: E402

# 阈值：宁可宽松。误报会让人关掉这个检查，那就等于没有检查（S13 降噪即有效性）。
MAX_LINES = 500
MAX_TOP_DEFS = 20
MAX_NESTING = 4
MAX_PARAMS = 5
MAX_CLASS_METHODS = 15

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             "dist", "build", ".next", "coverage", "_selftest"}
PY_EXT = (".py",)
TS_EXT = (".ts", ".tsx", ".js", ".jsx")


class Signal:
    __slots__ = ("sid", "file", "line", "detail")

    def __init__(self, sid: str, file: str, line: int, detail: str):
        self.sid = sid
        self.file = file
        self.line = line
        self.detail = detail

    def as_dict(self) -> dict:
        return {"id": self.sid, "file": self.file, "line": self.line,
                "detail": self.detail}


def iter_source_files(paths: list[str]) -> tuple[list[str], list[str]]:
    """收集源码文件。返回 (文件列表, 跳过说明)。"""
    files: list[str] = []
    notes: list[str] = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
            continue
        if not os.path.isdir(p):
            notes.append(f"{p} 不存在 —— 跳过")
            continue
        for dp, dn, fn in os.walk(p):
            dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
            for f in fn:
                if f.endswith(PY_EXT + TS_EXT):
                    files.append(os.path.join(dp, f))
        if not files:
            notes.append(f"{p} 下没有找到源码文件")
    return sorted(set(files)), notes


def _nesting_depth_py(tree: ast.AST) -> list[tuple[int, int]]:
    """用 ast 算**逻辑**嵌套深度（if/for/while/try/with 的嵌套层数）。

    ⚠️ 不要用物理缩进算：格式化工具（ruff/black/prettier）会把长调用折成
    多行，续行的缩进虚高 —— 实测 359 条"嵌套过深"里**几乎全是续行误报**。
    这种噪音会让人直接关掉这个检查（S13 降噪即有效性）。
    """
    out: list[tuple[int, int]] = []

    def walk(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            d = depth
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                  ast.Try, ast.With, ast.AsyncWith)):
                d = depth + 1
                if d > MAX_NESTING:
                    out.append((getattr(child, "lineno", 0), d))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef)):
                # 函数/类开启新的一层计数起点，但从父级深度继续
                d = depth
            walk(child, d)

    walk(tree, 0)
    return out


def scan_python(path: str, rel: str) -> tuple[list[Signal], str | None]:
    """Python：用 ast 精确分析（不用正则，正则查不出结构）。"""
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except OSError as e:
        return [], f"{rel} 读取失败: {e.__class__.__name__}"
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [], f"{rel} 语法错误（无法分析）: {e.msg} @ 行 {e.lineno}"

    out: list[Signal] = []
    lines = src.splitlines()

    # SM001 god-module
    if len(lines) > MAX_LINES:
        out.append(Signal("SM001", rel, 0,
                          f"{len(lines)} 行（阈值 {MAX_LINES}）—— 多半承担了多个职责"))
    top_defs = [n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    if len(top_defs) > MAX_TOP_DEFS:
        out.append(Signal("SM001", rel, 0,
                          f"顶层定义 {len(top_defs)} 个（阈值 {MAX_TOP_DEFS}）"))

    for node in ast.walk(tree):
        # SM004 long-params
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            n = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
            if n > MAX_PARAMS:
                out.append(Signal("SM004", rel, node.lineno,
                                  f"{node.name}() 有 {n} 个参数（阈值 {MAX_PARAMS}）"
                                  f" —— 考虑参数对象"))
        # SM005 god-class
        if isinstance(node, ast.ClassDef):
            methods = [n for n in node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if len(methods) > MAX_CLASS_METHODS:
                out.append(Signal("SM005", rel, node.lineno,
                                  f"类 {node.name} 有 {len(methods)} 个方法"
                                  f"（阈值 {MAX_CLASS_METHODS}）"))

    # SM003 deep-nesting：按**逻辑**嵌套（ast），不按物理缩进
    for lineno, depth in _nesting_depth_py(tree):
        out.append(Signal("SM003", rel, lineno,
                          f"控制流嵌套 {depth} 层（阈值 {MAX_NESTING}）"
                          f" —— 考虑提取函数或早返回"))
    return out, None


def scan_ts(path: str, rel: str) -> tuple[list[Signal], str | None]:
    """TS/JS：正则近似（不引第三方解析器，保持零依赖）。

    精度低于 Python 分支，所以阈值更宽松、只报最明确的信号。
    """
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except OSError as e:
        return [], f"{rel} 读取失败: {e.__class__.__name__}"

    out: list[Signal] = []
    if len(lines) > MAX_LINES:
        out.append(Signal("SM001", rel, 0,
                          f"{len(lines)} 行（阈值 {MAX_LINES}）—— 多半承担了多个职责"))

    exports = sum(1 for ln in lines if re.match(r"\s*export\s", ln))
    if exports > MAX_TOP_DEFS:
        out.append(Signal("SM001", rel, 0,
                          f"export {exports} 个（阈值 {MAX_TOP_DEFS}）"))

    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        # 长参数（单行函数签名里数逗号，粗略）
        m = re.search(r"function\s+\w+\s*\(([^)]*)\)", ln)
        if m:
            params = [p for p in m.group(1).split(",") if p.strip()]
            if len(params) > MAX_PARAMS:
                out.append(Signal("SM004", rel, i,
                                  f"参数 {len(params)} 个（阈值 {MAX_PARAMS}）"))
        indent = len(ln) - len(ln.lstrip())
        if indent // 2 > MAX_NESTING + 2:  # TS 常用 2 空格缩进
            out.append(Signal("SM003", rel, i, "嵌套过深 —— 考虑提取函数"))
    return out, None


def build_import_graph(files: list[str]) -> dict[str, set[str]]:
    """构建模块间依赖图（只处理 Python，TS 的路径别名太多、易错报）。"""
    graph: dict[str, set[str]] = {}
    py = [f for f in files if f.endswith(PY_EXT)]
    mods = {}
    for f in py:
        rel = os.path.relpath(f).replace("\\", "/")
        key = rel[:-3].replace("/", ".")
        if key.endswith(".__init__"):
            key = key[: -len(".__init__")]
        mods[key] = f
    for key, f in mods.items():
        graph.setdefault(key, set())
        try:
            src = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target = node.module
                if target in mods and target != key:
                    graph[key].add(target)
            elif isinstance(node, ast.Import):
                for al in node.names:
                    if al.name in mods and al.name != key:
                        graph[key].add(al.name)
    return graph


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """DFS 找环。返回环列表（每个环是模块名列表）。"""
    cycles: list[list[str]] = []
    seen_cycle: set[frozenset[str]] = set()
    visiting: list[str] = []
    visited: set[str] = set()

    def dfs(node: str) -> None:
        if node in visiting:
            idx = visiting.index(node)
            cyc = visiting[idx:]
            key = frozenset(cyc)
            if key not in seen_cycle:
                seen_cycle.add(key)
                cycles.append(list(cyc))
            return
        if node in visited:
            return
        visiting.append(node)
        for nxt in sorted(graph.get(node, ())):
            dfs(nxt)
        visiting.pop()
        visited.add(node)

    for n in sorted(graph):
        dfs(n)
    return cycles


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="技术债信号检测（不是 SOLID 合规检查）")
    ap.add_argument("paths", nargs="*", default=None, help="要扫描的路径（默认 src/）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on", choices=["none", "warn"], default="none",
                    help="warn=有信号就非零退出（CI 用，慎用）")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    paths = args.paths
    if not paths:
        # 默认取 config.json 的 code_root，没有就 src
        cfg_root = "src"
        try:
            cfgp = os.path.join(".harness", "config.json")
            if os.path.isfile(cfgp):
                cfg = json.load(open(cfgp, encoding="utf-8"))
                cfg_root = cfg.get("code_root") or "src"
        except (OSError, json.JSONDecodeError):
            pass
        paths = [cfg_root]

    files, notes = iter_source_files(paths)
    if not files:
        print("[!] 没有可扫描的源码文件。", file=sys.stderr)
        for n in notes:
            print(f"    · {n}", file=sys.stderr)
        return 2

    signals: list[Signal] = []
    failures: list[str] = []
    for f in files:
        rel = os.path.relpath(f).replace("\\", "/")
        if f.endswith(PY_EXT):
            s, err = scan_python(f, rel)
        else:
            s, err = scan_ts(f, rel)
        signals.extend(s)
        if err:
            failures.append(err)

    # SM002 循环依赖（Python）
    graph = build_import_graph(files)
    for cyc in find_cycles(graph):
        signals.append(Signal(
            "SM002", " → ".join(cyc) + " → " + cyc[0], 0,
            "模块循环依赖 —— 依赖方向错了，必然耦合；抽第三方或改用事件/回调"))

    by_id: dict[str, list[Signal]] = {}
    for s in signals:
        by_id.setdefault(s.sid, []).append(s)

    if args.json:
        print(json.dumps({
            "version": VERSION,
            "scanned_files": len(files),
            "signals": [s.as_dict() for s in signals],
            "parse_failures": failures,
        }, ensure_ascii=False, indent=2))
        return 1 if (signals and args.fail_on == "warn") else 0

    print(f"\n技术债信号检测 — 扫描 {len(files)} 个文件")
    print("=" * 64)
    if not signals:
        print("\n✅ 未发现技术债信号。")
    else:
        print(f"\n⚠️  {len(signals)} 条信号（**不是违规**，是「这里值得看一眼」）：\n")
        names = {
            "SM001": "god-module", "SM002": "circular-import",
            "SM003": "deep-nesting", "SM004": "long-params", "SM005": "god-class",
        }
        for sid in sorted(by_id):
            bucket = by_id[sid]
            print(f"--- {sid} {names.get(sid, '')} ({len(bucket)}) ---")
            for s in bucket[:10]:
                loc = f"{s.file}:{s.line}" if s.line else s.file
                print(f"    · {loc}")
                print(f"      {s.detail}")
            if len(bucket) > 10:
                print(f"    … 另有 {len(bucket) - 10} 条")

    if failures:
        # 不静默：解析失败的文件没被真正分析，必须让用户知道
        print(f"\n⚠️  {len(failures)} 个文件未能分析（其结果未纳入统计）:")
        for s in failures[:10]:
            print(f"    · {s}")

    print("\n" + "=" * 64)
    print("注意：本脚本只查**可统计的信号**，不能判断设计好坏。")
    print("      跑绿 ≠ 设计好；真正的判断见 .harness/design/DESIGN-PRINCIPLES.md")
    return 1 if (signals and args.fail_on == "warn") else 0


if __name__ == "__main__":
    sys.exit(main())
