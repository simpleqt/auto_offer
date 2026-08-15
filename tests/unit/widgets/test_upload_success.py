"""上传成功信号检测（_await_success）单元测试。

回归点：站点把「解析完成/上传成功」放在页面正文文本（body_text）而非表单元素里，
轮询必须扫描 body_text，且用 scroll_full=False 避免反复滚动页面。
"""

from __future__ import annotations

import pytest

from autooffer_core.perception.models import PageObservation
from autooffer_core.testing.fakes import FakeDriver
from autooffer_core.widgets.base import ExecContext
from autooffer_core.widgets.upload import UploadHandler


def _obs(body_text: str) -> PageObservation:
    return PageObservation(url="about:blank", title="", body_text=body_text)


@pytest.mark.asyncio
async def test_await_success_detects_body_text_signal() -> None:
    """成功提示出现在正文文本（而非表单元素）里，应能被识别。"""
    driver = FakeDriver(_obs("正在解析… 解析完成（张三_简历.pdf），请核对以下信息"))
    handler = UploadHandler(timeout_s=2.0, poll_s=0.01)
    ctx = ExecContext(driver=driver)

    ok = await handler._await_success(ctx, "张三_简历.pdf")
    assert ok is True


@pytest.mark.asyncio
async def test_await_success_detects_success_hint_without_stem() -> None:
    """只有「上传成功」类提示、无文件名，也应命中。"""
    driver = FakeDriver(_obs("简历上传成功"))
    handler = UploadHandler(timeout_s=2.0, poll_s=0.01)
    ctx = ExecContext(driver=driver)

    ok = await handler._await_success(ctx, "resume.pdf")
    assert ok is True


@pytest.mark.asyncio
async def test_await_success_times_out_without_signal() -> None:
    """无成功信号时超时返回 False。"""
    driver = FakeDriver(_obs("页面加载中…"))
    handler = UploadHandler(timeout_s=0.1, poll_s=0.01)
    ctx = ExecContext(driver=driver)

    ok = await handler._await_success(ctx, "resume.pdf")
    assert ok is False


@pytest.mark.asyncio
async def test_await_success_polls_without_scrolling() -> None:
    """轮询应使用 scroll_full=False（不滚动页面）。"""
    driver = FakeDriver(_obs("解析完成"))
    handler = UploadHandler(timeout_s=0.1, poll_s=0.01)
    ctx = ExecContext(driver=driver)

    await handler._await_success(ctx, "resume.pdf")

    observes = [c for c in driver.calls if c[0] == "observe"]
    assert observes, "应至少执行一次 observe"
    for call in observes:
        # call = ("observe", with_screenshot, scroll_full)
        assert call[1] is False  # with_screenshot=False
        assert call[2] is False  # scroll_full=False
