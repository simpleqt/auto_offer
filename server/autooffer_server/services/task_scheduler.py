"""任务队列与状态机（docs/03 §5.3）。

状态：QUEUED → RUNNING ⇄ WAITING_HUMAN → AWAITING_REVIEW → DONE / FAILED / CANCELLED
并发上限默认 2；实际执行体通过 TaskRunner 协议注入，测试可用假 runner。
人工介入：任务挂起等待 resume（服务层不阻塞事件循环）。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Literal, Protocol

import structlog

from autooffer_server.db.repo import Repo
from autooffer_server.services.events import EventBus

log = structlog.get_logger(__name__)

TaskState = Literal[
    "QUEUED", "RUNNING", "WAITING_HUMAN", "AWAITING_REVIEW", "DONE", "FAILED", "CANCELLED"
]

_ACTIVE_STATES = {"QUEUED", "RUNNING", "WAITING_HUMAN"}


class TaskRunner(Protocol):
    """任务执行体。

    on_event：执行过程中的事件回调（step/state/report）。
    human_gate：需要人工处理时调用，等待其返回表示用户已处理。
    返回 FillReport 的字典形式。
    """

    async def run(
        self,
        *,
        task_id: str,
        url: str,
        profile_id: str,
        on_event: Any,
        human_gate: Any,
    ) -> dict[str, Any]: ...


class TaskScheduler:
    def __init__(
        self,
        repo: Repo,
        bus: EventBus,
        runner: TaskRunner,
        *,
        max_concurrent: int = 2,
    ) -> None:
        self._repo = repo
        self._bus = bus
        self._runner = runner
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._resume_gates: dict[str, asyncio.Event] = {}
        # 审计写入走单写入者队列：避免每个事件派生一个任务造成任务风暴与线程池争用
        self._audit_q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=2000)
        self._audit_writer: asyncio.Task[None] | None = None

    # ---------- 审计写入 ----------

    def _ensure_audit_writer(self) -> None:
        if self._audit_writer is None or self._audit_writer.done():
            self._audit_writer = asyncio.create_task(self._audit_loop())

    async def _audit_loop(self) -> None:
        while True:
            task_id, payload = await self._audit_q.get()
            try:
                await self._repo.add_event(
                    task_id, int(payload.get("seq", 0)), str(payload.get("kind", "step")),
                    str(payload.get("agent", "")), str(payload.get("summary", "")),
                    payload.get("data"),
                )
            except Exception as exc:  # 审计失败不影响任务执行
                log.warning("scheduler.audit_write_failed", task_id=task_id, error=str(exc))
            finally:
                self._audit_q.task_done()

    def _enqueue_audit(self, task_id: str, payload: dict[str, Any]) -> None:
        self._ensure_audit_writer()
        try:
            self._audit_q.put_nowait((task_id, payload))
        except asyncio.QueueFull:
            log.warning("scheduler.audit_queue_full", task_id=task_id)

    # ---------- 生命周期 ----------

    async def submit(self, task_id: str, url: str, profile_id: str) -> None:
        await self._repo.create_task(task_id, url, profile_id)
        self._tasks[task_id] = asyncio.create_task(self._execute(task_id, url, profile_id))
        log.info("scheduler.submitted", task_id=task_id, url=url)

    async def _execute(self, task_id: str, url: str, profile_id: str) -> None:
        async with self._sem:
            if await self._is_cancelled(task_id):
                return
            await self._set_state(task_id, "RUNNING")
            seq = 0

            def on_event(event: Any) -> None:
                nonlocal seq
                seq += 1
                payload = _event_payload(event, seq)
                self._bus.publish(task_id, payload)
                self._enqueue_audit(task_id, payload)

            async def human_gate(reason: str) -> None:
                await self._set_state(task_id, "WAITING_HUMAN", wait_reason=reason)
                gate = self._resume_gates.setdefault(task_id, asyncio.Event())
                gate.clear()
                await gate.wait()
                await self._set_state(task_id, "RUNNING", wait_reason="")

            try:
                report = await self._runner.run(
                    task_id=task_id, url=url, profile_id=profile_id,
                    on_event=on_event, human_gate=human_gate,
                )
            except asyncio.CancelledError:
                await self._set_state(task_id, "CANCELLED")
                raise
            except Exception as exc:
                log.error("scheduler.task_failed", task_id=task_id, error=str(exc))
                await self._set_state(task_id, "FAILED", wait_reason=str(exc)[:500])
                return

            import json

            await self._repo.update_task(
                task_id,
                report=json.dumps(report, ensure_ascii=False),
                page_title=str(report.get("page_title", "")),
            )
            await self._set_state(task_id, "AWAITING_REVIEW")

    # ---------- 控制 ----------

    async def resume(self, task_id: str) -> bool:
        """人工处理完成后继续执行。"""
        gate = self._resume_gates.get(task_id)
        if gate is None:
            return False
        gate.set()
        return True

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.done():
            row = await self._repo.get_task(task_id)
            if row is not None and row["state"] in _ACTIVE_STATES:
                await self._set_state(task_id, "CANCELLED")
                return True
            return False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await self._set_state(task_id, "CANCELLED")
        return True

    async def shutdown(self) -> None:
        """优雅关停：取消在跑任务，并尽力把审计队列写完（软件退出时调用）。"""
        for task_id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                log.info("scheduler.cancelled_on_shutdown", task_id=task_id)
        self._tasks.clear()
        if self._audit_writer is not None and not self._audit_writer.done():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._audit_q.join(), timeout=5)
            self._audit_writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._audit_writer
            self._audit_writer = None

    async def drain_audit(self, timeout_s: float = 5.0) -> None:
        """等待审计队列写完（测试用：确保事件已入库可查）。"""
        if self._audit_writer is None:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._audit_q.join(), timeout=timeout_s)

    async def wait(self, task_id: str, timeout_s: float = 30.0) -> None:
        """等待任务结束（测试与 CLI 用）。"""
        task = self._tasks.get(task_id)
        if task is None:
            return
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), timeout_s)

    # ---------- 内部 ----------

    async def _set_state(
        self, task_id: str, state: TaskState, *, wait_reason: str | None = None
    ) -> None:
        fields: dict[str, Any] = {"state": state}
        if wait_reason is not None:
            fields["wait_reason"] = wait_reason
        await self._repo.update_task(task_id, **fields)
        self._bus.publish(
            task_id,
            {"type": "state", "kind": "state", "seq": 0, "value": state,
             "reason": wait_reason or ""},
        )
        log.info("scheduler.state", task_id=task_id, state=state)

    async def _is_cancelled(self, task_id: str) -> bool:
        row = await self._repo.get_task(task_id)
        return row is not None and row["state"] == "CANCELLED"


def _event_payload(event: Any, seq: int) -> dict[str, Any]:
    """AgentEvent（或任意带 kind/summary 的对象/字典）→ WS 事件字典。"""
    if isinstance(event, dict):
        data = dict(event)
        data.setdefault("seq", seq)
        data.setdefault("kind", "step")
        return data
    return {
        "seq": getattr(event, "seq", seq),
        "kind": getattr(event, "kind", "step"),
        "agent": getattr(event, "agent", ""),
        "summary": getattr(event, "summary", ""),
        "data": getattr(event, "data", {}) or {},
    }
