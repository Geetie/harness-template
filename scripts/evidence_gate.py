#!/usr/bin/env python3
"""证据门禁 —— 不允许"只声明完成"。

解决的根本问题
------------
**Agent 自己设的门禁拦不住自己。** 原因是所有门禁都在查**形态**：

| 门禁 | 查什么 | 垃圾 demo 怎么绕过去 |
|---|---|---|
| `no_placeholder_guard` | 有没有未完成标记/桩关键词 | 返回 `0.0` / `{}`，不含关键词 |<!-- guard:allow：本行在**讨论**该规则抓什么，不是在留标记 -->
| `check_integration` | 模块有没有被调用 | 需要人工指定入口，不指定就退出 |
| `harness_lint` | 文档有没有漂移 | 与代码质量无关 |
| `feature_list.json` | `status: completed` | **Agent 自己写的** |

最后一行是关键：`evidence` 字段在模板里**只是一个字符串**，
legend 写着"由 evidence 指向的真实路径核实"—— **但从来没有脚本真的去核实**。
于是"我做了"这句话本身就是通过条件。

本门禁把 `evidence` 从**声明**升级为**契约**：

    弱（旧）:  "evidence": "src/cart.py"                ← 只证明文件存在
    强（新）:  "evidence": {
                 "cmd": "python scripts/verify/F-001.py",   ← 必须真的执行
                 "expect_exit": 0,
                 "expect_stdout": ["总价: 42.0"],           ← 必须含具体值
                 "artifacts": ["out/receipt.json"],         ← 必须存在且非空
                 "touches": ["src/shopping/cart.py"]        ← 证据必须触及此文件
               }

**设计目标不是"无法伪造"，而是"伪造成本 ≥ 真做成本"。**
想骗过本门禁，你得写一个能跑出"总价: 42.0"的脚本，还得让它真的引用
`cart.py`（touches 交叉验证）—— 那还不如直接把 cart.py 实现对。

三道防线
--------
1. **必须有证据**：`completed` 却没有可执行证据 → 拦
2. **证据必须真跑通**：执行 cmd，比对退出码 / stdout / 产物 → 不符则拦
3. **证据必须触及实现（运行时验证，非静态）**：`touches` 列出的文件，
   其中的**函数必须真的被调用**。用 `_evidence_probe.py` 以 `sys.settrace`
   观测执行轨迹 —— 只 import 不调用会被拦（静态文本匹配拦不住这个，
   实测被绕过：`import src.cart` + 硬编码答案）。
   非 `python xxx.py` 形式的命令（pytest/node/go test）降级为静态检查，
   并在输出里**明确标注"未做运行时验证"**。
4. **产物必须是本次产出**：记录 artifacts 在执行前后的 size+mtime，
   完全没变 → 判为复用旧文件 → 拦

另外做**基线锁**：记录已完成数 + 强证据数，下降即拦
（防止悄悄把功能改回 missing 来"清理"门禁告警）。

用法
----
    python scripts/evidence_gate.py                  # 校验全部 completed 功能
    python scripts/evidence_gate.py --only F-001     # 只验一个
    python scripts/evidence_gate.py --json
    python scripts/evidence_gate.py --list           # 只列状态，不执行证据

退出码
------
    0  全部通过（可能含 WARN，会打印）
    1  有 ERROR（证据缺失/不符/未触及）
    2  feature_list.json 读不到或损坏
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness_version import TEMPLATE_VERSION as VERSION  # noqa: E402

FEATURE_LIST = ".harness/state/feature_list.json"
LOCK_FILE = ".harness/state/evidence.lock"

# 执行证据命令的超时（秒）。证据应当很快，慢说明它是"跑全套测试"而不是验收。
EVIDENCE_TIMEOUT = 300

# "通用词"——期望输出里只写这些，等于没有期望（不构成有效契约）
GENERIC_TOKENS = {
    "ok",
    "okay",
    "done",
    "success",
    "succeed",
    "passed",
    "pass",
    "fine",
    "completed",
    "complete",
    "finished",
    "true",
    "yes",
    "通过",
    "成功",
    "完成",
    "正常",
    "没问题",
    "好",
}

# 需要至少一个"具体值"（含数字）才认可为强期望
NUM_RE = re.compile(r"\d")


class Err(Exception):
    """配置/结构错误。"""


def load_features(root: str) -> dict:
    p = os.path.join(root, FEATURE_LIST)
    if not os.path.isfile(p):
        raise Err(f"找不到 {FEATURE_LIST} —— 项目没有状态文件，无法校验证据")
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise Err(f"{FEATURE_LIST} 不是合法 JSON: {e}") from e
    except OSError as e:
        raise Err(
            f"{FEATURE_LIST} 读取失败: {e.__class__.__name__}: {e.strerror or e}"
        ) from e
    if not isinstance(data, dict):
        raise Err(f"{FEATURE_LIST} 顶层不是对象")
    return data


def check_expect_strength(expect: list[str]) -> list[str]:
    """检查期望输出是否够"具体"。返回问题列表。

    为什么必须卡：如果允许 `expect_stdout: ["ok"]`，那契约就退化回"声明"——
    任何脚本 print 一句 ok 都能过，等于没门禁。
    """
    problems: list[str] = []
    if not expect:
        problems.append("expect_stdout 为空 —— 无法判断「正确」长什么样")
        return problems
    for tok in expect:
        t = (tok or "").strip()
        if not t:
            problems.append("expect_stdout 含空字符串")
            continue
        if t.lower() in GENERIC_TOKENS:
            problems.append(
                f"expect_stdout 含通用词 {t!r} —— 这类词任何输出都能满足，不构成契约"
            )
    if not any(NUM_RE.search(t or "") for t in expect):
        problems.append(
            "expect_stdout 里没有任何数字 —— "
            "建议至少校验一个具体值（金额/数量/ID），否则容易假通过"
        )
    return problems


def has_function_def(path: str) -> bool:
    """该 Python 文件是否定义了函数/方法。

    用途：判断「只有 <module> 被记录」是否可接受 ——
    纯脚本式模块（无函数定义）的模块级就是它的全部逻辑，import 即执行，
    此时接受；有函数定义却一次没被调用，说明证据没验证它。
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
    except (OSError, SyntaxError):
        return False
    return any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)
    )


