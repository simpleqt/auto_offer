"""全局字段 Checklist（docs/02 §2.2）：跨区块/跨分页维护填写进度。"""

from __future__ import annotations

from pydantic import BaseModel

from autooffer_core.report import FieldRecord, FieldStatus


class ChecklistItem(BaseModel):
    label: str
    section_title: str = ""
    status: FieldStatus = "pending_confirm"
    value: str | None = None
    attempts: int = 0
    note: str | None = None
    sensitive: bool = False


class Checklist:
    """字段级进度表。键为 (区块标题, 字段 label)。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ChecklistItem] = {}

    def upsert(
        self,
        label: str,
        *,
        section_title: str = "",
        status: FieldStatus,
        value: str | None = None,
        note: str | None = None,
        sensitive: bool = False,
    ) -> None:
        key = (section_title, label)
        item = self._items.get(key)
        if item is None:
            item = ChecklistItem(label=label, section_title=section_title)
            self._items[key] = item
        item.attempts += 1
        item.status = status
        if value is not None:
            item.value = value
        if note is not None:
            item.note = note
        item.sensitive = item.sensitive or sensitive

    def counts(self) -> dict[FieldStatus, int]:
        out: dict[FieldStatus, int] = {
            "filled": 0, "failed": 0, "skipped": 0, "pending_confirm": 0,
        }
        for item in self._items.values():
            out[item.status] += 1
        return out

    def to_text(self) -> str:
        """给 Planner 的紧凑进度文本。"""
        if not self._items:
            return "(尚无记录)"
        lines = []
        for item in self._items.values():
            sec = f"[{item.section_title}] " if item.section_title else ""
            note = f" 备注:{item.note}" if item.note else ""
            lines.append(f"{sec}{item.label}: {item.status}{note}")
        return "\n".join(lines)

    def to_report_fields(self) -> list[FieldRecord]:
        return [
            FieldRecord(
                label=i.label,
                status=i.status,
                value=i.value,
                attempts=max(1, i.attempts),
                note=i.note,
                sensitive=i.sensitive,
            )
            for i in self._items.values()
        ]
