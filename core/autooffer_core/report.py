"""任务执行结果契约（docs/01 FR-A10）。

填写完成后生成的报告，供界面展示与人工审核；同时是审计数据源。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

FieldStatus = Literal["filled", "failed", "skipped", "pending_confirm"]


class FieldRecord(BaseModel):
    """单个表单字段的填写结果。"""

    label: str
    status: FieldStatus
    value: str | None = None
    """实际填入/回读的值（restricted 级字段不记录明文）。"""

    attempts: int = 1
    note: str | None = None
    """失败原因 / 待确认说明等。"""

    sensitive: bool = False
    """是否使用了 sensitive/restricted 级档案数据（敏感字段单独列出，见 docs/03 §1.1）。"""


class FillReport(BaseModel):
    """一次填写任务的最终报告。"""

    task_id: str
    url: str
    profile_id: str
    fields: list[FieldRecord] = []
    started_at: str = ""
    finished_at: str = ""
    total_llm_calls: int = 0
    total_tokens: int = 0
    note: str | None = None

    def counts(self) -> dict[FieldStatus, int]:
        """按状态统计字段数量。"""
        result: dict[FieldStatus, int] = {
            "filled": 0,
            "failed": 0,
            "skipped": 0,
            "pending_confirm": 0,
        }
        for f in self.fields:
            result[f.status] += 1
        return result
