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
            "scripts/state_health.py",
            ".harness/hooks/hooks.json",
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
    "upgrade": {
        "desc": "升级层：把模板的改进三向合并回已生成的项目（sync_template.py）",
        "layer": "③验证层",
        "owned": [
            "scripts/sync_template.py",
            "scripts/sync_lib.py",
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
    "verification": [".harness/VERIFICATION.md"],
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
    "upgrade": ["scripts/sync_template.py", "scripts/sync_lib.py"],
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
    ],
}

# 元文档：无论关掉哪些模块都要保留（它们解释"这个模板是什么"）
# ⚠️ 路径必须与磁盘真实位置一致 —— 写错会让 init.py 体检报"缺失"，
#    让人以为是项目少了文件（真实事故：MAINTENANCE.md 漏写 .harness/ 前缀）。
ALWAYS_FILES = [
    "README.md",
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
    ".harness/memory/_REVIEW-候选清单.md",
    # 模板仓库自身标记：生成的项目不是模板仓库，绝不能继承它。
    # 一旦泄漏，新项目的 pre-commit 会误判"我是模板"，
    # 从而不去强制 progress.md 更新 —— 门禁静默失效。
    ".harness/TEMPLATE-REPO",
}


def module_paths() -> dict[str, list[str]]:
    """模块 ID → 拥有路径列表（供生成侧过滤、检查侧豁免共用）。"""
    return {mid: list(m["owned"]) for mid, m in MODULES.items()}


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
