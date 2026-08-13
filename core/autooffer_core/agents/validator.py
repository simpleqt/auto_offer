"""Validator：动作后回读校验与重试建议（docs/02 §2.1）。"""

from __future__ import annotations

import structlog

from autooffer_core.agents.prompt_loader import render_prompt
from autooffer_core.agents.schemas import ValidatorOutput
from autooffer_core.llm.interfaces import ChatMessage, LLMClient

log = structlog.get_logger(__name__)


class Validator:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def validate(
        self,
        *,
        goal: str,
        expected_text: str,
        readback_text: str,
    ) -> ValidatorOutput:
        prompt = render_prompt(
            "validator.j2",
            goal=goal,
            expected_text=expected_text or "(本轮无需要校验的填写动作)",
            readback_text=readback_text or "(无回读数据)",
        )
        result = await self._llm.complete_json(
            [ChatMessage(role="user", content=prompt)], ValidatorOutput
        )
        assert isinstance(result, ValidatorOutput)
        log.info(
            "validator.result",
            passed=result.passed,
            section_complete=result.section_complete,
            fields=len(result.field_results),
        )
        return result
