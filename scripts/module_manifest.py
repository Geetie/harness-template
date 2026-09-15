#!/usr/bin/env python3
"""模块清单（单一真相源）—— 定义每个可插拔模块拥有哪些文件与目录。

为什么单独抽一个模块：
--------------
此前 `init.py` / `new_project.py` / `harness_lint.py` 各自维护一份模块→路径的映射，
结果三份互相漂移（真实事故：new_project 缺 `.harness/ROUTER.md`，lint 有；
delivery 只声明了目录、没声明目录内文件，导致"关掉 delivery 后
文档里对 `acceptance.md` 的引用仍被当成死链"）。

漂移在可插拔场景下是**致命**的：
- 生成侧漏了路径 → 关模块时文件没被过滤 → "关掉的模块留下残骸"
- 检查侧漏了路径 → 死链检查不认"模块已关闭" → 几十条噪音淹没真问题

所以：模块归属只在这里定义一次，三个脚本都 import 它。

数据结构
--------
MODULES: dict[str, dict]  —— 以模块 ID 为键，值为:
    owned   : list[str]  该模块拥有的路径（文件用全路径，目录以 / 结尾）
    deps    : list[str]  依赖的模块 ID（缺依赖时显式降级，见 MODULES.md）
    desc    : str        一句话人话说明（用于 --modules 打印）

目录与文件都要列全：目录用于"复制/过滤"，文件用于"引用豁免"。
只列目录是不够的 —— 模块被关掉后目录已不存在，无法从目录反推文件名。
"""

from __future__ import annotations

import os