def probe_command(root: str, cmd: str, log_path: str) -> tuple[str | None, bool]:
    """把 `python x.py [args]` 重写成带运行时探针的调用。

    为什么必须做运行时探针：静态文本匹配只看"有没有出现这个名字"，
    于是 `import src.cart` + 硬编码答案 就能骗过门禁（**实测绕过了**）。
    只有观测"这段代码到底跑没跑"才拦得住。

    返回 (新命令 | None, 是否可探针化)。非 `python x.py` 形式（如 pytest、
    node、go test）返回 False —— 此时降级为静态检查，并在输出里明确标注。
    """
    m = re.match(r"^\s*(?:python3?|py)\s+([\w./\\-]+\.py)(.*)$", cmd or "")
    if not m:
        return None, False
    script, rest = m.group(1), (m.group(2) or "").strip()
    probe = os.path.join("scripts", "_evidence_probe.py")
    if not os.path.isfile(os.path.join(root, probe)):
        return None, False
    new = f'"{sys.executable}" {probe} "{script}" "{log_path}"'
    if rest:
        new += " " + rest
    return new, True


def check_touches_static(root: str, touches: list[str], cmd: str) -> list[str]:
    """静态交叉验证（**降级路径**）：证据脚本文本里是否引用了 touches 文件。

    ⚠️ 这是弱检查：`import src.cart` 但不调用即可绕过。
    仅当无法做运行时探针（非 Python 命令）时才走这里，且调用方必须
    在输出里标明"未做运行时验证"。
    """
    problems: list[str] = []
    for t in touches:
        tp = os.path.join(root, t)
        if not os.path.isfile(tp):
            problems.append(f"touches 声明的文件不存在: {t}")
            continue
    if not touches:
        return problems

    # 找证据脚本
    m = re.search(r"([\w./\\-]+\.py)", cmd or "")
    if not m:
        problems.append("无法从 cmd 里定位证据脚本（.py）—— 无法交叉验证 touches")
        return problems
    sp = os.path.join(root, m.group(1))
    if not os.path.isfile(sp):
        problems.append(f"证据脚本不存在: {m.group(1)}")
        return problems
    try:
        body = open(sp, encoding="utf-8", errors="ignore").read()
    except OSError as e:
        problems.append(f"证据脚本读取失败: {e.__class__.__name__}")
        return problems

    for t in touches:
        stem = os.path.splitext(os.path.basename(t))[0]
        mod = t.replace("\\", "/").replace("/", ".")
        if mod.endswith(".py"):
            mod = mod[:-3]
        if (t in body) or (stem in body) or (mod in body):
            continue
        problems.append(
            f"证据脚本 {m.group(1)} 没有引用 {t} —— "
            f"证据与它声称覆盖的实现无关（自说自话不算证据）"
        )
    return problems


