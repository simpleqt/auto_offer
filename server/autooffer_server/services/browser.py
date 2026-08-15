"""桌面模式共享浏览器：跨任务复用同一持久上下文，保留登录态避免重复登录。

问题背景：每个任务若各自 launch 一个新浏览器/临时上下文，cookie 不共享，
用户每次投递都要重新登录。本模块在服务生命周期内维护一个共享的持久上下文
（launch_persistent_context，profile 落在数据目录 browser_profile/），
每个任务通过 new_driver 拿到一个绑定到该上下文的驱动（新建一个 page），
任务结束后只关闭自己的 page，共享上下文与登录态保留到软件退出。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from playwright.async_api import BrowserContext, Playwright, async_playwright

from autooffer_core.drivers.playwright_driver import PlaywrightDriver

log = structlog.get_logger(__name__)


class SharedBrowser:
    """懒加载的共享持久浏览器。并发安全：首次启动用锁单飞。"""

    def __init__(self, user_data_dir: Path | str, *, headless: bool = False) -> None:
        self._user_data_dir = Path(user_data_dir)
        self._headless = headless
        self._pw: Playwright | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    async def new_driver(self) -> PlaywrightDriver:
        """返回一个绑定到共享上下文的驱动（每任务一个 page）。"""
        context = await self._ensure_context()
        return PlaywrightDriver(headless=self._headless, existing_context=context)

    async def _ensure_context(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        async with self._lock:
            if self._context is not None:
                return self._context
            self._user_data_dir.mkdir(parents=True, exist_ok=True)
            self._pw = await async_playwright().start()
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self._user_data_dir),
                headless=self._headless,
                viewport={"width": 1280, "height": 900},
            )
            log.info(
                "browser.shared_started",
                profile=str(self._user_data_dir),
                headless=self._headless,
            )
            return self._context

    async def close(self) -> None:
        """软件退出时关闭共享浏览器并释放登录态 profile 锁。"""
        if self._context is not None:
            await self._context.close()
        if self._pw is not None:
            await self._pw.stop()
        self._context = None
        self._pw = None
