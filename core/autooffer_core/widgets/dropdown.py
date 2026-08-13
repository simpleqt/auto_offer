"""下拉控件处理器（docs/03 §3.2）。

策略链（依次降级）：
1. 原生 select_option（tag=select，选项经三级语义匹配）
2. 点击展开 → 感知弹层 → 语义匹配选项点击
3. 搜索式：键入关键词 → 等待过滤 → 选首个匹配
"""

from __future__ import annotations

from typing import Any

import structlog

from autooffer_core.drivers.base import Driver
from autooffer_core.errors import ActionError
from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.widgets.base import ExecContext, FillResult
from autooffer_core.widgets.matching import match_option

log = structlog.get_logger(__name__)

# 弹层选项候选 role：感知层把 li/[role=option] 等提取为 custom
_OPTION_ROLES = {"custom", "button"}


async def _click_matched_option(
    driver: Driver, target: str, *, skip_index: int
) -> tuple[str, str] | None:
    """刷新感知，在可见候选元素中语义匹配并点击，返回 (选项文本, 级别)。"""
    obs: PageObservation = await driver.observe(with_screenshot=False)
    candidates = [
        e
        for e in obs.elements
        if e.visible and e.role in _OPTION_ROLES and e.label and e.index != skip_index
    ]
    hit = match_option(target, [e.label for e in candidates])
    if hit is None:
        return None
    text, level = hit
    chosen = next(e for e in candidates if e.label == text)
    await driver.click(chosen)
    return text, level


class DropdownHandler:
    """下拉（原生 select / 自定义弹层 / 搜索式 combobox）。"""

    def match(self, el: UIElement) -> bool:
        return el.role in ("select", "combobox")

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        if not isinstance(target, str) or not target.strip():
            raise ActionError(f"下拉目标值必须为字符串: {target!r} (元素[{el.index}]{el.label})")
        target = target.strip()

        # 策略 1：原生 select
        if el.tag == "select":
            options = el.options or []
            hit = match_option(target, options)
            if hit is not None:
                await ctx.driver.select_option(el, hit[0])
                return FillResult(ok=True, strategy="native_select", detail=hit[0])
            log.info("dropdown.native_miss", label=el.label, target=target, options=options[:10])

        # 策略 2：点击展开 → 感知弹层 → 语义匹配
        try:
            await ctx.driver.click(el)
        except Exception as exc:  # 展开失败直接落到搜索式
            log.info("dropdown.expand_failed", label=el.label, error=str(exc))
        else:
            hit = await _click_matched_option(ctx.driver, target, skip_index=el.index)
            if hit is not None:
                return FillResult(ok=True, strategy="panel_click", detail=f"{hit[0]}({hit[1]})")

        # 策略 3：搜索式（可键入的 combobox）
        if el.tag == "input":
            await ctx.driver.input_text(el, target, humanize=ctx.humanize)
            await ctx.driver.wait(0.5)
            hit = await _click_matched_option(ctx.driver, target, skip_index=el.index)
            if hit is not None:
                return FillResult(ok=True, strategy="search", detail=f"{hit[0]}({hit[1]})")

        log.warning("dropdown.exhausted", label=el.label, target=target)
        return FillResult(
            ok=False, strategy="exhausted", detail=f"下拉[{el.label}]未匹配到选项: {target}"
        )
