"""动作历史与折叠（docs/03 §4.3）：最近 N 轮保留全文，更早轮折叠为一行摘要。"""

from __future__ import annotations


class HistoryLog:
    def __init__(self, *, keep_recent: int = 5) -> None:
        self._keep = keep_recent
        self._entries: list[str] = []

    def add(self, summary: str) -> None:
        self._entries.append(summary.strip().replace("\n", " ")[:300])

    @property
    def rounds(self) -> int:
        return len(self._entries)

    def to_text(self) -> str:
        if not self._entries:
            return "(首轮，无历史)"
        old = self._entries[: -self._keep] if len(self._entries) > self._keep else []
        recent = self._entries[-self._keep :]
        lines: list[str] = []
        if old:
            lines.append(f"[第1-{len(old)}轮已折叠] " + "；".join(e[:60] for e in old[-8:]))
        start = len(old) + 1
        for i, e in enumerate(recent):
            lines.append(f"第{start + i}轮: {e}")
        return "\n".join(lines)
