"""ProfileResolver 按需注入单元测试（docs/03 §1.3）。"""

from __future__ import annotations

from autooffer_core.profile.resolver import ProfileResolver
from autooffer_core.testing import build_sample_profile

resolver = ProfileResolver()
profile = build_sample_profile()


def test_catalog_contains_paths_not_values() -> None:
    cat = resolver.catalog(profile)
    assert "extended.languages" in cat
    assert "extended.family_members" in cat
    assert "[敏感]" in cat
    # 目录只有路径与条数说明，不含具体值
    assert "张三" not in cat
    assert "CET-6" not in cat  # 语言等级值不出现在目录中


def test_catalog_skips_empty_fields() -> None:
    p = profile.model_copy(deep=True)
    assert p.extended is not None
    p.extended.references = []
    cat = resolver.catalog(p)
    assert "extended.references" not in cat


def test_slice_for_education_section() -> None:
    values = resolver.slice_for_section(profile, "教育经历")
    assert "education" in values
    assert values["education"][0]["school"] == "示例大学"
    assert "extended.family_members" not in values


def test_slice_for_family_section() -> None:
    values = resolver.slice_for_section(profile, "家庭成员信息")
    assert "extended.family_members" in values
    members = values["extended.family_members"]
    assert members[0]["relation"] == "父亲"


def test_slice_fallback_to_basic() -> None:
    values = resolver.slice_for_section(profile, "其他补充说明")
    assert "basic" in values


def test_resolve_nested_and_indexed_paths() -> None:
    values, restricted = resolver.resolve(
        profile,
        ["extended.personality.hobbies", "education[0].school", "basic.name"],
    )
    assert values["extended.personality.hobbies"] == ["篮球", "摄影"]
    assert values["education[0].school"] == "示例大学"
    assert values["basic.name"] == "张三"
    assert restricted == []


def test_resolve_restricted_field_withheld() -> None:
    p = profile.model_copy(deep=True)
    p.basic.id_number = "510100200205120000"
    values, restricted = resolver.resolve(p, ["basic.id_number", "basic.name"])
    assert "basic.id_number" not in values  # restricted 不直接给值
    assert restricted == ["basic.id_number"]
    assert values["basic.name"] == "张三"


def test_resolve_missing_path_ignored() -> None:
    values, restricted = resolver.resolve(profile, ["extended.marital_status", "no.such.path"])
    assert values == {}  # 婚姻状况未填、路径不存在均不返回
    assert restricted == []
