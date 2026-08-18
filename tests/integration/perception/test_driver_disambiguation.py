"""驱动层定位歧义消解集成测试（真实 Chromium）。

回归（真实站点 dahua.zhiye.com）：深层重复结构下 stableSelector 深度上限不足，
多个输入框共享同一选择器（"姓名"匹配 9 个元素）；_locate 的 .first 兜底挑中
错误元素后 fill 等待可编辑超时，两轮填写全灭（filled=0）。

修复链：
1. stableSelector 深度上限 6→12：深层重复结构下选择器恢复文档内唯一；
2. _locate 歧义时按 label 邻近度在页内挑选目标元素（人工找控件的方式）；
3. input_text 点击被浮层拦截时跳过点击直接 fill（fill 自带聚焦）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autooffer_core.drivers.playwright_driver import PlaywrightDriver

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "perception"
FORM_URL = (FIXTURES / "ambiguous_form.html").as_uri()


async def _form_inputs() -> tuple[PlaywrightDriver, dict[str, object]]:
    driver = PlaywrightDriver(headless=True, humanize=False)
    await driver.open(FORM_URL)
    obs = await driver.observe(with_screenshot=False, scroll_full=False)
    inputs = {e.label: e for e in obs.elements if e.role == "input"}
    return driver, inputs


@pytest.mark.asyncio
async def test_deep_duplicate_structure_selectors_unique() -> None:
    """4 个同构深链输入框的选择器必须互不相同（文档内唯一）。"""
    driver, inputs = await _form_inputs()
    try:
        assert len(inputs) >= 4
        sels = [e.selector for e in inputs.values()]
        assert len(set(sels)) == len(sels), f"选择器重复: {sels}"
    finally:
        await driver.close()


@pytest.mark.asyncio
async def test_label_disambiguation_picks_right_input() -> None:
    """宽选择器命中全部输入框时，按 label 邻近度挑中"姓名"而非 .first。"""
    driver, inputs = await _form_inputs()
    try:
        name = next(e for k, e in inputs.items() if "姓名" in k)
        email = next(e for k, e in inputs.items() if "邮箱" in k)
        wide_name = name.model_copy(update={"selector": "input"})  # 命中全部 4 个
        wide_email = email.model_copy(update={"selector": "input"})

        await driver.input_text(wide_name, "陈志谦")

        assert await driver.element_value(wide_name) == "陈志谦"  # 填进了姓名
        assert await driver.element_value(wide_email) == ""       # 未误伤邮箱
    finally:
        await driver.close()


@pytest.mark.asyncio
async def test_input_under_overlay_still_fills() -> None:
    """输入框被固定横幅遮挡（点击必超时）：跳过点击直接 fill 仍能填写。"""
    driver, inputs = await _form_inputs()
    try:
        name = next(e for k, e in inputs.items() if "姓名" in k)
        await driver.input_text(name, "陈志谦")  # 姓名框位于横幅覆盖区内
        assert await driver.element_value(name) == "陈志谦"
    finally:
        await driver.close()
