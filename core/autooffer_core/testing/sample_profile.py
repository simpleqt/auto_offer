"""一份虚构的示例档案，供各 Workstream 测试使用（全部为虚构数据）。

覆盖：基本信息、教育、实习/项目、技能、自我评价、扩展信息（语言/获奖/爱好/家庭成员）、附件。
"""

from __future__ import annotations

from autooffer_core.profile.schema import (
    Attachment,
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
)


def build_sample_profile() -> Profile:
    return Profile(
        id="demo-profile",
        label="中文-示例档案",
        basic=BasicInfo(
            name="张三",
            gender="男",
            birth_date=DateYM(year=2002, month=5, day=12),
            phone="13800001111",
            email="zhangsan@example.com",
            native_place="四川成都",
            current_city="成都",
            political_status="共青团员",
        ),
        intention=JobIntention(
            position="算法工程师",
            city=["成都", "北京"],
            salary_expectation="20-30K",
            available_date=DateYM(year=2026, month=7),
        ),
        education=[
            Education(
                school="示例大学",
                major="计算机科学与技术",
                degree="本科",
                period=DateRange(
                    start=DateYM(year=2020, month=9),
                    end=DateYM(year=2024, month=6),
                ),
                gpa="3.6/4.0",
            )
        ],
        experiences=[
            Experience(
                kind="internship",
                organization="某科技公司",
                title="后端开发实习生",
                period=DateRange(
                    start=DateYM(year=2023, month=7),
                    end=DateYM(year=2023, month=9),
                ),
                description="负责内部工具的接口开发与测试。",
                highlights=["独立完成 3 个 REST 接口", "接口平均时延降低 20%"],
            ),
            Experience(
                kind="project",
                organization="课程项目",
                title="校园二手交易平台",
                period=DateRange(
                    start=DateYM(year=2023, month=3),
                    end=None,  # 至今
                ),
                description="基于 FastAPI + React 的校园二手交易平台。",
            ),
        ],
        skills=["Python", "FastAPI", "Playwright", "SQL"],
        certificates=["CET-6"],
        self_evaluation="做事踏实，具备良好的工程习惯与快速学习能力。",
        extended=ExtendedInfo(
            personality=PersonalityInfo(
                traits=["沉稳", "抗压"],
                mbti="INTJ",
                hobbies=["篮球", "摄影"],
                specialties=["钢琴"],
            ),
            languages=[
                LanguageSkill(language="英语", level="CET-6", score="560"),
                LanguageSkill(language="日语", level="N2"),
            ],
            awards=[
                Award(
                    title="全国大学生程序设计竞赛二等奖",
                    level="国家级",
                    date=DateYM(year=2023, month=10),
                ),
                Award(title="校级一等奖学金", level="校级", date=DateYM(year=2022, month=11)),
            ],
            campus_roles=[
                CampusRole(organization="校学生会技术部", role="部长", period=None)
            ],
            family_members=[
                FamilyMember(relation="父亲", name="张父", workplace="某公司", title="工程师"),
            ],
            links={"github": "https://github.com/zhangsan"},
            travel_willingness="接受短期出差",
        ),
        qa_bank=[
            QAPair(
                question="你为什么选择我们公司？",
                answer="贵公司在技术方向与我的职业规划高度契合。",
            ),
        ],
        attachments=[
            Attachment(
                kind="resume", label="中文简历",
                path="resumes/zhangsan_cn.pdf", language="zh",
            ),
            Attachment(
                kind="resume", label="英文简历",
                path="resumes/zhangsan_en.pdf", language="en",
            ),
            Attachment(kind="photo", label="一寸白底照", path="photos/photo_1cun.jpg"),
        ],
    )
