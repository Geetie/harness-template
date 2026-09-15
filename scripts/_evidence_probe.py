#!/usr/bin/env python3
"""证据探针 —— 运行时确认"这段代码真的被执行了"。

为什么需要它
------------
`evidence_gate.py` 原来只做**静态文本匹配**：证据脚本里出现 `cart` 这个词
就算"触及了 src/cart.py"。于是下面这种写法能骗过门禁（实测绕过）：

    import src.cart          # 只为让文本匹配通过
    print("总价: 42.0")       # 硬编码正确答案，根本没调用

静态匹配永远可以这样绕（`getattr`、字符串拼名、变量间接调用……）。
只有**运行时观测**能回答"这段代码到底跑没跑"。

本探针的做法
------------
用 `sys.settrace` 记录执行过的所有文件，跑完后把清单写到日志文件。
不向 stdout/stderr 输出任何东西 —— 否则会污染证据脚本的输出比对。

调用方式（由 evidence_gate.py 自动拼接，不需要手写）：

    python scripts/_evidence_probe.py <目标脚本> <日志文件> [参数...]

退出码：透传目标脚本的退出码（探针自身出错才返回 90+ 并打印原因）

已知边界（必须知道）
--------------------
· `sys.settrace` **只对当前线程生效** —— 证据脚本若自己开线程跑被测代码，
  可能漏记。验收脚本通常单线程，可接受。
· 只支持 Python。其他语言（node/jest/go test）走静态检查降级，
  由 evidence_gate 明确标注"未做运行时验证"。
· 有性能开销（settrace 很慢），但验收脚本应当很短，可接受。
"""

from __future__ import annotations

import os
import runpy
import sys

# 探针自身的失败码（与目标脚本的退出码区分开，避免混淆）
PROBE_INTERNAL_ERROR = 90
PROBE_USAGE_ERROR = 91


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "用法: _evidence_probe.py <目标脚本> <日志文件> [参数...]", file=sys.stderr
        )
        return PROBE_USAGE_ERROR

    target = sys.argv[1]
    log_path = sys.argv[2]
    extra = sys.argv[3:]

    if not os.path.isfile(target):
        print(f"[probe] 目标脚本不存在: {target}", file=sys.stderr)
        return PROBE_INTERNAL_ERROR

    touched: set[str] = set()
    retvals: dict[str, str] = {}  # "文件::函数名" -> 返回值的字符串形式

    def tracer(frame, event, arg):
        if event == "call":
            fn = frame.f_code.co_filename
            if fn:
                # ⚠️ 记「文件::函数名」而不是只记文件 ——
                # 因为 `import src.cart` 本身就会执行模块级代码（co_name == "<module>"），
                # 只记文件的话「import 但不调用」会被误判成"执行过"（实测绕过）。
                # 校验时需要区分「模块被加载」与「里面的函数被调用」。
                touched.add(f"{os.path.abspath(fn)}::{frame.f_code.co_name}")
        elif event == "return":
            # 记返回值：只验证"函数被调用"是不够的 ——
            # `total()` 调了却 print 硬编码答案，照样能骗过（实测 E1 绕过）。
            # 有了返回值，就能要求「它的值必须出现在输出里」，
            # 从而验证"输出确实由它产生"，而不只是"它被碰过"。
            fn = frame.f_code.co_filename
            if fn:
                try:
                    s = str(arg)
                except Exception:  # noqa: BLE001 —— __str__ 可能抛任意异常
                    s = ""
                if s and len(s) <= 200:
                    key = f"{os.path.abspath(fn)}::{frame.f_code.co_name}"
                    retvals.setdefault(key, s)
        return tracer

    # 模拟把目标当脚本跑：设 sys.argv，让 `if __name__ == "__main__"` 生效
    saved_argv = sys.argv[:]
    sys.argv = [target, *extra]
    target_dir = os.path.dirname(os.path.abspath(target))
    sys.path.insert(0, target_dir)

    code = 0
    try:
        sys.settrace(tracer)
        runpy.run_path(target, run_name="__main__")
    except SystemExit as e:
        # 目标脚本主动退出（含 pytest 的退出码）—— 正常透传
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException as e:  # noqa: BLE001 —— 必须兜住，否则探针自己崩掉会掩盖真实结果
        # 不吞：把异常类型与信息写进 stderr，让调用方看到真实失败原因
        import traceback

        traceback.print_exc()
        print(f"[probe] 目标脚本抛出 {e.__class__.__name__}: {e}", file=sys.stderr)
        code = 1
    finally:
        sys.settrace(None)
        sys.argv = saved_argv
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(touched)))
            # 返回值单独一个文件：用 \x1f 分隔，避免值里含 : 或 :: 造成误解码
            with open(log_path + ".ret", "w", encoding="utf-8") as f:
                for k, v in sorted(retvals.items()):
                    f.write(f"{k}\x1f{v}\n")
        except OSError as e:
            # 日志写不了 = 无法验证 touches，必须显式报错而不是让门禁"以为通过"
            print(
                f"[probe] 写执行日志失败: {e.__class__.__name__}: {e.strerror or e}",
                file=sys.stderr,
            )
            return PROBE_INTERNAL_ERROR

    return code


if __name__ == "__main__":
    sys.exit(main())
