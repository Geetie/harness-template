#!/usr/bin/env python3
"""测试有效性审计（test audit）。

解决的问题
----------
**"测试跑绿了" 与 "测试能抓 bug" 是两件事。** 前者只证明测试执行了，
后者才证明它验证了行为。CI 通常只报告前者。

一手依据（可点开核实）
--------------------
Banik, Chowdhury & Shamim, *All Smoke, No Alarm: Oracle Signals in Agent-Authored
Test Code*, arXiv:2606.18168（arXiv Comments 字段：Accepted at the 8th IEEE
International Conference on Artificial Intelligence Testing, 2026）。
https://arxiv.org/abs/2606.18168

该文分析了 **86,156 个测试补丁 / 33,596 个 agent 提交的 PR / 2,807 个仓库**，
结论：**80.2% 的测试补丁含弱或不含显式 oracle 信号**；
强 oracle 率按 agent 从 18%（OpenAI Codex）到 67%（Claude Code）不等。

本脚本实现该文的 **8 类 oracle 分类法**（TABLE I 定义，逐字对照）：

    弱信号 W1  无断言                    weak
    弱信号 W2  只查存在/非空              weak
    弱信号 W3  只做布尔断言（不比值）      weak
    弱信号 W4  只验证 mock 调用           weak
    弱信号 W5  只做快照匹配               weak
    强信号 S1  值相等/比较                strong
    强信号 S2  错误、包含、类型检查        strong
    强信号 S3  两种以上不同强类型          strong

⚠️ **诚实边界（论文自己声明的局限，必须一并转达）**：
  1. 分类针对**语法信号**，不是语义。判为 S1 只说明存在相等性比较，
     **不说明比的是不是正确的属性**。
  2. 未覆盖隐式 oracle（如"崩溃即失败"、超时检测）。
  3. 因此本脚本输出是**信号**，不能证明测试无效 —— 需人工判断。
     与 `design_smell.py` 同一立场：**报出来的先看一眼，别无脑改。**

另外检测（论文之外，来自工程实践）
--------------------------------
- **孤儿测试**：测试文件对应的被测源码已不存在（架构变更/模块删除后遗留）
- 这是"测试在功能删除后依然通过"的常见成因之一

用法
----
    python scripts/test_audit.py                    # 扫描 tests/（或自动探测）
    python scripts/test_audit.py tests/ --json
    python scripts/test_audit.py --fail-on weak     # 弱 oracle 占比超阈值即非零退出
    python scripts/test_audit.py --threshold 0.5    # 弱 oracle 占比阈值（默认 0.8）

退出码
------
    0  通过（或只有信号且未 --fail-on）
    1  命中 --fail-on 阈值 / 有孤儿测试
    2  没有找到测试文件
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness_version import TEMPLATE_VERSION as VERSION  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────
# Oracle 信号分类（arXiv:2606.18168 TABLE I）
# ──────────────────────────────────────────────────────────────────────────
WEAK = ("W1", "W2", "W3", "W4", "W5")
STRONG = ("S1", "S2", "S3")

ORACLE_DESC = {
    "W1": "无断言 —— 只调用不验证",
    "W2": "只查存在/非空（assert x / assert x is not None）",
    "W3": "只做布尔断言，未比较具体值（assert ok == True）",
    "W4": "只验证 mock 被调用（mock.assert_called_once）",
    "W5": "只做快照匹配",
    "S1": "值相等/比较（assert got == expected）",
    "S2": "错误、包含或类型检查（pytest.raises / isinstance）",
    "S3": "两种以上不同强信号",
}

# 测试文件的路径特征（论文 §II-A 的筛选条件）
TEST_DIR_HINTS = ("test/", "tests/", "__tests__/", "testing/", "spec/")
TEST_FILE_HINTS = ("_test.", ".test.", ".spec.", "test_", "conftest")
PY_EXT = (".py",)
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs")

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "coverage",
    "_selftest",
    ".tox",
}


def is_test_file(rel: str) -> bool:
    r = rel.replace("\\", "/").lower()
    base = r.rsplit("/", 1)[-1]
    if any(h in r for h in TEST_DIR_HINTS):
        return not base.startswith("__")
    return any(h in base for h in TEST_FILE_HINTS)


def iter_test_files(paths: list[str]) -> tuple[list[str], list[str]]:
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
                fp = os.path.join(dp, f)
                rel = os.path.relpath(fp).replace("\\", "/")
                if f.endswith(PY_EXT + JS_EXT) and is_test_file(rel):
                    files.append(fp)
    return sorted(set(files)), notes


# ──────────────────────────────────────────────────────────────────────────
# Python：用 ast 精确分类（不用正则 —— 正则分不清 assert x 与 assert x == 1）
# ──────────────────────────────────────────────────────────────────────────
def _collect_asserts_py(node: ast.AST) -> list[ast.AST]:
    """收集函数体内所有断言节点（含 unittest 的 self.assertXxx 调用）。"""
    out: list[ast.AST] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Assert):
            out.append(n)
        elif isinstance(n, ast.Call):
            f = n.func
            name = ""
            if isinstance(f, ast.Attribute):
                name = f.attr
            elif isinstance(f, ast.Name):
                name = f.id
            if name.startswith("assert") or name in ("raises", "fail"):
                out.append(n)
    return out


def _is_snapshot_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    name = (
        f.attr
        if isinstance(f, ast.Attribute)
        else (f.id if isinstance(f, ast.Name) else "")
    )
    return ("snapshot" in name.lower()) or ("toMatchSnapshot" in name)


def _is_mock_verify(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    name = (
        f.attr
        if isinstance(f, ast.Attribute)
        else (f.id if isinstance(f, ast.Name) else "")
    )
    return bool(
        re.match(
            r"(assert_called|assert_not_called|assert_any_call|assert_has_calls"
            r"|assert_called_once|assert_called_with|assert_called_once_with"
            r"|verify|verifyNoMoreInteractions)$",
            name,
        )
    )


def _is_bool_only(node: ast.Assert) -> bool:
    """断言只比较 True/False（W3）。

    ⚠️ 判据是「**任一侧**是布尔常量」而不是「全部都是」——
    `assert ok == True` 只有右侧是常量，用 all() 会漏判，
    然后掉进"其他表达式"兜底分支被错当成 S1（实测 7/8 里的那个错）。
    """
    t = node.test
    if isinstance(t, ast.Compare) and len(t.comparators) == 1:
        vals = [t.left] + list(t.comparators)
        return any(
            isinstance(v, ast.Constant) and isinstance(v.value, bool) for v in vals
        )
    if isinstance(t, ast.Constant) and isinstance(t.value, bool):
        return True
    # assertTrue(x) / assertFalse(x) —— 参数不是比较，属"只查真值"
    if isinstance(t, ast.Call) and not isinstance(t, ast.Compare):
        f = t.func
        name = (
            f.attr
            if isinstance(f, ast.Attribute)
            else (f.id if isinstance(f, ast.Name) else "")
        )
        if name in ("assertTrue", "assertFalse"):
            return True
    return False


def _is_existence_only(node: ast.Assert) -> bool:
    """断言只查存在/非空（W2）：assert x / assert x is not None / assert len(x)。"""
    t = node.test
    if isinstance(t, ast.Name):
        return True
    if isinstance(t, ast.Compare) and len(t.comparators) == 1:
        ops = [type(o) for o in t.ops]
        vals = [t.left] + list(t.comparators)
        if ast.Is in ops or ast.IsNot in ops:
            return any(isinstance(v, ast.Constant) and v.value is None for v in vals)
    if isinstance(t, ast.Call):
        f = t.func
        name = (
            f.attr
            if isinstance(f, ast.Attribute)
            else (f.id if isinstance(f, ast.Name) else "")
        )
        if name in ("assertIsNotNone", "assertIsNone", "assertTrue"):
            return True
    return False


def _is_value_comparison(node: ast.Assert) -> bool:
    """值相等/比较（S1）：assert a == b（且不与 True/False/None 这类常量比）。"""
    t = node.test
    if isinstance(t, ast.Compare):
        # 任一侧是布尔常量 → 属 W3（布尔断言），不是值比较
        if any(
            isinstance(c, ast.Constant) and isinstance(c.value, bool)
            for c in t.comparators
        ):
            return False
        if any(isinstance(c, ast.Constant) and c.value is None for c in t.comparators):
            return False  # 与非空检查 → W2
        return True
    if isinstance(t, ast.Call):
        f = t.func
        name = (
            f.attr
            if isinstance(f, ast.Attribute)
            else (f.id if isinstance(f, ast.Name) else "")
        )
        if name in (
            "assertEqual",
            "assertNotEqual",
            "assertAlmostEqual",
            "assertEquals",
        ):
            return True
        if name in (
            "assertIn",
            "assertNotIn",
            "assertIsInstance",
            "assertRaises",
            "assertGreater",
            "assertLess",
            "assertRegex",
            "assertContains",
        ):
            return True
    return False


def classify_python_test(fn: ast.AST) -> tuple[str, list[str]]:
    """给单个测试函数分类。返回 (类别, 命中的信号列表)。"""
    asserts = _collect_asserts_py(fn)
    if not asserts:
        return "W1", ["W1"]

    sigs: list[str] = []
    has_value = False
    has_error = False

    for a in asserts:
        if _is_snapshot_call(a):
            sigs.append("W5")
            continue
        if _is_mock_verify(a):
            sigs.append("W4")
            continue
        if isinstance(a, ast.Assert):
            if _is_bool_only(a):
                sigs.append("W3")
            elif _is_existence_only(a):
                sigs.append("W2")
            elif _is_value_comparison(a):
                has_value = True
            else:
                # 兜底：无法归类的断言（如 assert callable(f)）—— 保守归**弱**。
                # 方向性选择：宁可误报弱信号（用户会去看一眼），
                # 也不要误报强信号（用户会因此放心）。假强比假弱危险。
                sigs.append("W3")
        else:
            # 非 assert 的调用：raises / fail / isinstance 类
            f = a.func if isinstance(a, ast.Call) else None
            name = ""
            if isinstance(f, ast.Attribute):
                name = f.attr
            elif isinstance(f, ast.Name):
                name = f.id
            if name in (
                "raises",
                "fail",
                "assertRaises",
                "assertIsInstance",
                "assertIn",
                "assertNotIn",
                "assertRegex",
            ):
                if name in ("raises", "fail", "assertRaises"):
                    has_error = True
                else:
                    has_error = True
            else:
                if re.match(r"assert", name):
                    has_value = True

    if has_value or has_error:
        # 已有强信号，看是否有两种以上不同强类型 → S3
        strong_types = set()
        if has_value:
            strong_types.add("S1")
        if has_error:
            strong_types.add("S2")
        if len(strong_types) >= 2:
            sigs.append("S3")
            return "S3", sigs + ["S3"]
        sid = "S1" if has_value else "S2"
        sigs.append(sid)
        return sid, sigs

    # 只有弱信号：取最强的一个（快照 > mock > 布尔 > 非空）
    for cand in ("W5", "W4", "W3", "W2"):
        if cand in sigs:
            return cand, sigs
    return "W2", sigs


def iter_py_tests(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """找出所有 test_* 函数（含类方法）。"""
    out: list[tuple[str, ast.AST]] = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.name.startswith("test_"):
                out.append((n.name, n))
    return out


# ──────────────────────────────────────────────────────────────────────────
# JS/TS：正则近似（不引第三方解析器，保持零依赖）
# ──────────────────────────────────────────────────────────────────────────
JS_TEST_RE = re.compile(r"(?:^|\s)(?:it|test)\s*\(\s*['\"`](.+?)['\"`]")
JS_SNAPSHOT = re.compile(r"toMatchSnapshot|toMatchInlineSnapshot")
JS_MOCK_VERIFY = re.compile(
    r"\.(toBeCalled|toHaveBeenCalled|toHaveBeenCalledWith"
    r"|toHaveBeenCalledTimes|toHaveBeenNthCalledWith)\b"
)
JS_BOOL = re.compile(
    r"\.(toBe|toEqual|toStrictEqual)\s*\(\s*(true|false)\s*\)|toBeTruthy|toBeFalsy"
)
JS_EXIST = re.compile(
    r"\.(toBeNull|toBeUndefined|toBeDefined|toBeTruthy|toBeFalsy)\s*\("
)
JS_VALUE = re.compile(
    r"\.(toBe|toEqual|toStrictEqual|toContain|toBeGreaterThan"
    r"|toBeLessThan|toBeCloseTo)\s*\("
)
JS_ERROR = re.compile(r"\.(toThrow|toThrowError)\s*\(|expect\.assertions|rejects\.")


def classify_js_block(body: str) -> tuple[str, list[str]]:
    if not re.search(r"\b(expect|assert)\b", body):
        return "W1", ["W1"]
    sigs = []
    has_value = bool(JS_VALUE.search(body))
    has_error = bool(JS_ERROR.search(body))
    if JS_SNAPSHOT.search(body):
        sigs.append("W5")
    if JS_MOCK_VERIFY.search(body):
        sigs.append("W4")
    # 排除纯布尔/存在性
    value_only = JS_VALUE.search(body)
    if value_only:
        for m in JS_VALUE.finditer(body):
            frag = body[m.start() : m.start() + 60]
            if JS_BOOL.search(frag):
                sigs.append("W3")
                has_value = False
                break
    if not has_value and not has_error and JS_EXIST.search(body):
        sigs.append("W2")

    if has_value or has_error:
        strong = set()
        if has_value:
            strong.add("S1")
        if has_error:
            strong.add("S2")
        if len(strong) >= 2:
            return "S3", sigs + ["S3"]
        sid = "S1" if has_value else "S2"
        return sid, sigs + [sid]
    for cand in ("W5", "W4", "W3", "W2"):
        if cand in sigs:
            return cand, sigs
    return "W2", sigs


def scan_js(path: str, rel: str) -> tuple[list[tuple[str, str]], str | None]:
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except OSError as e:
        return [], f"{rel} 读取失败: {e.__class__.__name__}"
    out = []
    marks = list(JS_TEST_RE.finditer(src))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(src)
        body = src[m.start() : end]
        cls, _ = classify_js_block(body)
        out.append((m.group(1)[:70], cls))
    return out, None


# ──────────────────────────────────────────────────────────────────────────
# 孤儿测试：测试对应的被测源码是否还在
# ──────────────────────────────────────────────────────────────────────────
def find_orphan_py(path: str, rel: str) -> tuple[list[str], str | None]:
    """测试文件 import 的本项目模块，是否还存在。"""
    try:
        src = open(path, encoding="utf-8", errors="ignore").read()
    except OSError as e:
        return [], f"{rel} 读取失败: {e.__class__.__name__}"
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return [], None

    missing: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod.startswith(
                (
                    "pytest",
                    "unittest",
                    "mock",
                    "typing",
                    "os",
                    "sys",
                    "json",
                    "re",
                    "pathlib",
                    "dataclasses",
                    "abc",
                )
            ):
                continue
            modpath = mod.replace(".", "/")
            if not (
                os.path.isfile(modpath + ".py")
                or os.path.isfile(os.path.join(modpath, "__init__.py"))
                or os.path.isdir(modpath)
            ):
                missing.append(mod)
    return missing, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="测试有效性审计（oracle 信号 + 孤儿测试）—— 输出是信号，不是判决"
    )
    ap.add_argument(
        "paths", nargs="*", default=None, help="测试目录（默认 tests/ 或自动探测）"
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="弱 oracle 占比阈值（默认 0.8，取自 arXiv:2606.18168 的总体弱信号率）",
    )
    ap.add_argument(
        "--fail-on",
        choices=["none", "weak", "orphan"],
        default="none",
        help="weak=弱占比超阈值即非零退出；orphan=有孤儿测试即非零退出",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    paths = args.paths
    if not paths:
        paths = [
            d for d in ("tests", "test", "__tests__", "src") if os.path.isdir(d)
        ] or ["tests"]

    files, notes = iter_test_files(paths)
    if not files:
        print("[!] 没有找到测试文件。", file=sys.stderr)
        for n in notes:
            print(f"    · {n}", file=sys.stderr)
        print(
            "    提示：可用 python scripts/test_audit.py <测试目录> 显式指定。",
            file=sys.stderr,
        )
        return 2

    counts: dict[str, int] = defaultdict(int)
    by_file: dict[str, list[tuple[str, str]]] = defaultdict(list)
    orphans: dict[str, list[str]] = {}
    failures: list[str] = []

    for f in files:
        rel = os.path.relpath(f).replace("\\", "/")
        if f.endswith(PY_EXT):
            try:
                tree = ast.parse(open(f, encoding="utf-8", errors="ignore").read())
            except (OSError, SyntaxError) as e:
                failures.append(f"{rel} 解析失败: {e.__class__.__name__}")
                continue
            for name, node in iter_py_tests(tree):
                cls, _ = classify_python_test(node)
                counts[cls] += 1
                by_file[rel].append((name, cls))
            miss, err = find_orphan_py(f, rel)
            if err:
                failures.append(err)
            if miss:
                orphans[rel] = sorted(set(miss))
        else:
            res, err = scan_js(f, rel)
            if err:
                failures.append(err)
            for name, cls in res:
                counts[cls] += 1
                by_file[rel].append((name, cls))

    total = sum(counts.values())
    weak = sum(counts[c] for c in WEAK)
    strong = sum(counts[c] for c in STRONG)
    ratio = (weak / total) if total else 0.0

    if args.json:
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "test_files": len(files),
                    "tests": total,
                    "distribution": dict(counts),
                    "weak": weak,
                    "strong": strong,
                    "weak_ratio": round(ratio, 4),
                    "orphan_tests": orphans,
                    "parse_failures": failures,
                    "reference": "arXiv:2606.18168 (IEEE AITest 2026)",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if args.fail_on == "weak" and ratio > args.threshold:
            return 1
        if args.fail_on == "orphan" and orphans:
            return 1
        return 0

    print(f"\n测试有效性审计 — {len(files)} 个测试文件 / {total} 个测试")
    print("=" * 66)

    if not total:
        print("\n⚠️  没有识别出任何测试函数（命名是否为 test_* / it() / test()？）")

    print("\n--- Oracle 信号分布（arXiv:2606.18168 的 8 类分类法）---")
    for c in list(WEAK) + list(STRONG):
        n = counts.get(c, 0)
        pct = (n / total * 100) if total else 0
        mark = "弱" if c in WEAK else "强"
        print(f"    {c} [{mark}] {n:>4} 个 ({pct:>5.1f}%)  {ORACLE_DESC[c]}")

    print(
        f"\n  弱信号合计 {weak}/{total} = {ratio * 100:.1f}%"
        f"   强信号 {strong}/{total} = {(1 - ratio) * 100:.1f}%"
    )

    if ratio > args.threshold:
        print(
            f"\n  ⚠️  弱信号占比超过阈值 {args.threshold * 100:.0f}%"
            f"（论文总体测量值 80.2%，区间 18%–67% 因 agent 而异）"
        )
        print("      含义：这些测试在**执行**代码，但未必在**验证**行为。")
        print("      做法：优先给 W1（无断言）与 W2（只查非空）补值比较。")
    else:
        print(
            f"\n  ✅ 弱信号占比 {ratio * 100:.1f}%，低于阈值 {args.threshold * 100:.0f}%"
        )

    if orphans:
        print(f"\n--- 孤儿测试 ({len(orphans)} 个文件 import 了不存在的模块) ---")
        for rel, mods in sorted(orphans.items())[:15]:
            print(f"    · {rel}")
            print(f"      找不到: {', '.join(mods[:5])}")
        print("\n    ⚠️  被测源码已删除/改名，但测试还在。")
        print("        这是「模块消失后测试依然通过」的常见成因之一。")
        print("        做法：确认该测试已无守护对象 → 一并删除（别留着当装饰）。")

    # 列出最该看的文件（弱信号最多的）
    if total:
        ranked = sorted(
            by_file.items(),
            key=lambda kv: sum(1 for _, c in kv[1] if c in WEAK),
            reverse=True,
        )
        hot = [(r, t) for r, t in ranked if sum(1 for _, c in t if c in WEAK) > 0][:5]
        if hot:
            print("\n--- 弱信号最集中的文件（先看这几个）---")
            for rel, tests in hot:
                w = sum(1 for _, c in tests if c in WEAK)
                print(f"    · {rel}  ({w}/{len(tests)} 个测试为弱信号)")
                for name, c in tests:
                    if c in WEAK:
                        print(f"        {c}  {name}")

    if failures:
        print(f"\n⚠️  {len(failures)} 个文件未能分析（其结果未纳入统计）:")
        for s in failures[:10]:
            print(f"    · {s}")

    print("\n" + "=" * 66)
    print("⚠️  这是**信号**不是判决。判为 S1 只说明存在值比较，不说明比得对。")
    print("    论文局限：只查语法信号，未覆盖隐式 oracle（崩溃即失败/超时）。")
    print("    依据：https://arxiv.org/abs/2606.18168")
    print("    要真正测有效性，用变异测试（mutmut / Stryker / PIT）。")

    if args.fail_on == "weak" and ratio > args.threshold:
        return 1
    if args.fail_on == "orphan" and orphans:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