# ──────────────────────────────────────────────────────────────────────────
# 模块清单
# ──────────────────────────────────────────────────────────────────────────
MODULES: dict[str, dict] = {
    "instructions": {
        "desc": "指令层：AGENTS.md 与项目约定，Agent 读它才知道要做什么",
        "layer": "①指令层",
        "owned": [
            "AGENTS.md",
            "CLAUDE.md",
            ".harness/instructions/AGENTS-guidelines.md",
        ],
        "deps": [],
    },
    "state": {
        "desc": "状态层：progress.md 等进度落点，跨会话交接的凭据",
        "layer": "②状态层",
        "owned": [
            ".harness/state/progress.md",
            ".harness/state/feature_list.json",
            ".harness/state/session-handoff.md",
            ".harness/state/archive/README.md",
            ".harness/STATE-PROTOCOL.md",
        ],
        "deps": ["instructions"],
    },
    "verification": {
        "desc": "验证层：结构校验 init.py + 一致性检查 harness_lint.py",
        "layer": "③验证层",
        "owned": [
            ".harness/VERIFICATION.md",
            "scripts/init.py",
            "scripts/harness_lint.py",
            "scripts/module_manifest.py",
            # sync_lib 与 module_manifest 同属"生成/校验基础设施"：
            # new_project 依赖二者的快照能力，而 new_project 在每个档位都有。
            "scripts/sync_lib.py",
            "scripts/state_health.py",
            ".harness/hooks/hooks.json",
            # 证据门禁：标 completed 必须给可执行证据（防"只声明完成"）
            "scripts/evidence_gate.py",
            # 运行时探针：确认证据真的调用了被测代码（拦"import 但不用"）
            "scripts/_evidence_probe.py",
            ".githooks/pre-commit",
            ".githooks/pre-commit.py",
            # harness_version.py 必须归 verification：它被 init/lint/new_project/guard
            # 全部 import 作为版本单一真相源，若随某个可选模块一起被关掉，
            # 其余脚本会立刻 ImportError。verification 是三档位都有的模块。
            "scripts/harness_version.py",
            # 注意：不要在这里写 ".githooks/hooks.json" —— 该文件从不存在，
            # 是早期版本凭印象写下的臆想路径（真实文件是 .harness/hooks/hooks.json）。
            # 后果：init 的"必需文件清单"永远少一项、可插拔自检报一条假缺失。
            # 教训同 P21：清单里的每一条都必须在磁盘上能被证实。
        ],
        "deps": [],
    },
    "memory": {
        "desc": "记忆层：lessons.md 等项目教训，避免重蹈覆辙",
        "layer": "④记忆层",
        "owned": [
            ".harness/memory/lessons.md",
            ".harness/memory/failure-modes.md",
            ".harness/memory/harness-antipatterns.md",
            ".harness/memory/GLOBAL-LESSONS.md",
            ".harness/LESSON-PROMOTION.md",
            ".harness/memory/LOCAL-ENV.md",
        ],
        "deps": ["instructions"],
    },
    "delivery": {
        "desc": "交付层：DoD 模板与验收清单，防『交付塌方』（占位符/未集成）",
        "layer": "⑥交付层",
        "owned": [
            ".harness/delivery/README.md",
            ".harness/delivery/DoD-TEMPLATE.md",
            ".harness/delivery/acceptance.md",
            ".harness/delivery/hardening-checklist.md",
            ".harness/delivery/audit-prompt.md",
        ],
        "deps": ["verification"],
    },
    "routing": {
        "desc": "路由层：ROUTER.md 三级加载，按需给 Agent 灌能力卡以省 token",
        "layer": "⑤技能层",
        "owned": [
            ".harness/routing/ROUTER.md",
            ".harness/routing/capabilities/orientation.md",
            ".harness/routing/capabilities/delivery-audit.md",
            ".harness/routing/capabilities/integration-check.md",
        ],
        "deps": [],
    },
    "decisions": {
        "desc": "决策层：ADR 台账与协议，保证决策变更后文档不再静默过时",
        "layer": "⑦决策层",
        "owned": [
            ".harness/DECISION-PROTOCOL.md",
            ".harness/planning/DECISIONS.md",
            ".harness/planning/decisions/ADR-NNN-TEMPLATE.md",
            ".harness/planning/decisions/ADR-000-decision-ledger.md",
        ],
        "deps": [],
    },
    "planning": {
        "desc": "规划层：CONSTITUTION.md 与 SPEC-TEMPLATE.md，任务前先定规矩",
        "layer": "⑧规划层",
        "owned": [
            ".harness/planning/CONSTITUTION.md",
            ".harness/planning/SPEC-TEMPLATE.md",
        ],
        "deps": [],
    },
    "skills": {
        "desc": "技能层：按需加载的操作手册（Orientation/交付门禁等）",
        "layer": "⑤技能层",
        "owned": [
            ".harness/skills/orientation/SKILL.md",
            ".harness/skills/delivery-gate/SKILL.md",
            ".harness/skills/converge-audit/SKILL.md",
            ".harness/skills/submit-and-harness-sync/SKILL.md",
        ],
        "deps": ["instructions"],
    },
    "code-quality": {
        "desc": "代码规范层：ESLint/Prettier/ruff 等 lint+format 的统一接线与门禁",
        "layer": "③验证层",
        "owned": [
            "scripts/quality.py",
            ".harness/CODE-QUALITY.md",
        ],
        # 依赖 verification：pre-commit 由它装载，且 quality.py 复用版本真相源。
        "deps": ["verification"],
    },
    "design": {
        "desc": "设计层：SOLID 判据 + 模式选择 + 技术债信号检测（写代码前的判断）",
        "layer": "⑧规划层",
        "owned": [
            "scripts/design_smell.py",
            ".harness/design/DESIGN-PRINCIPLES.md",
        ],
        "deps": [],
    },
    "testing": {
        "desc": "测试治理层：智能选测 / 分层 / oracle 有效性审计 / 汇报模板",
        "layer": "③验证层",
        "owned": [
            "scripts/test_runner.py",
            "scripts/test_audit.py",
            ".harness/testing/TEST-STRATEGY.md",
        ],
        "deps": ["verification"],
    },
    "upgrade": {
        "desc": "升级层：把模板的改进三向合并回已生成的项目（sync_template.py）",
        "layer": "③验证层",
        "owned": [
            "scripts/sync_template.py",
            # ⚠️ sync_lib.py **不在这里**（实测崩溃）：它是 new_project.py 的必需依赖
            # （要用 SYNC.snapshot 写生成基线），而 new_project 在每个档位都有。
            # 归到 upgrade 会让 minimal/standard 生成的项目里 new_project.py
            # 一跑就 `ModuleNotFoundError: No module named 'sync_lib'`。
            # 已移到 verification（与 module_manifest.py 同处，二者都是生成/校验基础设施）。
            # 注意：**排除优先于包含** —— 文件只要出现在任何"已关闭模块"的 owned 里
            # 就会被排除，所以不能"两边都放"，必须从这边移走。
        ],
        # 依赖 verification：sync_template 需要 harness_version（版本单一真相源），
        # 而它归 verification 所有。缺了会 ImportError，不是"优雅降级"。
        "deps": ["verification"],
    },
    "placeholder-guard": {
        # guard:allow —— 本行在描述「占位符守卫」这个模块，不是占位实现
        "desc": "占位符守卫：提交前扫未完成标记与占位表达",
        "layer": "③验证层",
        "owned": ["scripts/no_placeholder_guard.py"],
        "deps": ["verification"],
    },
    "integration-check": {
        "desc": "集成检查：确认新模块真的被接入调用链，而非只在仓库里躺着",
        "layer": "③验证层",
        "owned": ["scripts/check_integration.py"],
        "deps": ["verification"],
    },
}

