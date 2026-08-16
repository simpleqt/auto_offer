"""Planner：任务拆分、场景决策、进度管理（docs/02 §2.1）。"""

from __future__ import annotations

import structlog

from autooffer_core.agents.prompt_loader import (
    format_observation_overview,
    format_scenario,
    render_prompt,
)
from autooffer_core.agents.schemas import PlannerOutput
from autooffer_core.llm.interfaces import ChatMessage, LLMClient
from autooffer_core.perception.models import PageObservation

log = structlog.get_logger(__name__)


class Planner:
    def __init__(self, llm: LLMClient, *, prefill_threshold: float = 0.4) -> None:
        self._llm = llm
        self._prefill_threshold = prefill_threshold

    async def plan(
        self,
        *,
        task_instruction: str,
        observation: PageObservation,
        checklist_text: str,
        history_text: str,
        forced_verify: bool | None = None,
        done_sections_text: str = "",
    ) -> PlannerOutput:
        """forced_verify：是否提示进入核对模式。

        由 Runner 按"首轮观察"的预填比例判定并传入——智能体自己填过的字段
        不应在后续轮次触发核对模式；None 时退回按当前观察判定。
        done_sections_text：当前页面已完成区块列表（防止重复派发）。
        """
        if forced_verify is None:
            forced_verify = observation.scenario.prefilled_ratio >= self._prefill_threshold
        prompt = render_prompt(
            "planner.j2",
            task_instruction=task_instruction,
            url=observation.url,
            page_title=observation.title,
            scenario_text=format_scenario(observation.scenario),
            forced_mode=forced_verify,
            sections_text=format_observation_overview(observation),
            checklist_text=checklist_text,
            history_text=history_text,
            done_sections_text=done_sections_text,
        )
        images: list[bytes] = []
        if self._llm.supports_vision and observation.screenshot_som:
            images = [observation.screenshot_som]
        result = await self._llm.complete_json(
            [ChatMessage(role="user", content=prompt, images=images)], PlannerOutput
        )
        assert isinstance(result, PlannerOutput)
        log.info(
            "planner.decision",
            decision=result.decision,
            strategy=result.strategy,
            next_section=result.next_section_id,
            done=result.done,
        )
        return result
