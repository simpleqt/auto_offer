"""PlaywrightDriver 复用外部上下文（共享浏览器）/ CDP 连接的单元测试。

验证：绑定外部 context 时 close() 只关本页、不关闭共享上下文；
CDP 连接时复用当前页面、close 只断开不关闭用户浏览器。
全部用假对象，无需真实浏览器。
"""

from __future__ import annotations

import pytest

from autooffer_core.drivers.playwright_driver import PlaywrightDriver
from autooffer_core.errors import DriverError
from autooffer_core.perception.models import UIElement


class _FakePage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def goto(self, url: str, **kwargs: object) -> None:
        self.url = url


class _FakeContext:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_existing_context_reused_and_page_closed_but_context_kept() -> None:
    ctx = _FakeContext()
    driver = PlaywrightDriver(headless=False, existing_context=ctx)  # type: ignore[arg-type]

    # 首次 _ensure_page 复用外部 context，不新建浏览器
    page = await driver._ensure_page()
    assert page is ctx.page
    assert driver._pw is None  # 未启动 Playwright
    assert driver._browser is None

    # close 只关本页，保留共享 context（登录态）
    await driver.close()
    assert ctx.page.closed is True
    assert ctx.closed is False


@pytest.mark.asyncio
async def test_existing_context_returns_same_page_on_repeated_ensure() -> None:
    ctx = _FakeContext()
    driver = PlaywrightDriver(headless=False, existing_context=ctx)  # type: ignore[arg-type]
    first = await driver._ensure_page()
    second = await driver._ensure_page()
    assert first is second


def test_cdp_driver_close_does_not_close_user_browser() -> None:
    """CDP 模式下 close 只断开 Playwright，不触碰用户浏览器（无 close 调用）。"""
    driver = PlaywrightDriver(headless=False, cdp_endpoint="http://127.0.0.1:9222")
    # close 不应抛错（此时尚未真正连接，_pw 为 None）
    import asyncio

    asyncio.run(driver.close())
    assert driver._pw is None
    assert driver._browser is None


# ---------------------------------------------------------------------------
# _locate 唯一性纪律 & element_state 状态查询 单测
#
# 对齐本地浏览器自动化纪律：动手前确认唯一性；定位失败不盲目重试同一选择器。
# 全部用假对象模拟 Locator（count / filter / first / get_attribute / is_checked），
# 不启动真实浏览器。
# ---------------------------------------------------------------------------


class _MockLocator:
    """最小可用的 Locator 假对象：支撑 _locate 与 element_state 所需调用。

    - count(): 返回预设命中数
    - filter(visible=...): 返回"收紧后"的 locator（可见命中数可单独配置）
    - first: 属性，返回自身（单元素占位；测试只校验返回值身份与日志/异常）
    - get_attribute(name): 按预设 attrs 字典返回
    - is_checked(): 按预设 checked 标志返回
    """

    def __init__(
        self,
        *,
        count_value: int = 0,
        narrowed: _MockLocator | None = None,
        attrs: dict[str, str | None] | None = None,
        checked: bool = False,
    ) -> None:
        self._count_value = count_value
        self._narrowed = narrowed  # filter(visible=True) 的返回值
        self._attrs = attrs or {}
        self._checked = checked
        # 记录 filter 是否被调用，供断言"是否尝试收紧"
        self.filter_calls: list[bool] = []

    async def count(self) -> int:
        return self._count_value

    def filter(self, *, visible: bool | None = None) -> _MockLocator:
        # 仅模拟 visible 关键字（_locate 唯一用法）
        self.filter_calls.append(visible)
        return self._narrowed if self._narrowed is not None else self

    @property
    def first(self) -> _MockLocator:
        return self

    async def get_attribute(self, name: str, **kwargs: object) -> str | None:
        return self._attrs.get(name)

    async def is_checked(self, **kwargs: object) -> bool:
        return self._checked


class _MockPage:
    """最小 Page 假对象：locator() 返回预设 _MockLocator。"""

    def __init__(self, base: _MockLocator) -> None:
        self._base = base
        # _locate 会读 self._page 是否为 None，并调用 scope.locator(selector)
        self.url = "about:blank"

    def locator(self, selector: str) -> _MockLocator:
        return self._base


def _make_driver_with_page(page: _MockPage) -> PlaywrightDriver:
    """构造 driver 并直接注入假 page（跳过 _ensure_page 的真实浏览器启动）。"""
    driver = PlaywrightDriver(headless=False, humanize=False)
    driver._page = page  # type: ignore[assignment]
    return driver


def _make_el(selector: str = "button#submit") -> UIElement:
    return UIElement(index=0, tag="button", role="button", label="提交", selector=selector)


