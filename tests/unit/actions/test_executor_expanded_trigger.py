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


@pytest.mark.asyncio
async def test_batch_continues_after_single_action_failure() -> None:
    """单动作失败不中断整批：后续动作继续执行，失败记为 failed 结果。

    回归（真实站点）：一个日历控件导航失败（ActionError）曾把整批动作全部
    炸掉，页面上只留下先执行的姓名和电话。
    """
    from autooffer_core.actions.models import ActionBatch

    obs = PageObservation(
        url="u", title="t",
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#a"),
            UIElement(index=1, tag="input", role="input", label="邮箱", selector="#b"),
        ],
    )
    driver = FakeDriver(obs)
    batch = ActionBatch(actions=[
        Action(type="input_text", element_index=0, value="张三", reason="填姓名"),
        Action(type="input_text", element_index=99, value="x", reason="元素不存在"),
        Action(type="input_text", element_index=1, value="a@b.com", reason="填邮箱"),
    ])

    results = await ActionExecutor(driver).execute_batch(batch, obs)

    assert [r.status for r in results] == ["ok", "failed", "ok"]
    assert "不在当前观察中" in results[1].detail
    assert driver.values[0] == "张三"   # 失败前的动作生效
    assert driver.values[1] == "a@b.com"  # 失败后的动作未被连坐
