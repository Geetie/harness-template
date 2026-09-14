#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
harness_lint.py — harness 一致性与漂移检查

为什么需要它
------------
harness 文档之间会互相引用、互相复制数字、互相登记文件名。
**只要有一处没跟上，就会产生"Agent 遵循过期规则"的问题**——比缺失规则更危险。

实测三个真实项目暴露的漂移（2026-09）：

  · 同一份测试基线在四个文件里是四个值：
      init.sh 写 4614 / AGENTS.md 写 4614 / progress.md 写 4034
      verification.md §1 写 4614 而 §4 写 4630 / session-handoff.md 写 4630
  · 所有文档指针用硬编码绝对路径 `d:\\UGSimulator\\...`（换 clone 位置即失效）
  · pre-commit hook 的提示文案仍引用迁移前的旧路径（上次重构漏改）
  · ROUTER 注册表里登记的技能与实际磁盘文件不一致
  · AGENTS.md "最后更新" 停在两个月前，而项目天天在改

这些靠人眼审不出来，靠纪律反复失效。本脚本把它们变成可执行检查。

检查项
------
    L001 死链接        文档里引用的本项目文件不存在
    L002 绝对路径      harness 文档里出现盘符/根路径（换机器即废）
    L003 基线漂移      多处记录的测试基线数字互相矛盾
    L004 注册表失配    ROUTER 注册的技能/能力卡与磁盘不符
    L005 文档过期      "最后更新" 距今超过阈值
    L006 阅读清单过长  强制阅读清单项数超过阈值（token 黑洞）
    L007 占位符残留    模板占位符 {{XXX}} 未填写

用法
----
    python scripts/harness_lint.py
    python scripts/harness_lint.py --json
    python scripts/harness_lint.py --max-read-list 5 --stale-days 60
    python scripts/harness_lint.py --only L003,L002

退出码
------
    0  无 ERROR（可能有 WARN）
    1  发现 ERROR
    2  路径/配置错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime

VERSION = "1.0.0"

SCAN_TARGETS = ["AGENTS.md", "CLAUDE.md", ".harness", "docs"]
EXCLUDE_DIRS = {"archive", "node_modules", ".git", "__pycache__", "dist", "build", ".venv"}

# ── 作用域：治理文档 vs 历史档案 ──
# 为什么必须区分：历史计划/评审/运行日志里天然充满绝对路径与历史数字，
# 它们**描述过去**，改它们没有意义。实测扫全量 docs/ 时 L002 产生 554 条噪音，
# 真问题（AGENTS.md 硬编码路径）被淹没——噪音淹没真报警，门禁就会被关掉。
# 默认只扫"治理文档"：Agent 每次真正会读、且应当保持正确的那些。
GOVERNANCE_EXCLUDE_DIRS = {"archive", "operations", "retrospectives", "_archive_legacy"}
GOVERNANCE_EXCLUDE_FILES = [
    re.compile(r"verification-log", re.I),
    re.compile(r"[-_]log\.md$", re.I),
]
HISTORY_DOC_DIRS = {
    "docs/specs", "docs/designs", "docs/plans", "docs/superpowers",
    "docs/devops", "docs/data-sources", "docs/_archive_legacy",
}

# 建索引时跳过的目录（这些不是"可引用物"，扫它们只会拖慢并制造噪音）
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv",
             "venv", "target", ".next", ".nuxt", "archive", "coverage"}

# ── L002 绝对路径 ──
ABS_WIN = re.compile(r"\b[a-zA-Z]:[\\/][^\s`)\]\"']*")
ABS_POSIX_HOME = re.compile(r"(?<![\w.])/(?:Users|home|mnt|opt)/[^\s`)\]\"']*")

# ── L003 基线数字 ──
BASE_PATTERNS = [
    re.compile(r"(\d{3,6})\s*个?\s*(?:测试|用例|tests?)\b", re.I),
    re.compile(r"(\d{3,6})\s*(?:通过|passed)\b", re.I),
    re.compile(r"(\d{3,6})\s*/\s*\d+\s*/\s*\d+"),          # passed/failed/skipped
    re.compile(r"(?:total|全量|基线)\D{0,12}(\d{3,6})", re.I),
]

