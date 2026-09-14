#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
no_placeholder_guard.py — 反占位符交付门禁

用途
----
在 AI 辅助开发的项目里，拦截「看起来完成但其实是占位实现」的代码，
把「完成」从 Agent 的主观判断变成流程里的客观闸门。

典型用法（接 CI 或本地提交前自检）：
    python tools/no_placeholder_guard.py .
    python tools/no_placeholder_guard.py src app --fail-on warn
    python tools/no_placeholder_guard.py . --json > report.json
    python tools/no_placeholder_guard.py . --allowlist .placeholder-allowlist

退出码（显式声明，绝不静默）
----------------------------
    0  未发现 >= fail-on 级别的问题（注意：仍可能有更低级别的发现，会打印出来）
    1  发现了 >= fail-on 级别的问题  → 阻断交付
    2  用法错误 / 输入路径不存在 / 读取失败  → 阻断交付（不静默吞掉）

设计原则
--------
* 宁可漏报也不误报：误报太多会导致门禁被关掉，那就等于没有门禁。
* 每条发现都给出「文件:行号 + 规则名 + 原文」，方便直接定位。
* 不做任何自动修复。发现问题只报告，修不修由人决定（本脚本不修改源文件）。

输入：一个或多个文件/目录路径
输出：人类可读报告（默认）或 JSON（--json）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Iterable, Iterator

VERSION = "1.0.0"


def _norm(path: str) -> str:
    """规范化路径：正斜杠 + 去掉前导 `./`。

    ⚠️ 不要用 `path.lstrip("./")` —— lstrip 的参数是**字符集**不是前缀，
    它会连着吃掉 `.harness` 的前导点，使豁免清单里的点目录路径永远匹配不上
    （真实事故，与 module_manifest.norm_rel 同一根因）。
    """
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p

# --------------------------------------------------------------------------
# 默认忽略的目录 / 文件
# --------------------------------------------------------------------------
DEFAULT_IGNORE_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "bower_components",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", ".env",
    "dist", "build", "out", "target", "bin", "obj",
    "coverage", "htmlcov", ".next", ".nuxt", ".svelte-kit",
    ".idea", ".vscode", ".workbuddy",
    "site-packages", "vendor", "third_party",
    # 本仓库自带的正反例目录，扫真实项目时不应把它算进来
    "_selftest", "examples_placeholder",
}

# 本脚本自身含有大量占位关键词（规则定义），必须自我排除，
# 否则会出现「门禁脚本把自己判违规」的荒谬结果。
SELF_NAME = os.path.basename(__file__)

TEXT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".vue", ".svelte",
    ".java", ".kt", ".kts", ".scala", ".go", ".rs",
    ".rb", ".php", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".sh", ".bash", ".ps1",
    ".sql", ".graphql", ".gql", ".proto",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".mdx", ".txt",
    ".html", ".css", ".scss", ".less",
}


# --------------------------------------------------------------------------
# 规则定义
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    rid: str
    severity: str          # "error" | "warn"
    pattern: re.Pattern
    hint: str              # 人话解释：这通常意味着什么


def _r(rid: str, severity: str, regex: str, hint: str) -> Rule:
    return Rule(rid=rid, severity=severity, pattern=re.compile(regex, re.IGNORECASE), hint=hint)


# 说明：为避免本脚本扫描自身时命中规则，关键词在下面用字符串拼接构造。
_K_TODO = "TO" + "DO"
_K_FIXME = "FIX" + "ME"
_K_HACK = "HA" + "CK"

