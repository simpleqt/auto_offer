"""站点场景检测器（docs/03 §2.3）。

在 PageObservation 之上叠加轻量页面证据（标题/正文文本/遮罩层），
按 scenario_rules 中的规则集裁决 page_type 与 blocking_overlays。
规则不确定时 page_type 保持 unknown，交由 Planner 结合截图裁决。
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel

from autooffer_core.perception.models import (
    PageObservation,
    PageScenario,
    PageType,
)
from autooffer_core.perception.scenario_rules import DEFAULT_RULES, ScenarioRule

logger = structlog.get_logger(__name__)

_PAGE_TYPES: tuple[str, ...] = (
    "form", "login", "register", "job_list", "job_detail",
    "preview", "success", "error", "unknown",
)
_OVERLAYS: tuple[str, ...] = (
    "cookie_banner", "privacy_consent", "captcha", "qr_login", "generic_modal",
)
_FILL_ROLES: frozenset[str] = frozenset(
    {"input", "textarea", "select", "combobox", "date", "custom", "richtext"}
)

_CAPTCHA_HINT_RE_TEXT = ("captcha", "验证码", "滑块", "人机验证", "安全验证")


class PageEvidence(BaseModel):
    """检测所需的页面证据（由调用方从页面收集，避免检测器直接依赖浏览器）。"""

    body_text: str = ""
    """正文可见文本（可截断）。"""
    overlay_texts: list[str] = []
    """高 z-index 遮罩/弹层的可见文本列表。"""
    form_field_count: int = 0
    """可填字段数；0 表示由 observation 统计。"""


class ScenarioDetector:
    """规则驱动的场景检测器。"""

    def __init__(self, rules: list[ScenarioRule] | None = None) -> None:
        self._rules = list(rules) if rules is not None else list(DEFAULT_RULES)

    def detect(
        self, observation: PageObservation, evidence: PageEvidence | None = None
    ) -> PageScenario:
        evidence = evidence or PageEvidence()
        url = observation.url.lower()
        title = observation.title.lower()
        body = evidence.body_text.lower()
        overlays = [t.lower() for t in evidence.overlay_texts]
        # 契约模型无 input type 字段，密码框经 selector/label/placeholder 文本推断
        has_password = any(
            e.tag == "input" and self._looks_like_password(e.selector, e.label, e.placeholder)
            for e in observation.elements
        )
        has_captcha = self._has_captcha_hint(observation, body)
        field_count = evidence.form_field_count or sum(
            1 for e in observation.elements if e.role in _FILL_ROLES
        )

        page_hits: list[tuple[int, str, str]] = []  # (priority, value, signal)
        overlay_hits: dict[str, tuple[int, str]] = {}

        for rule in self._rules:
            signal = self._match(
                rule,
                url=url,
                title=title,
                body=body,
                overlays=overlays,
                has_password=has_password,
                has_captcha=has_captcha,
                field_count=field_count,
            )
            if signal is None:
                continue
            if rule.target == "page_type" and rule.value in _PAGE_TYPES:
                page_hits.append((rule.priority, rule.value, signal))
            elif rule.target == "overlay" and rule.value in _OVERLAYS:
                prev = overlay_hits.get(rule.value)
                if prev is None or rule.priority > prev[0]:
                    overlay_hits[rule.value] = (rule.priority, signal)

        page_type: PageType = "unknown"
        signals: list[str] = []
        if page_hits:
            page_hits.sort(key=lambda h: h[0], reverse=True)
            page_type = page_hits[0][1]  # type: ignore[assignment]
            signals.extend(h[2] for h in page_hits)
        overlay_kinds = [
            kind for kind, _ in sorted(overlay_hits.items(), key=lambda kv: kv[1][0], reverse=True)
        ]
        signals.extend(sig for _, sig in overlay_hits.values())

        scenario = PageScenario(
            page_type=page_type,
            blocking_overlays=[k for k in overlay_kinds if k in _OVERLAYS],  # type: ignore[misc]
            signals=signals,
            prefilled_ratio=observation.scenario.prefilled_ratio,
        )
        logger.info(
            "scenario_detected",
            url=observation.url,
            page_type=scenario.page_type,
            overlays=list(scenario.blocking_overlays),
            signals=len(signals),
        )
        return scenario

    def _looks_like_password(self, selector: str, label: str, placeholder: str | None) -> bool:
        hay = f"{selector} {label} {placeholder or ''}".lower()
        return "password" in hay or "密码" in hay

    def _has_captcha_hint(self, observation: PageObservation, body: str) -> bool:
        for e in observation.elements:
            hay = (e.selector + " " + e.label + " " + (e.placeholder or "")).lower()
            if any(k in hay for k in _CAPTCHA_HINT_RE_TEXT):
                return True
        return any(k in body for k in _CAPTCHA_HINT_RE_TEXT)

    def _match(  # noqa: PLR0913
        self,
        rule: ScenarioRule,
        *,
        url: str,
        title: str,
        body: str,
        overlays: list[str],
        has_password: bool,
        has_captcha: bool,
        field_count: int,
    ) -> str | None:
        """规则命中返回 signal 文本，否则 None。"""
        conditions: list[bool] = []
        specifics: list[bool] = []
        for kw in rule.url_keywords:
            specifics.append(kw.lower() in url)
        for kw in rule.title_keywords:
            specifics.append(kw.lower() in title)
        for kw in rule.body_text_keywords:
            specifics.append(kw.lower() in body)
        for kw in rule.overlay_text_keywords:
            specifics.append(any(kw.lower() in o for o in overlays))
        if rule.has_password_field:
            conditions.append(has_password)
        if rule.has_captcha_hint:
            conditions.append(has_captcha)
        if rule.min_form_fields is not None:
            conditions.append(field_count >= rule.min_form_fields)
        if not conditions and not specifics:
            return None
        # 关键词组内取"任一命中"，硬条件全部必须满足
        keyword_hit = any(specifics) if specifics else True
        if not (keyword_hit and all(conditions)):
            return None
        return f"rule:{rule.name}->{rule.target}={rule.value}"