# ── L001 文档内引用的文件路径 ──
BACKTICK_PATH = re.compile(r"`([A-Za-z0-9_./\\-]+\.(?:md|py|sh|ps1|json|yaml|yml|toml|ts|tsx|js|jsx))`")
MD_LINK = re.compile(r"\]\(([^)#\s]+\.(?:md|py|sh|ps1|json|yaml|yml|toml|ts|tsx|js|jsx))\)")

# ── L005 最后更新 ──
UPDATED = re.compile(r"最后更新\D{0,6}(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")

# ── L006 强制阅读清单 ──
READ_LIST_HEAD = re.compile(r"(?:强制阅读|必读|MANDATORY READ|启动路径|阅读清单)", re.I)
READ_LIST_ITEM = re.compile(r"^\s*(?:\d+[.、)]|[-*])\s+\S")

# ── L007 占位符 ──
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

# ── 行内豁免 ──
# 有些文档**故意**引用历史路径作为证据（如反模式库举证"某项目曾硬编码 E:\X"），
# 那不是"供使用的硬编码路径"，不该报。用法：在该行加 `lint-ignore`。
LINT_IGNORE = "lint-ignore"


def is_ignored(line: str) -> bool:
    return LINT_IGNORE in line

ALL_CHECKS = ["L001", "L002", "L003", "L004", "L005", "L006", "L007"]


@dataclass
class Finding:
    rule: str
    level: str
    file: str
    line: int
    message: str
    hint: str = ""


def read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def collect_docs(root: str, scope: str = "governance") -> list[str]:
    """收集待检查文档。

    scope="governance"（默认）：只收 Agent 每次真正会读的治理文档。
        排除历史档案目录与其内的审阅/运行日志——它们描述过去，改了没意义。
    scope="all"：全量（用于一次性盘库，噪音较大）。
    """
    out: list[str] = []
    for t in SCAN_TARGETS:
        p = os.path.join(root, t)
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isdir(p):
            for dp, dn, fn in os.walk(p):
                rel_dir = os.path.relpath(dp, root).replace("\\", "/")
                excl = set(EXCLUDE_DIRS)
                if scope == "governance":
                    excl |= GOVERNANCE_EXCLUDE_DIRS
                dn[:] = [d for d in dn
                         if d not in excl and (not d.startswith(".") or d == ".harness")]
                for f in fn:
                    if not f.lower().endswith((".md", ".markdown")):
                        continue
                    if scope == "governance":
                        if any(rx.search(f) for rx in GOVERNANCE_EXCLUDE_FILES):
                            continue
                        if any(rel_dir == h or rel_dir.startswith(h + "/")
                               for h in HISTORY_DOC_DIRS):
                            continue
                    out.append(os.path.join(dp, f))
    return sorted(set(out))


def rel(root: str, p: str) -> str:
    return os.path.relpath(p, root).replace("\\", "/")


# ── L001 豁免：生成物与约定名（模板自身/未初始化项目里本就不存在，报它是噪音）──
IGNORE_REFS = {".harness/config.json"}


def is_real_path_ref(ref: str) -> bool:
    """过滤掉明显不是文件引用的（如 `npm run build`、`src/**`）。"""
    if any(c in ref for c in "*?<>|"):
        return False
    if ref.startswith(("http", "git@", "npm ", "pip ", "python ", "git ")):
        return False
    if " " in ref:
        return False
    return True


def build_name_index(root: str) -> set[str]:
    """仓库内所有文件的文件名与相对路径索引。

    为什么需要：harness 文档里大量引用**裸文件名**（`progress.md`、`ROUTER.md`），
    它们相对于各自所在目录，而不是仓库根。若只按"根 + 文档目录"两处解析，
    会产生海量误报（实测 49 条里 40+ 是这种）。索引化后按同名判定即可。
    """
    idx: set[str] = set()
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".") or d == ".harness"]
        for f in fn:
            rel_p = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            for v in (f, rel_p):
                idx.add(v)
                # 小写兜底：Windows 文件名不区分大小写，文档里手写的大小写偏差
                # （如 state-protocol.md vs STATE-PROTOCOL.md）不该报成死链
                idx.add(v.lower())
    return idx