RULES: list[Rule] = [
    # ---------------- ERROR: 明确的未完成标记 ----------------
    _r(
        "todo-marker", "error",
        rf"\b({_K_TODO}|{_K_FIXME}|{_K_HACK}|TBD)\b\s*[:：]?",
        "显式的未完成标记；交付前必须实现或转成正式 issue",
    ),
    _r(
        # 必须要求标记词前面有注释符号：否则「本文档说明占位符的危害」这类
        # 描述性文字（docstring、字符串、 prose）会被当成占位标记，产生噪音误报。
        # 门禁误报太多会被关掉，那就等于没有门禁——所以宁可漏，不可吵。
        "todo-marker-zh", "error",
        r"(?:^|\s)(?:#|//|/\*|\*|<!--)[^\n]*?"
        r"(待实现|未实现|暂未实现|暂不实现|待补充|待完善|占位符|占位的|占位实现)",
        "中文未完成标记（要求出现在注释中，避免误伤说明性文字）",
    ),
    _r(
        "not-implemented", "error",
        r"\b(NotImplementedError|NotImplementedException|NotImplemented)\b",
        "抛出未实现异常，属于桩实现",
    ),
    _r(
        "stub-return", "error",
        r"return\s+(['\"])[^'\"]{0,40}?(mock|fake|dummy|placeholder|stub|示例|假数据|测试数据)[^'\"]{0,40}?\1",
        "返回硬编码的假数据字符串",
    ),
    _r(
        "stub-variable", "error",
        r"\b(mock_data|fake_data|dummy_data|假数据|示例数据|写死的?数据)\b",
        "假数据变量/常量：说明真实数据源没接上",
    ),
    _r(
        # 返回字面量对象里带 mock/fake 值，如 return {"name": "mock_user"}。
        # 定为 WARN 而非 ERROR：有些领域里 dummy/placeholder 是合法概念名。
        "stub-return-dict", "warn",
        r"return\s*[\{\[][^\n]{0,200}?\b(mock|fake|dummy|placeholder)\w*\b",
        "返回的对象字面量中带 mock/fake/dummy 值：疑似硬编码假数据",
    ),

    # ---------------- WARN: 可疑但可能合法 ----------------
    _r(
        "empty-body", "warn",
        r"^\s*(pass|\.\.\.)\s*(#.*)?$",
        "空函数体（Python 的 pass / ...）：抽象方法与协议定义合法，业务逻辑里出现即为桩",
    ),
    _r(
        "shallow-catch", "warn",
        r"(except[^\n:]*:\s*(?:#[^\n]*)?\n\s*pass\b|"
        r"catch\s*\([^)]*\)\s*\{\s*\}|"
        r"catch\s*\([^)]*\)\s*\{\s*(//|/\*)[^\n]*\})",
        "吞掉异常的浅层错误处理：catch 后什么都不做，等于隐藏故障",
    ),
    _r(
        "log-and-rethrow", "warn",
        r"(except[^\n:]*:\s*(?:#[^\n]*)?\n(?:\s+[^\n]*\n){0,3}?\s*raise(?!\s+\w*Error\s*\()|"
        r"catch\s*\([^)]*\)\s*\{\s*(?:console\.(log|error|warn)|logger\.\w+)\([^\n]*\)\s*;\s*(throw|})[^}]*\})",
        "日志后原样重抛：没有恢复动作、没有上下文，属于通用占位式错误处理",
    ),
    _r(
        "demo-wording", "warn",
        r"(coming\s+soon|not\s+implemented\s+yet|demo\s+only|for\s+now,?\s+(we|I|let)|"
        r"敬请期待|演示用|临时(返回|写死|方案)|暂时(返回|写死|用)|先写死)",
        "演示/临时话术：说明这块是过渡实现，不是最终交付",
    ),
    _r(
        "hardcoded-fallback", "warn",
        r"return\s+(null|None|undefined|\[\]|\{\}|0|1|\"\"|'')\s*(//|#)\s*\S",
        "带注释的兜底返回：常是「真实逻辑没做，先返回个默认值」",
    ),
]

# 需要跨行匹配的规则。
# 关键：scan_file 若只逐行扫描，这些规则永远命中不了（except 在一行、pass 在下一行），
# 而「吞掉异常」恰恰是最值得拦的占位实现之一。因此它们必须走全文匹配通道。
MULTILINE_RULE_IDS = {"shallow-catch", "log-and-rethrow"}

# ── 文档类文件只跑「模板占位符」这一族规则 ──
# 为什么：`.md` 里出现 TODO / NotImplementedError / 空函数体 / catch-pass ，
# 绝大多数情况是**在讲解这些反模式**，而不是真犯了它们。
# 实证：拿本仓库自检，AGENTS.md 写「不写 TODO / FIXME / NotImplementedError」这条规则本身，
# 被判 3 条 ERROR；README.md 讲「没有 DoD 会产出 Incomplete Implementation」又被判违规。
# 一个防占位符的系统被自己的门禁判违规 14 次 —— 说明扫描范围设计错了，不是文档写错了。
# 文档该被检查的只有一件事：**模板占位符填没填**（{{XXX}}）。
CODE_ONLY_RULES = {
    "todo-marker", "todo-marker-zh", "not-implemented",
    "stub-return", "stub-variable", "stub-return-dict",
    "empty-body", "shallow-catch", "log-and-rethrow",
    "hardcoded-fallback",
}
DOC_EXTENSIONS = {".md", ".mdx", ".txt", ".rst"}

MULTILINE_RULES = [r for r in RULES if r.rid in MULTILINE_RULE_IDS]
LINE_RULES = [r for r in RULES if r.rid not in MULTILINE_RULE_IDS]


def is_doc_file(path: str) -> bool:
    """文档类文件：只跑模板占位符检查，不跑代码语义检查。"""
    return os.path.splitext(path)[1].lower() in DOC_EXTENSIONS


