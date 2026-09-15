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
    L008 失效指针      决策被取代但缺少双向 superseded_by / supersedes 指针
    L009 台账一致      决策正文与 DECISIONS.md 台账状态不一致
    L010 引用已失效    文档 depends-on 了已失效的决策（STALE 水位）
    L011 欠账未声明    partial 决策缺少 gap / blocked_by

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
from datetime import date

# 模块归属只从共享清单读（单一真相源）—— 生成侧与检查侧必须认识同一份模块表，
# 否则会出现"关掉的模块仍被判死链"或"模块关不干净"。详见 module_manifest.py。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from module_manifest import MODULES, module_paths, norm_rel  # noqa: E402, F401

# 版本来自单一真相源（此前各脚本各写一份，实测已漂移：lint 1.1.1 / init 1.1.0）
from harness_version import TEMPLATE_VERSION as VERSION  # noqa: E402

# ── 读文件失败登记簿 ──
# 存在的理由：read() 返回 None 会让所有检查静默跳过，"没读到"与"读到且干净"
# 在输出上无法区分（M0 假成功）。把每次失败记下来，跑 --explain-skip 时打印，
# 就能一眼看出"这次全绿是不是因为压根没扫到东西"。
SKIPPED: list[str] = []

SCAN_TARGETS = ["AGENTS.md", "CLAUDE.md", ".harness", "docs"]
EXCLUDE_DIRS = {
    "archive",
    "node_modules",
    ".git",
    "__pycache__",
    "dist",
    "build",
    ".venv",
}

# ── 作用域：治理文档 vs 历史档案 ──
# 为什么必须区分：历史计划/评审/运行日志里天然充满绝对路径与历史数字，
# 它们**描述过去**，改它们没有意义。实测扫全量 docs/ 时 L002 产生 554 条噪音，
# 真问题（AGENTS.md 硬编码路径）被淹没——噪音淹没真报警，门禁就会被关掉。
# 默认只扫"治理文档"：Agent 每次真正会读、且应当保持正确的那些。
GOVERNANCE_EXCLUDE_DIRS = {"archive", "operations", "retrospectives", "_archive_legacy"}
GOVERNANCE_EXCLUDE_FILES = [
    re.compile(r"verification-log", re.I),
    re.compile(r"[-_]log\.md$", re.I),
    # 维护者自己的评审稿/草案：按约定以 `_` 开头。
    # 它们描述"将来可能要做的事"（引用尚未存在的文件属正常），
    # 且 new_project 不复制它们 —— 纳扫只会产生假死链。
    re.compile(r"^_.*\.md$", re.I),
]
HISTORY_DOC_DIRS = {
    "docs/specs",
    "docs/designs",
    "docs/plans",
    "docs/superpowers",
    "docs/devops",
    "docs/data-sources",
    "docs/_archive_legacy",
}

# 建索引时跳过的目录（这些不是"可引用物"，扫它们只会拖慢并制造噪音）
SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "dist",
    "build",
    ".venv",
    "venv",
    "target",
    ".next",
    ".nuxt",
    "archive",
    "coverage",
}

# ── L002 绝对路径 ──
ABS_WIN = re.compile(r"\b[a-zA-Z]:[\\/][^\s`)\]\"']*")
ABS_POSIX_HOME = re.compile(r"(?<![\w.])/(?:Users|home|mnt|opt)/[^\s`)\]\"']*")

# ── L003 基线数字 ──
# ⚠️ 中英混排的 `\b` 陷阱（实测踩到，导致 L003 完全不工作）：
# 原来写 `(?:测试|用例|tests?)\b` —— 但 `\b` 要求词边界，
# 而中文"测试通过"里的「试」与「通」都是 `\w`，两者之间**没有**词边界，
# 于是 `\b` 永远不成立 → 整条基线检查从不触发（静默失效）。
# 改用 `(?![a-zA-Z])`：只排除"后面紧跟英文字母"的情况
# （`test` 不该匹配 `testscript`），中文后无限制。
# ⚠️ 中英混排的 `\b` 陷阱（实测踩到，导致 L003 **完全不工作**）：
# 原来写 `(?:测试|用例|tests?)\b` —— 但 `\b` 要求词边界，
# 而中文「测试通过」里的「试」与「通」都是 `\w`，两者之间**没有**词边界，
# 于是 `\b` 永远不成立 → 整条基线检查从不触发，且**静默无报错**
# （看起来"没有漂移"，其实是"根本没查"）。
# 改用 `(?![a-zA-Z])`：只排除「后面紧跟英文字母」（`test` 不该匹配 `testscript`），
# 中文后则无限制。
BASE_PATTERNS = [
    re.compile(r"(\d{3,6})\s*个?\s*(?:测试|用例|tests?)(?![a-zA-Z])", re.I),
    re.compile(r"(\d{3,6})\s*(?:通过|passed)(?![a-zA-Z])", re.I),
    re.compile(r"(\d{3,6})\s*/\s*\d+\s*/\s*\d+"),  # passed/failed/skipped
    re.compile(r"(?:total|全量|基线)\D{0,12}(\d{3,6})", re.I),
]