def check_l001(root: str, docs: list[str], name_index: set[str]) -> list[Finding]:
    """死链接：引用的本项目文件在仓库内找不到同名/同路径文件。"""
    out = []
    for d in docs:
        content = read(d)
        if not content:
            continue
        for i, ln in enumerate(content.splitlines(), 1):
            if is_ignored(ln):
                continue
            for pat in (BACKTICK_PATH, MD_LINK):
                for m in pat.finditer(ln):
                    ref = m.group(1)
                    if not is_real_path_ref(ref):
                        continue
                    if "archive" in ref:
                        continue
                    norm = ref.replace("\\", "/").lstrip("./")
                    if ref in IGNORE_REFS or norm in IGNORE_REFS:
                        continue
                    # ① 绝对/根相对路径存在 ② 文档同目录相对存在 ③ 仓库内存在同名文件
                    if os.path.exists(os.path.join(root, ref)):
                        continue
                    if os.path.exists(os.path.join(os.path.dirname(d), ref)):
                        continue
                    base = os.path.basename(norm)
                    if (base in name_index or base.lower() in name_index
                            or norm in name_index or norm.lower() in name_index):
                        continue
                    out.append(Finding(
                        "L001", "warn", rel(root, d), i,
                        f"引用的文件在仓库内找不到: {ref}",
                        "文件已改名/迁移但引用未更新（重构漏改的典型）；若只是文档里的示例名，可忽略",
                    ))
    return out


def check_l002(root: str, docs: list[str], name_index: set[str]) -> list[Finding]:
    """绝对路径：换机器/clone 位置即失效。

    只报**指向本仓库内容**的绝对路径：判据是该绝对路径的文件名能在仓库里找到同名文件。
    这样 `D:/temp/xxx`（系统路径）、`C:/Program Files/...` 之类的正常引用不会被误报——
    实测不加这层过滤，70 条里有 1/3 是这类噪音。
    """
    out = []
    for d in docs:
        content = read(d)
        if not content:
            continue
        for i, ln in enumerate(content.splitlines(), 1):
            if is_ignored(ln):
                continue
            for pat in (ABS_WIN, ABS_POSIX_HOME):
                m = pat.search(ln)
                if not m:
                    continue
                raw = m.group(0).rstrip("\\/")
                base = os.path.basename(raw.replace("\\", "/"))
                # 仅在"这条绝对路径指向仓库里的某个文件"时才报
                if not base or base not in name_index:
                    continue
                out.append(Finding(
                    "L002", "error", rel(root, d), i,
                    f"硬编码绝对路径: {raw[:70]}",
                    "改用仓库相对路径（clone 到别处/换机器都会失效）",
                ))
                break
    return out


def check_l003(root: str, docs: list[str]) -> list[Finding]:
    """基线漂移：同一类基线数字出现多个互相矛盾的值。"""
    hits: dict[str, list[tuple[str, int]]] = {}
    for d in docs:
        content = read(d)
        if not content:
            continue
        for i, ln in enumerate(content.splitlines(), 1):
            for pat in BASE_PATTERNS:
                for m in pat.finditer(ln):
                    raw = m.group(1)
                    if len(raw) < 3:
                        continue
                    # 规范化去前导零：否则 "0800" 与 "800" 会被当成两个不同的基线值
                    num = str(int(raw))
                    hits.setdefault(num, []).append((rel(root, d), i))

    # 只看规模相近的数字簇（同一项目的不同批次基线相差不到一个数量级），
    # 避免把"1984 年""3 个模块"之类的无关数字搅进来。
    keys = sorted(hits, key=lambda k: int(k), reverse=True)
    out: list[Finding] = []
    used: set[str] = set()
    for ka in keys:
        if ka in used:
            continue
        a = int(ka)
        # 同项目的基线批次差异不会太大（15% 以上就说明是不同阶段的不同基线，
        # 那属于正常演进而非漂移）。收紧窗口可避免把 4805 与 3200 聚成一簇。
        cluster = [kb for kb in keys
                   if kb not in used and a * 0.8 <= int(kb) <= a * 1.25]
        if len(cluster) < 2:
            continue
        used.update(cluster)
        detail = "；".join(
            f"{cb}（{', '.join(f'{f}:{l}' for f, l in hits[cb][:3])}）"
            for cb in cluster
        )
        out.append(Finding(
            "L003", "error", "harness 全局", 0,
            f"疑似基线漂移：同类数字出现 {len(cluster)} 个不同值 —— {detail}",
            "基线数字必须多处同步。改动后跑 init.py 校验，或把数字只留一处、其余做指针",
        ))
    return out


