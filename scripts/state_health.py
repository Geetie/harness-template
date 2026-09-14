#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
state_health.py — 状态层健康检查与归档

为什么需要它
------------
harness 的状态层目标是「让 Agent 快速了解项目到哪了」。但状态文件**只增不减**，
最终会变成 Agent 读不动也读不完的档案：

    实测（2026-09 三个真实项目）：
      UGSimulator  feature_list.json 192 KB · progress.md 122 KB
      SylvaPPT     progress.md        58 KB · AGENTS.md   41 KB（540 行）
      AI投股工作台  progress.md        45 KB

    192 KB 的 JSON ≈ 50K token —— Agent 光读状态就烧掉半个上下文。

这与 harness 要治的 context rot 是**同一个病**，只是发生在磁盘上。
根因：只规定了「怎么写」（一行式），没规定「留多久」（生命周期）。

本脚本补上生命周期：
  1. 按阈值检查各状态文件的体积 / 行数 / 条目数
  2. `--archive` 把超期内容移入 `.harness/state/archive/`（git 保留历史，Agent 不再读）

用法
----
    python scripts/state_health.py                  # 只检查
    python scripts/state_health.py --json           # 结构化输出
    python scripts/state_health.py --dry-run --archive   # 看会归档什么，不实际写
    python scripts/state_health.py --archive        # 执行归档

阈值（写在 .harness/config.json 的 limits 段可覆盖）
---------------------------------------------------
    AGENTS.md           16 KB / 150 行
    progress.md         32 KB / 300 行（变更日志保留最近 120 行）
    session-handoff.md  16 KB / 200 行
    feature_list.json   64 KB / 150 条目（completed 保留最近 60 条）

退出码
------
    0  全部在阈值内
    1  有超限项（需归档或精简）
    2  配置/路径错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime

VERSION = "1.0.0"

DEFAULT_LIMITS = {
    "AGENTS.md": {"max_bytes": 16 * 1024, "max_lines": 150},
    "progress.md": {"max_bytes": 32 * 1024, "max_lines": 300, "keep_log_lines": 120},
    "session-handoff.md": {"max_bytes": 16 * 1024, "max_lines": 200},
    "feature_list.json": {"max_bytes": 64 * 1024, "max_items": 150, "keep_completed": 60},
}

STATE_DIR = ".harness/state"
ARCHIVE_DIR = ".harness/state/archive"

# 常见的"第二套状态"散件——它们与 state/ 三件功能重叠，是状态层分裂的信号
ROGUE_STATE_PATTERNS = [
    re.compile(r"^harness[-_].*\.(json|txt|md|log)$", re.I),
    re.compile(r"^.*[-_]progress\.(txt|log)$", re.I),
    re.compile(r"^\.harness-active$", re.I),
    re.compile(r"^harness-progress", re.I),
]


@dataclass
class Finding:
    level: str        # "error" | "warn" | "info"
    target: str
    message: str
    hint: str = ""


