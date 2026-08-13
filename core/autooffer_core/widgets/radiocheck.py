"""单选/复选处理器（docs/03 §3.2）：按 label 语义匹配点击。

感知层把每个选项提取为独立元素（role=radio/checkbox），本处理器在同组
候选中按三级语义匹配目标 label 并点击；el 本身即目标时直接点击。
"""

from __future__ import annotations

from typing import Any

import structlog

from autooffer_core.errors import ActionError
from autooffer_core.perception.models import UIElement
from autooffer_core.widgets.base import ExecContext, FillResult
from autooffer_core.widgets.matching import match_option

log = structlog.get_logger(__name__)


class RadioCheckHandler:
    """单选/复选。"""

    def match(self, el: UIElement) -> bool:
        return el.role in ("radio", "checkbox")

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        if not isinstance(target, str) or not target.strip():
            raise ActionError(f"单选/复选目标必须为字符串: {target!r} (元素[{el.index}]{el.label})")
        target = target.strip()

        # el 自身即目标（如"至今"复选框）
        if match_option(target, [el.label]) is not None:
            await ctx.driver.click(el)
            return FillResult(ok=True, strategy="self_click", detail=el.label)

        obs = await ctx.driver.observe(with_screenshot=False)
        candidates = [
            e
            for e in obs.elements
            if e.visible
            and e.role == el.role
            and e.label
            and (el.section_id is None or e.section_id == el.section_id)
        ]
        hit = match_option(target, [e.label for e in candidates])
        if hit is None:
            log.warning("radiocheck.miss", label=el.label, target=target)
            return FillResult(
                ok=False, strategy="exhausted", detail=f"选项未匹配: {target}（控件 {el.label}）"
            )
        chosen = next(e for e in candidates if e.label == hit[0])
        await ctx.driver.click(chosen)
        return FillResult(ok=True, strategy="label_click", detail=f"{hit[0]}({hit[1]})")
