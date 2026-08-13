"""级联控件处理器（docs/03 §3.2）：省/市/区逐级展开选择。

档案地名先经 region.split_region_chain 标准化（"四川成都" → 四川省/成都市），
再逐级：对当前级控件选择 → 等待下一级加载 → 在最新观察中定位下一级控件。
"""

from __future__ import annotations

from typing import Any

import structlog

from autooffer_core.errors import ActionError
from autooffer_core.perception.models import UIElement
from autooffer_core.widgets.base import ExecContext, FillResult
from autooffer_core.widgets.dropdown import _click_matched_option
from autooffer_core.widgets.matching import match_option
from autooffer_core.widgets.region import split_region_chain

log = structlog.get_logger(__name__)

# 级联控件常见 label 语义
_CASCADE_LABEL_HINTS = ("省", "市", "区", "地区", "籍贯", "户籍", "生源", "城市", "户口")


class CascadeHandler:
    """级联（省/市/区）。el 指向第一级控件。"""

    def match(self, el: UIElement) -> bool:
        if el.role not in ("combobox", "select"):
            return False
        return any(h in el.label for h in _CASCADE_LABEL_HINTS)

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        if not isinstance(target, str) or not target.strip():
            raise ActionError(f"级联目标必须为字符串: {target!r} (元素[{el.index}]{el.label})")
        levels = split_region_chain(target)
        if not levels:
            return FillResult(ok=False, detail=f"地名无法解析: {target}")

        current = el
        used: list[str] = []
        for depth, level in enumerate(levels):
            res = await self._select_level(current, level, ctx)
            if res is None:
                # 面板式级联：点击后选项里直接命中本级（首列/次列）
                hit = await _click_matched_option(ctx.driver, level, skip_index=current.index)
                if hit is not None:
                    res = hit[0]
            if res is None:
                log.warning(
                    "cascade.level_miss", level=level, depth=depth, label=current.label
                )
                return FillResult(
                    ok=False,
                    strategy="level_miss",
                    detail=f"第{depth + 1}级未匹配: {level}（已选 {used}）",
                )
            used.append(res)
            await ctx.driver.wait(0.3)  # 等下一级加载

            nxt = await self._next_level_element(current, ctx)
            if nxt is None:
                if depth < len(levels) - 1:
                    return FillResult(
                        ok=False,
                        strategy="next_missing",
                        detail=f"第{depth + 2}级控件未出现（已选 {used}）",
                    )
                break
            current = nxt
        return FillResult(ok=True, strategy="cascade", detail="/".join(used))

    @staticmethod
    async def _select_level(el: UIElement, level: str, ctx: ExecContext) -> str | None:
        """对单级控件完成选择：原生 select 直接选；否则点击展开。"""
        if el.tag == "select":
            hit = match_option(level, el.options or [])
            if hit is not None:
                await ctx.driver.select_option(el, hit[0])
                return hit[0]
            return None
        await ctx.driver.click(el)  # 展开本级弹层
        return None

    @staticmethod
    async def _next_level_element(prev: UIElement, ctx: ExecContext) -> UIElement | None:
        """在最新观察中定位下一级控件：同 section、编号靠后的 select/combobox。"""
        obs = await ctx.driver.observe(with_screenshot=False)
        candidates = [
            e
            for e in obs.elements
            if e.role in ("select", "combobox")
            and e.index != prev.index
            and (prev.section_id is None or e.section_id == prev.section_id)
        ]
        if not candidates:
            return None
        after = [e for e in candidates if e.index > prev.index]
        return min(after or candidates, key=lambda e: e.index)
