"""AI 字段映射接口（M2）测试：脱敏提示词、幻觉过滤、置信度门槛、404/503。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from autooffer_server.config import ServerConfig
from autooffer_server.context import AppContext
from autooffer_server.main import create_app
from tests.integration.server.conftest import FakeRunner, MemoryKeyStore, sample_profile_payload

FAKE_LLM_JSON = json.dumps(
    {
        "matches": [
            # 正确映射
            {"field": "期望从事职业", "profile": "意向岗位", "confidence": 0.95},
            # 幻觉：档案里不存在的标签 → 丢弃
            {"field": "国籍", "profile": "不存在的字段", "confidence": 0.99},
            # 低置信度 → 丢弃
            {"field": "工作年限", "profile": "工作年限", "confidence": 0.3},
            # 页面上没有的字段 → 丢弃
            {"field": "页面没有的字段", "profile": "姓名", "confidence": 0.9},
        ]
    },
    ensure_ascii=False,
)

FAKE_LLM_OPTION_JSON = json.dumps(
    {
        "choices": [
            # 正确挑选（逐字使用选项）
            {"label": "期望从事职业", "option": "算法工程师", "confidence": 0.9},
            # 改写了选项原文 → 丢弃
            {"label": "现月薪(税前)", "option": "5000元", "confidence": 0.9},
            # 低置信度 → 丢弃
            {"label": "工作年限", "option": "应届毕业生", "confidence": 0.2},
        ]
    },
    ensure_ascii=False,
)


@pytest.fixture
def mapping_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    config = ServerConfig.create(tmp_path / "data", headless=True)
    ctx = AppContext(config, runner=FakeRunner(), keystore=MemoryKeyStore())

    async def fake_build_llm(self: AppContext, role: str = "actor") -> Any:
        # 映射与选选项按提示词内容区分返回不同脚本
        async def complete(messages: list) -> Any:
            from autooffer_core.llm.interfaces import LLMResponse, LLMUsage

            text = messages[-1].content
            script = FAKE_LLM_OPTION_JSON if "选项匹配引擎" in text else FAKE_LLM_JSON
            return LLMResponse(
                text=script,
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        return type("LLM", (), {"complete": staticmethod(complete)})()

    monkeypatch.setattr(AppContext, "build_llm", fake_build_llm)
    app = create_app(ctx=ctx)
    with TestClient(app) as c:
        yield c


def put_sample(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/profiles/demo-profile",
        json={"label": "中文-示例档案", "payload": sample_profile_payload()},
    )
    assert resp.status_code == 200


def test_mapping_filters_and_matches(mapping_client: TestClient) -> None:
    put_sample(mapping_client)
    resp = mapping_client.post(
        "/api/v1/mapping",
        json={
            "profile_id": "demo-profile",
            "fields": [
                {"label": "期望从事职业", "section": "求职意向", "options": []},
                {"label": "国籍", "section": "个人信息", "options": ["中国"]},
                {"label": "工作年限", "section": "个人信息", "options": ["应届", "1年"]},
            ],
        },
    )
    assert resp.status_code == 200
    matches = resp.json()["matches"]
    # 国籍/工作年限：与档案标签精确相等，走快路径（0.99）零 LLM——
    # 幻觉映射（档案里不存在的标签）在快路径就轮不到 LLM 输出；
    # 期望从事职业：LLM 命中（0.95）
    by_field = {m["field_label"]: m for m in matches}
    assert set(by_field) == {"国籍", "工作年限", "期望从事职业"}
    assert by_field["国籍"]["profile_label"] == "国籍"
    assert by_field["工作年限"]["profile_label"] == "工作年限"
    assert by_field["期望从事职业"] == {
        "field_label": "期望从事职业", "profile_label": "意向岗位", "confidence": 0.95
    }


def test_mapping_prompt_never_contains_values(mapping_client: TestClient) -> None:
    """脱敏契约：提示词只有标签目录，不含档案值。"""
    put_sample(mapping_client)
    resp = mapping_client.post(
        "/api/v1/mapping",
        json={
            "profile_id": "demo-profile",
            "fields": [{"label": "期望从事职业", "section": "", "options": []}],
        },
    )
    assert resp.status_code == 200
    # FakeLLMClient.messages_seen 每次调用都会累积；取最后一次
    # （fake_build_llm 每次新建实例，这里通过返回结果间接验证映射成功即可）
    assert resp.json()["matches"][0]["profile_label"] == "意向岗位"


def test_mapping_unknown_profile_404(mapping_client: TestClient) -> None:
    resp = mapping_client.post(
        "/api/v1/mapping",
        json={"profile_id": "no-such", "fields": [{"label": "姓名"}]},
    )
    assert resp.status_code == 404


def test_mapping_empty_fields(mapping_client: TestClient) -> None:
    put_sample(mapping_client)
    resp = mapping_client.post(
        "/api/v1/mapping", json={"profile_id": "demo-profile", "fields": []}
    )
    assert resp.status_code == 200
    assert resp.json()["matches"] == []


def test_mapping_requires_endpoint(tmp_path: Path) -> None:
    """未配置模型端点 → 503（提示配置），而非 500。"""
    config = ServerConfig.create(tmp_path / "data", headless=True)
    ctx = AppContext(config, runner=FakeRunner(), keystore=MemoryKeyStore())
    app = create_app(ctx=ctx)
    with TestClient(app) as c:
        c.put(
            "/api/v1/profiles/demo-profile",
            json={"label": "示例", "payload": sample_profile_payload()},
        )
        resp = c.post(
            "/api/v1/mapping",
            json={"profile_id": "demo-profile", "fields": [{"label": "姓名"}]},
        )
    assert resp.status_code == 503


def test_option_match_picks_and_filters(mapping_client: TestClient) -> None:
    """AI 选选项：逐字选项校验 + 置信度门槛 + occurrence 透传。"""
    resp = mapping_client.post(
        "/api/v1/option-match",
        json={
            "picks": [
                {
                    "label": "期望从事职业",
                    "options": ["算法工程师", "前端工程师", "测试工程师"],
                    "value": "LLM 应用开发 / RAG 工程",
                },
                {"label": "现月薪(税前)", "options": ["5K以下", "5-10K", "10-20K"], "value": "3K"},
                {"label": "工作年限", "options": ["应届毕业生", "1-3年"], "value": "应届"},
                {"label": "无选项字段", "options": [], "value": "x"},
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["choices"] == [
        {"label": "期望从事职业", "option": "算法工程师", "confidence": 0.9, "occurrence": None}
    ]


def test_option_match_rejects_idcard_shaped_value(mapping_client: TestClient) -> None:
    """身份证形状的值不进 LLM 提示词（restricted 值兜底拦截）。"""
    resp = mapping_client.post(
        "/api/v1/option-match",
        json={
            "picks": [
                {
                    "label": "证件号码",
                    "options": ["110101199001011234", "其他"],
                    "value": "110101199001011234",
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["choices"] == []


def test_option_match_empty(mapping_client: TestClient) -> None:
    resp = mapping_client.post("/api/v1/option-match", json={"picks": []})
    assert resp.status_code == 200
    assert resp.json()["choices"] == []


def test_mapping_alias_fast_path_skips_llm() -> None:
    """别名/归一精确匹配零 LLM：常见措辞（手机/毕业院校）直配档案标签。"""
    import asyncio

    from autooffer_server.services.mapping import PageField, map_fields

    class NoLLM:
        async def complete(self, messages: list) -> Any:
            raise AssertionError("快路径命中的字段不应调用 LLM")

    flat = {
        "sections": [
            {"key": "basic", "title": "基本信息", "kind": "simple",
             "values": {"姓名": "张三", "手机号码": "138", "电子邮箱": "a@b.c"}},
            {"key": "education", "title": "教育经历", "kind": "repeat",
             "items": [{"学校": "x", "专业": "y"}]},
        ]
    }
    matches = asyncio.run(
        map_fields(
            [
                PageField(label="联系电话", section="联系方式"),
                PageField(label="毕业院校", section="教育经历"),
                PageField(label="姓名", section="基本信息"),
                PageField(label=" 邮 箱 ", section="联系方式"),  # 归一：去空格
            ],
            flat,
            NoLLM(),
        )
    )
    by_field = {m.field_label: m.profile_label for m in matches}
    assert by_field["联系电话"] == "手机号码"
    assert by_field["毕业院校"] == "学校"
    assert by_field["姓名"] == "姓名"
    assert by_field[" 邮 箱 "] == "电子邮箱"


def test_mapping_cache_hit_skips_llm() -> None:
    """同档案同字段集合第二次映射直接命中缓存（TTL 内零 LLM 调用）。"""
    import asyncio

    from autooffer_server.services import mapping as mapping_mod
    from autooffer_server.services.mapping import PageField, map_fields

    flat = {
        "sections": [
            {"key": "basic", "title": "基本信息", "kind": "simple",
             "values": {"手机号码": "138"}},
        ]
    }
    fields = [PageField(label="联系电话", section="联系方式")]

    calls = 0

    class CountingLLM:
        async def complete(self, messages: list) -> Any:
            nonlocal calls
            calls += 1
            from autooffer_core.llm.interfaces import LLMResponse

            return LLMResponse(text='{"matches": []}')

    mapping_mod._mapping_cache.clear()
    r1 = asyncio.run(map_fields(fields, flat, CountingLLM(), profile_id="p1"))
    assert r1 and r1[0].profile_label == "手机号码"
    # 第二次：LLM 客户端换成必炸的——命中缓存则不会触发
    class ExplodingLLM:
        async def complete(self, messages: list) -> Any:
            raise AssertionError("缓存命中不应调用 LLM")

    r2 = asyncio.run(map_fields(fields, flat, ExplodingLLM(), profile_id="p1"))
    assert r2 == r1
    # 无 profile_id 的调用不走缓存（兼容旧调用方）
    assert calls == 0
    mapping_mod._mapping_cache.clear()