def check_l004(root: str, docs: list[str]) -> list[Finding]:
    """ROUTER 注册表与磁盘失配。"""
    out = []
    router_dir = os.path.join(root, ".harness", "routing")
    router = os.path.join(router_dir, "ROUTER.md")
    content = read(router)
    if content:
        for m in re.finditer(r"`?([\w./-]*(?:capabilities|skills)/[\w./-]+\.md)`?", content):
            ref = m.group(1).strip()
            # 注册表里的路径是**相对 ROUTER.md 所在目录**的（如 capabilities/x.md、../skills/y/SKILL.md）
            cand = os.path.normpath(os.path.join(router_dir, ref))
            if not os.path.exists(cand):
                out.append(Finding(
                    "L004", "error", ".harness/routing/ROUTER.md", 0,
                    f"注册表引用的技能/能力卡不存在: {ref}",
                    "注册了但文件没了 → Agent 会找不到它",
                ))

    # 反向：磁盘上有能力卡但未注册
    cap_dir = os.path.join(root, ".harness", "routing", "capabilities")
    if os.path.isdir(cap_dir):
        for f in sorted(os.listdir(cap_dir)):
            if not f.endswith(".md") or f.startswith("_"):
                continue
            if content and f not in content:
                out.append(Finding(
                    "L004", "warn", f".harness/routing/capabilities/{f}", 0,
                    "能力卡存在但未在 ROUTER 注册",
                    "未注册 = Agent 不知道它存在 = 等于没有",
                ))

    # 技能层同理
    sk_dir = os.path.join(root, ".harness", "skills")
    if os.path.isdir(sk_dir):
        for name in sorted(os.listdir(sk_dir)):
            sk = os.path.join(sk_dir, name, "SKILL.md")
            if os.path.isfile(sk):
                if content and name not in content:
                    out.append(Finding(
                        "L004", "warn", f".harness/skills/{name}/SKILL.md", 0,
                        "技能存在但未在 ROUTER 注册",
                        "未注册的技能不会被触发",
                    ))
            elif os.path.isdir(os.path.join(sk_dir, name)):
                out.append(Finding(
                    "L004", "warn", f".harness/skills/{name}", 0,
                    "技能目录存在但没有 SKILL.md",
                    "目录存在但无入口文件，等于空壳",
                ))
    return out


def check_l005(root: str, docs: list[str], stale_days: int) -> list[Finding]:
    """文档过期：最后更新距今超过阈值。"""
    out = []
    today = date.today()
    for d in docs:
        content = read(d)
        if not content:
            continue
        # 只看文件头 40 行，避免正文里的历史日期
        head = "\n".join(content.splitlines()[:40])
        m = UPDATED.search(head)
        if not m:
            continue
        try:
            dt = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        days = (today - dt).days
        if days > stale_days:
            out.append(Finding(
                "L005", "warn", rel(root, d), 0,
                f"『最后更新』距今 {days} 天（{dt.isoformat()}）",
                "长期未更新的治理文档，很可能已有过期规则（stale rules 比缺失更有害）",
            ))
    return out


def check_l006(root: str, docs: list[str], max_items: int) -> list[Finding]:
    """强制阅读清单过长 = token 黑洞。"""
    out = []
    for d in docs:
        content = read(d)
        if not content:
            continue
        lines = content.splitlines()
        for i, ln in enumerate(lines):
            if not READ_LIST_HEAD.search(ln) or ln.strip().startswith(">"):
                continue
            # 往下数连续的列表项
            n = 0
            j = i + 1
            while j < len(lines) and j < i + 20:
                if READ_LIST_ITEM.match(lines[j]):
                    n += 1
                elif lines[j].strip() == "":
                    if n:
                        break
                elif n:
                    break
                j += 1
            if n > max_items:
                out.append(Finding(
                    "L006", "warn", rel(root, d), i + 1,
                    f"强制阅读清单有 {n} 项（阈值 {max_items}）",
                    "一次性全读是 token 黑洞。改为分级加载（L0 常驻 / L1 按需）",
                ))
    return out


