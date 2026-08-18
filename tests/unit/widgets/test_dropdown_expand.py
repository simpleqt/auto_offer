"""下拉控件"点击展开 → 展开态验证"单元测试。

回归点：自定义下拉（combobox）策略链原先点击后不验证面板是否真展开就去找选项，
找不到即超时重试——真实站点"性别"类自定义下拉反复失败的根因之一。现新增
元素级 expanded 状态（UIElement.expanded，来自 aria-expanded）后的展开态验证：
- expanded=True：面板确认展开，应成功选中。
- expanded 恒为 None 但选项已渲染：降级路径仍能选中（验证非硬门槛）。
- 选项不匹配：失败 detail 应区分"面板未展开"与"面板已展开但选项未匹配"。

FakeDriver.observation 可由测试直接替换以推进"页面变化"（点击展开后面板出现）。
"""

from __future__ import annotations

import pytest

from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.testing.fakes import FakeDriver
from autooffer_core.widgets.base import ExecContext
from autooffer_core.widgets.dropdown import DropdownHandler


def _combobox(
    *,
    index: int = 0,
    label: str = "性别",
    selector: str = "#gender",
    expanded: bool | None = None,
) -> UIElement:
    """构造一个自定义下拉（combobox）触发控件。"""
    return UIElement(
        index=index,
        tag="div",
        role="combobox",
        label=label,
        selector=selector,
        expanded=expanded,
    )


def _option(label: str, *, index: int) -> UIElement:
    """构造一个弹层选项元素（感知层把 li/[role=option] 提取为 custom）。"""
    return UIElement(
        index=index,
        tag="li",
        role="custom",
        label=label,
        selector=f"#opt-{index}",
        visible=True,
    )


@pytest.mark.asyncio
async def test_panel_click_expanded_true_then_select_success() -> None:
    """点击后 observation 替换为 expanded=True 的同 selector 控件 + 选项 → 成功选中。

    覆盖 happy path：展开态验证命中（expanded=True），随后语义匹配并点击选项成功。
    应记录 expanded_verified=True 且无补点。
    """
    trigger = _combobox(expanded=None)  # 点击前尚未展开
    initial = PageObservation(url="about:blank", title="", elements=[trigger])
    driver = FakeDriver(initial)
    ctx = ExecContext(driver=driver)

    # 点击后页面"变化"：同一 selector 控件 expanded=True，且弹层渲染了选项
    expanded_trigger = _combobox(expanded=True)
    options = [_option("男", index=1), _option("女", index=2)]
    after_click = PageObservation(
        url="about:blank", title="", elements=[expanded_trigger, *options]
    )

    # FakeDriver.observe 每次返回当前 observation；在首次 verify 后切换到"展开后"快照。
    # 这里直接置为展开后快照：首次点击→verify→命中 True，无需补点。
    driver.set_observation(after_click)

    result = await DropdownHandler().fill(trigger, "男", ctx)

    assert result.ok is True
    assert result.strategy == "panel_click"
    # 命中"男"，且展开验证为真、无补点
    assert "男" in result.detail
    assert "expanded_verified=True" in result.detail
    assert "extra_clicks=0" in result.detail
    # 末尾应记录对选项元素的点击
    assert any(c == ("click", 1) for c in driver.calls)


@pytest.mark.asyncio
async def test_panel_click_expanded_none_degraded_still_selects() -> None:
    """expanded 恒为 None（组件不维护 aria-expanded）但选项已渲染 → 降级仍能选中。

    覆盖降级路径：验证非硬门槛。点击后无 expanded 信号 → 补点一次 → 仍无信号 →
    按现有逻辑找弹层选项，找到即继续。最终成功选中，但 expanded_verified=False。
    """
    trigger = _combobox(expanded=None)
    initial = PageObservation(url="about:blank", title="", elements=[trigger])
    driver = FakeDriver(initial)
    ctx = ExecContext(driver=driver)

    # 展开后快照：控件 expanded 仍为 None（不维护该属性），但选项已渲染
    same_trigger = _combobox(expanded=None)
    options = [_option("男", index=1), _option("女", index=2)]
    after_click = PageObservation(
        url="about:blank", title="", elements=[same_trigger, *options]
    )
    driver.set_observation(after_click)

    result = await DropdownHandler().fill(trigger, "女", ctx)

    assert result.ok is True
    assert result.strategy == "panel_click"
    assert "女" in result.detail
    # 无 expanded 信号 → 验证未通过，但降级成功
    assert "expanded_verified=False" in result.detail
    # expanded 非 True 触发了一次补点（最多 1 次）
    assert "extra_clicks=1" in result.detail
    # 触发控件自身被点击：初始 1 次 + 补点 1 次 = 2 次（index=0）
    trigger_clicks = [c for c in driver.calls if c == ("click", 0)]
    assert len(trigger_clicks) == 2