def rules_for(path: str) -> list[Rule]:
    """按文件类型选择适用规则（文档只跑文档适用的那部分）。"""
    if is_doc_file(path):
        return [r for r in RULES if r.rid not in CODE_ONLY_RULES]
    return list(RULES)


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------
@dataclass
class Finding:
    file: str
    line: int
    severity: str
    rule: str
    hint: str
    text: str


def iter_files(paths: Iterable[str], ignore_dirs: set[str], extra_exclude: list[str]) -> Iterator[str]:
    """产出待扫描的文件路径。目录递归，文件直接用。"""
    exclude_patterns = [re.compile(p) for p in extra_exclude]

    for p in paths:
        if os.path.isfile(p):
            if os.path.basename(p) != SELF_NAME:
                yield p
            continue
        if not os.path.isdir(p):
            print(f"[!] 路径不存在，已跳过: {p}", file=sys.stderr)
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            for fn in files:
                if fn == SELF_NAME:
                    continue
                if os.path.splitext(fn)[1].lower() not in TEXT_EXTENSIONS:
                    continue
                full = os.path.join(root, fn)
                norm = full.replace("\\", "/")
                if any(rx.search(norm) for rx in exclude_patterns):
                    continue
                yield full


def load_allowlist(path: str | None) -> set[tuple[str, int]]:
    """
    白名单格式：每行 `path[:line]`，忽略 `#` 开头的注释与空行。
    用于存放「已确认接受的技术债」，让门禁能持续生效而不是被一次性关掉。
    """
    allowed: set[tuple[str, int]] = set()
    if not path:
        return allowed
    if not os.path.isfile(path):
        print(f"[!] allowlist 文件不存在，已忽略: {path}", file=sys.stderr)
        return allowed
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            # 支持整行注释与行尾注释（路径里不含 #，据此剥离是安全的）
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            line = _norm(line)
            if ":" in line and line.rsplit(":", 1)[1].isdigit():
                p, ln = line.rsplit(":", 1)
                allowed.add((p, int(ln)))
            else:
                allowed.add((line, -1))  # -1 = 整文件豁免
    return allowed


def _path_matches(norm_file: str, pattern: str) -> bool:
    """扫描路径与白名单路径的匹配：精确相等，或白名单是被扫路径的后缀。

    这样 allowlist 写相对路径、扫描时传绝对路径也能命中。
    """
    return norm_file == pattern or norm_file.endswith("/" + pattern)


def is_allowed(allow: set[tuple[str, int]], filepath: str, lineno: int) -> bool:
    norm = _norm(filepath)
    for p, ln in allow:
        if not _path_matches(norm, p):
            continue
        if ln == -1 or ln == lineno:
            return True
    return False


# ── 行内豁免指令 ──
# 用途：任何项目都会有"**在描述规则本身**"的地方 —— 规范文档、门禁脚本的注释、
# 解释"什么算占位实现"的说明。这些文字会被规则打中，但它们不是违规。
# 用法：在所在行（或紧邻的上一行）加 `guard:allow`
#     # guard:allow —— 本行在解释规则本身，不是占位实现
# 为什么用显式指令而不是自动识别：自动识别"这句话是不是在讲规则"不可靠
# （自然语言判断），而显式指令零误判、可审计、且让作者主动思考一次。
INLINE_ALLOW = re.compile(r"guard\s*:\s*allow", re.I)


def _inline_allowed(lines: list[str], lineno: int) -> bool:
    """该行是否带行内豁免指令（本行或紧邻上一行）。"""
    for cand in (lineno, lineno - 1):
        if 1 <= cand <= len(lines) and INLINE_ALLOW.search(lines[cand - 1]):
            return True
    return False


