"""Writer：开放性问题文案生成（FR-A8）。"""

from __future__ import annotations

import json

import structlog

from autooffer_core.agents.prompt_loader import render_prompt
from autooffer_core.agents.schemas import WriterOutput
from autooffer_core.llm.interfaces import ChatMessage, LLMClient
from autooffer_core.profile.schema import QAPair

log = structlog.get_logger(__name__)


class Writer:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def write(
        self,
        *,
        question: str,
        slice_values: dict[str, object],
        qa_bank: list[QAPair],
        max_chars: int = 300,
    ) -> WriterOutput:
        hits = [q for q in qa_bank if _similar(question, q.question)]
        qa_text = (
            "\n".join(f"Q: {q.question}\nA: {q.answer}" for q in hits) if hits else "(无命中)"
        )
        prompt = render_prompt(
            "writer.j2",
            question=question,
            slice_json=json.dumps(slice_values, ensure_ascii=False),
            qa_text=qa_text,
            max_chars=max_chars,
        )
        result = await self._llm.complete_json(
            [ChatMessage(role="user", content=prompt)], WriterOutput
        )
        assert isinstance(result, WriterOutput)
        log.info("writer.answered", question=question[:40], used_qa_bank=result.used_qa_bank)
        return result


def _similar(question: str, stored: str) -> bool:
    """极简相似判断：去空白后互相包含或字符重合率高。"""
    a = "".join(question.split())
    b = "".join(stored.split())
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    inter = len(set(a) & set(b))
    return inter / max(len(set(a)), len(set(b))) > 0.6
