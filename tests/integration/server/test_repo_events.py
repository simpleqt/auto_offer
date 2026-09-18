"""list_events 截断语义回归：超限时保留最新而非最旧。

曾按 seq 升序直接 limit，>500 条的任务回放只能看到最老一段，
最新事件既不在回放里也不在订阅队列里——中段黑洞。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from autooffer_server.db.repo import Repo


def test_list_events_keeps_newest_on_truncation(tmp_path: Path) -> None:
    repo = Repo(tmp_path / "tasks.db")
    for i in range(1, 7):
        asyncio.run(repo.add_event("t1", i, "step", "actor", f"事件{i}"))

    rows = asyncio.run(repo.list_events("t1", limit=3))
    assert [r["summary"] for r in rows] == ["事件4", "事件5", "事件6"]

    # 未超限时仍是全量升序，不受降序取尾影响
    rows_all = asyncio.run(repo.list_events("t1"))
    assert [r["summary"] for r in rows_all] == [f"事件{i}" for i in range(1, 7)]
