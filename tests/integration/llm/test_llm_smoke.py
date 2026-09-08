"""真实端点冒烟（llm marker）：AI 映射与选选项最小闭环。

只验证链路连通与契约（结构化输出、幻觉过滤），不追求映射准确率——
那属于基准表单集的专项评测。本地默认被 `-m "not llm"` 排除。
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        os.environ.get("AO_RUN_LLM") != "1"
        or not os.environ.get("AO_BASE_URL")
        or not os.environ.get("AO_MODEL"),
        reason="需要 AO_RUN_LLM=1 与 AO_BASE_URL/AO_MODEL（真实端点）",
    ),
]

_FLAT: dict[str, Any] = {
    "schema": 1,
    "sections": [
        {"key": "basic", "title": "基本信息", "kind": "simple",
         "values": {"姓名": "张三", "手机号码": "13800001111", "电子邮箱": "z@example.com"}},
        {"key": "intention", "title": "求职意向", "kind": "simple",
         "values": {"意向岗位": "算法工程师"}},
    ],
}


def _real_llm() -> Any:
    from autooffer_core.llm.client import ChatOpenAIClient

    return ChatOpenAIClient(
        base_url=os.environ["AO_BASE_URL"],
        model=os.environ["AO_MODEL"],
        api_key=os.environ.get("AO_API_KEY") or "EMPTY",
    )


@pytest.mark.asyncio
async def test_mapping_llm_smoke() -> None:
    """别名快路径 + LLM 兜底：至少返回结构合法且引用存在的档案标签。"""
    from autooffer_server.services.mapping import PageField, map_fields

    fields = [
        PageField(label="出生地", section="个人信息", kind="text"),
        PageField(label="手机", section="联系方式", kind="text"),
        PageField(label="意向岗位", section="求职意向", kind="text"),
    ]
    matches = await map_fields(fields, _FLAT, _real_llm())
    # 契约：只引用请求中出现过的页面字段与目录中存在的档案标签
    assert all(m.field_label in {f.label for f in fields} for m in matches)
    assert all(m.profile_label in {"姓名", "手机号码", "电子邮箱", "意向岗位"} for m in matches)
    # 快路径必中：精确相等（意向岗位）与别名词典（手机→手机号码）零 LLM
    by_field = {m.field_label: m.profile_label for m in matches}
    assert by_field.get("意向岗位") == "意向岗位"
    assert by_field.get("手机") == "手机号码"


@pytest.mark.asyncio
async def test_option_match_llm_smoke() -> None:
    """选选项闭环：值能挑到语义最接近的选项原文。"""
    from autooffer_server.services.mapping import OptionPick, match_options

    picks = [
        OptionPick(
            label="工作年限",
            options=["应届毕业生", "1-3年", "3-5年"],
            value="2026届毕业生，无正式工作经历",
        )
    ]
    choices = await match_options(picks, _real_llm())
    assert all(c.option in {"应届毕业生", "1-3年", "3-5年"} for c in choices)
