#!/usr/bin/env python3
"""模板升级同步器 —— 把模板仓库的改进拉进已生成的项目。

解决的问题
----------
模板改好了，但**已经生成出去的项目拿不到**。此前没有任何升级机制，
于是"模板 v1.2 修了个重要 bug"与"三个月前生成的项目"永远无关。

设计：三向合并（见 sync_lib.classify 的详细说明）
------------------------------------------
只用"项目文件 vs 模板文件"两个快照无法判断差异是谁造成的，
因此本脚本读三方快照：

    base   = 生成时记在 config.json 里的哈希（当初给你的那一版）
    ours   = 项目当前文件
    theirs = 模板当前文件

由此得出五类结论，处理策略各不相同（见 classify）。

**最重要的一条安全原则**：base 缺失（旧项目没记录）时无法溯源，
此时**一律不覆盖**，只报告差异。宁可不同步，也不能吃掉用户写的东西。

用法
----
    # 只看差异（默认，不写任何文件）
    python scripts/sync_template.py --check

    # 应用"可安全更新 + 新增"的部分（冲突跳过并列出）
    python scripts/sync_template.py --apply

    # 连冲突一起覆盖（危险：会丢你的本地改动，必须显式确认）
    python scripts/sync_template.py --apply --force

退出码
------
    0  无待同步项 / 同步成功
    1  有冲突未处理（不算失败，是"需要你裁决"）
    2  环境错误（不是模板生成的项目 / 找不到模板 / 配置损坏）

**错误边界**（每条都会显式打印原因，绝不静默）：
    - 项目没有 .harness/config.json      → 退出 2，拒绝猜测
    - 找不到模板仓库                      → 退出 2，并说明怎么指定
    - config.json 损坏 / 不是 JSON        → 退出 2
    - 单个文件读失败                      → 记入 failed 并打印，不中断整体
    - 写入失败                            → 逐条打印，退出 1
    - MAJOR 版本跨代                      → 拒绝自动同步（需人工迁移）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync_lib as SYNC  # noqa: E402
from harness_version import (  # noqa: E402
    SYNC_ALLOW_CROSS_MAJOR,
    TEMPLATE_VERSION,
)

VERSION = TEMPLATE_VERSION

# 模板仓库的候选位置（按顺序探测）
TEMPLATE_CANDIDATES = [
    ("环境变量 HARNESS_TEMPLATE", lambda: os.environ.get("HARNESS_TEMPLATE")),
]

# 判断"这是模板仓库吗"的标记
TEMPLATE_MARKER = ".harness/TEMPLATE-REPO"


def find_template(explicit: str | None) -> tuple[str | None, str]:
    """定位模板仓库。返回 (路径|None, 说明)。

    **找不到一定要说清试过哪些地方**，而不是一句"找不到"，
    否则用户只能猜该去哪里配。
    """
    if explicit:
        if os.path.isdir(explicit):
            return os.path.abspath(explicit), f"命令行指定: {explicit}"
        return None, f"--template 指向的目录不存在: {explicit}"

    tried = []
    for label, getter in TEMPLATE_CANDIDATES:
        v = getter()
        tried.append(f"{label}={v!r}")
        if v and os.path.isdir(v):
            return os.path.abspath(v), f"{label} 命中"

    # 同级目录探测：常见布局是 <parent>/harness-template 与 <parent>/my-project 并列
    here = os.path.abspath(os.getcwd())
    parent = os.path.dirname(here)
    for name in ("harness-template", "harness_template"):
        cand = os.path.join(parent, name)
        tried.append(f"同级目录 {cand}")
        if os.path.isdir(cand):
            return cand, f"同级目录命中: {cand}"

    return None, (
        "自动定位失败，已尝试: "
        + "; ".join(tried)
        + "\n  请用 --template <模板仓库路径> 指定，"
        "或设置环境变量 HARNESS_TEMPLATE"
    )


def load_project_config(project: str) -> tuple[dict | None, str]:
    """读项目的 .harness/config.json。失败返回原因，绝不静默。"""
    p = os.path.join(project, ".harness", "config.json")
    if not os.path.isfile(p):
        return None, (
            f"找不到 {p}\n"
            "  → 这个目录不是 harness 模板生成的项目（或 .harness 被删了）。\n"
            "  同步器拒绝猜测它的模块配置，以免覆盖你的文件。"
        )
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        return None, f"config.json 不是合法 JSON: {e}"
    except OSError as e:
        return None, f"config.json 读取失败: {e.__class__.__name__}: {e.strerror or e}"
    if not isinstance(cfg, dict):
        return None, "config.json 顶层不是对象"
    return cfg, ""


def collect_project_rels(project: str) -> list[str]:
    """列出项目里参与同步的相对路径（排除 .git 等）。"""
    out = []
    for dp, dn, fn in os.walk(project):
        dn[:] = [
            d
            for d in dn
            if d not in (".git", "__pycache__", "node_modules", ".venv", "_selftest")
        ]
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), project).replace("\\", "/")
            out.append(rel)
    return out


def collect_template_rels(template: str, modules: dict) -> list[str]:
    """模板侧要参与同步的路径 —— **按项目的模块开关过滤 + 排除不复制项**。

    两处过滤缺一不可：
    - 关掉的模块不该被同步进来（否则等于偷偷把模块打开了，
      与"关掉的模块不留残骸"铁律冲突）
    - EXCLUDE_FILES（评审稿等）本就不该复制，若列进来会被当成"可新增项"反复报
    """
    from module_manifest import EXCLUDE_FILES, module_paths, norm_rel

    mpaths = module_paths()
    skip = set()
    for mod, on in (modules or {}).items():
        if not on:
            skip |= set(mpaths.get(mod, []))

    exclude = {norm_rel(f) for f in EXCLUDE_FILES}

    out = []
    for dp, dn, fn in os.walk(template):
        dn[:] = [
            d
            for d in dn
            if d not in (".git", "__pycache__", "node_modules", ".venv", "_selftest")
        ]
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), template).replace("\\", "/")
            if rel in skip or rel in exclude or SYNC.is_never_sync(rel):
                continue
            out.append(rel)
    return out


def major(v: str) -> str:
    return (v or "").split(".")[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把 harness 模板的改进同步进已生成的项目")
    ap.add_argument("--project", default=None, help="项目根（默认当前目录）")
    ap.add_argument("--template", default=None, help="模板仓库根（默认自动定位）")
    ap.add_argument(
        "--check", action="store_true", help="只报告差异，不写任何文件（默认行为）"
    )
    ap.add_argument("--apply", action="store_true", help="实际应用同步")
    ap.add_argument(
        "--force",
        action="store_true",
        help="连冲突项一起覆盖（会丢本地改动，需配合 --apply）",
    )
    ap.add_argument(
        "--adopt-now",
        action="store_true",
        help="把项目当前状态设为同步基线（旧项目补救用，不复制任何文件）",
    )
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    project = os.path.abspath(args.project or os.getcwd())

    # ── 环境校验（每条失败都给原因，不静默）──
    if not os.path.isdir(project):
        print(f"[!] 项目目录不存在: {project}", file=sys.stderr)
        return 2

    cfg, err = load_project_config(project)
    if cfg is None:
        print(f"[!] {err}", file=sys.stderr)
        return 2

    template, tnote = find_template(args.template)
    if template is None:
        print(f"[!] {tnote}", file=sys.stderr)
        return 2
    if not os.path.isfile(os.path.join(template, TEMPLATE_MARKER)):
        print(
            f"[!] {template} 看起来不是 harness 模板仓库"
            f"（缺少 {TEMPLATE_MARKER}）\n"
            f"  定位依据: {tnote}\n"
            f"  若确定它是模板仓库，用 --template 显式指定正确路径。",
            file=sys.stderr,
        )
        return 2

    # ── 版本兼容性 ──
    sync_info = cfg.get(SYNC.SYNC_FIELD) or {}
    proj_ver = str(sync_info.get("template_version", ""))
    base: dict[str, str] = sync_info.get("files") or {}
    if not isinstance(base, dict):
        print(
            "[!] config.json 的 template_sync.files 格式不对（应为对象）",
            file=sys.stderr,
        )
        return 2

    if (
        proj_ver
        and major(proj_ver) != major(TEMPLATE_VERSION)
        and not SYNC_ALLOW_CROSS_MAJOR
    ):
        print(
            f"[!] MAJOR 版本跨代（项目 {proj_ver} → 模板 {TEMPLATE_VERSION}）\n"
            "  跨代变更可能含架构级调整，自动同步不安全。\n"
            "  请人工迁移，或阅读模板的 MAINTENANCE.md §5 维护史。",
            file=sys.stderr,
        )
        return 2

    # ── 补充基线（旧项目补救）：不复制任何文件，只把「现在」记为基线 ──
    modules = cfg.get("modules") or {}
    t_rels = collect_template_rels(template, modules)

    if args.adopt_now:
        ours_now, adopt_fail = SYNC.snapshot(project, t_rels)
        sync_info["files"] = ours_now
        sync_info["template_version"] = TEMPLATE_VERSION
        sync_info["adopted_at"] = date.today().isoformat()
        cfg[SYNC.SYNC_FIELD] = sync_info
        cfg_path = os.path.join(project, ".harness", "config.json")
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[!] 写入 config.json 失败: {e}", file=sys.stderr)
            return 1
        print(f"\n✅ 已把项目当前状态记为同步基线（{len(ours_now)} 个文件）")
        if adopt_fail:
            print(f"⚠️  {len(adopt_fail)} 个文件读失败，未记入基线:")
            for s in adopt_fail[:10]:
                print(f"    · {s}")
        print("  以后再跑 --check 就能分辨「模板更新」与「你自己的改动」了。")
        return 0

    # ── 三向比较 ──
    # 模板侧必须施加项目生成时的替换映射，否则占位符差异会让判断全错
    # （模板 `{{PROJECT_NAME}}` vs 项目 `myapp`，永远不等 → 误报"有更新"）。
    subs = sync_info.get("substitutions") or {}
    if not isinstance(subs, dict):
        print(
            "[!] config.json 的 template_sync.substitutions 格式不对，已忽略",
            file=sys.stderr,
        )
        subs = {}

    theirs, t_fail = SYNC.snapshot(template, t_rels, substitutions=subs)
    ours, o_fail = SYNC.snapshot(project, t_rels)  # 项目侧已是实值，不再替换
    all_fail = t_fail + o_fail

    res = SYNC.classify(base, ours, theirs)

    payload = {
        "project": project,
        "template": template,
        "project_version": proj_ver or "(未记录)",
        "template_version": TEMPLATE_VERSION,
        "has_baseline": bool(base),
        "added": res["added"],
        "updatable": res["updatable"],
        "conflict": res["conflict"],
        "local_only": res["local_only"],
        "unchanged": len(res["unchanged"]),
        "read_failures": all_fail,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not res["conflict"] else 1

    # ── 报告 ──
    print(f"\n模板同步检查 — {os.path.basename(project)}")
    print(f"  项目版本 {payload['project_version']}  →  模板版本 {TEMPLATE_VERSION}")
    print(f"  模板来源: {template}")
    print("=" * 60)

    if not base:
        print("\n⚠️  项目未记录同步基线（由旧版模板生成）")
        print("    无法判断差异是谁造成的 → **默认一个都不覆盖**，只列出差异。")
        print(
            "    想让它以后能自动同步，跑: python scripts/sync_template.py --apply --adopt-now"
        )
        print("    （见下方说明）")

    print(f"\n  可安全新增  {len(res['added'])} 项")
    print(f"  可安全更新  {len(res['updatable'])} 项（你没改过、模板升级了）")
    print(f"  需要你裁决  {len(res['conflict'])} 项（你改过，模板也改了）")
    print(f"  项目专属    {len(res['local_only'])} 项（模板无，保留不动）")
    print(f"  已一致      {len(res['unchanged'])} 项")

    if all_fail:
        # S14：读失败必须露面，否则"没扫到"会被当成"没问题"
        print(f"\n⚠️  {len(all_fail)} 次读取失败（这些文件未纳入比较）:")
        for s in all_fail[:10]:
            print(f"    · {s}")
        if len(all_fail) > 10:
            print(f"    … 另有 {len(all_fail) - 10} 条")

    if not (res["added"] or res["updatable"] or res["conflict"]):
        print("\n✅ 已是最新，无需同步。")
        return 0

    for title, key in (
        ("可安全新增", "added"),
        ("可安全更新", "updatable"),
        ("需要你裁决", "conflict"),
    ):
        if not res[key]:
            continue
        print(f"\n--- {title} ({len(res[key])}) ---")
        for rel in res[key][:30]:
            print(f"    · {rel}")
        if len(res[key]) > 30:
            print(f"    … 另有 {len(res[key]) - 30} 项")

    if not args.apply:
        print("\n这是预览（--check）。确认无误后跑：")
        print("  python scripts/sync_template.py --apply")
        if res["conflict"]:
            print(f"\n其中 {len(res['conflict'])} 项冲突会被跳过（保护你的本地改动）。")
            print("确要覆盖请跑: --apply --force  (会丢本地改动，慎用)")
        return 1 if res["conflict"] else 0

    # ── 应用 ──
    targets = res["added"] + res["updatable"]
    if args.force:
        targets += res["conflict"]
        if res["conflict"]:
            print(
                f"\n⚠️  --force: {len(res['conflict'])} 项冲突将被覆盖（本地改动会丢失）"
            )

    if not targets:
        print("\n没有可安全应用的项。")
        return 1

    applied, failures = [], []
    for rel in targets:
        src = os.path.join(template, rel)
        dst = os.path.join(project, rel)
        try:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with open(src, "rb") as f:
                data = f.read()
            # ⚠️ 必须施加替换：模板里是 {{PROJECT_NAME}}，直接复制会把占位符
            # 塞回项目，把用户填好的项目名冲成 {{...}}（比不同步还糟）。
            data = SYNC.apply_substitutions(data, subs, rel=rel)
            with open(dst, "wb") as f:
                f.write(data)
            # 更新基线：同步后该文件的"当初给你的版本"就是模板现在这版（已替换）
            base[rel] = SYNC.sha256_bytes(data)
            applied.append(rel)
        except OSError as e:
            # 不静默：写失败必须逐条说清
            failures.append(f"{rel} — {e.__class__.__name__}: {e.strerror or e}")

    # 回写基线（让下次同步能正确溯源）
    if applied:
        sync_info["files"] = base
        sync_info["last_sync"] = date.today().isoformat()
        cfg[SYNC.SYNC_FIELD] = sync_info
        cfg_path = os.path.join(project, ".harness", "config.json")
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError as e:
            failures.append(f"回写 config.json 失败（下次同步会重复报这些项）: {e}")

    print(f"\n✅ 已同步 {len(applied)} 项")
    for rel in applied[:20]:
        print(f"    · {rel}")
    if len(applied) > 20:
        print(f"    … 另有 {len(applied) - 20} 项")

    if failures:
        print(f"\n❌ {len(failures)} 项失败:")
        for s in failures:
            print(f"    · {s}")
        return 1

    if res["conflict"] and not args.force:
        print(f"\n⚠️  {len(res['conflict'])} 项冲突已跳过（保护你的本地改动）")
        return 1

    print("\n下一步: python scripts/init.py  &&  python scripts/harness_lint.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
