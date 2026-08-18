"""执行器"面板已展开禁止再点触发器"预检测试。

回归：自定义下拉点开面板后，Actor 下一轮原样重复裸 click 触发器 → 面板被
toggle 收起 → 再点再收起……死循环。预检在执行前拒绝该动作并指路选项元素。
"""

from __future__ import annotations

import pytest

from autooffer_core.actions.executor import ActionExecutor
from autooffer_core.actions.models import Action
from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.testing import FakeDriver


@pytest.mark.asyncio
async def test_click_on_expanded_trigger_rejected() -> None:
    el = UIElement(
        index=3, tag="div", role="combobox", label="类型",
        selector="#type", expanded=True, visible=True,
    )
    obs = PageObservation(url="u", title="t", elements=[el])
    driver = FakeDriver(obs)

    res = await ActionExecutor(driver).execute(
        Action(type="click", element_index=3, reason="点开类型下拉"), obs
    )

    assert res.status == "failed"
    assert "面板已展开" in res.detail
    # 被拒绝的动作不产生真实点击（避免 toggle 收起面板）
    assert ("click", 3) not in driver.calls


@pytest.mark.asyncio
async def test_click_on_collapsed_trigger_still_allowed() -> None:
    el = UIElement(
        index=3, tag="div", role="combobox", label="类型",
        selector="#type", expanded=False, visible=True,
    )
    obs = PageObservation(url="u", title="t", elements=[el])
    driver = FakeDriver(obs)

    res = await ActionExecutor(driver).execute(
        Action(type="click", element_index=3, reason="点开类型下拉"), obs
    )

    assert res.status == "ok"
    assert ("click", 3) in driver.calls