# ── 通用：围栏代码块边界（``` / ~~~），用于"讲解用的示例不要当声明扫描" ──
FENCE = re.compile(r"^(`{3,}|~{3,})")

# ── L001 文档内引用的文件路径 ──
BACKTICK_PATH = re.compile(
    r"`([A-Za-z0-9_./\\-]+\.(?:md|py|sh|ps1|json|yaml|yml|toml|ts|tsx|js|jsx))`"
)
MD_LINK = re.compile(
    r"\]\(([^)#\s]+\.(?:md|py|sh|ps1|json|yaml|yml|toml|ts|tsx|js|jsx))\)"
)

# ── L005 最后更新 ──
UPDATED = re.compile(r"最后更新\D{0,6}(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")

# ── L006 强制阅读清单 ──
READ_LIST_HEAD = re.compile(r"(?:强制阅读|必读|MANDATORY READ|启动路径|阅读清单)", re.I)
READ_LIST_ITEM = re.compile(r"^\s*(?:\d+[.、)]|[-*])\s+\S")

# ── L007 占位符 ──  guard:allow（本节标题在描述规则，非占位实现）
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

# ── 行内豁免 ──
# 有些文档**故意**引用历史路径作为证据（如反模式库举证"某项目曾硬编码 E:\X"），
# 那不是"供使用的硬编码路径"，不该报。用法：在该行加 `lint-ignore`。
LINT_IGNORE = "lint-ignore"


def is_ignored(line: str) -> bool:
    return LINT_IGNORE in line


ALL_CHECKS = [
    "L001",
    "L002",
    "L003",
    "L004",
    "L005",
    "L006",
    "L007",
    "L008",
    "L009",
    "L010",
    "L011",
    "L012",
]


@dataclass
class Finding:
    rule: str
    level: str
    file: str
    line: int
    message: str
    hint: str = ""