# 模块必须检查的"关键文件"（用于体检输出里点名"这一层少了哪一份"）。
# 与 owned 的区别：owned 是"模块拥有什么"（含协议文档、模板）；
# required 是"少这份就算这层不完整"（体检红线，越少越好，避免噪音）。
MODULE_REQUIRED: dict[str, list[str]] = {
    "instructions": ["AGENTS.md"],
    "state": [
        ".harness/state/progress.md",
        ".harness/state/feature_list.json",
        ".harness/state/session-handoff.md",
    ],
    "verification": [".harness/VERIFICATION.md", "scripts/evidence_gate.py"],
    "memory": [
        ".harness/memory/lessons.md",
        ".harness/memory/failure-modes.md",
        ".harness/memory/GLOBAL-LESSONS.md",
    ],
    "delivery": [
        ".harness/delivery/README.md",
        ".harness/delivery/DoD-TEMPLATE.md",
        ".harness/delivery/acceptance.md",
        ".harness/delivery/hardening-checklist.md",
    ],
    "routing": [".harness/routing/ROUTER.md"],
    "decisions": [".harness/DECISION-PROTOCOL.md", ".harness/planning/DECISIONS.md"],
    "planning": [
        ".harness/planning/CONSTITUTION.md",
        ".harness/planning/SPEC-TEMPLATE.md",
    ],
    "skills": [".harness/skills/orientation/SKILL.md"],
    "placeholder-guard": ["scripts/no_placeholder_guard.py"],
    "integration-check": ["scripts/check_integration.py"],
    "code-quality": ["scripts/quality.py", ".harness/CODE-QUALITY.md"],
    "design": ["scripts/design_smell.py", ".harness/design/DESIGN-PRINCIPLES.md"],
    "testing": ["scripts/test_runner.py", ".harness/testing/TEST-STRATEGY.md"],
    # ⚠️ sync_lib.py **不在这里**（实测崩溃）：它是 new_project.py 的必需依赖
    # （要用 SYNC.snapshot 写生成基线），而 new_project 在基础档就存在。
    # 归到 upgrade 会让 minimal/standard 生成的项目里 new_project.py
    # 一跑就 ModuleNotFoundError: No module named 'sync_lib'。
    # 已移到 verification（与 module_manifest.py 同处，二者都是生成/校验的基础设施）。
    "upgrade": ["scripts/sync_template.py"],
}

# 三个预置档位：从少到多。minimal 是"能跑起来的最小可信骨架"。
PRESETS: dict[str, list[str]] = {
    "minimal": ["instructions", "state", "verification", "memory"],
    "standard": [
        "instructions",
        "state",
        "verification",
        "memory",
        "delivery",
        "planning",
        "placeholder-guard",
        "skills",
        "code-quality",
        "design",
        "testing",
        "integration-check",
    ],
    "full": [
        "instructions",
        "state",
        "verification",
        "memory",
        "delivery",
        "routing",
        "decisions",
        "planning",
        "skills",
        "placeholder-guard",
        "integration-check",
        "upgrade",
        "code-quality",
        "design",
        "testing",
    ],
}

# 元文档：无论关掉哪些模块都要保留（它们解释"这个模板是什么"）
# ⚠️ 路径必须与磁盘真实位置一致 —— 写错会让 init.py 体检报"缺失"，
#    让人以为是项目少了文件（真实事故：MAINTENANCE.md 漏写 .harness/ 前缀）。
ALWAYS_FILES = [
    "README.md",
    ".harness/CAPABILITIES.md",
    ".harness/MAINTENANCE.md",
    ".harness/MODULES.md",
    ".harness/README.md",
]

