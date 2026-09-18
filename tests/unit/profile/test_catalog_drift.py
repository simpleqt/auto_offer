"""字段语义目录漂移守护（canonical dictionary 一致性）。

字段语义曾分散 6 处维护（户籍修复一次动 4 个代码点）。catalog 收敛
Python 侧后，本文件锁住三端一致性：
1. flat_profile 实际输出的标签 ⊆ FLAT_LABELS（新标签必须先登记）；
2. 别名目标 ⊆ 实际可输出标签（改 flat 标签不改别名即被拦下）；
3. resolver._CATALOG_SPEC 的路径在 Profile schema 上真实存在
   （schema 改名/删字段不更新目录即被拦下）。
"""

from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel

from autooffer_core.profile.catalog import (
    FLAT_LABELS,
    LABEL_ALIASES,
    RESTRICTED_LABELS,
    validate_catalog,
)
from autooffer_core.profile.resolver import _CATALOG_SPEC
from autooffer_core.profile.schema import Profile
from autooffer_core.testing import build_sample_profile
from autooffer_server.services.flat_profile import flatten_profile


def _emitted_labels(payload: dict[str, Any], *, sensitive: bool) -> set[str]:
    flat = flatten_profile(payload, include_sensitive=sensitive)
    labels: set[str] = set()
    for sec in flat["sections"]:
        if sec["kind"] == "repeat":
            for item in sec["items"]:
                labels.update(item)
        else:
            labels.update(sec["values"])
    return labels


def test_catalog_self_consistent() -> None:
    assert validate_catalog() == []


def test_flat_output_labels_are_registered() -> None:
    """实际输出 ⊆ 登记；授权后的敏感扩展标签也在册。"""
    payload = build_sample_profile().model_dump(mode="json")
    # other 段并入 extended.links 的用户自定键（github 等）：宽容豁免
    link_keys = set((payload.get("extended") or {}).get("links") or {})
    normal = _emitted_labels(payload, sensitive=False)
    sensitive = _emitted_labels(payload, sensitive=True)
    rogue = normal - FLAT_LABELS - link_keys
    assert not rogue, f"未登记标签: {sorted(rogue)}"
    rogue_s = sensitive - FLAT_LABELS - link_keys
    assert not rogue_s, f"未登记标签(含敏感): {sorted(rogue_s)}"
    # 敏感授权只多不少
    assert normal <= sensitive


def test_alias_targets_are_emittable_labels() -> None:
    """别名目标必须是扁平输出可出现的标签——flat 改标签不改别名即被拦。"""
    payload = build_sample_profile().model_dump(mode="json")
    emittable = _emitted_labels(payload, sensitive=True)
    for src, dst in LABEL_ALIASES.items():
        assert dst in emittable or dst in FLAT_LABELS, f"别名目标不可达: {src} -> {dst}"


def test_restricted_labels_marked_when_present() -> None:
    """受限值出现时 restrictedLabels 必须带上对应标签（LLM 过滤凭据）。"""
    payload = build_sample_profile().model_dump(mode="json")
    flat = flatten_profile(payload, include_sensitive=True)
    marked = set(flat["restrictedLabels"])
    emitted = _emitted_labels(payload, sensitive=True)
    for label in RESTRICTED_LABELS:
        if label in emitted:
            assert label in marked, f"受限标签未标记: {label}"
    assert marked <= RESTRICTED_LABELS, marked - RESTRICTED_LABELS


def test_resolver_catalog_paths_exist_in_schema() -> None:
    """_CATALOG_SPEC 路径逐段能在 Profile schema 上解析（含 list/Optional）。"""
    from types import UnionType
    from typing import Union

    def unwrap(t: Any) -> Any:
        origin = get_origin(t)
        if origin is None:
            return t
        args = [a for a in get_args(t) if a is not type(None)]
        if origin is list:
            return unwrap(args[0]) if args else t
        if origin in (Union, UnionType):
            for a in args:
                if isinstance(a, type) and issubclass(a, BaseModel):
                    return a
        return t

    def resolve(model: type[BaseModel], path: str) -> bool:
        cur: Any = model
        for part in path.split("."):
            cur = unwrap(cur)
            if not (isinstance(cur, type) and issubclass(cur, BaseModel)):
                return False
            if part not in cur.model_fields:
                return False
            cur = cur.model_fields[part].annotation
        return True

    for path, _desc in _CATALOG_SPEC:
        assert resolve(Profile, path), f"_CATALOG_SPEC 路径不存在: {path}"
