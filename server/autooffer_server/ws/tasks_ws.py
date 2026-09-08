"""任务事件 WebSocket（docs/03 §5.2）：/ws/tasks/{task_id}。

连接建立后先回放已入库的历史事件（便于界面中途接入），再持续推送新事件。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = structlog.get_logger(__name__)

ws_router = APIRouter()

_HEARTBEAT_S = 20.0


@ws_router.websocket("/ws/tasks/{task_id}")
async def task_events_ws(websocket: WebSocket, task_id: str) -> None:
    ctx: Any = websocket.app.state.ctx
    await websocket.accept()
    queue = ctx.bus.subscribe(task_id)
    log.info("ws.connected", task_id=task_id)
    try:
        # 历史回放（先订阅再回放：两步之间产生的事件会同时入队与入库，
        # 记住已回放的 seq，推送阶段跳过——客户端不收到重复事件）
        history = await ctx.repo.list_events(task_id)
        replayed_seqs = {int(e.get("seq") or 0) for e in history}
        for event in history:
            await websocket.send_json({"type": event["kind"], **event})
        row = await ctx.repo.get_task(task_id)
        if row is not None:
            await websocket.send_json(
                {"type": "state", "value": row["state"], "reason": row["wait_reason"]}
            )

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_S)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            if int(event.get("seq") or 0) in replayed_seqs:
                continue
            await websocket.send_json({"type": event.get("kind", "step"), **event})
    except WebSocketDisconnect:
        log.info("ws.disconnected", task_id=task_id)
    finally:
        ctx.bus.unsubscribe(task_id, queue)
        with contextlib.suppress(RuntimeError):
            await websocket.close()
