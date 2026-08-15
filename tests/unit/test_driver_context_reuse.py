"""PlaywrightDriver 复用外部上下文（共享浏览器）/ CDP 连接的单元测试。

验证：绑定外部 context 时 close() 只关本页、不关闭共享上下文；
CDP 连接时复用当前页面、close 只断开不关闭用户浏览器。
全部用假对象，无需真实浏览器。
"""

from __future__ import annotations

import pytest

from autooffer_core.drivers.playwright_driver import PlaywrightDriver


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
