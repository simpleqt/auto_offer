"""档案完整度评分测试。

夹具与 frontend/src/__tests__ 的 TS 镜像测试保持一致：
两侧对同一份档案断言相同分数（跨语言同步契约）。
"""

from __future__ import annotations

from autooffer_core.profile.completeness import profile_completeness
from autooffer_core.profile.schema import Profile

# 最小档案：仅必填字段（与前端夹具 minimal 一致）
MINIMAL: dict = {
    "id": "p1",
    "label": "最小档案",
    "basic": {"name": "张三", "phone": "13800000000", "email": "z@example.com"},
}

# 完整档案：全部维度都有值（与前端夹具 full 一致）
FULL: dict = {
    "id": "p2",
    "label": "完整档案",
    "basic": {
        "name": "张三",
        "phone": "13800000000",
        "email": "z@example.com",
        "gender": "男",
        "birth_date": {"year": 2000, "month": 1},
        "political_status": "共青团员",
        "current_city": "成都市",
        "native_place": "四川",
        "ethnicity": "汉族",
    },
    "intention": {
        "position": "算法工程师",
        "city": ["成都"],
        "salary_expectation": "20-30K",
    },
    "education": [
        {
            "school": "示例大学",
            "college": "计算机学院",
            "major": "计算机",
            "degree": "本科",
            "gpa": "3.5",
            "period": {"start": {"year": 2019, "month": 9}},
        }
    ],
    "experiences": [
        {
            "kind": "internship",
            "organization": "示例公司",
            "period": {"start": {"year": 2023, "month": 3}},
        },
        {
            "kind": "project",
            "organization": "实验室",
            "period": {"start": {"year": 2022, "month": 9}},
        },
    ],
    "skills": ["Python"],
    "certificates": ["CET-6"],
    "self_evaluation": "踏实肯干",
    "extended": {"origin_place": "四川"},
    "attachments": [
        {"kind": "resume", "label": "中文简历", "path": "C:/x.pdf"}
    ],
}


def test_minimal_profile_score() -> None:
    score, missing = profile_completeness(Profile.model_validate(MINIMAL))
    # 姓名/手机/邮箱 = 15；其余全缺
    assert score == 15
    assert "教育经历" in missing
    assert "默认简历附件" in missing
    assert "学院" not in missing  # 无教育经历时不逐项列学院


def test_full_profile_scores_100() -> None:
    score, missing = profile_completeness(Profile.model_validate(FULL))
    assert score == 100, missing
    assert missing == []
