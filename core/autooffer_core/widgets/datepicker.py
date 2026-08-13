"""日期控件处理器（docs/03 §3.2）。

策略链（依次降级）：
1. 按 placeholder 格式直接键入（如 yyyy-mm-dd）
2. 原生 fill（input[type=date/month]，ISO 格式）
3. 日历面板逐级导航（年/月 → 日）
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from autooffer_core.errors import ActionError
from autooffer_core.perception.models import UIElement
from autooffer_core.profile.schema import DateYM
from autooffer_core.widgets.base import ExecContext, FillResult

log = structlog.get_logger(__name__)

# placeholder 常见格式 token → 渲染规则
_FMT_RE = re.compile(
    r"(?P<y>y{2,4}|Y{2,4})(?P<s1>[^\w\s]?)(?P<m>m{1,2}|M{1,2})?(?P<s2>[^\w\s]?)(?P<d>d{1,2}|D{1,2})?"
)

# 面板导航控件文本特征
_PREV_HINTS = ("‹", "«", "<", "prev", "上一", "上年", "上一月")
_NEXT_HINTS = ("›", "»", ">", "next", "下一", "下年", "下一月")
# 面板当前年月标题，如 "2026年8月" / "2026-08" / "August 2026"
_TITLE_YM_RE = re.compile(r"(\d{4})\s*[年\-/.]?\s*(\d{1,2})\s*月?")
# 纯年份标题（年-月面板），如 "2024" / "2024年"
_TITLE_Y_RE = re.compile(r"^(\d{4})\s*年?$")

_MAX_NAV_STEPS = 48  # 防止导航死循环


def parse_placeholder_format(placeholder: str | None) -> str | None:
    """从 placeholder 识别日期格式，返回规范化格式串（yyyy-mm-dd 风格）。"""
    if not placeholder:
        return None
    m = _FMT_RE.search(placeholder.strip())
    if m is None:
        return None
    parts = ["yyyy"]
    if m.group("m"):
        parts.append("mm")
    if m.group("d"):
        parts.append("dd")
    sep1 = m.group("s1") or "-"
    sep2 = m.group("s2") or sep1
    if len(parts) <= 1:
        return "yyyy"
    return sep1.join(parts[:2]) + (sep2 + parts[2] if len(parts) > 2 else "")


def format_date(d: DateYM, fmt: str) -> str:
    """按规范化格式串渲染 DateYM；缺段（month/day 为 None）自动省略。"""
    seps = [c for c in fmt if not c.isalpha()]
    sep = seps[0] if seps else "-"
    if "-" in fmt and not seps:
        sep = "-"
    out = [f"{d.year:04d}"]
    if "mm" in fmt and d.month is not None:
        out.append(f"{d.month:02d}")
    if "dd" in fmt and d.month is not None and d.day is not None:
        out.append(f"{d.day:02d}")
    # 中文格式特殊处理
    if "年" in fmt or (seps and seps[0] not in "-/."):
        pass
    return sep.join(out)


def _iso(d: DateYM) -> str:
    if d.month is None:
        return f"{d.year:04d}"
    if d.day is None:
        return f"{d.year:04d}-{d.month:02d}"
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


class DatePickerHandler:
    """单日期控件。"""

    def match(self, el: UIElement) -> bool:
        return el.role == "date"

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        if not isinstance(target, DateYM):
            raise ActionError(f"日期目标必须为 DateYM: {target!r} (元素[{el.index}]{el.label})")

        # 策略 1：按 placeholder 格式键入
        fmt = parse_placeholder_format(el.placeholder)
        if fmt is not None:
            text = format_date(target, fmt)
            try:
                await ctx.driver.input_text(el, text, humanize=ctx.humanize)
                got = await ctx.driver.element_value(el)
                if got:
                    return FillResult(ok=True, strategy="placeholder_type", detail=text)
            except Exception as exc:
                log.info("datepicker.type_failed", label=el.label, error=str(exc))

        # 策略 2：原生 date/month input 直接填 ISO 值
        if el.tag == "input":
            try:
                await ctx.driver.input_text(el, _iso(target), humanize=False)
                got = await ctx.driver.element_value(el)
                if got:
                    return FillResult(ok=True, strategy="native_fill", detail=_iso(target))
            except Exception as exc:
                log.info("datepicker.native_failed", label=el.label, error=str(exc))

        # 策略 3：日历面板导航
        return await self._fill_via_panel(el, target, ctx)

    async def _fill_via_panel(self, el: UIElement, target: DateYM, ctx: ExecContext) -> FillResult:
        await ctx.driver.click(el)  # 打开面板
        for _ in range(_MAX_NAV_STEPS):
            obs = await ctx.driver.observe(with_screenshot=False)
            visible = [e for e in obs.elements if e.visible and e.label]

            # 面板形态 A：标题=年月，格子=日；形态 B：标题=纯年份，格子=月（年-月面板）
            current = self._panel_ym(visible)
            year_only = self._panel_year(visible) if current is None else None

            if current is not None and target.month is not None:
                cur_y, cur_m = current
                if (cur_y, cur_m) < (target.year, target.month):
                    await self._click_nav(visible, _NEXT_HINTS, ctx)
                    continue
                if (cur_y, cur_m) > (target.year, target.month):
                    await self._click_nav(visible, _PREV_HINTS, ctx)
                    continue
            elif year_only is not None:
                if year_only < target.year:
                    await self._click_nav(visible, _NEXT_HINTS, ctx)
                    continue
                if year_only > target.year:
                    await self._click_nav(visible, _PREV_HINTS, ctx)
                    continue
                # 年份到位：点击月份格子（如"7月"），精确匹配防止 6/7 混淆
                if target.month is not None:
                    month_el = self._find_month(visible, target.month)
                    if month_el is not None:
                        await ctx.driver.click(month_el)
                        return FillResult(ok=True, strategy="panel_nav", detail=_iso(target))

            # 到位（或面板无年月标题）：点击目标日
            if target.day is not None:
                day_el = self._find_day(visible, target.day)
                if day_el is not None:
                    await ctx.driver.click(day_el)
                    return FillResult(ok=True, strategy="panel_nav", detail=_iso(target))
            elif current is not None:
                # 只到年月（month 控件型面板）
                return FillResult(ok=True, strategy="panel_nav", detail=_iso(target))
            return FillResult(
                ok=False, strategy="panel_nav", detail=f"日历面板中未找到目标日: {_iso(target)}"
            )
        return FillResult(ok=False, strategy="panel_nav", detail="日历面板导航超步")

    @staticmethod
    def _panel_ym(visible: list[UIElement]) -> tuple[int, int] | None:
        """从面板元素文本中解析当前展示的年月（取首个命中，通常为标题）。"""
        for e in visible:
            m = _TITLE_YM_RE.search(e.label)
            if m is not None:
                y, mo = int(m.group(1)), int(m.group(2))
                if 1 <= mo <= 12:
                    return y, mo
        return None

    @staticmethod
    def _panel_year(visible: list[UIElement]) -> int | None:
        """解析纯年份标题（年-月面板，如日历头只显示 "2024"）。"""
        for e in visible:
            m = _TITLE_Y_RE.match(e.label.strip())
            if m is not None:
                return int(m.group(1))
        return None

    @staticmethod
    def _find_month(visible: list[UIElement], month: int) -> UIElement | None:
        """精确匹配月份格子："7月"/"07月"/"Jul" 不与 "6月" 混淆。"""
        wants = {f"{month}月", f"{month:02d}月", str(month), f"{month:02d}"}
        for e in visible:
            if e.role in ("custom", "button") and e.label.strip() in wants:
                return e
        return None

    @staticmethod
    async def _click_nav(
        visible: list[UIElement], hints: tuple[str, ...], ctx: ExecContext
    ) -> None:
        for e in visible:
            label = e.label.strip()
            if any(h in label for h in hints) and len(label) <= 6:
                await ctx.driver.click(e)
                await ctx.driver.wait(0.2)
                return
        raise ActionError("日历面板未找到年月导航控件")

    @staticmethod
    def _find_day(visible: list[UIElement], day: int) -> UIElement | None:
        want = str(day)
        for e in visible:
            if e.role in ("custom", "button") and e.label.strip() == want:
                return e
        return None
