"""档案模块：schema、简历解析、按需注入解析器。"""

from autooffer_core.profile.parser import parse_resume
from autooffer_core.profile.resolver import ProfileResolver
from autooffer_core.profile.schema import (
    Attachment,
    AttachmentSpec,
    Award,
    BasicInfo,
    CampusRole,
    DateRange,
    DateYM,
    Education,
    Experience,
    ExtendedInfo,
    FamilyMember,
    JobIntention,
    LanguageSkill,
    PersonalityInfo,
    Profile,
    QAPair,
    Reference,
)
from autooffer_core.profile.store import (
    load_profile,
    profile_from_yaml,
    profile_to_yaml,
    save_profile,
)

__all__ = [
    "Attachment",
    "AttachmentSpec",
    "ProfileResolver",
    "load_profile",
    "parse_resume",
    "profile_from_yaml",
    "profile_to_yaml",
    "save_profile",
    "Award",
    "BasicInfo",
    "CampusRole",
    "DateRange",
    "DateYM",
    "Education",
    "Experience",
    "ExtendedInfo",
    "FamilyMember",
    "JobIntention",
    "LanguageSkill",
    "PersonalityInfo",
    "Profile",
    "QAPair",
    "Reference",
]