def read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def load_config(root: str) -> dict:
    p = os.path.join(root, ".harness", "config.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def check_files(root: str, limits: dict) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    metrics: dict[str, dict] = {}

    for name, lim in limits.items():
        # AGENTS.md 在根，其余在 state/
        cand = [os.path.join(root, name), os.path.join(root, STATE_DIR, name)]
        path = next((p for p in cand if os.path.isfile(p)), None)
        if not path:
            metrics[name] = {"exists": False}
            continue

        size = os.path.getsize(path)
        content = read_text(path) or ""
        # 用 splitlines 而不是 count("\n")+1：后者会把文件末尾的换行多算成一行，
        # 导致"编辑器显示 150 行"与"工具报 151 行"不一致（实测踩到）。
        lines = len(content.splitlines())
        metrics[name] = {
            "exists": True,
            "path": os.path.relpath(path, root).replace("\\", "/"),
            "bytes": size,
            "lines": lines,
        }

        mb = lim.get("max_bytes")
        ml = lim.get("max_lines")
        if mb and size > mb:
            findings.append(Finding(
                "error", name,
                f"体积 {size:,} bytes 超过上限 {mb:,}（{size / mb:.1f}x）",
                "执行 --archive 归档，或人工精简。状态文件是给 Agent 读的，不是档案",
            ))
        elif mb and size > mb * 0.8:
            findings.append(Finding(
                "warn", name,
                f"体积 {size:,} bytes 已达上限 {mb:,} 的 {size / mb:.0%}",
                "提前规划归档",
            ))
        if ml and lines > ml:
            findings.append(Finding(
                "error", name,
                f"行数 {lines} 超过上限 {ml}",
                "外推内容到 skills/memory，或归档历史",
            ))

    # feature_list.json 条目数 + completed 比例
    fl_path = os.path.join(root, STATE_DIR, "feature_list.json")
    if os.path.isfile(fl_path):
        try:
            with open(fl_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            feats = data.get("features", []) if isinstance(data, dict) else []
            lim = limits.get("feature_list.json", {})
            mi = lim.get("max_items")
            done = [x for x in feats if isinstance(x, dict) and x.get("status") == "completed"]
            metrics["feature_list.json"].update({
                "items": len(feats),
                "completed": len(done),
                "completed_ratio": round(len(done) / len(feats), 3) if feats else 0,
            })
            if mi and len(feats) > mi:
                findings.append(Finding(
                    "error", "feature_list.json",
                    f"条目数 {len(feats)} 超过上限 {mi}",
                    "执行 --archive 把已完成的旧条目移入归档区",
                ))
        except json.JSONDecodeError as e:
            findings.append(Finding(
                "error", "feature_list.json",
                f"JSON 解析失败（并发写常见）: {e}",
                "用工具重写为合法 JSON；不要手拼",
            ))

    return findings, metrics


def check_rogue_state(root: str) -> list[Finding]:
    """检测根目录下的'第二套状态'散件——状态层分裂的信号。"""
    findings: list[Finding] = []
    official = {"AGENTS.md", "CLAUDE.md", "README.md"}
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return findings
    for e in entries:
        p = os.path.join(root, e)
        if not os.path.isfile(p) or e in official:
            continue
        if any(rx.match(e) for rx in ROGUE_STATE_PATTERNS):
            size = os.path.getsize(p)
            level = "error" if size == 0 else "warn"
            findings.append(Finding(
                level, e,
                f"疑似第二套状态文件（{size:,} bytes）"
                + ("，且为空文件" if size == 0 else ""),
                "状态层只允许 state/ 三件。历史流水请归档，空文件请删除",
            ))
    return findings


def find_section_lines(lines: list[str], heading_pattern: str) -> tuple[int, int]:
    """返回 [start, end) —— §10 之类的章节范围（不含标题行本身）。"""
    start = -1
    for i, ln in enumerate(lines):
        if re.search(heading_pattern, ln):
            start = i
            break
    if start < 0:
        return -1, -1
    for j in range(start + 1, len(lines)):
        if re.match(r"^#{1,3}\s", lines[j]):
            return start + 1, j
    return start + 1, len(lines)


def archive_progress_log(root: str, keep: int, dry: bool) -> tuple[str | None, int]:
    """把 progress.md 变更日志中超出 keep 的最老行移入归档文件。"""
    path = os.path.join(root, STATE_DIR, "progress.md")
    content = read_text(path)
    if not content:
        return None, 0
    lines = content.splitlines(keepends=True)
    s, e = find_section_lines(lines, r"^#{1,3}\s*.*(§?\s*10|变更日志)")
    if s < 0:
        return None, 0

    log_idx = [i for i in range(s, e) if lines[i].lstrip().startswith("|")]
    # 前两行通常是表头与分隔行
    data_idx = [i for i in log_idx if not re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[i])]
    header_idx = data_idx[:1]
    body_idx = data_idx[1:]
    if len(body_idx) <= keep:
        return None, 0

    move = body_idx[: len(body_idx) - keep]
    stamp = datetime.now().strftime("%Y-%m")
    arc_dir = os.path.join(root, ARCHIVE_DIR)
    arc_path = os.path.join(arc_dir, f"progress-log-{stamp}.md")

    if not dry:
        os.makedirs(arc_dir, exist_ok=True)
        header = "".join(lines[i] for i in header_idx) or "| 日期 | 变更 |\n"
        sep = "| --- | --- |\n"
        with open(arc_path, "a", encoding="utf-8") as f:
            f.write(f"\n## 归档 {datetime.now().isoformat(timespec='seconds')}\n\n")
            f.write(header if header.endswith("\n") else header + "\n")
            f.write(sep)
            for i in move:
                f.write(lines[i])
        keep_set = set(move)
        new_lines = [ln for i, ln in enumerate(lines) if i not in keep_set]
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(new_lines))

    return os.path.relpath(arc_path, root).replace("\\", "/"), len(move)


