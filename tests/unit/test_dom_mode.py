"""纯 DOM 无视觉模式的单元测试：状态标记渲染 + 默认零截图。"""

from __future__ import annotations

import pytest

from autooffer_core.actions.executor import ActionExecutor
from autooffer_core.actions.models import Action, ActionBatch
from autooffer_core.agents.prompt_loader import format_elements
from autooffer_core.agents.schemas import PlannerOutput
from autooffer_core.perception.models import PageObservation, SectionInfo, UIElement
from autooffer_core.runner import AgentRunner
from autooffer_core.testing import FakeDriver, ScriptedLLMClient, build_sample_profile


def make_el(**overrides: object) -> UIElement:
    defaults: dict[str, object] = {
        "index": 0, "tag": "input", "role": "input", "label": "字段", "selector": "#a",
    }
    defaults.update(overrides)
    return UIElement(**defaults)  # type: ignore[arg-type]


# ---------- 状态标记渲染（对齐 ARIA 快照模式） ----------

def test_format_elements_state_markers() -> None:
    text = format_elements([
        make_el(disabled=True),
        make_el(index=1, role="combobox", expanded=True, label="下拉"),
        make_el(index=2, readonly=True, label="只读字段"),
        make_el(index=3, label="普通字段"),
    ])
    lines = text.split("\n")
    assert "禁用" in lines[0]
    assert "已展开" in lines[1]
    assert "只读" in lines[2]
    assert "禁用" not in lines[3] and "只读" not in lines[3]


# ---------- 纯 DOM 模式：默认零截图 ----------

class _ObservedDriver(FakeDriver):
    """记录 observe 调用的 with_screenshot 参数。"""

    def __init__(self, observation: PageObservation) -> None:
        super().__init__(observation)
        self.screenshot_calls: list[bool] = []

    async def observe(
        self, *, with_screenshot: bool = True, scroll_full: bool = True
    ) -> PageObservation:
        self.screenshot_calls.append(with_screenshot)
        return await super().observe(with_screenshot=with_screenshot, scroll_full=scroll_full)


class _RoleRouter:
    """按角色返回各自的脚本客户端（避免队列串台）。"""

    def __init__(self, clients: dict[str, ScriptedLLMClient]) -> None:
        self._clients = clients

    def get(self, role: str) -> ScriptedLLMClient:
        return self._clients[role]

    def default(self) -> ScriptedLLMClient:
        return next(iter(self._clients.values()))


@pytest.mark.asyncio
async def test_runner_dom_only_no_screenshots_by_default() -> None:
    """默认 use_vision=False：全程 observe 不带截图（首轮/未知场景/翻页均不触发）。"""
    obs = PageObservation(
        url="https://example.com/apply",
        title="表单",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=0)],
        elements=[make_el()],
    )
    driver = _ObservedDriver(obs)
    planner = ScriptedLLMClient([
        PlannerOutput(
            decision="dispatch_section", next_section_id="s1", subtask_goal="填", reason="派发",
        ).model_dump_json(),
        PlannerOutput(decision="finish", done=True, reason="完成").model_dump_json(),
    ])
    actor = ScriptedLLMClient(['{"actions": [], "section_complete": true, "summary": "完成"}'])
    validator = ScriptedLLMClient(['{"passed": true, "section_complete": true}'])
    runner = AgentRunner(
        task_id="t", task_instruction="x", driver=driver,
        router=_RoleRouter({"planner": planner, "actor": actor, "validator": validator}),
        executor=ActionExecutor(driver), profile=build_sample_profile(),
    )
    await runner.run("https://example.com/apply")
    # 零截图：所有 observe 调用 with_screenshot 均为 False
    assert driver.screenshot_calls, "应至少调用过 observe"
    assert not any(driver.screenshot_calls), "纯 DOM 模式不应请求任何截图"


@pytest.mark.asyncio
async def test_executor_skips_disabled_and_readonly() -> None:
    """执行器预检：禁用元素不点击、只读元素不填写，返回失败说明。"""
    obs = PageObservation(
        url="https://x.com", title="t",
        elements=[
            make_el(disabled=True, label="禁用按钮", role="button"),
            make_el(index=1, readonly=True, label="只读框"),
        ],
    )
    driver = FakeDriver(obs)
    ex = ActionExecutor(driver)
    results = await ex.execute_batch(
        ActionBatch(actions=[
            Action(type="click", element_index=0, reason="点禁用"),
            Action(type="input_text", element_index=1, value="x", reason="填只读"),
        ]),
        obs,
    )
    assert results[0].status == "failed" and "禁用" in results[0].detail
    assert results[1].status == "failed" and "只读" in results[1].detail
    # 没有产生真实交互
    assert not driver.calls  # 只有 observe 不算；click/input 均未执行
