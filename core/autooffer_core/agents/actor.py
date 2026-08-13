"""Actor：区块子任务内的动作决策（docs/02 §2.1）。"""

from __future__ import annotations

import json

import structlog

from autooffer_core.actions.models import ActionBatch
from autooffer_core.agents.prompt_loader import format_elements, render_prompt
from autooffer_core.agents.schemas import FlowStrategy
from autooffer_core.llm.interfaces import ChatMessage, LLMClient
from autooffer_core.perception.models import PageObservation, UIElement

log = structlog.get_logger(__name__)

_MODE_TEXT: dict[FlowStrategy, str] = {
    "fill": "正常填写（fill）",
    "verify_and_fix": "核对修正（verify_and_fix）：只纠错误、补空缺，一致的跳过",
    "locate_apply_entry": "定位申请入口（locate_apply_entry）：找到申请/投递按钮并点击进入表单",
}


class Actor:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def act(
        self,
        *,
        goal: str,
        mode: FlowStrategy,
        observation: PageObservation,
        section_elements: list[UIElement],
        catalog: str,
        slice_values: dict[str, object],
        extra_profile: dict[str, object] | None,
        history_text: str,
        retry_advice: str | None = None,
    ) -> ActionBatch:
        prompt = render_prompt(
            "actor.j2",
            goal=goal,
            mode=mode,
            mode_text=_MODE_TEXT[mode],
            retry_advice=retry_advice,
            catalog=catalog,
            slice_json=json.dumps(slice_values, ensure_ascii=False),
            extra_profile_json=(
                json.dumps(extra_profile, ensure_ascii=False) if extra_profile else None
            ),
            elements_text=format_elements(section_elements),
            history_text=history_text,
        )
        images: list[bytes] = []
        if self._llm.supports_vision and observation.screenshot_som:
            images = [observation.screenshot_som]
        result = await self._llm.complete_json(
            [ChatMessage(role="user", content=prompt, images=images)], ActionBatch
        )
        assert isinstance(result, ActionBatch)
        log.info(
            "actor.batch",
            actions=len(result.actions),
            section_complete=result.section_complete,
            summary=result.summary[:80],
        )
        return result
