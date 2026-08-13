"""日期区间控件处理器（docs/03 §3.2）。

复用 DatePickerHandler 处理起/止两个输入；end 为 None 时匹配"至今"
复选框或选项（至今/present）。
"""

from __future__ import annotations

from typing import Any

import structlog

from autooffer_core.errors import ActionError
from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.profile.schema import DateRange
from autooffer_core.widgets.base import ExecContext, FillResult
from autooffer_core.widgets.datepicker import DatePickerHandler

log = structlog.get_logger(__name__)

_TILL_NOW = ("至今", "现在", "目前", "present", "now")
_END_HINTS = ("结束", "止", "至", "end", "to", "～", "~", "-")


class DateRangeHandler:
    """日期区间（实习/项目/教育起止）。el 指向起始日期输入。"""

    def __init__(self, date_handler: DatePickerHandler | None = None) -> None:
        self._date = date_handler or DatePickerHandler()

    def match(self, el: UIElement) -> bool:
        return el.role == "date"

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        if not isinstance(target, DateRange):
            raise ActionError(
                f"日期区间目标必须为 DateRange: {target!r} (元素[{el.index}]{el.label})"
            )

        start_res = await self._date.fill(el, target.start, ctx)
        if not start_res.ok:
            return FillResult(
                ok=False,
                strategy=f"start:{start_res.strategy}",
                detail=f"起始日期失败: {start_res.detail}",
                needs_human=start_res.needs_human,
            )

        if target.end is None:
            return await self._fill_till_now(el, ctx, start_res)

        end_el = await self._find_end_element(el, ctx)
        if end_el is None:
            return FillResult(ok=False, strategy="end_missing", detail="未找到结束日期输入")
        end_res = await self._date.fill(end_el, target.end, ctx)
        if not end_res.ok:
            return FillResult(
                ok=False,
                strategy=f"end:{end_res.strategy}",
                detail=f"结束日期失败: {end_res.detail}",
                needs_human=end_res.needs_human,
            )
        return FillResult(
            ok=True, strategy=f"{start_res.strategy}+{end_res.strategy}", detail="区间完成"
        )

    async def _fill_till_now(
        self, el: UIElement, ctx: ExecContext, start_res: FillResult
    ) -> FillResult:
        """勾选"至今"：在最新观察中找 label 含 至今/present 的复选框或可点击项。"""
        obs = await ctx.driver.observe(with_screenshot=False)
        for e in obs.elements:
            if not e.visible or not e.label:
                continue
            label = e.label.strip().lower()
            if e.role in ("checkbox", "custom", "button") and any(
                h in label for h in _TILL_NOW
            ):
                await ctx.driver.click(e)
                return FillResult(ok=True, strategy=f"{start_res.strategy}+till_now", detail="至今")
        log.warning("daterange.till_now_missing", label=el.label)
        return FillResult(
            ok=False, strategy="till_now_missing", detail="未找到'至今'选项", needs_human=True
        )

    @staticmethod
    async def _find_end_element(el: UIElement, ctx: ExecContext) -> UIElement | None:
        """结束日期输入：同 section 的另一个 date 元素，label 含结束语义的优先。"""
        obs: PageObservation = await ctx.driver.observe(with_screenshot=False)
        dates = [
            e
            for e in obs.elements
            if e.role == "date" and e.index != el.index
            and (el.section_id is None or e.section_id == el.section_id)
        ]
        if not dates:
            return None
        for e in dates:
            label = e.label.strip().lower()
            if any(h in label for h in _END_HINTS):
                return e
        return dates[0]
