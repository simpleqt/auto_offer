"""档案数据模型（契约，docs/03 §1.1）。

字段敏感级别通过 json_schema_extra["sensitivity"] 标注:
- normal: 命中即注入（默认，不标注）
- sensitive: 命中才注入 + 填写报告单独列出
- restricted: 命中时暂停, 界面单独授权本次使用
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# pydantic Field(json_schema_extra=...) 期望 dict[str, Any]（JsonDict）。
SENSITIVE: dict[str, Any] = {"sensitivity": "sensitive"}
RESTRICTED: dict[str, Any] = {"sensitivity": "restricted"}


class DateYM(BaseModel):
    year: int
    month: int | None = None
    day: int | None = None


class DateRange(BaseModel):
    start: DateYM
    end: DateYM | None = None
    """end 为 None 表示"至今"。"""


class Education(BaseModel):
    school: str
    major: str | None = None
    degree: Literal["高中", "大专", "本科", "硕士", "博士", "其他"] | None = None
    period: DateRange
    gpa: str | None = None
    description: str | None = None


class Experience(BaseModel):
    kind: Literal["internship", "work", "project", "research"]
    """实习/工作/工程项目/科研项目。科研单列：站点有专门科研模块才使用，优先级最低。"""
    organization: str
    title: str | None = None
    period: DateRange
    description: str | None = None
    highlights: list[str] = []
    link: str | None = None
    """项目/作品主页或代码仓库地址（如 GitHub），对应站点「项目链接」类字段。"""


class BasicInfo(BaseModel):
    name: str
    gender: Literal["男", "女", "其他"] | None = None
    birth_date: DateYM | None = None
    phone: str
    email: str
    native_place: str | None = None
    current_city: str | None = None
    political_status: str | None = None
    nationality: str | None = None
    """国籍（招聘表常见必填，如「中国」）。"""
    work_years: str | None = None
    """工作年限（如「应届毕业生」「3年」），校园投递常问。"""
    id_number: str | None = Field(default=None, json_schema_extra=RESTRICTED)


class JobIntention(BaseModel):
    position: str | None = None
    city: list[str] = []
    salary_expectation: str | None = None
    """期望薪资/期望月薪（如「20-30K」）。"""
    current_salary: str | None = None
    """现月薪（税前），社招/校招表常见。"""
    expected_industry: str | None = None
    """期望从事行业（如「人工智能/互联网」）。"""
    available_date: DateYM | None = None


class QAPair(BaseModel):
    question: str
    answer: str


class LanguageSkill(BaseModel):
    language: str
    level: str | None = None
    score: str | None = None
    certificate_date: DateYM | None = None


class Award(BaseModel):
    title: str
    level: str | None = None
    date: DateYM | None = None
    description: str | None = None


class CampusRole(BaseModel):
    organization: str
    role: str
    period: DateRange | None = None
    description: str | None = None


class FamilyMember(BaseModel):
    relation: str
    name: str
    workplace: str | None = None
    title: str | None = None
    phone: str | None = Field(default=None, json_schema_extra=RESTRICTED)


class Reference(BaseModel):
    name: str
    relation: str
    organization: str | None = None
    title: str | None = None
    phone: str | None = Field(default=None, json_schema_extra=RESTRICTED)
    email: str | None = None


class PersonalityInfo(BaseModel):
    traits: list[str] = []
    mbti: str | None = None
    assessment_summary: str | None = None
    hobbies: list[str] = []
    specialties: list[str] = []


class ExtendedInfo(BaseModel):
    personality: PersonalityInfo | None = None
    languages: list[LanguageSkill] = []
    awards: list[Award] = []
    campus_roles: list[CampusRole] = []
    family_members: list[FamilyMember] = Field(default=[], json_schema_extra=SENSITIVE)
    emergency_contact: FamilyMember | None = Field(default=None, json_schema_extra=SENSITIVE)
    marital_status: str | None = Field(default=None, json_schema_extra=SENSITIVE)
    height_cm: int | None = Field(default=None, json_schema_extra=SENSITIVE)
    weight_kg: int | None = Field(default=None, json_schema_extra=SENSITIVE)
    health_status: str | None = Field(default=None, json_schema_extra=SENSITIVE)
    party_join_date: DateYM | None = None
    hukou_location: str | None = Field(default=None, json_schema_extra=SENSITIVE)
    origin_place: str | None = None
    references: list[Reference] = []
    links: dict[str, str] = {}
    available_date: DateYM | None = None
    travel_willingness: str | None = None
    relocation_willingness: str | None = None


class AttachmentSpec(BaseModel):
    """站点对附件的要求（感知层从 accept 属性与提示文本解析所得）。"""

    formats: list[str] = []
    max_size_kb: int | None = None
    pixel_size: str | None = None


class Attachment(BaseModel):
    kind: Literal["resume", "photo", "transcript", "certificate", "portfolio", "other"]
    label: str
    path: str
    language: Literal["zh", "en"] | None = None
    meta: dict[str, str | int] = {}


class Profile(BaseModel):
    id: str
    label: str
    basic: BasicInfo
    intention: JobIntention | None = None
    education: list[Education] = []
    experiences: list[Experience] = []
    skills: list[str] = []
    certificates: list[str] = []
    self_evaluation: str | None = None
    extended: ExtendedInfo | None = None
    qa_bank: list[QAPair] = []
    attachments: list[Attachment] = []
