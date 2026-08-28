"""档案扁平化：Profile → 浏览器插件规则引擎可用的「标签 → 值」分区结构。

插件侧（extension/src/content.js）按 OpenJobAutofill 式标签评分消费该结构：
sections[] 各带 key/title/kind；simple 段 values 为 {标签: 值}；
repeat 段 items[] 每条含独立 values。

敏感契约（docs/03 §1.1）：schema 中 sensitivity=sensitive/restricted 的字段
默认剔除，仅在 include_sensitive=True（插件弹窗单独授权）时输出。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from autooffer_core.profile.schema import (
    BasicInfo,
    DateRange,
    DateYM,
    Education,
    ExtendedInfo,
    Profile,
)

# 学历 → 学位 的常规换算（大专/高中无学位）。
_DEGREE_NAME: dict[str, str] = {
    "大专": "无",
    "高中": "无",
    "本科": "学士",
    "硕士": "硕士",
    "博士": "博士",
    "其他": "无",
}


def _fmt_date(d: DateYM | None) -> str:
    if d is None:
        return ""
    if d.day:
        return f"{d.year:04d}-{d.month or 1:02d}-{d.day:02d}"
    if d.month:
        return f"{d.year:04d}-{d.month:02d}"
    return f"{d.year:04d}"


def _fmt_month(d: DateYM | None) -> str:
    """年月精度（教育/经历时段的站点控件均为月份选择器，日为解析噪音）。"""
    if d is None:
        return ""
    return f"{d.year:04d}-{d.month or 1:02d}"


def _period_values(period: DateRange | None) -> dict[str, str]:
    if period is None:
        return {}
    out = {"开始时间": _fmt_month(period.start)}
    out["结束时间"] = _fmt_month(period.end) if period.end else "至今"
    return out


def _clean(values: dict[str, Any]) -> dict[str, str]:
    """剔除空值并统一为字符串。"""
    return {
        k: str(v)
        for k, v in values.items()
        if v is not None and v != "" and v != []
    }


def _sensitive_names(model: type[BaseModel]) -> set[str]:
    """从 pydantic schema 元数据收集 sensitive/restricted 字段名。"""
    out: set[str] = set()
    for name, field in model.model_fields.items():
        extra = field.json_schema_extra
        if not isinstance(extra, dict):
            continue
        sens = extra.get("sensitivity")
        if isinstance(sens, str) and sens in ("sensitive", "restricted"):
            out.add(name)
    return out


_SENSITIVE_BASIC = _sensitive_names(BasicInfo)


class _Flattener:
    def __init__(self, include_sensitive: bool) -> None:
        self.include_sensitive = include_sensitive
        self.sections: list[dict[str, Any]] = []

    def add_simple(self, key: str, title: str, values: dict[str, Any]) -> None:
        cleaned = _clean(values)
        if cleaned:
            self.sections.append(
                {"key": key, "title": title, "kind": "simple", "values": cleaned}
            )

    def add_repeat(self, key: str, title: str, items: list[dict[str, Any]]) -> None:
        cleaned_items = [_clean(v) for v in items if _clean(v)]
        if cleaned_items:
            self.sections.append(
                {"key": key, "title": title, "kind": "repeat", "items": cleaned_items}
            )

    def _basic(self, basic: BasicInfo) -> None:
        values: dict[str, Any] = {
            "姓名": basic.name,
            "姓": basic.name[:1] if len(basic.name) >= 2 else None,
            "名": basic.name[1:] if len(basic.name) >= 2 else None,
            "性别": basic.gender,
            "出生日期": _fmt_date(basic.birth_date),
            "手机号码": basic.phone,
            "电子邮箱": basic.email,
            "籍贯": basic.native_place,
            "现居住城市": basic.current_city,
            "政治面貌": basic.political_status,
            "国籍": basic.nationality,
            "工作年限": basic.work_years,
        }
        if self.include_sensitive and "id_number" in _SENSITIVE_BASIC:
            values["身份证号"] = basic.id_number
        self.add_simple("basic", "基本信息", values)

    def _intention(self, p: Profile, ext: ExtendedInfo | None) -> None:
        it = p.intention
        values: dict[str, Any] = {
            "意向岗位": it.position if it else None,
            "期望城市": "、".join(it.city) if it and it.city else None,
            "期望月薪(税前)": it.salary_expectation if it else None,
            "现月薪(税前)": it.current_salary if it else None,
            "期望从事行业": it.expected_industry if it else None,
            "可到岗时间": _fmt_date(it.available_date) if it else None,
            "出差意愿": ext.travel_willingness if ext else None,
            "接受工作地调剂": ext.relocation_willingness if ext else None,
        }
        self.add_simple("intention", "求职意向", values)

    @staticmethod
    def _edu_values(e: Education) -> dict[str, Any]:
        values: dict[str, Any] = {
            "学校": e.school,
            "专业": e.major,
            "学历": e.degree,
            "学位": _DEGREE_NAME.get(e.degree or "", None),
            "成绩": e.gpa,
        }
        values.update(_period_values(e.period))
        return values

    def _education(self, p: Profile) -> None:
        self.add_repeat(
            "education", "教育经历", [self._edu_values(e) for e in p.education]
        )

    def _experiences(self, p: Profile) -> None:
        intern: list[dict[str, Any]] = []
        work: list[dict[str, Any]] = []
        project: list[dict[str, Any]] = []
        for x in p.experiences:
            base: dict[str, Any] = _period_values(x.period)
            if x.kind == "project":
                base.update(
                    {
                        "项目名称": x.organization,
                        "项目职务": x.title,
                        "项目描述": x.description,
                        "项目成果": "；".join(x.highlights) if x.highlights else None,
                    }
                )
                project.append(base)
                continue
            base.update(
                {
                    "公司": x.organization,
                    "职位": x.title,
                    "工作内容": x.description,
                    "工作成果": "；".join(x.highlights) if x.highlights else None,
                }
            )
            (intern if x.kind == "internship" else work).append(base)
        self.add_repeat("internship", "实习经历", intern)
        self.add_repeat("work", "工作经历", work)
        self.add_repeat("project", "项目经历", project)

    def _extended(self, ext: ExtendedInfo) -> None:
        self.add_repeat(
            "language",
            "外语能力",
            [
                {
                    "外语种类": lang.language,
                    "外语水平": lang.level,
                    "外语成绩": lang.score,
                    "获得时间": _fmt_date(lang.certificate_date),
                }
                for lang in ext.languages
            ],
        )
        self.add_repeat(
            "awards",
            "奖惩情况",
            [
                {
                    "奖惩名称": a.title,
                    "奖励等级": a.level,
                    "奖惩时间": _fmt_date(a.date),
                    "奖惩描述": a.description,
                }
                for a in ext.awards
            ],
        )
        self.add_repeat(
            "campus",
            "学生工作",
            [
                {
                    "组织名称": c.organization,
                    "职务": c.role,
                    "工作内容": c.description,
                    **_period_values(c.period),
                }
                for c in ext.campus_roles
            ],
        )
        if self.include_sensitive:
            self.add_repeat(
                "family",
                "家庭情况",
                [
                    {
                        "姓名": m.name,
                        "关系": m.relation,
                        "工作单位": m.workplace,
                        "职务": m.title,
                        # FamilyMember.phone 为 restricted，单独门控
                        "电话": m.phone,
                    }
                    for m in ext.family_members
                ],
            )
            if ext.emergency_contact:
                ec = ext.emergency_contact
                self.add_simple(
                    "emergency",
                    "紧急联系人",
                    {
                        "紧急联系人": ec.name,
                        "紧急联系人电话": ec.phone,
                        "与紧急联系人关系": ec.relation,
                    },
                )

    def _other(self, p: Profile, ext: ExtendedInfo | None) -> None:
        values: dict[str, Any] = {
            "专业技能": "、".join(p.skills) if p.skills else None,
            "证书": "、".join(p.certificates) if p.certificates else None,
            "自我评价": p.self_evaluation,
        }
        if ext is not None:
            personality = ext.personality
            if personality:
                values.update(
                    {
                        "兴趣爱好": "、".join(personality.hobbies)
                        if personality.hobbies
                        else None,
                        "特长": "、".join(personality.specialties)
                        if personality.specialties
                        else None,
                        "性格特点": "、".join(personality.traits)
                        if personality.traits
                        else None,
                        "MBTI": personality.mbti,
                    }
                )
            values.update(ext.links)
        self.add_simple("other", "其他信息", values)

    def flatten(self, p: Profile) -> dict[str, Any]:
        ext = p.extended
        self._basic(p.basic)
        self._intention(p, ext)
        self._education(p)
        self._experiences(p)
        if ext is not None:
            self._extended(ext)
        # 敏感扩展字段并入基本信息（默认剔除）
        if ext is not None and self.include_sensitive:
            for sec in self.sections:
                if sec["key"] == "basic":
                    sec["values"].update(
                        {
                            "婚姻状况": ext.marital_status,
                            "身高（厘米）": ext.height_cm,
                            "体重（公斤）": ext.weight_kg,
                            "健康状况": ext.health_status,
                            "户籍所在地": ext.hukou_location,
                        }
                    )
                    sec["values"] = _clean(sec["values"])
                    break
        self._other(p, ext)
        return {
            "schema": 1,
            "profile": {"id": p.id, "label": p.label},
            "sections": self.sections,
        }


def flatten_profile(payload: dict[str, Any], *, include_sensitive: bool = False) -> dict[str, Any]:
    """档案载荷 → 扁平分区结构（供浏览器插件规则直填引擎消费）。"""
    profile = Profile.model_validate(payload)
    return _Flattener(include_sensitive).flatten(profile)
