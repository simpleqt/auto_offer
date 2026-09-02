"""档案完整度评分：0-100 + 缺失项清单。

用于界面提示「这份档案还能补什么」——档案越全，站点可直填的字段越多。
权重：核心联系方式 15 / 个人补充 10 / 教育 20 / 求职意向 10 / 经历 20 /
技能证书 7 / 自评 3 / 扩展信息 5 / 简历附件 10。

前端有同逻辑的 TS 镜像（frontend/src/completeness.ts），
两侧用同一份测试夹具断言相同结果，修改时保持同步。
"""

from __future__ import annotations

from autooffer_core.profile.schema import Profile


def profile_completeness(p: Profile) -> tuple[int, list[str]]:
    """返回 (完整度 0-100, 缺失项中文清单)。"""
    score = 0
    missing: list[str] = []

    def check(value: object, weight: int, label: str) -> None:
        nonlocal score
        if value:
            score += weight
        else:
            missing.append(label)

    b = p.basic
    check(b.name, 5, "姓名")
    check(b.phone, 5, "手机号")
    check(b.email, 5, "邮箱")
    check(b.gender, 2, "性别")
    check(b.birth_date, 2, "出生日期")
    check(b.political_status, 2, "政治面貌")
    check(b.current_city, 2, "现居住城市")
    check(b.native_place, 2, "籍贯")
    check(b.ethnicity, 1, "民族")

    if p.education:
        score += 10
        e = p.education[0]
        check(e.college, 3, "学院")
        check(e.major, 3, "专业")
        check(e.degree, 2, "学历")
        check(e.gpa, 2, "成绩/GPA")
    else:
        missing.append("教育经历")

    it = p.intention
    if it:
        check(it.position, 5, "意向岗位")
        check(it.city, 3, "期望城市")
        check(it.salary_expectation, 2, "期望薪资")
    else:
        missing.extend(["意向岗位", "期望城市", "期望薪资"])

    check(any(x.kind in ("internship", "work") for x in p.experiences), 10, "实习/工作经历")
    check(any(x.kind == "project" for x in p.experiences), 10, "项目经历")

    check(p.skills, 4, "专业技能")
    check(p.certificates, 3, "证书")
    check(p.self_evaluation, 3, "自我评价")

    ext = p.extended
    has_ext = bool(
        ext
        and (
            ext.origin_place
            or ext.hukou_location
            or ext.marital_status
            or ext.travel_willingness
            or ext.relocation_willingness
            or ext.available_date
            or ext.party_join_date
            or ext.personality
            or ext.languages
            or ext.awards
            or ext.campus_roles
            or ext.references
        )
    )
    check(has_ext, 5, "扩展信息（婚姻/户口/获奖等）")

    check(any(a.kind == "resume" for a in p.attachments), 10, "默认简历附件")

    return min(score, 100), missing
