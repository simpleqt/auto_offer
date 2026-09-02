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

CONFIDENCE_FLOOR = 0.55

MAPPING_SYSTEM_PROMPT = """你是招聘表单的字段映射引擎。输入包含两部分：
A. 招聘页面上的字段（label=标签，section=所属区块，kind=控件类型（select=下拉/date=日期/text=文本），placeholder=输入提示，options=候选选项）
B. 求职者档案字段目录（label=标签，category=分区）

任务：为 A 中每个字段找出 B 中语义相同或最接近的一个标签。

规则：
1. 只依据标签、控件类型与选项的语义判断，不要臆造 B 中不存在的标签。
2. 只输出 JSON：
   {"matches": [{"field": "A的label", "profile": "B的label", "confidence": 0到1}]}
3. 没有对应关系或拿不准的字段不要输出。
4. confidence 低于 0.6 的不要输出。
5. A 中明显不是个人信息的字段（搜索框、推荐码、验证码等）不要输出。
6. 措辞不同不代表不匹配，常见同义对应要敢映射：
   出生地/成长地/户口所在地/生源地 → 籍贯；毕业时间 → 教育经历的结束时间；
   获奖/荣誉/奖学金 → 奖惩类字段；单位名称/实习单位 → 公司；职务名称 → 职位；
   实习内容/工作内容 → 职责描述；掌握程度 → 技能相关字段。
7. A 的字段与 B 的分区对应（如页面字段在「教育经历」区块，优先映射 B 的教育经历分区字段）。
"""


class PageField(BaseModel):
    label: str
    section: str | None = None
    kind: str | None = None
    placeholder: str | None = None
    options: list[str] = []


class MappingMatch(BaseModel):
    field_label: str
    profile_label: str
    confidence: float


class OptionPick(BaseModel):
    """待选选项的固定选项字段（页面标签 + 选项 + 档案值）。

    隐私说明：value 会进入 LLM 提示词——与简历解析同一信任域
    （该值本就要写入公开页面），且仅逐字段发送。
    """

    label: str
    options: list[str] = []
    value: str = ""


class OptionChoice(BaseModel):
    label: str
    option: str
    confidence: float


OPTION_MATCH_PROMPT = """你是招聘表单的选项匹配引擎。给你若干「字段标签 + 候选选项 + 求职者的值」，
为每个值从对应选项中选出语义最接近的一项。

规则：
1. 只输出 JSON：{"choices": [{"label": "字段标签", "option": "选中的选项原文", "confidence": 0到1}]}
2. option 必须逐字使用候选选项之一，不得改写。
3. 没有接近的选项（完全不同的语义）就不要输出该字段。
4. confidence 低于 0.55 的不要输出。"""


async def match_options(picks: list[OptionPick], llm: Any) -> list[OptionChoice]:
    """为固定选项字段挑选项（值 → 选项）。模型偶发拒答时空结果重试一次。"""
    valid = [p for p in picks if p.options and p.value]
    if not valid:
        return []
    payload = [
        {"label": p.label, "options": p.options[:60], "value": p.value[:80]}
        for p in valid[:60]
    ]
    from autooffer_core.llm.interfaces import ChatMessage

    def build_prompt(extra: str = "") -> str:
        return (
            OPTION_MATCH_PROMPT
            + "\n\n输入：\n"
            + json.dumps(payload, ensure_ascii=False)
            + extra
        )

    def filter_choices(raw: Any) -> list[OptionChoice]:
        by_label = {p.label: set(p.options) for p in valid}
        out: list[OptionChoice] = []
        for item in raw.get("choices", []):
            try:
                c = OptionChoice.model_validate(
                    {
                        "label": str(item.get("label", "")),
                        "option": str(item.get("option", "")),
                        "confidence": float(item.get("confidence", 0)),
                    }
                )
            except (ValueError, TypeError):
                continue
            if c.confidence >= 0.55 and c.option in by_label.get(c.label, set()):
                out.append(c)
        return out

    response = await llm.complete([ChatMessage(role="user", content=build_prompt())])
    choices = filter_choices(_extract_json(response.text))
    if not choices:
        # 具体职位/方向 → 职业大类 的归类是合法匹配，追加提示重试一次
        extra = (
            "\n\n注意：若选项是大类（如「计算机·网络·技术类」）"
            "而值是具体职位/方向，请选择所属大类。"
        )
        response = await llm.complete([ChatMessage(role="user", content=build_prompt(extra))])
        choices = filter_choices(_extract_json(response.text))
    log.info("option_match.done", picks=len(valid), choices=len(choices))
    return choices


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