def archive_feature_list(root: str, keep_completed: int, dry: bool) -> tuple[str | None, int]:
    """把 feature_list.json 中最早的 completed 条目移入归档文件。"""
    path = os.path.join(root, STATE_DIR, "feature_list.json")
    if not os.path.isfile(path):
        return None, 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None, 0
    if not isinstance(data, dict):
        return None, 0

    feats = data.get("features", [])
    completed_idx = [i for i, x in enumerate(feats)
                     if isinstance(x, dict) and x.get("status") == "completed"]
    if len(completed_idx) <= keep_completed:
        return None, 0

    move_idx = set(completed_idx[: len(completed_idx) - keep_completed])
    moved = [feats[i] for i in sorted(move_idx)]
    remain = [x for i, x in enumerate(feats) if i not in move_idx]

    stamp = datetime.now().strftime("%Y-%m")
    arc_dir = os.path.join(root, ARCHIVE_DIR)
    arc_path = os.path.join(arc_dir, f"feature_list-{stamp}.json")

    if not dry:
        os.makedirs(arc_dir, exist_ok=True)
        old = {"features": []}
        if os.path.isfile(arc_path):
            try:
                with open(arc_path, "r", encoding="utf-8") as f:
                    old = json.load(f)
            except (json.JSONDecodeError, OSError):
                old = {"features": []}
        old.setdefault("features", []).extend(moved)
        old["archived_at"] = datetime.now().isoformat(timespec="seconds")
        old["project"] = data.get("project", "")
        old["note"] = "已归档条目：git 保留完整历史，Agent 不再读取本文件"
        with open(arc_path, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)

        data["features"] = remain
        s = data.get("summary", {})
        if isinstance(s, dict):
            s["total"] = len(remain)
            s["completed"] = sum(1 for x in remain
                                 if isinstance(x, dict) and x.get("status") == "completed")
            s["completion_rate"] = (f"{round(s['completed'] / len(remain) * 100)}%"
                                    if remain else "0%")
            data["summary"] = s
        data["last_updated"] = datetime.now().date().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return os.path.relpath(arc_path, root).replace("\\", "/"), len(moved)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="状态层健康检查与归档")
    ap.add_argument("--root", default=None, help="仓库根（默认从脚本位置推断）")
    ap.add_argument("--archive", action="store_true", help="执行归档")
    ap.add_argument("--dry-run", action="store_true", help="配合 --archive：只显示不写入")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else \
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(root):
        print(f"[!] 仓库根不存在: {root}", file=sys.stderr)
        return 2

    cfg = load_config(root)
    limits = dict(DEFAULT_LIMITS)
    for k, v in (cfg.get("limits") or {}).items():
        limits.setdefault(k, {}).update(v)

    findings, metrics = check_files(root, limits)
    findings += check_rogue_state(root)

    archived: list[dict] = []
    if args.archive:
        dry = bool(args.dry_run)
        p = limits.get("progress.md", {})
        path, n = archive_progress_log(root, p.get("keep_log_lines", 120), dry)
        if n:
            archived.append({"file": path, "moved": n, "kind": "progress-log", "dry_run": dry})
        path2, n2 = archive_feature_list(
            root, limits.get("feature_list.json", {}).get("keep_completed", 60), dry)
        if n2:
            archived.append({"file": path2, "moved": n2,
                             "kind": "feature_list", "dry_run": dry})
        if not archived:
            print("无需归档：所有内容都在保留配额内。")

    errors = [f for f in findings if f.level == "error"]
    exit_code = 1 if errors else 0

    if args.json:
        print(json.dumps({
            "version": VERSION, "root": root.replace("\\", "/"),
            "metrics": metrics,
            "findings": [asdict(f) for f in findings],
            "archived": archived,
            "errors": len(errors), "exit_code": exit_code,
        }, ensure_ascii=False, indent=2))
        return exit_code

    print(f"\n状态层健康检查 — {root}\n" + "=" * 62)
    for name, m in metrics.items():
        if not m.get("exists"):
            continue
        extra = ""
        if "items" in m:
            extra = f"  · {m['items']} 条目（{m['completed']} completed）"
        print(f"  {name:22s} {m['bytes']:>9,} B  {m['lines']:>5} 行{extra}")

    if archived:
        print("\n[归档结果]" + ("（dry-run，未写入）" if args.dry_run else ""))
        for a in archived:
            print(f"  移动 {a['moved']:>4} 条 → {a['file']}")

    if findings:
        print()
        for lv, mark in (("error", "❌"), ("warn", "⚠️ "), ("info", "ℹ️ ")):
            bucket = [f for f in findings if f.level == lv]
            if not bucket:
                continue
            print(f"--- {lv.upper()} ({len(bucket)}) ---")
            for f in bucket:
                print(f"{mark} {f.target}: {f.message}")
                if f.hint:
                    print(f"      ↳ {f.hint}")
            print()

    print("=" * 62)
    if errors:
        print(f"❌ {len(errors)} 项超限 —— 状态文件正在变成 Agent 读不完的档案。")
        print("   修复：python scripts/state_health.py --dry-run --archive   先看")
        print("         python scripts/state_health.py --archive           再执行")
    else:
        print("✅ 状态层健康：所有文件都在阈值内。")
    print(f"\n退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