@pytest.mark.asyncio
async def test_panel_click_no_match_panel_not_open() -> None:
    """选项不匹配且无候选、无 expanded 信号 → 失败 detail 含"面板未展开"。

    覆盖失败分类一：面板确实没展开（点击没生效），感知层既无 expanded=True 也找不到
    任何弹层选项。detail 应归因为"面板未展开"，给上层 retry_advice"重试展开"的信号。
    """
    trigger = _combobox(expanded=None)
    initial = PageObservation(url="about:blank", title="", elements=[trigger])
    driver = FakeDriver(initial)
    ctx = ExecContext(driver=driver)

    # 展开后快照：控件仍 expanded=None，且没有任何弹层选项渲染
    same_trigger = _combobox(expanded=None)
    after_click = PageObservation(url="about:blank", title="", elements=[same_trigger])
    driver.set_observation(after_click)

    result = await DropdownHandler().fill(trigger, "男", ctx)

    assert result.ok is False
    assert result.strategy == "panel_click"
    assert "面板未展开" in result.detail
    assert "选项未匹配" not in result.detail


@pytest.mark.asyncio
async def test_panel_click_no_match_panel_open_with_options() -> None:
    """面板已展开（有候选选项）但目标不在其中 → 失败 detail 含"面板已展开但选项未匹配"。

    覆盖失败分类二：展开验证或候选存在表明面板已展开，但语义匹配未命中目标值。
    detail 应归因为"面板已展开但选项未匹配"，与"面板未展开"区分，避免上层盲目重试展开。
    """
    trigger = _combobox(expanded=None)
    initial = PageObservation(url="about:blank", title="", elements=[trigger])
    driver = FakeDriver(initial)
    ctx = ExecContext(driver=driver)

    # 展开后：控件 expanded=None（无信号），但弹层渲染了与目标不同的选项
    same_trigger = _combobox(expanded=None)
    options = [_option("保密", index=1), _option("不愿透露", index=2)]
    after_click = PageObservation(
        url="about:blank", title="", elements=[same_trigger, *options]
    )
    driver.set_observation(after_click)

    result = await DropdownHandler().fill(trigger, "男", ctx)

    assert result.ok is False
    assert result.strategy == "panel_click"
    assert "面板已展开但选项未匹配" in result.detail
    assert "面板未展开" not in result.detail


@pytest.mark.asyncio
async def test_panel_click_expanded_false_triggers_retry_then_true() -> None:
    """首次 expanded=False（明确收起）→ 补点一次后 expanded=True → 成功选中。

    覆盖补点救回场景：首次点击被页面事件吞掉（expanded 仍 False），补点后面板才真展开。
    验证补点机制能在"明确收起"情况下挽回。
    """
    trigger = _combobox(expanded=None)
    initial = PageObservation(url="about:blank", title="", elements=[trigger])
    driver = FakeDriver(initial)
    ctx = ExecContext(driver=driver)

    # 通过脚本化 observation 模拟"补点后才展开"：
    # 前 1 次 observe（首次 verify）返回 expanded=False；
    # 第 2 次起（补点后 verify + 找选项）返回 expanded=True + 选项。
    closed_trigger = _combobox(expanded=False)
    obs_closed = PageObservation(url="about:blank", title="", elements=[closed_trigger])

    open_trigger = _combobox(expanded=True)
    options = [_option("男", index=1), _option("女", index=2)]
    obs_open = PageObservation(
        url="about:blank", title="", elements=[open_trigger, *options]
    )

    original_observe = driver.observe
    state = {"n": 0}

    async def scripted_observe(*, with_screenshot: bool = True, scroll_full: bool = True):  # type: ignore[no-untyped-def]
        state["n"] += 1
        # 第 1 次 observe = 首次 verify（expanded=False）；之后返回展开后快照
        if state["n"] == 1:
            return obs_closed
        driver.set_observation(obs_open)
        return await original_observe(with_screenshot=with_screenshot, scroll_full=scroll_full)

    driver.observe = scripted_observe  # type: ignore[assignment]

    result = await DropdownHandler().fill(trigger, "男", ctx)

    assert result.ok is True
    assert result.strategy == "panel_click"
    assert "男" in result.detail
    # 补点救回：最终展开验证为真，补点 1 次
    assert "expanded_verified=True" in result.detail
    assert "extra_clicks=1" in result.detail