# 不复制到新项目的文件（评审稿、模板仓库自身标记、临时产物）
# ⚠️ 必须写**完整相对路径**：早先只写 basename 时，memory 子目录下的同名文件
#    因路径比较不匹配而逃过过滤，被复制进了新项目（交付泄漏，已修）。
# 这里也是单一真相源：new_project（复制侧）与 sync_template（比较侧）共用，
# 否则同步器会把"模板有但故意不复制"的文件当成"新增项"反复报。
EXCLUDE_FILES = {
    # 模板仓库自身的运行配置：生成的项目会**新写**自己的 config.json，
    # 不该继承模板的那份（否则 new_project 先复制再覆盖，白做一遍且易出错）。
    ".harness/config.json",
    ".harness/memory/_REVIEW-候选清单.md",
    # 模板仓库自身标记：生成的项目不是模板仓库，绝不能继承它。
    # 一旦泄漏，新项目的 pre-commit 会误判"我是模板"，
    # 从而不去强制 progress.md 更新 —— 门禁静默失效。
    ".harness/TEMPLATE-REPO",
}


def module_paths() -> dict[str, list[str]]:
    """模块 ID → 拥有路径列表（供生成侧过滤、检查侧豁免共用）。"""
    return {mid: list(m["owned"]) for mid, m in MODULES.items()}


def self_check(root: str | None = None) -> list[str]:
    """校验本清单自身的**不变式**，返回问题列表（空 = 通过）。

    为什么需要它（实测踩到两个坑）：
      ① **一个文件被两个模块 own** —— `sync_lib.py` 曾同时出现在
         `verification` 与 `upgrade` 的 owned 里。由于**排除优先于包含**
         （文件只要落在任一"已关闭模块"的 owned 里就会被排除），
         结果是 minimal/standard 档生成的项目里 `new_project.py` 一跑
         就 `ModuleNotFoundError`。**清单自己矛盾，但没有任何地方检查过。**
      ② **required 与 owned 语义不同却容易漂移** ——
         owned 是"模块拥有什么"（复制过滤用），
         required 是"体检红线"（少了就算这层不完整）。
         两者必须满足 `required ⊆ owned`，但没有校验时很容易改一边忘一边。

    校验项（每条都对应一种真实故障）：
      1. 同一文件不被两个模块 own（否则排除/包含行为不可预期）
      2. `required ⊆ owned`（否则体检会点名一个模块并不拥有的文件）
      3. 所有声明路径存在于磁盘（否则复制时会静默少文件）
      4. 每个模块的 owned 非空（空模块 = 声明了但没内容）
      5. deps 引用的模块确实存在（否则依赖解析会无声跳过）

    root 为 None 时以本文件所在目录的上级为仓库根。
    """
    problems: list[str] = []
    if root is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. 同一文件被多个模块 own
    owner_of: dict[str, list[str]] = {}
    for mid, info in MODULES.items():
        for f in info.get("owned", []):
            owner_of.setdefault(f, []).append(mid)
    for f, owners in sorted(owner_of.items()):
        if len(owners) > 1:
            problems.append(
                f"文件被多个模块同时 own: {f} → {owners}。"
                f"因「排除优先于包含」，任一模块关闭都会把它排除，"
                f"行为不可预期。应只留一个归属"
            )

    # 2. required ⊆ owned
    for mid, req in sorted(MODULE_REQUIRED.items()):
        owned = set(MODULES.get(mid, {}).get("owned", []))
        extra = sorted(set(req) - owned)
        if extra:
            problems.append(
                f"MODULE_REQUIRED[{mid}] 有文件不在 owned 里: {extra}"
                f"（体检会点名该模块并不拥有的文件）"
            )

    # 3. 声明路径存在于磁盘
    for mid, info in sorted(MODULES.items()):
        for f in info.get("owned", []):
            if not os.path.exists(os.path.join(root, f)):
                problems.append(f"MODULES[{mid}].owned 声明了不存在的路径: {f}")
    for mid, req in sorted(MODULE_REQUIRED.items()):
        for f in req:
            if not os.path.exists(os.path.join(root, f)):
                problems.append(f"MODULE_REQUIRED[{mid}] 声明了不存在的路径: {f}")

    # 4. owned 非空
    for mid, info in sorted(MODULES.items()):
        if not info.get("owned"):
            problems.append(f"MODULES[{mid}] 的 owned 为空（声明了模块却没有内容）")

    # 5. deps 指向存在的模块
    for mid, info in sorted(MODULES.items()):
        for dep in info.get("deps", []):
            if dep not in MODULES:
                problems.append(
                    f"MODULES[{mid}].deps 引用了不存在的模块: {dep}"
                    f"（依赖解析会无声跳过）"
                )

    return problems


