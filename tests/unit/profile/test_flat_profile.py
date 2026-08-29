"""档案扁平化：项目经历的链接字段与标题编号剥离。"""

from __future__ import annotations

from autooffer_server.services.flat_profile import flatten_profile


def _profile_payload(**experience_overrides: object) -> dict[str, object]:
    exp: dict[str, object] = {
        "kind": "project",
        "organization": "示例大学",
        "title": "示例平台",
        "period": {"start": {"year": 2025, "month": 9}, "end": None},
        "description": "示例描述",
        "highlights": ["负责人"],
    }
    exp.update(experience_overrides)
    return {
        "id": "p1",
        "label": "示例档案",
        "basic": {"name": "张三", "phone": "13800000000", "email": "z@example.com"},
        "experiences": [exp],
    }


def _project_item(payload: dict[str, object]) -> dict[str, object]:
    flat = flatten_profile(payload)
    sections = flat["sections"]
    proj = next(s for s in sections if s["key"] == "project")
    items = proj["items"]
    assert len(items) == 1
    return items[0]  # type: ignore[no-any-return]


def test_project_link_emitted() -> None:
    item = _project_item(_profile_payload(link="https://example.com/demo"))
    assert item["项目链接"] == "https://example.com/demo"


def test_project_without_link_omits_field() -> None:
    item = _project_item(_profile_payload())
    assert "项目链接" not in item


def test_project_title_strips_leading_numbering() -> None:
    item = _project_item(_profile_payload(title="1. 示例平台"))
    assert item["项目名称"] == "示例平台"
    item2 = _project_item(_profile_payload(title="2、示例平台"))
    assert item2["项目名称"] == "示例平台"
