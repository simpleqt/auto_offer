"""仓储：同步 SQLAlchemy + asyncio.to_thread 包装（未装 aiosqlite，见 docs/06 W5）。

所有公开方法均为协程，避免在事件循环中阻塞（docs/05 §1.1）。
"""

from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from autooffer_server.db.models import (
    AgentEventRow,
    Base,
    LLMUsageRow,
    ModelEndpointRow,
    ProfileRow,
    RoleRoutingRow,
    TaskRow,
)


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class Repo:
    """单机单用户仓储。"""

    def __init__(self, db_path: Path | str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：to_thread 会在不同线程访问同一连接池
        self._engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self._engine)
        self._session = sessionmaker(self._engine, expire_on_commit=False)

    def _run(self, fn: Any) -> Any:
        with self._session() as s:
            result = fn(s)
            s.commit()
            return result

    # ---------- 档案 ----------

    async def save_profile(self, profile_id: str, label: str, payload: dict[str, Any]) -> None:
        def work(s: Session) -> None:
            row = s.get(ProfileRow, profile_id)
            text = json.dumps(payload, ensure_ascii=False)
            if row is None:
                s.add(ProfileRow(id=profile_id, label=label, payload=text))
            else:
                row.label = label
                row.payload = text
                row.updated_at = _now()

        await asyncio.to_thread(self._run, work)

    async def list_profiles(self) -> list[dict[str, Any]]:
        def work(s: Session) -> list[dict[str, Any]]:
            rows = s.scalars(select(ProfileRow)).all()
            return [
                {
                    "id": r.id,
                    "label": r.label,
                    "updated_at": r.updated_at,
                    "payload": json.loads(r.payload),
                }
                for r in rows
            ]

        result: list[dict[str, Any]] = await asyncio.to_thread(self._run, work)
        return result

    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        def work(s: Session) -> dict[str, Any] | None:
            row = s.get(ProfileRow, profile_id)
            return json.loads(row.payload) if row else None

        result: dict[str, Any] | None = await asyncio.to_thread(self._run, work)
        return result

    async def delete_profile(self, profile_id: str) -> bool:
        def work(s: Session) -> bool:
            row = s.get(ProfileRow, profile_id)
            if row is None:
                return False
            s.delete(row)
            return True

        result: bool = await asyncio.to_thread(self._run, work)
        return result

    # ---------- 模型端点 ----------

    async def save_endpoint(self, data: dict[str, Any]) -> None:
        def work(s: Session) -> None:
            row = s.get(ModelEndpointRow, data["id"])
            fields = {
                "name": data.get("name", ""),
                "base_url": data["base_url"],
                "model": data["model"],
                "key_hint": data.get("key_hint", ""),
                "temperature": float(data.get("temperature", 0.1)),
                "max_tokens": int(data.get("max_tokens", 4096)),
                "timeout_s": int(data.get("timeout_s", 600)),
                "max_concurrency": int(data.get("max_concurrency", 4)),
                "extra_body": json.dumps(data.get("extra_body", {}), ensure_ascii=False),
                "supports_vision": int(data.get("supports_vision", -1)),
                "is_default": int(data.get("is_default", 0)),
            }
            if row is None:
                s.add(ModelEndpointRow(id=data["id"], **fields))
            else:
                for k, v in fields.items():
                    setattr(row, k, v)
            if fields["is_default"]:
                for other in s.scalars(select(ModelEndpointRow)).all():
                    if other.id != data["id"]:
                        other.is_default = 0

        await asyncio.to_thread(self._run, work)

    async def list_endpoints(self) -> list[dict[str, Any]]:
        def work(s: Session) -> list[dict[str, Any]]:
            return [_endpoint_dict(r) for r in s.scalars(select(ModelEndpointRow)).all()]

        result: list[dict[str, Any]] = await asyncio.to_thread(self._run, work)
        return result

    async def get_endpoint(self, endpoint_id: str) -> dict[str, Any] | None:
        def work(s: Session) -> dict[str, Any] | None:
            row = s.get(ModelEndpointRow, endpoint_id)
            return _endpoint_dict(row) if row else None

        result: dict[str, Any] | None = await asyncio.to_thread(self._run, work)
        return result

    async def get_default_endpoint(self) -> dict[str, Any] | None:
        def work(s: Session) -> dict[str, Any] | None:
            row = s.scalars(
                select(ModelEndpointRow).where(ModelEndpointRow.is_default == 1)
            ).first()
            if row is None:  # 未显式设默认时取第一个
                row = s.scalars(select(ModelEndpointRow)).first()
            return _endpoint_dict(row) if row else None

        result: dict[str, Any] | None = await asyncio.to_thread(self._run, work)
        return result

    async def delete_endpoint(self, endpoint_id: str) -> bool:
        def work(s: Session) -> bool:
            row = s.get(ModelEndpointRow, endpoint_id)
            if row is None:
                return False
            s.delete(row)
            return True

        result: bool = await asyncio.to_thread(self._run, work)
        return result

    async def set_vision(self, endpoint_id: str, supports: bool | None) -> None:
        def work(s: Session) -> None:
            row = s.get(ModelEndpointRow, endpoint_id)
            if row is not None:
                row.supports_vision = -1 if supports is None else int(supports)

        await asyncio.to_thread(self._run, work)

    # ---------- 角色路由 ----------

    async def set_routing(self, mapping: dict[str, str]) -> None:
        def work(s: Session) -> None:
            s.execute(delete(RoleRoutingRow))
            for role, endpoint_id in mapping.items():
                s.add(RoleRoutingRow(role=role, endpoint_id=endpoint_id))

        await asyncio.to_thread(self._run, work)

    async def get_routing(self) -> dict[str, str]:
        def work(s: Session) -> dict[str, str]:
            return {r.role: r.endpoint_id for r in s.scalars(select(RoleRoutingRow)).all()}

        result: dict[str, str] = await asyncio.to_thread(self._run, work)
        return result

    # ---------- 任务 ----------

    async def create_task(self, task_id: str, url: str, profile_id: str) -> None:
        def work(s: Session) -> None:
            s.add(TaskRow(id=task_id, url=url, profile_id=profile_id, state="QUEUED"))

        await asyncio.to_thread(self._run, work)

    async def update_task(self, task_id: str, **fields: Any) -> None:
        def work(s: Session) -> None:
            row = s.get(TaskRow, task_id)
            if row is None:
                return
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = _now()

        await asyncio.to_thread(self._run, work)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        def work(s: Session) -> dict[str, Any] | None:
            row = s.get(TaskRow, task_id)
            return _task_dict(row) if row else None

        result: dict[str, Any] | None = await asyncio.to_thread(self._run, work)
        return result

    async def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        def work(s: Session) -> list[dict[str, Any]]:
            rows = s.scalars(
                select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit)
            ).all()
            return [_task_dict(r) for r in rows]

        result: list[dict[str, Any]] = await asyncio.to_thread(self._run, work)
        return result

    # ---------- 审计事件 ----------

    async def add_event(
        self, task_id: str, seq: int, kind: str, agent: str, summary: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        def work(s: Session) -> None:
            s.add(
                AgentEventRow(
                    task_id=task_id, seq=seq, kind=kind, agent=agent, summary=summary,
                    data=json.dumps(data or {}, ensure_ascii=False),
                )
            )

        await asyncio.to_thread(self._run, work)

    async def list_events(self, task_id: str, limit: int = 500) -> list[dict[str, Any]]:
        def work(s: Session) -> list[dict[str, Any]]:
            rows = s.scalars(
                select(AgentEventRow)
                .where(AgentEventRow.task_id == task_id)
                .order_by(AgentEventRow.seq_id)
                .limit(limit)
            ).all()
            return [
                {
                    "seq": r.seq, "kind": r.kind, "agent": r.agent,
                    "summary": r.summary, "data": json.loads(r.data),
                    "created_at": r.created_at,
                }
                for r in rows
            ]

        result: list[dict[str, Any]] = await asyncio.to_thread(self._run, work)
        return result

    # ---------- LLM 用量（FR-M5） ----------

    async def add_llm_usage(self, record: dict[str, Any]) -> None:
        """写入一条 LLM 调用记录（task_id / model / tokens / 时延 / 成败）。"""

        def work(s: Session) -> None:
            s.add(
                LLMUsageRow(
                    task_id=str(record.get("task_id", "")),
                    model=str(record.get("model", "")),
                    prompt_tokens=int(record.get("prompt_tokens", 0)),
                    completion_tokens=int(record.get("completion_tokens", 0)),
                    total_tokens=int(record.get("total_tokens", 0)),
                    latency_ms=int(record.get("latency_ms", 0)),
                    success=int(record.get("success", 1)),
                    error=str(record.get("error", "")),
                )
            )

        await asyncio.to_thread(self._run, work)

    async def aggregate_llm_usage(self) -> dict[str, Any]:
        """按模型与按任务聚合 token 用量、平均时延、失败率（FR-M5）。"""

        def work(s: Session) -> dict[str, Any]:
            rows = s.scalars(select(LLMUsageRow)).all()

            by_model: dict[str, dict[str, Any]] = {}
            by_task: dict[str, dict[str, Any]] = {}
            for r in rows:
                m = by_model.setdefault(
                    r.model,
                    {
                        "model": r.model,
                        "calls": 0,
                        "failed": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "total_latency_ms": 0,
                    },
                )
                t = by_task.setdefault(
                    r.task_id or "(非任务)",
                    {
                        "task_id": r.task_id,
                        "calls": 0,
                        "failed": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "total_latency_ms": 0,
                    },
                )
                for agg in (m, t):
                    agg["calls"] += 1
                    if not r.success:
                        agg["failed"] += 1
                    agg["prompt_tokens"] += r.prompt_tokens
                    agg["completion_tokens"] += r.completion_tokens
                    agg["total_tokens"] += r.total_tokens
                    agg["total_latency_ms"] += r.latency_ms

            def _finalize(rows_: dict[str, dict[str, Any]], key: str) -> list[dict[str, Any]]:
                out: list[dict[str, Any]] = []
                for agg in rows_.values():
                    calls = agg["calls"]
                    out.append(
                        {
                            key: agg[key],
                            "calls": calls,
                            "failed": agg["failed"],
                            "failure_rate": round(agg["failed"] / calls, 4) if calls else 0.0,
                            "prompt_tokens": agg["prompt_tokens"],
                            "completion_tokens": agg["completion_tokens"],
                            "total_tokens": agg["total_tokens"],
                            "avg_latency_ms": (
                                round(agg["total_latency_ms"] / calls) if calls else 0
                            ),
                        }
                    )
                return out

            return {
                "by_model": _finalize(by_model, "model"),
                "by_task": _finalize(by_task, "task_id"),
            }

        result: dict[str, Any] = await asyncio.to_thread(self._run, work)
        return result


def _endpoint_dict(row: ModelEndpointRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "base_url": row.base_url,
        "model": row.model,
        "key_hint": row.key_hint,
        "temperature": row.temperature,
        "max_tokens": row.max_tokens,
        "timeout_s": row.timeout_s,
        "max_concurrency": row.max_concurrency,
        "extra_body": json.loads(row.extra_body or "{}"),
        "supports_vision": None if row.supports_vision < 0 else bool(row.supports_vision),
        "is_default": bool(row.is_default),
    }


def _task_dict(row: TaskRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "url": row.url,
        "profile_id": row.profile_id,
        "state": row.state,
        "page_title": row.page_title,
        "report": json.loads(row.report) if row.report else None,
        "wait_reason": row.wait_reason,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
