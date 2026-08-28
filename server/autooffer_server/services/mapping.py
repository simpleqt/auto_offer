"""AI 字段映射通道（M2）：页面字段标签 → 档案字段标签。

隐私契约（OJA redactPersonalValues 同款思想）：
- LLM 只看到页面字段的「标签/区块/候选选项文本」与档案的「字段目录（标签+分区）」；
- 档案值永不出本地服务，更不进入提示词；
- 映射结果只引用档案标签，由插件在本地取值写入。

置信度低于阈值的映射直接丢弃；引用了不存在标签的映射视为模型幻觉丢弃。
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from pydantic import BaseModel

log = structlog.get_logger(__name__)

CONFIDENCE_FLOOR = 0.6

MAPPING_SYSTEM_PROMPT = """你是招聘表单的字段映射引擎。输入包含两部分：
A. 招聘页面上的字段（label=标签，section=所属区块，options=候选选项）
B. 求职者档案字段目录（label=标签，category=分区）

任务：为 A 中每个字段找出 B 中语义相同或最接近的一个标签。

规则：
1. 只依据标签与选项的语义判断，不要臆造 B 中不存在的标签。
2. 只输出 JSON：
   {"matches": [{"field": "A的label", "profile": "B的label", "confidence": 0到1}]}
3. 没有对应关系或拿不准的字段不要输出。
4. confidence 低于 0.7 的不要输出。
5. A 中明显不是个人信息的字段（搜索框、推荐码、验证码等）不要输出。
"""


class PageField(BaseModel):
    label: str
    section: str | None = None
    options: list[str] = []


class MappingMatch(BaseModel):
    field_label: str
    profile_label: str
    confidence: float


def _extract_json(text: str) -> Any:
    """从模型输出中提取 JSON（容忍代码围栏与前后缀文本）。"""
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型输出中未找到 JSON")
    return json.loads(cleaned[start : end + 1])


def _catalog(flat: dict[str, Any]) -> list[dict[str, str]]:
    """扁平档案 → 仅标签+分区的目录（无值）。"""
    catalog: list[dict[str, str]] = []
    for section in flat.get("sections", []):
        title = section.get("title", "")
        if section.get("kind") == "repeat":
            for item in section.get("items", [])[:1]:  # M1/M2 只映射首条
                for label in item:
                    catalog.append({"label": label, "category": title})
        else:
            for label in section.get("values", {}):
                catalog.append({"label": label, "category": title})
    return catalog


async def map_fields(
    fields: list[PageField],
    flat: dict[str, Any],
    llm: Any,
) -> list[MappingMatch]:
    """页面字段 → 档案标签映射。"""
    catalog = _catalog(flat)
    if not fields or not catalog:
        return []

    known_fields = {f.label for f in fields}
    known_labels = {c["label"] for c in catalog}

    prompt = (
        f"{MAPPING_SYSTEM_PROMPT}\n\nA. 页面字段：\n"
        + json.dumps(
            [f.model_dump() for f in fields[:60]], ensure_ascii=False, indent=None
        )
        + "\n\nB. 档案字段目录：\n"
        + json.dumps(catalog, ensure_ascii=False, indent=None)
    )

    from autooffer_core.llm.interfaces import ChatMessage

    response = await llm.complete(
        [ChatMessage(role="user", content=prompt)],
    )
    raw = _extract_json(response.text)
    matches: list[MappingMatch] = []
    for item in raw.get("matches", []):
        try:
            m = MappingMatch.model_validate(
                {
                    "field_label": str(item.get("field", "")),
                    "profile_label": str(item.get("profile", "")),
                    "confidence": float(item.get("confidence", 0)),
                }
            )
        except (ValueError, TypeError):
            continue
        if (
            m.confidence >= CONFIDENCE_FLOOR
            and m.field_label in known_fields
            and m.profile_label in known_labels
        ):
            matches.append(m)
    log.info("mapping.done", fields=len(fields), matches=len(matches))
    return matches