@pytest.mark.asyncio
async def test_text_click_fallback_when_options_not_extracted() -> None:
    """面板已展开但选项未被感知层提取（嵌套/传送门渲染）→ 文本锚定点击兜底。

    回归（真实站点）：北森系表单下拉面板类名不在提取提示内、选项带嵌套 span，
    面板点开后元素表里没有任何选项 → 策略链走驱动的 click_visible_text 兜底。
    """
    from autooffer_core.perception.models import UIElement as El

    class TextClickDriver(FakeDriver):
        def __init__(self, obs: PageObservation) -> None:
            super().__init__(obs)
            self.text_clicks: list[list[str]] = []

        async def click_visible_text(self, texts: list[str]) -> str | None:
            self.text_clicks.append(texts)
            return texts[0]

    trigger = _combobox(index=0, label="性别")
    other = El(index=1, tag="button", role="button", label="下一步",
               selector="#next", visible=True)
    # 面板展开后的观察里只有触发器与无关按钮——选项完全未被提取
    after_click = PageObservation(url="about:blank", title="", elements=[trigger, other])
    driver = TextClickDriver(after_click)
    ctx = ExecContext(driver=driver)

    result = await DropdownHandler().fill(trigger, "男", ctx)

    assert result.ok is True
    assert result.strategy == "text_click"
    assert driver.text_clicks and driver.text_clicks[0][0] == "男"


@pytest.mark.asyncio
async def test_no_text_click_when_panel_not_open() -> None:
    """面板未展开（无候选无信号）时不做文本锚定——避免误点页面其它同文本元素。"""

    class TextClickDriver(FakeDriver):
        def __init__(self, obs: PageObservation) -> None:
            super().__init__(obs)
            self.text_clicks: list[list[str]] = []

        async def click_visible_text(self, texts: list[str]) -> str | None:
            self.text_clicks.append(texts)
            return None

    trigger = _combobox(index=0, label="性别")
    # 点击后页面毫无变化：无候选、无 expanded 信号 → 面板未展开
    same = PageObservation(url="about:blank", title="", elements=[trigger])
    driver = TextClickDriver(same)
    ctx = ExecContext(driver=driver)

    result = await DropdownHandler().fill(trigger, "男", ctx)

    assert result.ok is False
    assert "面板未展开" in result.detail
    assert driver.text_clicks == []  # 未启用兜底


@pytest.mark.asyncio
async def test_already_expanded_skips_trigger_click() -> None:
    """控件已展开（上轮点开）时跳过触发器点击直接选选项。

    回归：面板已展开再点触发器只会把它收起。el.expanded=True 时应直接进入
    选项匹配，不产生对触发器的点击。
    """
    trigger = _combobox(expanded=True)
    options = [_option("全职", index=1), _option("实习", index=2)]
    driver = FakeDriver(
        PageObservation(url="about:blank", title="", elements=[trigger, *options])
    )
    ctx = ExecContext(driver=driver)

    result = await DropdownHandler().fill(trigger, "全职", ctx)

    assert result.ok is True
    assert result.strategy == "panel_click"
    # 未点击触发器，直接点击了选项元素
    assert ("click", 0) not in driver.calls
    assert any(c == ("click", 1) for c in driver.calls)
    assert "expanded_verified=True" in result.detail
    assert "extra_clicks=0" in result.detail


@pytest.mark.asyncio
async def test_panel_click_observe_uses_lightweight_flags() -> None:
    """展开验证与找选项的 observe 应使用 with_screenshot=False、scroll_full=False。

    覆盖"动作后最便宜验证"约定：不截图、不滚动以保持轻量，避免反复滚动页面。
    """
    trigger = _combobox(expanded=None)
    initial = PageObservation(url="about:blank", title="", elements=[trigger])
    driver = FakeDriver(initial)
    ctx = ExecContext(driver=driver)

    open_trigger = _combobox(expanded=True)
    options = [_option("男", index=1)]
    driver.set_observation(
        PageObservation(url="about:blank", title="", elements=[open_trigger, *options])
    )

    await DropdownHandler().fill(trigger, "男", ctx)

    observes = [c for c in driver.calls if c[0] == "observe"]
    assert observes, "应至少执行一次 observe"
    for call in observes:
        # call = ("observe", with_screenshot, scroll_full)
        assert call[1] is False  # with_screenshot=False
        assert call[2] is False  # scroll_full=False