def module_deps() -> dict[str, list[str]]:
    """模块 ID → 依赖的模块 ID 列表。"""
    return {mid: list(m["deps"]) for mid, m in MODULES.items()}


def module_required() -> dict[str, list[str]]:
    """模块 ID → 该层"少了就算不完整"的关键文件列表。"""
    return {mid: list(MODULE_REQUIRED.get(mid, [])) for mid in MODULES}


def module_layers() -> dict[str, str]:
    """模块 ID → 人话层名（①指令层…⑧规划层），用于体检报告。"""
    return {mid: m.get("layer", "") for mid, m in MODULES.items()}


def always_files() -> list[tuple[str, str]]:
    """始终检查的元文档：(标签, 路径)。这些文件解释"模板是什么"，不随模块开关关闭。"""
    labels = {
        "README.md": "总览",
        ".harness/README.md": "总览",
        ".harness/MAINTENANCE.md": "维护",
        ".harness/MODULES.md": "模块",
    }
    return [(labels.get(p, "总览"), p) for p in ALWAYS_FILES]


def resolve_modules(
    enabled_off: set[str] | None = None, preset: str | None = None
) -> tuple[dict[str, bool], list[str]]:
    """算出每个模块的最终开关，并**自动补齐依赖**。

    返回 (开关表, 告警列表)。告警不静默 —— 依赖被自动打开时必须让用户知道，
    否则他会以为"我关掉的东西真的没跑"。
    """
    off = set(enabled_off or ())
    if preset:
        keep = set(PRESETS.get(preset, PRESETS["full"]))
        off |= set(MODULES) - keep

    on = {mid: (mid not in off) for mid in MODULES}

    warnings: list[str] = []
    changed = True
    while changed:
        changed = False
        for mid, m in MODULES.items():
            if not on[mid]:
                continue
            for dep in m["deps"]:
                if not on.get(dep, True):
                    on[dep] = True
                    warnings.append(
                        f"模块 {mid} 依赖 {dep}，已自动启用 {dep}"
                        f"（否则 {mid} 缺少依赖会静默降级）"
                    )
                    changed = True
    return on, warnings


def norm_rel(path: str) -> str:
    """把仓库相对路径规范化成统一形式（正斜杠、无前导 `./`）。

    ⚠️ 千万不要写 `path.lstrip("./")` —— `lstrip` 的参数是**字符集**不是前缀，
    它会把开头的 `.` 和 `/` 全部剥掉，于是 `.harness/x.md` 变成 `harness/x.md`，
    **前导点被吃掉**，所有以点开头的目录都会匹配失败。
    （真实事故：模块归属匹配全部失效，报一堆"不属于任何模块"的假阳性。）
    """
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def owned_by(rel_path: str) -> str | None:
    """判断某个仓库相对路径属于哪个模块；不属于任何模块返回 None。

    匹配规则：精确相等，或路径落在某个"目录型"所属物之下。
    """
    norm = norm_rel(rel_path)
    best: tuple[str, int] | None = None
    for mid, m in MODULES.items():
        for p in m["owned"]:
            pn = norm_rel(p)
            if pn.endswith("/"):
                if norm == pn.rstrip("/") or norm.startswith(pn):
                    cand = (mid, len(pn))
                    if best is None or cand[1] > best[1]:
                        best = cand
            elif norm == pn:
                cand = (mid, len(pn))
                if best is None or cand[1] > best[1]:
                    best = cand
    return best[0] if best else None


def owned_names() -> set[str]:
    """所有模块拥有的产物的 basename 集合（供"裸文件名引用"豁免比对）。"""
    names: set[str] = set()
    for m in MODULES.values():
        for p in m["owned"]:
            pn = norm_rel(p).rstrip("/")
            if not pn:
                continue
            names.add(pn.rsplit("/", 1)[-1])
    return names


if __name__ == "__main__":
    import json

    print(
        json.dumps(
            {
                "modules": MODULES,
                "presets": PRESETS,
                "always_files": ALWAYS_FILES,
                "exclude_files": sorted(EXCLUDE_FILES),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
