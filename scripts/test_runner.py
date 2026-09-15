#!/usr/bin/env python3
"""测试运行器 —— 智能选测 + 分层 + 进度可见。

解决的三个具体问题
----------------
1. **"明明只改一行，却要跑全量"**
   → 默认只跑**受改动影响的测试**（`--all` 才全量）。
     选择逻辑**显式打印**：跑了几个、共几个、因为哪些文件被改。

2. **"没有进度条，不知道在跑哪项、每项多久"**
   → 默认开 `-v`（逐项输出测试名 = 有进度感）+ 结束报告 `--durations`。
     若装了 `pytest-sugar` 自动启用（真进度条）。

3. **"没有分层，慢测试拖垮反馈"**
   → `--layer unit|integration|e2e` 按标记/路径分层跑；
     `--slow` 单独列出最慢的 N 个，便于定点优化。

⚠️ **安全规则（来自测试影响分析的通行做法）**
------------------------------------------------
**TIA 只做选择，不替代全量。** 影响映射可能漏（动态派发、反射、配置、
运行时开关都会绕过静态映射）。所以：
  · 日常/PR  → 跑受影响子集（快反馈）
  · merge 前 / 每日 → 跑 `--all`（兜底）
本脚本在跑子集时**会明确提醒**这一点，不让你误以为已经全测过了。

用法
----
    python scripts/test_runner.py                # 只跑受影响的（默认）
    python scripts/test_runner.py --all          # 全量
    python scripts/test_runner.py --layer unit   # 只跑单元测试
    python scripts/test_runner.py --slow         # 看最慢的 10 个
    python scripts/test_runner.py --explain      # 只说明会跑什么，不执行
    python scripts/test_runner.py --report       # 生成测试汇报（给非工程读者）

退出码：透传被测命令（0 通过 / 非 0 失败）；2 = 环境/配置错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness_version import TEMPLATE_VERSION as VERSION  # noqa: E402

# 分层约定：marker 名 ←→ 目录名（两者都认，任一命中即算该层）
LAYERS = {
    "unit": ("unit", ("tests/unit", "test/unit", "unit_tests")),
    "integration": (
        "integration",
        ("tests/integration", "tests/it", "integration_tests"),
    ),
    "e2e": ("e2e", ("tests/e2e", "tests/end_to_end", "e2e_tests")),
}

SRC_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs")
TEST_HINTS = ("test/", "tests/", "__tests__/", "spec/")


def load_cfg(root: str) -> tuple[dict, str]:
    p = os.path.join(root, ".harness", "config.json")
    if not os.path.isfile(p):
        return {}, f"找不到 {p}"
    try:
        with open(p, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {}, f"config.json 读取失败: {e.__class__.__name__}: {e}"
    return (cfg if isinstance(cfg, dict) else {}), ""


def test_command(cfg: dict) -> tuple[str | None, str]:
    """取测试命令。优先 quality/test，其次 commands.test。"""
    cmds = cfg.get("commands") or {}
    if isinstance(cmds, dict) and cmds.get("test"):
        return cmds["test"], "config.json commands.test"
    return None, "config.json 里没有 commands.test"


def git_changed(root: str) -> tuple[list[str], str]:
    """取相对 HEAD 的改动文件（含未暂存）。返回 (文件, 说明)。"""
    tries = [
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--name-only"],
    ]
    last = ""
    for args in tries:
        try:
            r = subprocess.run(
                args, cwd=root, capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.SubprocessError) as e:
            last = f"{e.__class__.__name__}: {e}"
            continue
        if r.returncode == 0:
            files = [
                ln.strip().replace("\\", "/")
                for ln in r.stdout.splitlines()
                if ln.strip()
            ]
            return files, f"`{' '.join(args)}` 得到 {len(files)} 个改动文件"
        last = (r.stderr or "").strip()[:160]
    return [], f"git diff 失败: {last}"


def is_test_path(rel: str) -> bool:
    r = rel.replace("\\", "/").lower()
    return any(h in r for h in TEST_HINTS)


def affected_tests(root: str, changed: list[str]) -> tuple[list[str], list[str]]:
    """找受影响的测试文件。

    映射方式（从粗到细，命中即收）：
      ① 测试自身的改动            → 直接跑它
      ② 测试文件 import 了改动模块 → 跑该测试
      ③ 改动模块与测试同名         → 跑该测试（test_foo.py ← foo.py）
    返回 (测试文件列表, 选择理由)。
    """
    reasons: list[str] = []
    picked: set[str] = set()

    all_tests: list[str] = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [
            d
            for d in dn
            if d
            not in (
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                "dist",
                "build",
                ".next",
                "_selftest",
            )
        ]
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            if is_test_path(rel) and rel.endswith(SRC_EXT):
                all_tests.append(rel)

    changed_src = [c for c in changed if c.endswith(SRC_EXT) and not is_test_path(c)]
    changed_test = [c for c in changed if is_test_path(c)]

    # ① 改动本身就是测试
    for t in changed_test:
        if os.path.isfile(os.path.join(root, t)):
            picked.add(t)
            reasons.append(f"测试文件本身被改动: {t}")

    if not changed_src:
        return sorted(picked), reasons

    # ② 反向引用：测试里有没有提到改动的模块名
    stems = {}
    for c in changed_src:
        stem = os.path.splitext(os.path.basename(c))[0]
        if stem and stem != "__init__":
            stems.setdefault(stem, []).append(c)

    for t in all_tests:
        if t in picked:
            continue
        try:
            body = open(os.path.join(root, t), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for stem, files in stems.items():
            # import 形式 或 模块名出现（含 test_<stem>.py 命名约定）
            if re.search(rf"\b{re.escape(stem)}\b", body):
                picked.add(t)
                reasons.append(f"{t} 引用了 {stem}（来自 {files[0]}）")
                break

    return sorted(picked), reasons


def detect_sugar() -> bool:
    """检测 pytest-sugar（真进度条）。"""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    try:
        import importlib.util

        return importlib.util.find_spec("pytest_sugar") is not None
    except (ImportError, ValueError):
        return False


def build_cmd(base: str, args, root: str) -> tuple[list[str], list[str]]:
    """组装最终命令。返回 (argv, 说明列表)。"""
    notes: list[str] = []
    cmd = [base]

    if args.all:
        notes.append("模式: 全量（--all）")
    elif args.layer:
        marker, dirs = LAYERS[args.layer]
        notes.append(f"模式: 只跑 {args.layer} 层（marker={marker} 或目录 {dirs[0]}）")
        if "pytest" in base:
            cmd += ["-m", marker]
        else:
            cmd += dirs[:1]
    else:
        changed, how = git_changed(root)
        picked, reasons = affected_tests(root, changed)
        notes.append(f"模式: 受改动影响（{how}）")
        if picked:
            notes.append(f"选中 {len(picked)} 个测试文件:")
            for p in picked[:12]:
                notes.append(f"    · {p}")
            if len(picked) > 12:
                notes.append(f"    … 另有 {len(picked) - 12} 个")
            cmd += picked
        else:
            # 选不出来 → 分三种情况，每种都给明确结论（不假装跑了测试）
            notes.append("⚠️ 没有映射出受影响的测试")
            notes.append(
                f"    改动文件: {len(changed)} 个"
                + (f"（{', '.join(changed[:4])}）" if changed else "（工作区干净）")
            )
            has_cache = os.path.isdir(os.path.join(root, ".pytest_cache"))
            if not changed:
                notes.append("    → 工作区无改动，**无需跑测试**")
                notes.append("      要全量验证请显式跑 --all")
                return [], notes
            if any(
                c.endswith(
                    (
                        ".md",
                        ".txt",
                        ".rst",
                        ".json",
                        ".yaml",
                        ".yml",
                        ".toml",
                        ".ini",
                        ".cfg",
                    )
                )
                for c in changed
            ) and not any(c.endswith(SRC_EXT) for c in changed):
                notes.append("    → 改动只涉及文档/配置，**不影响代码测试**")
                notes.append("      若要确认，跑 --all；否则可跳过")
                return [], notes
            if has_cache and "pytest" in base:
                notes.append("    → 降级为 --lf（只跑上次失败的）")
                cmd += ["--lf"]
            else:
                notes.append("    → 无历史失败记录，降级为全量")
                notes.append(
                    "      提示：在 pytest 配置里声明 marker 并开 --strict-markers，"
                    "可让分层选测更准"
                )

    # 进度可见性（问题 6）
    if "pytest" in base:
        # -q 与 -v 互斥：用户配了 `pytest -q`，但 -q 正是"看不到进度"的来源。
        # 这里移除 -q 换成 -v，并在说明里讲清楚做了什么（不静默改命令）。
        if re.search(r"(?:^|\s)-q(?:\s|$)", base):
            cmd = [re.sub(r"\s*-(?:q|quiet)\b", "", c) for c in cmd]
            notes.append("进度: 已把配置里的 -q 换成 -v（-q 会隐藏逐项进度）")
        if detect_sugar():
            notes.append("进度: pytest-sugar 已启用（进度条）")
        else:
            notes.append(
                "进度: 逐项输出（装了 pytest-sugar 会有进度条: pip install pytest-sugar）"
            )
        cmd += ["-v"]
        if args.slow:
            cmd += ["--durations=10", "--durations-min=0.5"]
        else:
            cmd += ["--durations=5", "--durations-min=0.5"]
    return cmd, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="测试运行器：智能选测 + 分层 + 进度可见")
    ap.add_argument("--root", default=None, help="项目根（默认当前目录）")
    ap.add_argument("--all", action="store_true", help="全量跑（默认只跑受影响）")
    ap.add_argument(
        "--layer",
        choices=sorted(LAYERS),
        default=None,
        help="只跑某一层（unit/integration/e2e）",
    )
    ap.add_argument("--slow", action="store_true", help="报告最慢的测试")
    ap.add_argument("--explain", action="store_true", help="只说明会跑什么，不执行")
    ap.add_argument(
        "--report", action="store_true", help="生成测试汇报（给自己/他人看）"
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or os.getcwd())
    cfg, err = load_cfg(root)
    if err:
        print(f"[!] {err}", file=sys.stderr)
        return 2
    base, how = test_command(cfg)
    if not base:
        print(
            f"[!] 没有配置测试命令（{how}）\n"
            f"    在 .harness/config.json 里加：\n"
            f'      "commands": {{"test": "pytest -q"}}',
            file=sys.stderr,
        )
        return 2

    cmd, notes = build_cmd(base, args, root)

    print(f"\n测试运行器 — {os.path.basename(root)}")
    print("=" * 66)
    for n in notes:
        print(f"  {n}")

    if not cmd:
        # 明确结论：本次没有需要跑的测试（而不是"跑了 0 个"这种含糊结果）
        print("=" * 66)
        print("  结论: 无需运行测试（原因见上）")
        return 0

    print(f"\n  命令: {' '.join(cmd)}")

    if args.explain:
        print("\n（--explain：未执行）")
        if not args.all and args.layer is None:
            print("提醒: 这是**子集**。merge 前请跑 --all，否则可能漏测。")
        return 0

    # 安全提醒（TIA 只做选择，不替代全量）
    subset = (not args.all) and (args.layer is None)
    if subset:
        print("\n  ⚠️  这是受影响的子集，不是全量。")
        print("      影响映射会漏（动态派发/反射/配置/运行时开关）。")
        print("      merge 前请跑: python scripts/test_runner.py --all")
    print("=" * 66 + "\n")
    # ⚠️ 必须 flush：否则子进程的输出会与上面这些 print 交错，
    # 终端里看起来像"测试结果跑到了标题前面"（实测踩到）。
    sys.stdout.flush()

    try:
        r = subprocess.run(cmd, cwd=root, timeout=None)
    except OSError as e:
        print(f"[!] 执行失败: {e}", file=sys.stderr)
        return 2
    sys.stdout.flush()

    if args.report:
        print("\n" + "=" * 66)
        print("测试汇报（可直接贴给别人）")
        print("=" * 66)
        print(f"  项目      : {os.path.basename(root)}")
        print(
            f"  范围      : {'全量' if args.all else ('只跑 ' + args.layer + ' 层' if args.layer else '受改动影响的子集')}"
        )
        print(f"  命令      : {' '.join(cmd)}")
        print(
            f"  结果      : {'通过' if r.returncode == 0 else '失败'}"
            f"（退出码 {r.returncode}）"
        )
        if subset:
            print("  未覆盖    : 全部测试（本次只跑了受影响的子集）")
        print("  说明      : 测试覆盖哪一层、是否有场景/集成测试，见")
        print("              .harness/testing/TEST-STRATEGY.md 的分层要求")

    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
