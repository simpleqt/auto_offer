"""下拉控件处理器（docs/03 §3.2）。

策略链（依次降级）：
1. 原生 select_option（tag=select，选项经三级语义匹配）
2. 点击展开 → 感知弹层 → 语义匹配选项点击
3. 搜索式：键入关键词 → 等待过滤 → 选首个匹配

策略 2 在"点击展开"后增加**展开态验证**（对齐本地浏览器自动化"动作后最便宜验证"
模式）：点击控件后重新 observe，按 selector 找到同一控件并读取其
`expanded`（来自 aria-expanded）。该验证只是"加速失败发现"的手段而非硬门槛——
即便没有 expanded 信号，仍会按现有逻辑尝试在弹层中找选项（部分组件不维护
aria-expanded 但选项已渲染），找到就继续。验证结果与选项匹配结果分类写入
FillResult.detail / 日志，供上层 retry_advice 获得更准确信号。
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


async def _refresh_and_find_options(
    driver: Driver, *, skip_index: int
) -> tuple[PageObservation, list[UIElement]]:
    """刷新感知（不截图、不滚动），返回可见候选选项元素。

    skip_index 用于排除触发控件自身（其 role 多为 combobox，本就不会命中
    _OPTION_ROLES，但部分站点把展开控件渲染为 button，此时需排除以免误选）。
    """
    obs: PageObservation = await driver.observe(with_screenshot=False, scroll_full=False)
    candidates = [
        e
        for e in obs.elements
        if e.visible and e.role in _OPTION_ROLES and e.label and e.index != skip_index
    ]
    return obs, candidates


async def _click_matched_option(
    driver: Driver, target: str, *, skip_index: int
) -> tuple[str, str] | None:
    """刷新感知，在可见候选元素中语义匹配并点击，返回 (选项文本, 级别)。

    供搜索式策略复用。无命中返回 None。
    """
    _obs, candidates = await _refresh_and_find_options(driver, skip_index=skip_index)
    hit = match_option(target, [e.label for e in candidates])
    if hit is None:
        return None
    text, level = hit
    chosen = next(e for e in candidates if e.label == text)
    await driver.click(chosen)
    return text, level


async def _verify_expanded(driver: Driver, selector: str) -> bool | None:
    """重新 observe，按 selector 找到同一控件并读取 expanded 状态。

    返回 True=已展开；False=明确收起（aria-expanded=false）；None=无该信号
    （元素未出现或 expanded 字段为 None）。observe 不截图、不滚动以保持轻量。
    """
    obs = await driver.observe(with_screenshot=False, scroll_full=False)
    for e in obs.elements:
        if e.selector == selector:
            return e.expanded
    return None


async def _try_match_option(
    driver: Driver, target: str, *, skip_index: int
) -> tuple[tuple[str, str] | None, list[UIElement]]:
    """刷新感知并尝试匹配选项；返回 (命中结果或 None, 候选元素列表)。

    候选列表用于在失败时区分"面板未展开（无候选）"与"面板已展开但选项未匹配"。
    """
    _obs, candidates = await _refresh_and_find_options(driver, skip_index=skip_index)
    hit = match_option(target, [e.label for e in candidates])
    if hit is None:
        return None, candidates
    text, level = hit
    chosen = next(e for e in candidates if e.label == text)
    await driver.click(chosen)
    return (text, level), candidates


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

        # 策略 2：点击展开 → 展开态验证 → 感知弹层 → 语义匹配
        panel_result = await self._try_panel_click(el, target, ctx)
        if panel_result is not None:
            return panel_result

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

    async def _try_panel_click(
        self, el: UIElement, target: str, ctx: ExecContext
    ) -> FillResult | None:
        """策略 2：点击展开控件 → 展开态验证 → 匹配弹层选项。

        面板已展开（el.expanded=True，如上轮已点开）时跳过触发器点击直接找选项——
        再点触发器只会把面板收起。展开态验证为"加速失败发现"的手段，非硬门槛：
        - expanded=True：面板确认展开，直接找选项。
        - expanded=False/None：补点一次（最多 1 次）后仍未有 expanded 信号时，
          降级按现有逻辑尝试找弹层选项（部分组件不维护 aria-expanded 但选项已渲染）。
        返回 None 表示本策略未命中，交回上层降级到策略 3。
        """
        expanded: bool | None = el.expanded
        extra_clicks = 0
        if expanded is True:
            log.info("dropdown.already_expanded", label=el.label, selector=el.selector)
        else:
            try:
                await ctx.driver.click(el)
            except Exception as exc:  # 展开失败直接落到搜索式
                log.info("dropdown.expand_failed", label=el.label, error=str(exc))
                return None

            # 展开态验证（动作后最便宜的验证）
            expanded = await _verify_expanded(ctx.driver, el.selector)
            if expanded is not True:
                log.info(
                    "dropdown.expand_no_signal",
                    label=el.label,
                    selector=el.selector,
                    expanded=expanded,
                )
                # 补点一次（最多 1 次）：某些控件首次点击被页面事件吞掉
                try:
                    await ctx.driver.click(el)
                    extra_clicks = 1
                except Exception as exc:  # 补点失败不再阻塞，降级找选项
                    log.info("dropdown.expand_retry_failed", label=el.label, error=str(exc))
                else:
                    expanded = await _verify_expanded(ctx.driver, el.selector)

        # 降级/正常路径统一在此找选项；候选列表用于失败时分类归因
        hit, candidates = await _try_match_option(ctx.driver, target, skip_index=el.index)
        if hit is not None:
            log.info(
                "dropdown.panel_hit",
                label=el.label,
                target=target,
                option=hit[0],
                level=hit[1],
                expanded_verified=expanded is True,
                extra_clicks=extra_clicks,
            )
            # detail 记录命中选项与展开验证结果（expanded_verified/补点次数），供审计
            return FillResult(
                ok=True,
                strategy="panel_click",
                detail=(
                    f"{hit[0]}({hit[1]}) "
                    f"[expanded_verified={expanded is True}, extra_clicks={extra_clicks}]"
                ),
            )

        # 选项未命中：区分"面板未展开（无候选且无 expanded 信号）"
        # 与"面板已展开但选项未匹配"，给上层 retry_advice 更准确信号
        panel_open_signal = expanded is True or bool(candidates)
        if not panel_open_signal:
            detail = (
                f"下拉[{el.label}]面板未展开（无 expanded 信号且未找到选项）: {target}"
            )
            log.warning(
                "dropdown.panel_not_open",
                label=el.label,
                selector=el.selector,
                target=target,
                expanded=expanded,
                extra_clicks=extra_clicks,
            )
        else:
            detail = (
                f"下拉[{el.label}]面板已展开但选项未匹配: {target} "
                f"(expanded={expanded}, 候选数={len(candidates)})"
            )
            log.warning(
                "dropdown.panel_open_no_match",
                label=el.label,
                selector=el.selector,
                target=target,
                expanded=expanded,
                candidates=[c.label for c in candidates[:10]],
            )
        return FillResult(ok=False, strategy="panel_click", detail=detail)
