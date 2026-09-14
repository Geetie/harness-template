#!/usr/bin/env python3
"""模板同步的共享库（单一真相源）。

为什么单独抽一个模块：
--------------
`new_project.py`（生成时记录基线）与 `sync_template.py`（同步时做三向合并）
必须**用同一套哈希算法与同一套分类规则**。两份各写一份必然漂移（P21）。

三向合并是什么、为什么必须它：
--------------------------
只看"项目文件 vs 模板文件"两个快照，无法区分下面两种完全不同的情况：

| base(当初给你的) | ours(你现在) | theirs(模板现在) | 真实情况 | 该怎么办 |
|---|---|---|---|---|
| A | A | B | 你没动过，模板升级了 | **安全覆盖** |
| A | B | A | 你改过，模板没变 | **不动**（保护你的改动） |
| A | B | C | 你改过，模板也改了 | **冲突**，人工裁决 |

如果只看 ours vs theirs，第 2 行和第 3 行看起来一模一样（都是"两边内容不同"），
于是要么粗暴覆盖（吃掉用户的手工填写），要么一律不覆盖（模板永远升不上去）。

所以：**生成时把 base 记进 config.json 的 `template_sync.files`**，
同步时三个快照一起比，才能得出正确结论。

旧项目（没有 template_sync 字段）怎么办：
------------------------------
降级为**双向比较**，`base` 缺失。此时无法判断"差异是谁造成的"，
因此**默认一律不覆盖**，只报告差异 + 给出 diff，交给人裁决。
宁可不同步，也不能吃掉用户写的东西。
"""

from __future__ import annotations

import hashlib
import os

# 同步时永远不碰的文件（相对项目根）。
# 这些是"项目自己的内容"，模板只提供空壳，用户填的东西是资产。
NEVER_SYNC = {
    ".harness/config.json",  # 项目自身的开关，同步它等于覆盖用户的模块选择
    ".harness/state/progress.md",  # 项目变更日志 —— 用户资产
    ".harness/state/session-handoff.md",
    ".harness/state/feature_list.json",
    ".harness/memory/lessons.md",  # 项目踩的坑 —— 用户资产
    ".harness/TEMPLATE-REPO",  # 模板仓库标记，绝不能泄漏
}

# 目录：整棵跳过（内容与项目强相关）
NEVER_SYNC_DIRS = (
    ".harness/state/archive",
    ".harness/planning/decisions",  # 项目的 ADR 是项目自己的决策
)

SYNC_FIELD = "template_sync"


class ReadError(Exception):
    """读文件失败。携带路径与原因，绝不静默吞掉。"""


def sha256_file(path: str) -> str:
    """算文件 sha256。

    ⚠️ 读失败**抛异常而不是返回 None**（S14：静默返回 None 会让调用方
    `if not x: continue`，于是"没读到"与"读到且一致"输出完全一样，
    整个同步器会安静地空转，界面还显示"已是最新"）。
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError as e:
        raise ReadError(f"{path} — {e.__class__.__name__}: {e.strerror or e}") from e
    return h.hexdigest()


def is_never_sync(rel: str) -> bool:
    """该文件是否属于"永不同步"的项目资产。"""
    r = rel.replace("\\", "/")
    if r in NEVER_SYNC:
        return True
    return any(r == d or r.startswith(d + "/") for d in NEVER_SYNC_DIRS)


def sha256_bytes(data: bytes) -> str:
    """对内存字节算 sha256 —— 用于"替换后再算哈希"的场景。"""
    return hashlib.sha256(data).hexdigest()


# 这些文件**不参与**占位符替换 —— 生成侧与同步侧必须遵守同一规则。
# new_project.py 的源码里含有 {{PROJECT_NAME}} 等字面量（用作打印提示），
# 替换会把它写死成某个项目名，下次用它生成别的项目就出错。
# 所以生成时 substitute() 跳过它；同步器若不同样跳过，
# 两边口径就又不一致（实测：全新项目稳定报 new_project.py"有更新"）。
NO_SUBSTITUTE_BASENAMES = {"new_project.py"}


def apply_substitutions(
    data: bytes, mapping: dict[str, str], rel: str | None = None
) -> bytes:
    """把 {{KEY}} 替换成 mapping 里的值。

    为什么必须有它：模板里是 `{{PROJECT_NAME}}`，项目里是实值。
    同步器比较的是"模板当前 vs 项目当前"，若不对模板施加同样的替换，
    两边**永远不相等**，于是每个新项目都被误判成"模板有更新"（实测踩到）。

    替换失败（编码不是 utf-8）时**原样返回**而不抛错 ——
    二进制文件（图片等）本来就没有占位符，不该因为解码失败就中断整个同步。
    """
    if not mapping:
        return data
    if rel:
        base_name = rel.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base_name in {n.lower() for n in NO_SUBSTITUTE_BASENAMES}:
            return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    for k, v in mapping.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text.encode("utf-8")


def snapshot(
    root: str, rels: list[str], substitutions: dict[str, str] | None = None
) -> tuple[dict[str, str], list[str]]:
    """对给定相对路径列表做快照。

    substitutions: 若提供，先对内容施加替换再算哈希。
      **模板侧快照必须传它**（用项目 config.json 里记录的 mapping），
      否则与项目侧口径不一致，判断全错。项目侧快照不传（项目里已是实值）。

    返回 ({rel: sha}, [读失败说明])。**失败不静默**：第二条一定返回可读的原因，
    调用方必须打印它，否则"同步成功"可能是假象。
    """
    out: dict[str, str] = {}
    failed: list[str] = []
    for rel in rels:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "rb") as f:
                data = f.read()
        except OSError as e:
            failed.append(f"{p} — {e.__class__.__name__}: {e.strerror or e}")
            continue
        if substitutions:
            data = apply_substitutions(data, substitutions, rel=rel)
        out[rel] = sha256_bytes(data)
    return out, failed


def classify(
    base: dict[str, str], ours: dict[str, str], theirs: dict[str, str]
) -> dict[str, list[str]]:
    """三向比较，输出五类结果。

    base   : 生成时记录的基线（可能为空 —— 旧项目没有）
    ours   : 项目当前文件哈希
    theirs : 模板当前文件哈希

    返回键：
      added       模板有、项目无            → 可安全新增
      updatable   模板改了、项目没动过      → 可安全覆盖
      local_only  项目有、模板无            → 保留（不删），仅提示
      conflict    两边都改过                → 必须人工裁决
      unchanged   一致                     → 不动

    **base 为空时（旧项目）**：无法区分"谁改的"，一律归入 conflict（不覆盖）。
    """
    res = {
        "added": [],
        "updatable": [],
        "local_only": [],
        "conflict": [],
        "unchanged": [],
    }
    for rel, th in theirs.items():
        if is_never_sync(rel):
            continue
        ou = ours.get(rel)
        ba = base.get(rel)
        if ou is None:
            res["added"].append(rel)
        elif ou == th:
            res["unchanged"].append(rel)
        elif ba is None:
            # 没有基线 → 不知道差异是谁造成的 → 保守归入冲突
            res["conflict"].append(rel)
        elif ba == ou:
            res["updatable"].append(rel)  # 项目没动过，模板改了
        elif ba == th:
            res["unchanged"].append(rel)  # 模板没改，是项目自己改的 → 保护
        else:
            res["conflict"].append(rel)  # 两边都改了

    for rel in ours:
        if rel not in theirs and not is_never_sync(rel):
            res["local_only"].append(rel)

    for k in res:
        res[k].sort()
    return res