def run_evidence(root: str, ev: dict, fid: str) -> tuple[list[str], list[str]]:
    """执行证据契约。返回 (ERROR 列表, 信息列表)。"""
    errors: list[str] = []
    info: list[str] = []

    cmd = ev.get("cmd")
    if not cmd or not isinstance(cmd, str):
        return ["evidence.cmd 缺失或不是字符串"], info

    # ── 强度检查（在执行之前，避免"跑了但契约是空的"）──
    expect = ev.get("expect_stdout") or []
    if not isinstance(expect, list):
        return ["expect_stdout 必须是数组"], info
    strength = check_expect_strength(expect)
    errors += list(strength)

    touches = ev.get("touches") or []
    if not isinstance(touches, list):
        errors += ["touches 必须是数组"]
        touches = []

    # touches 的存在性先查（快，且明确）
    for t in touches:
        if not os.path.isfile(os.path.join(root, t)):
            errors.append(f"touches 声明的文件不存在: {t}")

    # ── 决定走运行时探针（强）还是静态检查（弱，须显式标注）──
    log_path = os.path.join(
        tempfile.gettempdir(), f"evidence_touch_{os.getpid()}_{fid}.log"
    )
    probed_cmd, can_probe = probe_command(root, cmd, log_path)
    run_cmd = probed_cmd or cmd
    if can_probe and touches:
        info.append(f"运行时探针已启用（验证 {len(touches)} 个文件是否真的被执行）")
    elif touches:
        errors += check_touches_static(root, touches, cmd)
        info.append(
            "⚠️ 未做运行时验证（证据命令非 `python xxx.py` 形式）"
            "—— 本次仅静态检查，import 但不调用即可绕过"
        )
    else:
        info.append("⚠️ 未声明 touches —— 无法验证证据是否真的触及相关实现")

    # 强度/交叉验证没过就不再执行（省时间，且结论已定）
    if errors:
        return errors, info

    # ── 执行前记录产物指纹 ──
    # 为什么需要：门禁原来只检查产物「存在且非空」，于是**预先放一个旧文件**
    # 就能满足 artifacts 要求（实测绕过了）。记录执行前的 size+mtime，
    # 执行后若完全没变，说明这个产物不是本次跑出来的。
    art_before: dict[str, tuple[int, int]] = {}
    for a in ev.get("artifacts") or []:
        ap = os.path.join(root, a)
        if os.path.isfile(ap):
            try:
                st = os.stat(ap)
                art_before[a] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass  # 读不到指纹就不做"是否变化"的判断（下面仍会检查存在与非空）

    # ── 真的执行 ──
    try:
        r = subprocess.run(
            run_cmd,
            cwd=root,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=EVIDENCE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return [
            f"证据命令超时（{EVIDENCE_TIMEOUT}s）—— "
            f"验收证据应当很快，慢说明它跑的是全套测试"
        ], info
    except OSError as e:
        return [f"证据命令无法执行: {e.__class__.__name__}: {e}"], info

    out = (r.stdout or "") + (r.stderr or "")
    info.append(f"执行 {cmd} -> exit={r.returncode}")

    # ── 运行时校验：touches 里的文件是否**真的被执行了** ──
    # 这是拦住「import 但不用 + 硬编码答案」的关键一步（静态匹配拦不住）。
    #
    # 判定规则（实测校准）：
    #   只记到 `<module>` 不算数 —— 因为 `import src.cart` 就会触发模块级执行。
    #   必须有**具名函数**被调用；除非该文件本身没有任何函数定义
    #   （纯脚本式模块，模块级就是它的全部逻辑）。
    if can_probe and touches:
        per_file: dict[str, set[str]] = {}
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or "::" not in line:
                        continue
                    f_, _, fn_ = line.rpartition("::")
                    per_file.setdefault(f_.lower(), set()).add(fn_)
        except OSError as e:
            errors.append(
                f"探针日志读取失败（无法验证 touches）: "
                f"{e.__class__.__name__}: {e.strerror or e}"
            )

        for t in touches:
            want = os.path.abspath(os.path.join(root, t)).lower()
            names = per_file.get(want, set())
            if not names:
                errors.append(
                    f"{t} 在证据执行过程中**从未被执行** —— 只是 import/提及不算验证"
                )
                continue
            named = {n for n in names if n and n != "<module>"}
            if named:
                continue
            # 只有 <module>：看该文件是不是纯脚本式（无函数定义）
            if has_function_def(os.path.join(root, t)):
                errors.append(
                    f"{t} 只被 import 加载、其中的函数**一次都没被调用** —— "
                    f"证据没有真正验证它的行为"
                )
        if not errors:
            info.append(f"运行时校验通过：{len(touches)} 个文件的函数均被真实调用")

    want_exit = ev.get("expect_exit", 0)
    if r.returncode != want_exit:
        errors.append(
            f"退出码 {r.returncode} != 期望 {want_exit}\n"
            f"        输出尾部: {out.strip()[-300:]}"
        )

    for tok in expect:
        if tok not in out:
            errors.append(
                f"输出里找不到期望串 {tok!r}\n"
                f"        实际输出尾部: {out.strip()[-300:]}"
            )

    if can_probe:
        try:
            os.remove(log_path)
        except OSError:
            pass  # 临时文件删不掉不影响结论，不打扰用户

    for a in ev.get("artifacts") or []:
        ap = os.path.join(root, a)
        if not os.path.isfile(ap):
            errors.append(f"产物不存在: {a}")
        elif os.path.getsize(ap) == 0:
            errors.append(f"产物是空文件: {a}（0 字节 = 没有真的产出）")
        elif a in art_before:
            try:
                st = os.stat(ap)
                if (st.st_size, st.st_mtime_ns) == art_before[a]:
                    errors.append(
                        f"产物 {a} 在证据执行前后**完全没变** —— "
                        f"它不是本次跑出来的（疑似复用预先放好的旧文件）。\n"
                        f"        修法：让证据命令真的生成它；"
                        f"若确属幂等/缓存产出，请改用 stdout 校验代替 artifacts"
                    )
            except OSError:
                pass

    return errors, info


def lock_fingerprint(data: dict) -> str:
    """对"门禁强度指标"做指纹，用于防悄悄放宽。"""
    feats = data.get("features") or []
    done = [f for f in feats if (f.get("status") == "completed")]
    strong = [
        f
        for f in done
        if isinstance(f.get("evidence"), dict) and f["evidence"].get("cmd")
    ]
    payload = json.dumps(
        {
            "total": len(feats),
            "completed": len(done),
            "strong_evidence": len(strong),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="证据门禁：标 completed 必须提供可执行的验收证据"
    )
    ap.add_argument("--root", default=None, help="项目根（默认当前目录）")
    ap.add_argument("--only", default=None, help="只校验指定功能 ID（逗号分隔）")
    ap.add_argument("--list", action="store_true", help="只列状态，不执行证据")
    ap.add_argument(
        "--update-lock",
        action="store_true",
        help="接受当前强度指标作为新基线（有意降级时才用）",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or os.getcwd())
    try:
        data = load_features(root)
    except Err as e:
        print(f"[!] {e}", file=sys.stderr)
        return 2

    feats = data.get("features") or []
    if not isinstance(feats, list):
        print(f"[!] {FEATURE_LIST} 的 features 不是数组", file=sys.stderr)
        return 2

    only = set(args.only.split(",")) if args.only else None
    errors: list[str] = []
    warns: list[str] = []
    infos: list[str] = []
    rows: list[dict] = []

    done = [f for f in feats if isinstance(f, dict) and f.get("status") == "completed"]
    if only:
        done = [f for f in done if f.get("id") in only]

    for f in done:
        fid = f.get("id") or f.get("title") or "<无 id>"
        ev = f.get("evidence")

        # 防线 1：必须有证据
        if ev is None or (isinstance(ev, str) and not ev.strip()):
            errors.append(
                f"{fid}: 状态是 completed 但**没有任何证据** —— "
                f"标完成必须给出可执行证据（见本文档头部的 evidence 契约）"
            )
            rows.append({"id": fid, "level": "error", "why": "无证据"})
            continue

        # 弱证据（字符串路径）：兼容但要求升级
        if isinstance(ev, str):
            p = os.path.join(root, ev)
            exists = os.path.isfile(p) or os.path.isdir(p)
            if not exists:
                errors.append(f"{fid}: evidence 指向的路径不存在: {ev}")
                rows.append({"id": fid, "level": "error", "why": "路径不存在"})
            else:
                warns.append(
                    f"{fid}: 证据是**字符串路径**（只证明文件存在，不证明它能跑）"
                    f" → {ev}\n"
                    f"        升级为可执行契约后可真正拦住假完成"
                )
                rows.append({"id": fid, "level": "warn", "why": "弱证据（字符串）"})
            continue

        # 强证据（对象）：执行校验
        if not isinstance(ev, dict):
            errors.append(f"{fid}: evidence 既不是字符串也不是对象")
            rows.append({"id": fid, "level": "error", "why": "evidence 类型不合法"})
            continue

        if args.list:
            rows.append(
                {"id": fid, "level": "info", "why": f"强证据: {ev.get('cmd', '')[:60]}"}
            )
            continue

        e_raw, i = run_evidence(root, ev, fid)
        e = [f"{fid}: {x}" for x in e_raw]
        errors += e
        infos += i
        rows.append(
            {
                "id": fid,
                "level": "error" if e else "ok",
                "why": "; ".join(e)[:160] if e else "证据通过",
            }
        )

    # ── 基线锁：强度指标不许悄悄下降 ──
    fp = lock_fingerprint(data)
    lp = os.path.join(root, LOCK_FILE)
    lock_note = ""
    if args.update_lock:
        try:
            os.makedirs(os.path.dirname(lp), exist_ok=True)
            with open(lp, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "fingerprint": fp,
                        "completed": len(
                            [f for f in feats if f.get("status") == "completed"]
                        ),
                    },
                    fh,
                    ensure_ascii=False,
                    indent=2,
                )
            infos.append(f"基线已更新: {fp}")
        except OSError as e:
            errors.append(f"写基线失败: {e.__class__.__name__}: {e.strerror or e}")
    elif os.path.isfile(lp):
        try:
            old = json.load(open(lp, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = {}
        if old.get("fingerprint") and old["fingerprint"] != fp:
            old_done = old.get("completed", 0)
            new_done = len([f for f in feats if f.get("status") == "completed"])
            if new_done < old_done:
                errors.append(
                    f"门禁强度下降：completed 从 {old_done} 降到 {new_done}。\n"
                    f"        功能被改回未完成却不说明理由，是绕过门禁的常见手法。\n"
                    f"        如果确实是有意降级，跑 --update-lock 并说明原因。"
                )
                lock_note = "强度下降"
            else:
                lock_note = "指标有变动（completed 未下降）"
    else:
        warns.append(
            "尚无证据基线（首次运行）。建议跑 --update-lock 建立基线，"
            "之后强度下降会被拦。"
        )

    exit_code = 1 if errors else 0

    if args.json:
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "root": root.replace("\\", "/"),
                    "completed": len(done),
                    "rows": rows,
                    "errors": errors,
                    "warnings": warns,
                    "info": infos,
                    "lock": {"fingerprint": fp, "note": lock_note},
                    "exit_code": exit_code,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return exit_code

    print(f"\n证据门禁 — {os.path.basename(root)}")
    print("=" * 68)
    print(f"  校验的 completed 功能: {len(done)} 个")
    if not done:
        print("\n  没有 completed 功能需要校验。")
        print("  （这也意味着：还没有任何功能声称「做完」）")

    for r in rows:
        mark = {"ok": "✅", "warn": "⚠️ ", "error": "❌", "info": "·"}[r["level"]]
        print(f"  {mark} {r['id']}: {r['why']}")

    if infos:
        print("\n--- 执行记录 ---")
        for i in infos:
            print(f"  · {i}")

    if warns:
        print(f"\n--- WARN ({len(warns)}) ---")
        for w in warns:
            print(f"  ⚠️  {w}")

    if errors:
        print(f"\n--- ERROR ({len(errors)}) ---")
        for e in errors:
            print(f"  ❌ {e}")

    print("\n" + "=" * 68)
    if errors:
        print(f"❌ {len(errors)} 项未通过 —— 交付被阻断。")
    else:
        print("✅ 所有 completed 功能都有可执行证据且校验通过。")
    print(f"退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