def read(path: str) -> str | None:
    """读文件；读不到返回 None。

    ⚠️ 调用方必须意识到：`None` 会让 `if not content: continue` 静默跳过该文件，
    于是"文件没读到"和"文件读了没问题"在输出上**完全一样** —— 这就是 M0
    「假成功」的典型形态（实测踩过：测试时传了相对路径，所有检查静默返回 0 条，
    界面上显示"全绿"，实为一条都没扫）。

    因此：路径必须是 **绝对路径**（`collect_docs` 的产物天然如此）；
    想看"到底跳过了哪些"，跑 `python scripts/harness_lint.py --explain-skip`。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError as e:
        SKIPPED.append(f"{path} — {e.__class__.__name__}: {e.strerror or e}")
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
                dn[:] = [
                    d
                    for d in dn
                    if d not in excl and (not d.startswith(".") or d == ".harness")
                ]
                for f in fn:
                    if not f.lower().endswith((".md", ".markdown")):
                        continue
                    if scope == "governance":
                        if any(rx.search(f) for rx in GOVERNANCE_EXCLUDE_FILES):
                            continue
                        if any(
                            rel_dir == h or rel_dir.startswith(h + "/")
                            for h in HISTORY_DOC_DIRS
                        ):
                            continue
                    out.append(os.path.join(dp, f))
    return sorted(set(out))


def rel(root: str, p: str) -> str:
    return os.path.relpath(p, root).replace("\\", "/")


# ── L001 豁免：生成物与约定名（模板自身/未初始化项目里本就不存在，报它是噪音）──
# 每条都要写清"为什么它不是死链"，否则这个集合会变成垃圾桶。
IGNORE_REFS = {
    # 由 new_project.py 在生成时创建
    ".harness/config.json",
    # ↓ 以下是"教训正文里提到的历史文件名"：GLOBAL-LESSONS / harness-antipatterns
    #   在描述别项目的坑时原样引用了当时的文件名。它们**不该**在本仓库存在，
    #   但确实是真实引用（不是笔误），报出来只会让人以为文档写错了。
    "harness-tasks.json",  # SylvaPPT 时代与 state/ 并存的第二套状态（反面教材）
    "harness-progress.txt",  # 同上，Antipattern 章节列举的噪音文件
    "init.sh",  # V9 讲基线漂移时泛指"记录基线的那些文件"
    "package.json",  # 泛指；模板是 stack 无关的，不带包管理文件
    "docs/CURRENT/02-technical-specs/cv-first-architecture.md",  # SylvaPPT 真实设计文档
}


# ── 模块可插拔：被关闭模块的路径不算死链 ──
# 为什么需要：关掉某模块后，其余文档里**必然**还存在指向它的引用
# （清单文档要列举模块、总览要说明六层结构）。把这些报成死链会瞬间产生
# 几十条噪音，把真问题淹没 —— 违背"降噪即有效性"。
# 正确姿势：检查规则本身要认识"模块未启用"这个状态。
# 模块拥有的路径从共享清单读取（module_manifest.MODULES）。
# 注意：**不要**试图从磁盘反推文件名 —— 模块被关闭后其文件/目录已不存在，
# 反推只会得到空集，豁免形同虚设（这个是阳性对照抓出来的真实教训）。
MODULE_PATHS = module_paths()


def disabled_module_paths(root: str) -> set[str]:
    """返回"已关闭模块"拥有的路径集合（用于免报死链）。

    无 config.json 或无 modules 字段 → 视为全开（返回空集，保持原行为）。
    """
    cfg_path = os.path.join(root, ".harness", "config.json")
    if not os.path.isfile(cfg_path):
        return set()
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    mods = cfg.get("modules")
    if not isinstance(mods, dict):
        return set()
    out: set[str] = set()
    for mod, paths in MODULE_PATHS.items():
        if mods.get(mod, True):
            continue
        for p in paths:
            out.add(p.replace("\\", "/"))
    return out


def iter_lines_skip_fence(content: str):
    """逐行产出 (行号, 行内容)，**跳过 ``` / ~~~ 围栏内的内容**。

    为什么必须有它：文档里讲"怎么写依赖声明"时必然要在代码块里放示例，
    例如 DECISION-PROTOCOL.md 的示例 `<!-- depends-on: ADR-010, ADR-012 -->`。
    这类示例若被当成真声明扫描，就会把讲解文字误判成"文件依赖了不存在的 ADR"
    （实测 L010 在模板上唯一的命中就是这条示例）。

    围栏规则：行首（允许缩进）出现 3 个及以上连续的 ` 或 ~ 即视为围栏边界；
    记录当前围栏所用字符，只有同种字符且长度不短于开启者才算闭合。
    """
    fence: str | None = None
    for i, ln in enumerate(content.splitlines(), 1):
        stripped = ln.lstrip()
        m = FENCE.match(stripped)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker[0] * len(marker)
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        yield i, ln


def disabled_module_basenames(disabled: set[str], root: str | None = None) -> set[str]:
    """把已关闭模块的路径集合转成 basename 集合，供"裸文件名引用"比对。

    为什么必须双面比对：文档里引用同一个产物有两种写法 ——
    全路径（`scripts/no_placeholder_guard.py`）和裸名（`hardening-checklist.md`，
    常见于表格列、清单项）。只比全路径会漏掉后者，豁免就形同虚设
    （实测：33 条死链一条都没豁免掉）。

    root 参数保留只为兼容旧调用；文件名一律来自共享清单的静态声明，
    不从磁盘扫描（原因见 MODULE_PATHS 上方注释）。
    """
    names: set[str] = set()
    for p in disabled:
        pn = p.replace("\\", "/").rstrip("/")
        if not pn:
            continue
        names.add(pn.rsplit("/", 1)[-1])
    return names


def is_real_path_ref(ref: str) -> bool:
    """过滤掉明显不是文件引用的东西。

    排除三类（每一类都是实测踩出来的误报源）：
    1. 含通配/重定向字符 —— `src/**`、`a > b`
    2. 命令行而非路径 —— `npm run build`、`git commit`
    3. **示例占位名** —— `xxx.ts`、`yyy.json`、`foo.md`、`<name>`
       文档里常拿它们当"你应该建一个这样的文件"的示意，
       不是真的引用某份已存在文件（`AGENTS-guidelines.md` 里的表格就用了 `xxx.ts`）。
    """
    if any(c in ref for c in "*?<>|"):
        return False
    if ref.startswith(("http", "git@", "npm ", "pip ", "python ", "git ")):
        return False
    if " " in ref:
        return False
    # 示例占位名：`xxx` / `yyy` / `zzz` / `foo` / `bar` / `baz` 等
    stem = ref.replace("\\", "/").rsplit("/", 1)[-1].split(".", 1)[0].lower()
    if stem in {
        "xxx",
        "yyy",
        "zzz",
        "foo",
        "bar",
        "baz",
        "qux",
        "yourfile",
        "your_file",
        "filename",
        "somefile",
        "example",
    }:
        return False
    if stem and len(set(stem)) == 1 and stem[0].isalpha():
        return False  # `xxx` / `aaa` / `x` 这类重复单字符
    # 4. **包/工程基建文件名** —— 文档里提到它们几乎总是在「列举一类文件」
    #    （如"排除 __init__.py / conftest.py / setup.py"），
    #    而不是"引用本仓库里的某个具体文件"。
    #    实测不加这条，CAPABILITIES.md 的一行列举就产生 7 条误报。
    if ref.replace("\\", "/").rsplit("/", 1)[-1].lower() in {
        "__init__.py",
        "conftest.py",
        "setup.py",
        "manage.py",
        "settings.py",
        "wsgi.py",
        "asgi.py",
        "py.typed",
    }:
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
        dn[:] = [
            d
            for d in dn
            if d not in SKIP_DIRS and not d.startswith(".") or d == ".harness"
        ]
        for f in fn:
            rel_p = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            for v in (f, rel_p):
                idx.add(v)
                # 小写兜底：Windows 文件名不区分大小写，文档里手写的大小写偏差
                # （如 state-protocol.md vs STATE-PROTOCOL.md）不该报成死链
                idx.add(v.lower())
    return idx


def check_l001(
    root: str, docs: list[str], name_index: set[str], disabled: set[str] | None = None
) -> list[Finding]:
    """死链接：引用的本项目文件在仓库内找不到同名/同路径文件。

    disabled：已关闭模块的路径集合 —— 跳过它们（模块没启用，文件本就不该存在）。
    比对同时覆盖「全路径」与「裸 basename」两种引用写法，否则表格/清单里的
    裸名引用会照报不误（这是实测踩到的坑，详见 disabled_module_basenames）。
    """
    disabled = disabled or set()
    disabled_names = disabled_module_basenames(disabled, root)
    out = []
    for d in docs:
        content = read(d)
        if not content:
            continue
        for i, ln in iter_lines_skip_fence(content):
            if is_ignored(ln):
                continue
            for pat in (BACKTICK_PATH, MD_LINK):
                for m in pat.finditer(ln):
                    ref = m.group(1)
                    if not is_real_path_ref(ref):
                        continue
                    if "archive" in ref:
                        continue
                    norm = norm_rel(ref)
                    # 属于已关闭模块 → 不是死链（模块未启用，跳过错开）
                    # 面①：全路径前缀/相等；面②：裸 basename 命中该模块的产物名
                    if (
                        any(
                            norm.startswith(dp)
                            or ("/" + dp) in ("/" + norm)
                            or norm == dp.rstrip("/")
                            for dp in disabled
                        )
                        or norm.rsplit("/", 1)[-1] in disabled_names
                    ):
                        continue
                    if ref in IGNORE_REFS or norm in IGNORE_REFS:
                        continue
                    # ① 绝对/根相对路径存在 ② 文档同目录相对存在 ③ 仓库内存在同名文件
                    if os.path.exists(os.path.join(root, ref)):
                        continue
                    if os.path.exists(os.path.join(os.path.dirname(d), ref)):
                        continue
                    base = os.path.basename(norm)
                    if (
                        base in name_index
                        or base.lower() in name_index
                        or norm in name_index
                        or norm.lower() in name_index
                    ):
                        continue
                    out.append(
                        Finding(
                            "L001",
                            "warn",
                            rel(root, d),
                            i,
                            f"引用的文件在仓库内找不到: {ref}",
                            "文件已改名/迁移但引用未更新（重构漏改的典型）；若只是文档里的示例名，可忽略",
                        )
                    )
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
        for i, ln in iter_lines_skip_fence(content):
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
                out.append(
                    Finding(
                        "L002",
                        "error",
                        rel(root, d),
                        i,
                        f"硬编码绝对路径: {raw[:70]}",
                        "改用仓库相对路径（clone 到别处/换机器都会失效）",
                    )
                )
                break
    return out


def check_l003(root: str, docs: list[str]) -> list[Finding]:
    """基线漂移：同一类基线数字出现多个互相矛盾的值。"""
    hits: dict[str, list[tuple[str, int]]] = {}
    for d in docs:
        content = read(d)
        if not content:
            continue
        for i, ln in iter_lines_skip_fence(content):
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
        cluster = [
            kb for kb in keys if kb not in used and a * 0.8 <= int(kb) <= a * 1.25
        ]
        if len(cluster) < 2:
            continue
        used.update(cluster)
        detail = "；".join(
            f"{cb}（{', '.join(f'{fn}:{ln}' for fn, ln in hits[cb][:3])}）"
            for cb in cluster
        )
        out.append(
            Finding(
                "L003",
                "error",
                "harness 全局",
                0,
                f"疑似基线漂移：同类数字出现 {len(cluster)} 个不同值 —— {detail}",
                "基线数字必须多处同步。改动后跑 init.py 校验，或把数字只留一处、其余做指针",
            )
        )
    return out


def check_l004(
    root: str, docs: list[str], disabled: set[str] | None = None
) -> list[Finding]:
    """ROUTER 注册表与磁盘失配。

    disabled：已关闭模块的路径集合。**必须传**，否则 ROUTER.md（⑤技能层，开启）
    里指向 skills 模块（⑤技能层，可能被关闭）的注册项会被判成 error ——
    实测在 `--disable skills` 的项目上，L004 稳定报 3 条假 ERROR。
    这正是 MODULES.md 铁律④「检查规则本身必须认识模块已关闭状态」的反面教材：
    规则只认磁盘、不认开关，可插拔就等于半残。
    """
    disabled = disabled or set()
    disabled_names = disabled_module_basenames(disabled, root)
    out = []
    router_dir = os.path.join(root, ".harness", "routing")
    router = os.path.join(router_dir, "ROUTER.md")
    content = read(router)
    if content:
        for m in re.finditer(
            r"`?([\w./-]*(?:capabilities|skills)/[\w./-]+\.md)`?", content
        ):
            ref = m.group(1).strip()
            # 属于已关闭模块 → 不是失配（模块没启用，文件本就不该存在）
            norm = norm_rel(ref)
            if (
                any(
                    norm.startswith(dp)
                    or ("/" + dp) in ("/" + norm)
                    or norm == dp.rstrip("/")
                    for dp in disabled
                )
                or norm.rsplit("/", 1)[-1] in disabled_names
            ):
                continue
            # 注册表里的路径是**相对 ROUTER.md 所在目录**的（如 capabilities/x.md、../skills/y/SKILL.md）
            cand = os.path.normpath(os.path.join(router_dir, ref))
            if not os.path.exists(cand):
                out.append(
                    Finding(
                        "L004",
                        "error",
                        ".harness/routing/ROUTER.md",
                        0,
                        f"注册表引用的技能/能力卡不存在: {ref}",
                        "注册了但文件没了 → Agent 会找不到它",
                    )
                )

    # 反向：磁盘上有能力卡但未注册
    cap_dir = os.path.join(root, ".harness", "routing", "capabilities")
    if os.path.isdir(cap_dir):
        for f in sorted(os.listdir(cap_dir)):
            if not f.endswith(".md") or f.startswith("_"):
                continue
            if norm_rel(f".harness/routing/capabilities/{f}") in disabled:
                continue
            if content and f not in content:
                out.append(
                    Finding(
                        "L004",
                        "warn",
                        f".harness/routing/capabilities/{f}",
                        0,
                        "能力卡存在但未在 ROUTER 注册",
                        "未注册 = Agent 不知道它存在 = 等于没有",
                    )
                )

    # 技能层同理
    sk_dir = os.path.join(root, ".harness", "skills")
    if os.path.isdir(sk_dir):
        for name in sorted(os.listdir(sk_dir)):
            sk = os.path.join(sk_dir, name, "SKILL.md")
            if norm_rel(f".harness/skills/{name}/SKILL.md") in disabled:
                continue
            if os.path.isfile(sk):
                if content and name not in content:
                    out.append(
                        Finding(
                            "L004",
                            "warn",
                            f".harness/skills/{name}/SKILL.md",
                            0,
                            "技能存在但未在 ROUTER 注册",
                            "未注册的技能不会被触发",
                        )
                    )
            elif os.path.isdir(os.path.join(sk_dir, name)):
                out.append(
                    Finding(
                        "L004",
                        "warn",
                        f".harness/skills/{name}",
                        0,
                        "技能目录存在但没有 SKILL.md",
                        "目录存在但无入口文件，等于空壳",
                    )
                )
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
            out.append(
                Finding(
                    "L005",
                    "warn",
                    rel(root, d),
                    0,
                    f"『最后更新』距今 {days} 天（{dt.isoformat()}）",
                    "长期未更新的治理文档，很可能已有过期规则（stale rules 比缺失更有害）",
                )
            )
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
                out.append(
                    Finding(
                        "L006",
                        "warn",
                        rel(root, d),
                        i + 1,
                        f"强制阅读清单有 {n} 项（阈值 {max_items}）",
                        "一次性全读是 token 黑洞。改为分级加载（L0 常驻 / L1 按需）",
                    )
                )
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
        for i, ln in iter_lines_skip_fence(content):
            if is_ignored(ln):
                continue
            for m in PLACEHOLDER.finditer(ln):
                keys.setdefault(m.group(1), i)
        if keys:
            out.append(
                Finding(
                    "L007",
                    "warn",
                    rel(root, d),
                    min(keys.values()),
                    f"残留占位符 {len(keys)} 个: {', '.join(sorted(keys)[:6])}"
                    + (" ..." if len(keys) > 6 else ""),
                    "脚手架初始化后需人工填写；未填写时 Agent 只能猜",
                )
            )
    return out


# ─── L008-L011：决策演进校验 ───
# 为什么需要：决策记录若"有文档无状态"，会退化成"看起来定了、实际没做、
# 且没人知道哪条还有效"。实测 UGSimulator 12 条 ADR 无一标注 superseded，
# ADR-012 的验收标准全未勾选却无人追踪 —— 这就是本组规则要消灭的形态。
# 详见 .harness/DECISION-PROTOCOL.md

DECISION_DIR = os.path.join(".harness", "planning")
DECISIONS_LEDGER = os.path.join(DECISION_DIR, "DECISIONS.md")
DECISION_BODY_DIR = os.path.join(DECISION_DIR, "decisions")

VALID_STATUS = {
    "proposed",
    "accepted",
    "partial",
    "superseded",
    "rejected",
    "deprecated",
}

FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
FM_LINE = re.compile(r"^([a-z_]+):\s*(.*)$")
ADR_ID = re.compile(r"ADR-(\d{3})")

# depends-on 声明（HTML 注释形式，不污染正文渲染）
DEPENDS_ON = re.compile(r"<!--\s*depends-on:\s*([^>]*?)-->")


def parse_frontmatter(text: str) -> dict[str, str]:
    """解析 ADR 正文的 YAML frontmatter（极简实现，只支持 key: value 与 [a, b]）。

    为什么不用 yaml 库：模板必须零第三方依赖（用户 clone 即用，不装包）。
    frontmatter 结构由模板固定，简单解析足够。
    """
    m = FRONTMATTER.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for ln in m.group(1).splitlines():
        mm = FM_LINE.match(ln.strip())
        if mm:
            out[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return out


def parse_list_field(raw: str) -> list[str]:
    """把 `[ADR-001, ADR-002]` 或 `ADR-001` 解析成编号列表。"""
    if not raw or raw in ("[]", '""', "''"):
        return []
    s = raw.strip().strip("[]")
    return [x.strip().strip('"').strip("'") for x in s.split(",") if x.strip()]


def collect_adr_bodies(root: str) -> dict[str, dict[str, str]]:
    """收集所有 ADR 正文的 frontmatter，键为 ADR-NNN。"""
    out: dict[str, dict[str, str]] = {}
    d = os.path.join(root, DECISION_BODY_DIR)
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if not f.lower().endswith(".md"):
            continue
        p = os.path.join(d, f)
        content = read(p)
        if not content:
            continue
        fm = parse_frontmatter(content)
        adr = fm.get("adr", "")
        if adr and adr.upper() != "ADR-NNN":  # 跳过模板本身
            out[adr.upper()] = fm
            out[adr.upper()]["_file"] = f
    return out


def parse_ledger(root: str) -> dict[str, dict[str, str]]:
    """从 DECISIONS.md 的 §1 状态表解析出 编号 → {状态, 取代关系}。

    只解析表格行（以 | ADR- 开头）。表格列顺序：
      编号 | 标题 | 状态 | 日期 | 取代关系 | 落地证据 | 文件
    """
    p = os.path.join(root, DECISIONS_LEDGER)
    content = read(p)
    if not content:
        return {}
    out: dict[str, dict[str, str]] = {}
    for ln in content.splitlines():
        s = ln.strip()
        if not s.startswith("|") or "ADR-" not in s:
            continue
        cols = [c.strip() for c in s.strip("|").split("|")]
        if len(cols) < 3:
            continue
        m = ADR_ID.search(cols[0])
        if not m:
            continue
        adr = "ADR-" + m.group(1)
        status = cols[2].strip("`* ").lower()
        out[adr] = {"status": status, "rel": cols[4] if len(cols) > 4 else ""}
    return out


def check_l008(root: str, bodies: dict[str, dict[str, str]]) -> list[Finding]:
    """L008 失效指针完整性：superseded 必须有 superseded_by；双向指针必须闭合。"""
    out: list[Finding] = []
    for adr, fm in sorted(bodies.items()):
        status = fm.get("status", "").strip().lower()
        sup_by = fm.get("superseded_by", "").strip()
        supersedes = parse_list_field(fm.get("supersedes", ""))
        f = fm.get("_file", "")

        # ① 已失效但没写被谁取代
        if status == "superseded" and not sup_by:
            out.append(
                Finding(
                    "L008",
                    "error",
                    f"{DECISION_BODY_DIR}/{f}",
                    0,
                    f"{adr} 状态为 superseded 但未填 superseded_by",
                    "失效指针缺失 → Agent 无法知道该改看哪条决策。填 frontmatter 的 superseded_by",
                )
            )

        # ② superseded_by 指向的 ADR 必须存在
        if sup_by:
            target = sup_by.upper()
            if ADR_ID.match(target) and target not in bodies:
                out.append(
                    Finding(
                        "L008",
                        "error",
                        f"{DECISION_BODY_DIR}/{f}",
                        0,
                        f"{adr} 的 superseded_by 指向不存在的 {target}",
                        "指针悬空 → 顺着它读不到任何东西",
                    )
                )
            # ③ 反向指针必须闭合
            elif target in bodies:
                back = parse_list_field(bodies[target].get("supersedes", ""))
                if adr not in back:
                    out.append(
                        Finding(
                            "L008",
                            "error",
                            f"{DECISION_BODY_DIR}/{bodies[target]['_file']}",
                            0,
                            f"{target} 被 {adr} 取代，但 {target} 未声明 supersedes: [{adr}]",
                            "双向指针缺一侧 → 链路断裂，Agent 可能顺旧指针继续走",
                        )
                    )

        # ④ supersedes 指向的 ADR 必须存在，且反向指针必须闭合
        for old in supersedes:
            if not ADR_ID.match(old):
                continue
            if old not in bodies:
                out.append(
                    Finding(
                        "L008",
                        "error",
                        f"{DECISION_BODY_DIR}/{f}",
                        0,
                        f"{adr} 声明取代 {old}，但该 ADR 不存在",
                        "指向不存在的决策（编号写错或文件丢失）",
                    )
                )
                continue
            # 反向：旧的必须回指 superseded_by = 本条
            back = bodies[old].get("superseded_by", "").strip().upper()
            back_status = bodies[old].get("status", "").strip().lower()
            if back != adr:
                out.append(
                    Finding(
                        "L008",
                        "error",
                        f"{DECISION_BODY_DIR}/{bodies[old].get('_file', '')}",
                        0,
                        f"{adr} 声明取代 {old}，但 {old} 未回指（superseded_by 应为 {adr}）",
                        "双向指针缺一侧 → 链路断裂，Agent 可能顺旧指针继续走"
                        + (
                            f"；且 {old} 状态仍为 {back_status}，未标记为 superseded"
                            if back_status != "superseded"
                            else ""
                        ),
                    )
                )
    return out


def check_l009(root: str, bodies: dict[str, dict[str, str]]) -> list[Finding]:
    """L009 台账与正文状态一致性。

    两边不一致时以**台账**为准（协议 §2 铁律 3），但必须报出来让人改正文。
    """
    ledger = parse_ledger(root)
    if not ledger:
        return []
    out: list[Finding] = []
    for adr, fm in sorted(bodies.items()):
        body_status = fm.get("status", "").strip().lower()

        # ① 状态值合法性：**先查，不受是否登记台账影响**
        # （阳性对照抓到的 bug：原实现把这条放在 ledger 检查之后，
        #   未登记的 ADR 会 continue 跳过，非法状态值被静默漏过）
        if body_status and body_status not in VALID_STATUS:
            out.append(
                Finding(
                    "L009",
                    "error",
                    f"{DECISION_BODY_DIR}/{fm.get('_file', '')}",
                    0,
                    f"{adr} 状态值非法: {body_status}",
                    f"必须为五态之一: {', '.join(sorted(VALID_STATUS))}",
                )
            )

        # ② 未登记台账
        if adr not in ledger:
            out.append(
                Finding(
                    "L009",
                    "warn",
                    f"{DECISION_BODY_DIR}/{fm.get('_file', '')}",
                    0,
                    f"{adr} 有正文但未登记到 DECISIONS.md 状态表",
                    "台账是唯一权威源 → 未登记的决策等于不存在",
                )
            )
            continue

        # ③ 台账与正文状态一致性
        ledger_status = ledger[adr]["status"]
        if body_status and ledger_status and body_status != ledger_status:
            out.append(
                Finding(
                    "L009",
                    "error",
                    f"{DECISION_BODY_DIR}/{fm.get('_file', '')}",
                    0,
                    f"{adr} 状态不一致：正文={body_status} / 台账={ledger_status}",
                    "以台账为准，但两者必须同步改（Agent 可能只读到其中一处）",
                )
            )
    return out
    # 台账登记了但正文不存在
    for adr in sorted(ledger):
        if adr not in bodies:
            out.append(
                Finding(
                    "L009",
                    "error",
                    DECISIONS_LEDGER,
                    0,
                    f"台账登记了 {adr} 但 decisions/ 下无对应正文",
                    "死指针 → 顺着台账读不到论证",
                )
            )
    return out


def check_l010(
    root: str, docs: list[str], bodies: dict[str, dict[str, str]]
) -> list[Finding]:
    """L010 引用已失效决策（STALE 检测）。

    文档头部写 `<!-- depends-on: ADR-010 -->`，若依赖的决策已失效 → 报 STALE。
    **首轮为 warn**：历史项目升级会一次报很多条，立刻拦提交会被关掉门禁
    （"降噪即有效性"原则）。稳定后再升 error。

    扫描时**跳过围栏代码块**（见 iter_lines_skip_fence）：协议文档里必然有
    "怎么写声明"的示例，示例被当声明扫会造成假 STALE。
    """
    dead: dict[str, str] = {}
    for adr, fm in bodies.items():
        st = fm.get("status", "").strip().lower()
        if st in ("superseded", "deprecated"):
            dead[adr] = st
    if not dead:
        return []

    out: list[Finding] = []
    for d in docs:
        content = read(d)
        if not content:
            continue
        for i, ln in iter_lines_skip_fence(content):
            if is_ignored(ln):
                continue
            for m in DEPENDS_ON.finditer(ln):
                for ref in parse_list_field(m.group(1)):
                    ref = ref.upper()
                    if ref in dead:
                        out.append(
                            Finding(
                                "L010",
                                "warn",
                                rel(root, d),
                                i,
                                f"STALE：本文件依赖的 {ref} 已失效（{dead[ref]}）",
                                "先读 DECISIONS.md 确认现行决策，然后更新本文或移入 archive/",
                            )
                        )
    return out


def check_l012(root: str) -> list[Finding]:
    """L012 模块清单自洽（`module_manifest` 的不变式）。

    为什么需要它（实测踩到的真实事故）：
    `sync_lib.py` 曾**同时**出现在 `verification` 与 `upgrade` 的 `owned` 里。
    由于生成侧是「**排除优先于包含**」（文件只要落在任一"已关闭模块"的
    owned 里就会被排除），结果是 minimal/standard 档生成的项目里
    `new_project.py` 一跑就 `ModuleNotFoundError: No module named 'sync_lib'`。
    —— **清单自己矛盾，却没有任何地方检查过。**

    另外 `MODULE_REQUIRED`（体检红线）与 `MODULES[].owned`（复制依据）
    语义不同但必须满足 `required ⊆ owned`，也容易改一边忘一边。

    校验项见 `module_manifest.self_check` 的 docstring。
    """
    try:
        from module_manifest import self_check  # noqa: PLC0415
    except ImportError:
        # 清单不在（模块被关闭或未生成）→ 本规则无对象可查，明确跳过
        return []
    out: list[Finding] = []
    for p in self_check(root):
        out.append(
            Finding(
                "L012",
                "error",
                "scripts/module_manifest.py",
                0,
                p,
                "清单是生成过滤与检查豁免的共同依据；自相矛盾会让行为不可预期"
                "（典型后果：某档位生成的项目里脚本一跑就 ModuleNotFoundError）",
            )
        )
    return out


def check_l011(root: str, bodies: dict[str, dict[str, str]]) -> list[Finding]:
    """L011 partial 决策必须写明 gap 与 blocked_by。

    partial（已决未落地）是最危险的形态：看起来已经定了，实际没做。
    实测 ADR-012 就是这个形态 —— 它自己写了"留到 Gap 3 一并做"，
    但没有机器可查的标记，于是没人追踪。
    """
    out: list[Finding] = []
    for adr, fm in sorted(bodies.items()):
        if fm.get("status", "").strip().lower() != "partial":
            continue
        f = fm.get("_file", "")
        if not fm.get("gap", "").strip():
            out.append(
                Finding(
                    "L011",
                    "error",
                    f"{DECISION_BODY_DIR}/{f}",
                    0,
                    f"{adr} 状态为 partial 但 gap 为空",
                    "已决未落地必须写明『还差什么』，否则新 Agent 会以为已生效",
                )
            )
        if not fm.get("blocked_by", "").strip():
            out.append(
                Finding(
                    "L011",
                    "error",
                    f"{DECISION_BODY_DIR}/{f}",
                    0,
                    f"{adr} 状态为 partial 但 blocked_by 为空",
                    "必须写明『为何没做』——这是后续能否接手的唯一线索",
                )
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="harness 一致性与漂移检查")
    ap.add_argument("--root", default=None, help="仓库根（默认从脚本位置推断）")
    ap.add_argument(
        "--only", default=None, help="只跑指定规则，逗号分隔（如 L003,L002）"
    )
    ap.add_argument(
        "--scope",
        default="governance",
        choices=["governance", "all"],
        help="governance=只扫治理文档（默认，低噪音）；all=全量盘库",
    )
    ap.add_argument("--max-read-list", type=int, default=5, help="强制阅读清单项数阈值")
    ap.add_argument("--stale-days", type=int, default=90, help="文档过期天数阈值")
    ap.add_argument(
        "--explain-skip",
        action="store_true",
        help="打印所有『没读到而被静默跳过』的文件（防假成功）",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = (
        os.path.abspath(args.root)
        if args.root
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if not os.path.isdir(root):
        print(f"[!] 仓库根不存在: {root}", file=sys.stderr)
        return 2

    docs = collect_docs(root, args.scope)
    if not docs:
        print(
            "[!] 未找到任何 harness 文档 —— 这本身就是异常，请检查 --root。",
            file=sys.stderr,
        )
        return 2

    only = set(args.only.split(",")) if args.only else set(ALL_CHECKS)
    name_index = build_name_index(root) if ({"L001", "L002"} & only) else set()
    disabled = disabled_module_paths(root)
    findings: list[Finding] = []
    if "L001" in only:
        findings += check_l001(root, docs, name_index, disabled)
    if "L002" in only:
        findings += check_l002(root, docs, name_index)
    if "L003" in only:
        findings += check_l003(root, docs)
    if "L004" in only:
        findings += check_l004(root, docs, disabled)
    if "L005" in only:
        findings += check_l005(root, docs, args.stale_days)
    if "L006" in only:
        findings += check_l006(root, docs, args.max_read_list)
    if "L007" in only:
        findings += check_l007(root, docs)

    # L012 清单自洽：不依赖任何可选模块（清单文件本身缺失时规则内部会明确跳过），
    # 所以放在主流程，不进 decision_checks 组。
    if "L012" in only:
        findings += check_l012(root)

    # 决策演进组：只有存在 planning/decisions/ 时才跑（可插拔 —— 未启用 decisions
    # 模块的项目不该被这些规则打扰）。这是"缺失即降级，不报错"的落地。
    decision_checks = {"L008", "L009", "L010", "L011"} & only
    if decision_checks:
        if os.path.isdir(os.path.join(root, DECISION_BODY_DIR)):
            bodies = collect_adr_bodies(root)
            if "L008" in decision_checks:
                findings += check_l008(root, bodies)
            if "L009" in decision_checks:
                findings += check_l009(root, bodies)
            if "L010" in decision_checks:
                findings += check_l010(root, docs, bodies)
            if "L011" in decision_checks:
                findings += check_l011(root, bodies)
        else:
            # 显式声明跳过原因（不静默）
            print(
                f"[SKIP] {DECISION_BODY_DIR}/ 不存在 → 跳过决策演进检查 "
                f"({', '.join(sorted(decision_checks))})",
                file=sys.stderr,
            )

    errors = [f for f in findings if f.level == "error"]
    exit_code = 1 if errors else 0

    if args.json:
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "root": root.replace("\\", "/"),
                    "docs_scanned": len(docs),
                    "counts": {
                        "error": len(errors),
                        "warn": len(findings) - len(errors),
                    },
                    "findings": [asdict(f) for f in findings],
                    "exit_code": exit_code,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return exit_code

    print(f"\nharness 一致性检查 — {root}")
    print(
        f"扫描 {len(docs)} 份文档 · 发现 {len(errors)} ERROR / {len(findings) - len(errors)} WARN"
    )
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
    if SKIPPED:
        # 不静默：被跳过的文件必须显式露面，否则"全绿"可能是假象
        print(f"\n⚠️  {len(SKIPPED)} 次读取失败（被静默跳过 → 其结果未纳入检查）:")
        for s in SKIPPED[:20]:
            print(f"    · {s}")
        if len(SKIPPED) > 20:
            print(f"    … 另有 {len(SKIPPED) - 20} 条（--explain-skip 看全量）")
    print(f"退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