@pytest.mark.asyncio
async def test_locate_count_zero_raises_drivererror_with_reobserve_message() -> None:
    """count==0：选择器已失效，应抛 DriverError 且消息含"重新观察"。"""
    page = _MockPage(_MockLocator(count_value=0))
    driver = _make_driver_with_page(page)

    with pytest.raises(DriverError) as exc_info:
        await driver._locate(_make_el("button#gone"))
    assert "重新观察" in str(exc_info.value)
    assert "button#gone" in str(exc_info.value)


@pytest.mark.asyncio
async def test_locate_count_one_returns_first() -> None:
    """count==1：唯一命中，正常返回 locator（first）。"""
    loc = _MockLocator(count_value=1)
    page = _MockPage(loc)
    driver = _make_driver_with_page(page)

    got = await driver._locate(_make_el())
    # first 返回自身；唯一命中时不应触发 filter 收紧
    assert got is loc
    assert loc.filter_calls == []


@pytest.mark.asyncio
async def test_locate_count_gt_one_warns_and_returns_narrowed_first() -> None:
    """count>1：记录 warning 并返回收紧后首个；收紧到 1 时不回退原 .first。"""
    # 基础命中 3 个，收紧后仅 1 个可见 -> 返回 narrowed.first，但仍按规格记 warning
    narrowed = _MockLocator(count_value=1)
    base = _MockLocator(count_value=3, narrowed=narrowed)
    page = _MockPage(base)
    driver = _make_driver_with_page(page)

    got = await driver._locate(_make_el())
    assert base.filter_calls == [True]  # 确实尝试了 visible 收紧
    assert got is narrowed  # 返回收紧后的首个


@pytest.mark.asyncio
async def test_locate_count_gt_one_still_ambiguous_warns_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收紧后仍 >1：记 structlog warning（含 selector 与 count）并回退 .first。"""
    # 收紧后仍 2 个：filter 返回 narrowed2，其 count=2
    narrowed2 = _MockLocator(count_value=2)
    base = _MockLocator(count_value=4, narrowed=narrowed2)
    page = _MockPage(base)
    driver = _make_driver_with_page(page)

    # structlog 默认不走 stdlib logging，caplog 捕不到；用假 logger 记录 warning
    # 调用以验证"仍歧义即留痕"（不依赖 structlog 内部路由，跨环境稳定）。
    warnings: list[tuple[str, dict[str, object]]] = []

    class _FakeLogger:
        def warning(self, event: str, **kw: object) -> None:
            warnings.append((event, kw))

    import autooffer_core.drivers.playwright_driver as drv_mod

    monkeypatch.setattr(drv_mod, "log", _FakeLogger())

    got = await driver._locate(_make_el("input[name=city]"))

    # 回退到收紧后的首个（narrowed2.first 即 narrowed2 自身）
    assert got is narrowed2
    # 确有且仅有一条 warning，事件名与字段齐全（含 selector 与 count）
    assert len(warnings) == 1
    event, kw = warnings[0]
    assert event == "driver.locate_ambiguous"
    assert kw["selector"] == "input[name=city]"
    assert kw["count"] == 4
    assert kw["narrowed_count"] == 2


@pytest.mark.asyncio
async def test_element_state_reads_three_fields() -> None:
    """element_state 读 checked/disabled/expanded 三字段并按约定归一化。"""
    loc = _MockLocator(
        count_value=1,
        attrs={
            "aria-checked": "true",
            "aria-disabled": "true",
            "aria-expanded": "false",
        },
        checked=True,
    )
    page = _MockPage(loc)
    driver = _make_driver_with_page(page)

    state = await driver.element_state(_make_el())
    assert state["checked"] == "true"
    assert state["disabled"] is True
    assert state["expanded"] is False


@pytest.mark.asyncio
async def test_element_state_expanded_missing_returns_none() -> None:
    """aria-expanded 缺失时 expanded 为 None；disabled 走原生属性回退。"""
    loc = _MockLocator(
        count_value=1,
        attrs={
            # 无 aria-disabled -> 走原生 disabled（存在即禁用）
            "disabled": "",
            # 无 aria-expanded -> None
        },
        checked=False,
    )
    page = _MockPage(loc)
    driver = _make_driver_with_page(page)

    state = await driver.element_state(_make_el())
    assert state["checked"] == ""
    assert state["disabled"] is True  # 原生 disabled 属性存在（"" 也算）
    assert state["expanded"] is None


@pytest.mark.asyncio
async def test_element_state_disabled_false_when_neither_attr_present() -> None:
    """既无 aria-disabled 也无原生 disabled：disabled 为 False。"""
    loc = _MockLocator(count_value=1, attrs={}, checked=False)
    page = _MockPage(loc)
    driver = _make_driver_with_page(page)

    state = await driver.element_state(_make_el())
    assert state["disabled"] is False
    assert state["expanded"] is None

