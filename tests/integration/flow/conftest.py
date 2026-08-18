"""全链路流程测试公共设施：真实 Chromium + 真实 Runner/执行器/控件处理器 +
脚本化 Planner + 按 label 动态解析编号的假 Actor。

不依赖真实 LLM 端点：Planner 决策序列脚本化；Actor 动作从提示词元素表中按
label 解析 element_index——翻页/添加条目/展开面板导致编号漂移时依然稳定。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest_asyncio
from pydantic import BaseModel

from autooffer_core.actions.executor import ActionExecutor
from autooffer_core.actions.models import Action, ActionBatch
from autooffer_core.drivers.playwright_driver import PlaywrightDriver
from autooffer_core.llm.interfaces import LLMClient, LLMResponse, Role
from autooffer_core.runner import AgentRunner
from autooffer_core.testing import ScriptedLLMClient, build_sample_profile

FLOW_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "flow"

_ELEMENT_LINE = re.compile(r"^#(\d+) (\S+) (\S+)")


def flow_url(name: str) -> str:
    return (FLOW_DIR / name).as_uri()


def parse_elements(messages: list[Any]) -> dict[str, int]:
    """从提示词元素表解析 label → element_index 映射。"""
    table: dict[str, int] = {}
    for msg in messages:
        content = getattr(msg, "content", "") or ""
        for line in content.splitlines():
            m = _ELEMENT_LINE.match(line.strip())
            if m:
                table.setdefault(m.group(3), int(m.group(1)))
    return table


class LabelDrivenActorClient:
    """假 Actor：按轮次脚本输出动作，元素编号按 label 实时解析。

    每轮脚本形如：
        {"actions": [{"label": "姓名", "type": "input_text", "value": "陈志谦"},
                      {"label": "性别", "type": "select_option", "value": "男"}],
         "complete": True, "summary": "填写基本信息"}
    label 在当前元素表中不存在时直接抛错（测试失败原因可见）。
    """

    supports_vision = False

    def __init__(self, rounds: list[dict[str, Any]]) -> None:
        self._rounds = rounds
        self._cursor = 0
        self.calls = 0

    async def complete(self, messages: list[Any]) -> LLMResponse:
        raise AssertionError("Actor 走 complete_json 路径，不应调用 complete")

    async def complete_json(self, messages: list[Any], schema: type[BaseModel]) -> BaseModel:
        self.calls += 1
        rnd = self._rounds[min(self._cursor, len(self._rounds) - 1)]
        self._cursor += 1
        table = parse_elements(messages)
        actions: list[Action] = []
        for step in rnd["actions"]:
            label = step["label"]
            if label not in table:
                raise AssertionError(
                    f"元素表中不存在 label={label!r}（现有: {sorted(table)}）"
                )
            actions.append(
                Action(
                    type=step["type"],
                    element_index=table[label],
                    value=step.get("value"),
                    reason=f"{step['type']} {label}",
                )
            )
        return ActionBatch(
            actions=actions,
            section_complete=bool(rnd.get("complete", True)),
            summary=rnd.get("summary", ""),
        )


class FlowRouter:
    """按角色返回预置客户端（planner/validator 脚本化，actor label 驱动）。"""

    def __init__(self, planner: LLMClient, actor: LLMClient, validator: LLMClient) -> None:
        self._clients: dict[Role, LLMClient] = {
            "planner": planner, "actor": actor, "validator": validator,
        }

    def get(self, role: Role) -> LLMClient:
        return self._clients[role]

    def default(self) -> LLMClient:
        return next(iter(self._clients.values()))


@pytest_asyncio.fixture
async def flow_driver() -> AsyncIterator[PlaywrightDriver]:
    driver = PlaywrightDriver(headless=True, humanize=False)
    yield driver
    await driver.close()


def build_flow_runner(
    driver: PlaywrightDriver,
    *,
    planner_script: list[BaseModel],
    actor_rounds: list[dict[str, Any]],
    events: list[Any],
) -> AgentRunner:
    """装配全链路 Runner：真驱动 + 真执行器 + 脚本化 LLM。"""
    return AgentRunner(
        task_id="flow-test",
        task_instruction="根据档案填写简历表单，不要上传文件",
        driver=driver,
        router=FlowRouter(
            planner=ScriptedLLMClient(list(planner_script)),
            actor=LabelDrivenActorClient(actor_rounds),
            validator=ScriptedLLMClient([]),
        ),
        executor=ActionExecutor(driver, humanize=False),
        profile=build_sample_profile(),
        on_event=events.append,
    )
