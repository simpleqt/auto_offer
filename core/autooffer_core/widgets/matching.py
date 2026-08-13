"""选项语义匹配（docs/03 §3.2）：精确 → 归一化 → 包含 三级降级。

归一化只做去空白与全半角转换，不引入站点特定规则；
同义映射表仅作加速（把常见别名归一到候选词），不做硬依赖。
"""

from __future__ import annotations

import unicodedata

# 常见同义/别名映射（加速用）：key 归一化后等价于 value 列表中的候选。
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "本科": ("大学本科", "统招本科", "全日制本科", "学士"),
    "硕士": ("硕士研究生", "研究生"),
    "博士": ("博士研究生",),
    "大专": ("专科", "大学专科", "高职"),
    "至今": ("现在", "目前", "present", "now", "今"),
    "男": ("男性", "male"),
    "女": ("女性", "female"),
}


def normalize_text(s: str) -> str:
    """归一化：去全部空白、全角转半角、小写。"""
    s = unicodedata.normalize("NFKC", s)
    return "".join(s.split()).lower()


def _expand(target: str) -> list[str]:
    """目标词 + 同义词候选（归一化后去重，目标本身优先）。"""
    base = normalize_text(target)
    out = [base]
    for key, aliases in _SYNONYMS.items():
        group = (key, *aliases)
        if base in {normalize_text(g) for g in group}:
            out.extend(normalize_text(a) for a in group)
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def match_option(target: str, options: list[str]) -> tuple[str, str] | None:
    """在选项列表中按 精确 → 归一化 → 包含 三级匹配目标值。

    返回 (命中的原始选项文本, 匹配级别)；未命中返回 None。
    包含级为双向包含（目标含选项 或 选项含目标），取最短候选以减少误命中。
    """
    if not target or not options:
        return None

    # L1 精确
    for opt in options:
        if opt == target:
            return opt, "exact"

    targets = _expand(target)

    # L2 归一化（含同义词）
    for opt in options:
        if normalize_text(opt) in targets:
            return opt, "normalized"

    # L3 包含（双向）
    best: tuple[str, int] | None = None
    for opt in options:
        norm = normalize_text(opt)
        if not norm:
            continue
        for t in targets:
            if t and (t in norm or norm in t):
                if best is None or len(opt) < len(best[0]):
                    best = (opt, len(opt))
                break
    if best is not None:
        return best[0], "contains"
    return None
