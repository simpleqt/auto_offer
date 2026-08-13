"""W0 契约冒烟测试：验证契约模型可实例化、mock 可用、包可导入。

这是契约冻结的基线；后续 Workstream 在此之上补充各自测试。
"""

from __future__ import annotations

import pytest

from autooffer_core import AutoOfferError, PerceptionError
from autooffer_core.actions import Action, ActionBatch
from autooffer_core.drivers import Driver
from autooffer_core.llm import LLMClient, ModelEndpoint, Role
from autooffer_core.perception import PageObservation, UIElement
from autooffer_core.profile import Profile
from autooffer_core.report import FillReport
from autooffer_core.testing import (
    FakeDriver,
    FakeLLMClient,
    ScriptedLLMClient,
    build_sample_profile,
)


def test_sample_profile_valid() -> None:
    p = build_sample_profile()
    assert isinstance(p, Profile)
    assert p.basic.name == "张三"
    assert p.extended is not None
    assert len(p.experiences) == 2


def test_sample_profile_restricted_annotations() -> None:
    """restricted 字段（身份证号、家庭成员电话）必须带敏感度标注。"""
    from autooffer_core.profile.schema import BasicInfo, FamilyMember

    assert BasicInfo.model_fields["id_number"].json_schema_extra == {"sensitivity": "restricted"}
    assert FamilyMember.model_fields["phone"].json_schema_extra == {"sensitivity": "restricted"}


def test_action_roundtrip() -> None:
    a = Action(type="input_text", element_index=3, value="张三", reason="填姓名")
    batch = ActionBatch(actions=[a], summary="填写姓名")
    assert batch.actions[0].type == "input_text"
    assert Action.model_validate_json(a.model_dump_json()) == a


def test_fake_driver_is_driver() -> None:
    d = FakeDriver()
    assert isinstance(d, Driver)


@pytest.mark.asyncio
async def test_fake_driver_flow() -> None:
    obs = PageObservation(
        url="about:blank",
        title="t",
        elements=[UIElement(index=1, tag="input", role="input", label="姓名", selector="#n")],
    )
    d = FakeDriver(obs)
    await d.open("https://example.com/apply")
    got = await d.observe()
    assert got.elements[0].label == "姓名"
    await d.input_text(got.elements[0], "张三")
    assert await d.element_value(got.elements[0]) == "张三"


@pytest.mark.asyncio
async def test_fake_llm_is_client() -> None:
    c = FakeLLMClient("hello")
    assert isinstance(c, LLMClient)
    resp = await c.complete([])
    assert resp.text == "hello"


@pytest.mark.asyncio
async def test_scripted_llm_cycles() -> None:
    c = ScriptedLLMClient(["a", "b"])
    r1 = await c.complete([])
    r2 = await c.complete([])
    r3 = await c.complete([])  # 耗尽后复用最后一个
    assert (r1.text, r2.text, r3.text) == ("a", "b", "b")


def test_model_endpoint_secret_not_plain() -> None:
    ep = ModelEndpoint(
        id="m1",
        name="qwen",
        base_url="http://127.0.0.1:8011/v1",
        api_key="sk-secret-123",  # type: ignore[arg-type]
        model="qwen3.5-35b",
    )
    assert "sk-secret-123" not in repr(ep.api_key)


def test_role_literal() -> None:
    roles: list[Role] = ["planner", "actor", "validator", "profile_parser", "writer"]
    assert "actor" in roles


def test_fill_report_counts() -> None:
    from autooffer_core.report import FieldRecord

    r = FillReport(
        task_id="t1",
        url="u",
        profile_id="p",
        fields=[
            FieldRecord(label="姓名", status="filled", value="张三"),
            FieldRecord(label="期望薪资", status="pending_confirm"),
        ],
    )
    assert r.counts()["filled"] == 1
    assert r.counts()["pending_confirm"] == 1


def test_error_hierarchy() -> None:
    assert issubclass(PerceptionError, AutoOfferError)
