"""PlaywrightDriver 复用外部上下文（共享浏览器）的单元测试。

验证：绑定外部 context 时 close() 只关本页、不关闭共享上下文；
不绑定外部 context 时行为不变（整体释放）。全部用假对象，无需真实浏览器。
"""

from __future__ import annotations

import pytest

from autooffer_core.drivers.playwright_driver import PlaywrightDriver


class _FakePage:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


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
