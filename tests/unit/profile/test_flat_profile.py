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


def _education_item(payload: dict[str, object]) -> dict[str, object]:
    flat = flatten_profile(payload)
    edu = next(s for s in flat["sections"] if s["key"] == "education")
    assert len(edu["items"]) == 1
    return edu["items"][0]  # type: ignore[no-any-return]


def test_education_college_emitted() -> None:
    payload = _profile_payload()
    payload["education"] = [
        {"school": "示例大学", "college": "计算机与网络安全学院",
         "period": {"start": {"year": 2020, "month": 9}}}
    ]
    item = _education_item(payload)
    assert item["学校"] == "示例大学"
    assert item["学院"] == "计算机与网络安全学院"


def test_education_without_college_omits_field() -> None:
    payload = _profile_payload()
    payload["education"] = [
        {"school": "示例大学", "period": {"start": {"year": 2020, "month": 9}}}
    ]
    item = _education_item(payload)
    assert "学院" not in item


def test_research_section_separate_and_last() -> None:
    payload = _profile_payload()
    payload["experiences"] = payload["experiences"] + [  # type: ignore[union-attr]
        {
            "kind": "research",
            "organization": "示例工业学院",
            "title": "1. 示例科研课题",
            "period": {"start": {"year": 2024, "month": 9}, "end": None},
            "description": "课题研究内容",
            "highlights": ["课题骨干"],
        }
    ]
    flat = flatten_profile(payload)
    titles = [s["title"] for s in flat["sections"] if s["kind"] == "repeat"]
    assert titles == ["项目经历", "科研经历"]  # 科研排最后（优先级最低）
    research = next(s for s in flat["sections"] if s["key"] == "research")
    assert research["items"][0]["项目名称"] == "示例科研课题"  # 编号剥离同样生效


def test_no_research_section_when_absent() -> None:
    flat = flatten_profile(_profile_payload())
    assert all(s["key"] != "research" for s in flat["sections"])
