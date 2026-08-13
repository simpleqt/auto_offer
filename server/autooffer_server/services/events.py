"""任务事件总线（docs/03 §5.2）：调度器产生事件，WebSocket 连接订阅。

内存实现（单机单进程）；每个订阅者一个队列，慢订阅者不阻塞生产者。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_QUEUE_MAX = 500


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subs.setdefault(task_id, []).append(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        queues = self._subs.get(task_id)
        if not queues:
            return
        if q in queues:
            queues.remove(q)
        if not queues:
            self._subs.pop(task_id, None)

    def publish(self, task_id: str, event: dict[str, Any]) -> None:
        """向该任务的所有订阅者投递事件；队列满时丢弃最旧事件避免阻塞。"""
        for q in self._subs.get(task_id, []):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - 竞态兜底
                    pass
            q.put_nowait(event)

    def subscriber_count(self, task_id: str) -> int:
        return len(self._subs.get(task_id, []))