def scan_file(filepath: str, allow: set[tuple[str, int]]) -> list[Finding]:
    """
    扫描单个文件。

    两阶段：
      1) 跨行规则 —— 在全文上匹配（单行扫描命中不了 `except:` + 换行 + `pass`）
      2) 单行规则 —— 逐行匹配

    同一 (行号, 规则) 只报一次；被跨行规则覆盖的行不再重复报 empty-body，
    避免同一处 `except: pass` 被拆成两条重复告警。

    豁免来源：① allowlist 文件（文件/行级） ② 行内 `guard:allow` 指令。
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError as e:
        print(f"[!] 读取失败，已跳过 {filepath}: {e}", file=sys.stderr)
        return []

    lines = content.splitlines()
    norm_path = filepath.replace("\\", "/")
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    covered_by_multiline: set[int] = set()

    def emit(lineno: int, rule: Rule, text: str) -> None:
        key = (lineno, rule.rid)
        if key in seen:
            return
        if _inline_allowed(lines, lineno):       # 行内 `guard:allow` 指令
            return
        seen.add(key)
        findings.append(Finding(
            file=norm_path,
            line=lineno,
            severity=rule.severity,
            rule=rule.rid,
            hint=rule.hint,
            text=text.strip()[:200],
        ))

    # --- 阶段 1：跨行规则（全文匹配）---
    # 按文件类型取规则：文档只跑模板占位符族（详见 CODE_ONLY_RULES 上方注释）
    applicable = rules_for(filepath)
    ml_rules = [r for r in applicable if r.rid in MULTILINE_RULE_IDS]
    ln_rules = [r for r in applicable if r.rid not in MULTILINE_RULE_IDS]
    for rule in ml_rules:
        for m in rule.pattern.finditer(content):
            start_line = content.count("\n", 0, m.start()) + 1
            end_line = content.count("\n", 0, m.end()) + 1
            if is_allowed(allow, filepath, start_line):
                continue
            for ln in range(start_line, end_line + 1):
                covered_by_multiline.add(ln)
            emit(start_line, rule, lines[start_line - 1] if start_line <= len(lines) else "")

    # --- 阶段 2：单行规则 ---
    for i, line in enumerate(lines, start=1):
        if is_allowed(allow, filepath, i):
            continue
        prev_line = lines[i - 2] if i >= 2 else ""
        for rule in ln_rules:
            # `except X: \n pass` 已由 shallow-catch 报告，不用再报 empty-body
            if rule.rid == "empty-body":
                if i in covered_by_multiline:
                    continue
                if re.search(r"\b(except|try)\b", prev_line):
                    continue
            if rule.pattern.search(line):
                emit(i, rule, line)

    return findings


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
SEV_ORDER = {"error": 0, "warn": 1}


def print_report(findings: list[Finding], scanned: int) -> None:
    if not findings:
        print(f"✅ 通过：扫描 {scanned} 个文件，未发现占位实现。")
        return

    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]

    print(f"\n扫描文件数: {scanned}")
    print(f"发现: {len(errors)} 个 ERROR, {len(warns)} 个 WARN\n")

    for sev, bucket, mark in (("error", errors, "❌"), ("warn", warns, "⚠️ ")):
        if not bucket:
            continue
        print(f"--- {sev.upper()} ({len(bucket)}) ---")
        for f in sorted(bucket, key=lambda x: (x.file, x.line)):
            print(f"{mark} {f.file}:{f.line}  [{f.rule}]")
            print(f"      {f.text}")
            print(f"      ↳ {f.hint}")
        print()

    print("处置建议:")
    print("  1) 真实实现缺失 → 实现它（而不是删掉标记）")
    print("  2) 确属已接受的技术债 → 写进 allowlist，并登记 issue 编号")
    print("  3) 误报 → 写进 allowlist，并在 issue 里说明为何合法")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="反占位符交付门禁：拦截 TODO / 桩实现 / 假数据 / 浅层错误处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("paths", nargs="+", help="要扫描的文件或目录")
    ap.add_argument("--fail-on", choices=["error", "warn"], default="error",
                    help="达到该级别即非零退出（默认 error）")
    ap.add_argument("--allowlist", default=None,
                    help="白名单文件，每行 `path[:line]`")
    ap.add_argument("--exclude", action="append", default=[],
                    help="额外排除路径（正则，可重复）")
    ap.add_argument("--ignore-dir", action="append", default=[],
                    help="额外忽略的目录名（可重复）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    ignore_dirs = set(DEFAULT_IGNORE_DIRS) | set(args.ignore_dir)
    allow = load_allowlist(args.allowlist)

    files = list(iter_files(args.paths, ignore_dirs, args.exclude))
    if not files:
        print("[!] 没有扫描到任何文件 —— 这本身就是异常，请检查 paths / exclude 配置。",
              file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for fp in files:
        findings.extend(scan_file(fp, allow))

    findings.sort(key=lambda f: (SEV_ORDER[f.severity], f.file, f.line))

    blocking = [f for f in findings
                if f.severity == "error" or args.fail_on == "warn"]
    exit_code = 1 if blocking else 0

    if args.json:
        print(json.dumps(
            {
                "version": VERSION,
                "scanned_files": len(files),
                "counts": {
                    "error": sum(1 for f in findings if f.severity == "error"),
                    "warn": sum(1 for f in findings if f.severity == "warn"),
                },
                "blocking": len(blocking),
                "exit_code": exit_code,
                "findings": [asdict(f) for f in findings],
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        print_report(findings, len(files))
        print(f"\n退出码: {exit_code}"
              + ("（阻断交付）" if exit_code else "（放行）"))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