def check_l007(root: str, docs: list[str]) -> list[Finding]:
    """模板占位符残留。

    仅在**已初始化**的项目里检查：模板仓库自身带占位符是设计使然
    （它就是给人填的），报它只会制造噪音。初始化的标志是脚手架生成了
    .harness/config.json。
    """
    if not os.path.isfile(os.path.join(root, ".harness", "config.json")):
        return []
    out = []
    for d in docs:
        content = read(d)
        if not content:
            continue
        keys: dict[str, int] = {}
        for i, ln in enumerate(content.splitlines(), 1):
            if is_ignored(ln):
                continue
            for m in PLACEHOLDER.finditer(ln):
                keys.setdefault(m.group(1), i)
        if keys:
            out.append(Finding(
                "L007", "warn", rel(root, d), min(keys.values()),
                f"残留占位符 {len(keys)} 个: {', '.join(sorted(keys)[:6])}"
                + (" ..." if len(keys) > 6 else ""),
                "脚手架初始化后需人工填写；未填写时 Agent 只能猜",
            ))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="harness 一致性与漂移检查")
    ap.add_argument("--root", default=None, help="仓库根（默认从脚本位置推断）")
    ap.add_argument("--only", default=None, help="只跑指定规则，逗号分隔（如 L003,L002）")
    ap.add_argument("--scope", default="governance", choices=["governance", "all"],
                    help="governance=只扫治理文档（默认，低噪音）；all=全量盘库")
    ap.add_argument("--max-read-list", type=int, default=5, help="强制阅读清单项数阈值")
    ap.add_argument("--stale-days", type=int, default=90, help="文档过期天数阈值")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else \
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(root):
        print(f"[!] 仓库根不存在: {root}", file=sys.stderr)
        return 2

    docs = collect_docs(root, args.scope)
    if not docs:
        print("[!] 未找到任何 harness 文档 —— 这本身就是异常，请检查 --root。", file=sys.stderr)
        return 2

    only = set(args.only.split(",")) if args.only else set(ALL_CHECKS)
    name_index = build_name_index(root) if ({"L001", "L002"} & only) else set()
    findings: list[Finding] = []
    if "L001" in only:
        findings += check_l001(root, docs, name_index)
    if "L002" in only:
        findings += check_l002(root, docs, name_index)
    if "L003" in only:
        findings += check_l003(root, docs)
    if "L004" in only:
        findings += check_l004(root, docs)
    if "L005" in only:
        findings += check_l005(root, docs, args.stale_days)
    if "L006" in only:
        findings += check_l006(root, docs, args.max_read_list)
    if "L007" in only:
        findings += check_l007(root, docs)

    errors = [f for f in findings if f.level == "error"]
    exit_code = 1 if errors else 0

    if args.json:
        print(json.dumps({
            "version": VERSION, "root": root.replace("\\", "/"),
            "docs_scanned": len(docs),
            "counts": {"error": len(errors),
                       "warn": len(findings) - len(errors)},
            "findings": [asdict(f) for f in findings],
            "exit_code": exit_code,
        }, ensure_ascii=False, indent=2))
        return exit_code

    print(f"\nharness 一致性检查 — {root}")
    print(f"扫描 {len(docs)} 份文档 · 发现 {len(errors)} ERROR / {len(findings) - len(errors)} WARN")
    print("=" * 64)

    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)

    if not findings:
        print("\n✅ 未发现漂移。harness 内部一致。")
    for rule in sorted(by_rule):
        bucket = by_rule[rule]
        lv = bucket[0].level
        mark = "❌" if lv == "error" else "⚠️ "
        print(f"\n--- {rule} ({len(bucket)}) ---")
        for f in bucket:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"{mark} {loc}")
            print(f"    {f.message}")
            if f.hint:
                print(f"    ↳ {f.hint}")

    print("\n" + "=" * 64)
    print(f"退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
