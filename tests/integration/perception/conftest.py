"""感知模块集成测试公共夹具：真实 Chromium 加载本地静态 HTML。"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from playwright.async_api import Page, async_playwright

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "perception"


def fixture_url(name: str) -> str:
    return (FIXTURES_DIR / name).as_uri()


@pytest_asyncio.fixture
async def page() -> AsyncIterator[Page]:
    async with async_playwright() as p:
        # file:// 场景下访问同源 iframe 的 contentDocument 需要放开本地文件访问
        browser = await p.chromium.launch(args=["--allow-file-access-from-files"])
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        pg = await context.new_page()
        yield pg
        await browser.close()
