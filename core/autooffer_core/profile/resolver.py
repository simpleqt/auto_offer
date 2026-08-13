"""档案按需注入解析器（docs/03 §1.3，FR-P8 核心）。

原则：表单不问，档案不给。
- catalog：紧凑字段目录（路径 + 说明 + 有无值/条数，不含值本身），常驻 Actor 提示词。
- slice_for_section：按区块标题语义预取相关分组。
- resolve：按字段路径取值；restricted 级路径单独返回，由上层触发人工授权。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from autooffer_core.profile.schema import Profile

# 字段路径 → (中文说明, 目录中是否默认展示)
_CATALOG_SPEC: list[tuple[str, str]] = [
    ("basic", "基本信息(姓名/性别/出生/电话/邮箱/籍贯/现居/政治面貌)"),
    ("intention", "求职意向(职位/城市/薪资/到岗)"),
    ("education", "教育经历"),
    ("experiences", "实习/工作/项目经历"),
    ("skills", "技能"),
    ("certificates", "证书"),
    ("self_evaluation", "自我评价"),
    ("qa_bank", "预存问答"),
    ("attachments", "附件(简历/照片等)"),
    ("extended.personality.traits", "性格特点"),
    ("extended.personality.mbti", "MBTI"),
    ("extended.personality.hobbies", "兴趣爱好"),
    ("extended.personality.specialties", "特长"),
    ("extended.languages", "语言能力"),
    ("extended.awards", "获奖荣誉"),
    ("extended.campus_roles", "学生干部/社团经历"),
    ("extended.family_members", "家庭成员"),
    ("extended.emergency_contact", "紧急联系人"),
    ("extended.marital_status", "婚姻状况"),
    ("extended.height_cm", "身高"),
    ("extended.weight_kg", "体重"),
    ("extended.health_status", "健康状况"),
    ("extended.party_join_date", "入党时间"),
    ("extended.hukou_location", "户口所在地"),
    ("extended.origin_place", "生源地"),
    ("extended.references", "推荐人"),
    ("extended.links", "作品集/主页链接"),
    ("extended.available_date", "到岗时间"),
    ("extended.travel_willingness", "出差意愿"),
    ("extended.relocation_willingness", "工作地点调剂意愿"),
]

# 通用简历表单（整页单区块）预取的核心全集
_CORE_PATHS: list[str] = [
    "basic", "intention", "education", "experiences",
    "skills", "certificates", "self_evaluation",
]

# 区块标题关键词 → 预取的字段路径组
_SECTION_HINTS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"简历|登记|申请|求职|信息表|apply|resume|application"), _CORE_PATHS),
    (re.compile(r"基本|个人信息|personal"), ["basic", "extended.origin_place"]),
    (re.compile(r"教育|学历|education"), ["education"]),
    (re.compile(r"实习|intern"), ["experiences"]),
    (re.compile(r"工作|职业|work|experience"), ["experiences"]),
    (re.compile(r"项目|project"), ["experiences"]),
    (re.compile(r"技能|skill"), ["skills", "certificates"]),
    (re.compile(r"证书|certificate"), ["certificates", "extended.languages"]),
    (re.compile(r"语言|language"), ["extended.languages"]),
    (re.compile(r"获奖|荣誉|award"), ["extended.awards"]),
    (re.compile(r"社团|学生干部|校园"), ["extended.campus_roles"]),
    (re.compile(r"家庭|family"), ["extended.family_members", "extended.emergency_contact"]),
    (re.compile(r"意向|期望|intention"), ["intention", "extended.available_date"]),
    (re.compile(r"自我|评价|介绍|summary"), ["self_evaluation", "extended.personality.traits"]),
    (re.compile(r"兴趣|爱好|特长|hobby"), ["extended.personality.hobbies",
                                          "extended.personality.specialties"]),
    (re.compile(r"附件|简历上传|上传|attachment|upload"), ["attachments"]),
    (re.compile(r"推荐|reference"), ["extended.references"]),
]

_INDEX_RE = re.compile(r"^(\w+)\[(\d+)\]$")


def _sensitivity_of(model: type[BaseModel], field: str) -> str:
    info = model.model_fields.get(field)
    if info is None:
        return "normal"
    extra = info.json_schema_extra
    if isinstance(extra, dict):
        return str(extra.get("sensitivity", "normal"))
    return "normal"


def _get_by_path(obj: Any, path: str) -> tuple[Any, str]:
    """按点路径取值，返回 (值, 路径上的最高敏感级)。路径不存在返回 (None, normal)。"""
    cur: Any = obj
    level = "normal"
    for part in path.split("."):
        if cur is None:
            return None, level
        m = _INDEX_RE.match(part)
        idx: int | None = None
        if m:
            part, idx = m.group(1), int(m.group(2))
        if isinstance(cur, BaseModel):
            sens = _sensitivity_of(type(cur), part)
            if sens == "restricted":
                level = "restricted"
            elif sens == "sensitive" and level == "normal":
                level = "sensitive"
            cur = getattr(cur, part, None)
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None, level
        if idx is not None:
            if isinstance(cur, list) and 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None, level
    return cur, level


def _has_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, dict, str)):
        return len(v) > 0
    return True


def _dump(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump(exclude_none=True)
    if isinstance(v, list):
        return [_dump(x) for x in v]
    return v


class ProfileResolver:
    """档案取值链路的实现（目录 / 区块切片 / 按路径补取）。"""

    def catalog(self, profile: Profile) -> str:
        lines: list[str] = []
        for path, desc in _CATALOG_SPEC:
            value, level = _get_by_path(profile, path)
            if not _has_value(value):
                continue
            count = f"({len(value)}条)" if isinstance(value, list) else "(有值)"
            mark = "[敏感]" if level in ("sensitive", "restricted") else ""
            lines.append(f"{path}: {desc}{count}{mark}")
        return "\n".join(lines) if lines else "(档案为空)"

    def slice_for_section(self, profile: Profile, section_title: str) -> dict[str, Any]:
        """按区块标题预取相关字段组；未命中时回落核心全集（整页表单常无明确分区）。"""
        paths: list[str] = []
        title = section_title or ""
        for pattern, group in _SECTION_HINTS:
            if pattern.search(title):
                paths.extend(group)
        if not paths:
            paths = list(_CORE_PATHS)
        values, _restricted = self.resolve(profile, paths)
        return values

    def resolve(
        self, profile: Profile, paths: list[str]
    ) -> tuple[dict[str, Any], list[str]]:
        """按路径取值。restricted 路径不返回值，单独列出待人工授权。"""
        values: dict[str, Any] = {}
        restricted: list[str] = []
        for path in dict.fromkeys(paths):  # 去重保序
            value, level = _get_by_path(profile, path)
            if level == "restricted":
                restricted.append(path)
                continue
            if _has_value(value):
                values[path] = _dump(value)
        return values, restricted
