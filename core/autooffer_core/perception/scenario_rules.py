"""站点场景检测规则集（数据驱动，可持续扩充；docs/03 §2.3）。

每条规则命中即产生一条 signal；ScenarioDetector 汇总所有命中信号后
按优先级裁决 page_type 与 blocking_overlays。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ScenarioRule(BaseModel):
    """一条启发式场景规则。"""

    name: str
    target: Literal["page_type", "overlay"]
    value: str
    """page_type 取值或 overlay 种类。"""
    url_keywords: list[str] = []
    title_keywords: list[str] = []
    body_text_keywords: list[str] = []
    has_password_field: bool = False
    has_captcha_hint: bool = False
    """存在验证码类元素（类名/id/label 含 captcha/验证码/滑块）。"""
    overlay_text_keywords: list[str] = []
    """要求高 z-index 遮罩层文本命中。"""
    min_form_fields: int | None = None
    """页面可填字段数下限（用于区分表单页与列表页）。"""
    priority: int = 0
    """同 target 多规则命中时取 priority 大者。"""


DEFAULT_RULES: list[ScenarioRule] = [
    # ---- page_type ----
    ScenarioRule(
        name="login_by_url_or_password",
        target="page_type",
        value="login",
        url_keywords=["login", "signin", "sign_in", "passport"],
        title_keywords=["登录", "登陆", "login", "sign in"],
        has_password_field=True,
        priority=80,
    ),
    ScenarioRule(
        name="register",
        target="page_type",
        value="register",
        url_keywords=["register", "signup", "sign_up"],
        title_keywords=["注册", "register", "sign up"],
        priority=70,
    ),
    ScenarioRule(
        name="job_list",
        target="page_type",
        value="job_list",
        url_keywords=["jobs", "position", "search", "list"],
        title_keywords=["职位列表", "招聘岗位", "job list"],
        priority=30,
    ),
    ScenarioRule(
        name="job_detail",
        target="page_type",
        value="job_detail",
        url_keywords=["job_detail", "jobdetail", "position_detail", "job/"],
        title_keywords=["职位详情", "岗位详情", "job detail"],
        priority=40,
    ),
    ScenarioRule(
        name="success",
        target="page_type",
        value="success",
        body_text_keywords=[
            "投递成功", "已投递", "申请成功", "提交成功", "apply success", "submitted",
        ],
        url_keywords=["success", "done", "complete"],
        priority=90,
    ),
    ScenarioRule(
        name="error",
        target="page_type",
        value="error",
        body_text_keywords=["页面不存在", "404", "系统繁忙", "出错了", "server error"],
        title_keywords=["错误", "error", "404"],
        priority=85,
    ),
    ScenarioRule(
        name="preview",
        target="page_type",
        value="preview",
        url_keywords=["preview", "confirm", "review"],
        title_keywords=["预览", "确认信息", "preview"],
        body_text_keywords=["请确认以下信息", "信息确认"],
        priority=60,
    ),
    ScenarioRule(
        name="form",
        target="page_type",
        value="form",
        url_keywords=["apply", "form", "resume", "edit"],
        min_form_fields=3,
        priority=10,
    ),
    # ---- blocking_overlays ----
    ScenarioRule(
        name="cookie_banner",
        target="overlay",
        value="cookie_banner",
        overlay_text_keywords=["cookie", "cookies", "我们使用cookie", "同意所有cookie"],
        priority=50,
    ),
    ScenarioRule(
        name="privacy_consent",
        target="overlay",
        value="privacy_consent",
        overlay_text_keywords=[
            "隐私政策", "个人信息保护", "同意并继续", "privacy policy", "个人信息授权",
        ],
        priority=60,
    ),
    ScenarioRule(
        name="captcha",
        target="overlay",
        value="captcha",
        has_captcha_hint=True,
        overlay_text_keywords=["验证码", "安全验证", "拖动滑块", "captcha", "人机验证"],
        priority=90,
    ),
    ScenarioRule(
        name="qr_login",
        target="overlay",
        value="qr_login",
        overlay_text_keywords=["扫码登录", "微信扫码", "扫描二维码", "scan qr"],
        priority=80,
    ),
    ScenarioRule(
        name="generic_modal",
        target="overlay",
        value="generic_modal",
        overlay_text_keywords=["提示", "请注意", "notice"],
        priority=10,
    ),
]
