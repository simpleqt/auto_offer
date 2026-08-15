"""SQLAlchemy ORM 模型（docs/03 §5.4）。

api_key 不入库：只存 keyring 引用与掩码提示（docs/05 §5 安全规范）。
"""

from __future__ import annotations

import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class ProfileRow(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    payload: Mapped[str] = mapped_column(Text)
    """Profile 的 JSON 序列化。"""

    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now)


class ModelEndpointRow(Base):
    __tablename__ = "model_endpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    base_url: Mapped[str] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(128))
    key_hint: Mapped[str] = mapped_column(String(64), default="")
    """api_key 掩码提示（如 sk-***7f8a），真实值在系统密钥库。"""

    temperature: Mapped[float] = mapped_column(default=0.1)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    timeout_s: Mapped[int] = mapped_column(Integer, default=600)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=4)
    extra_body: Mapped[str] = mapped_column(Text, default="{}")
    supports_vision: Mapped[int] = mapped_column(Integer, default=-1)
    """-1 未探测 / 0 不支持 / 1 支持。"""

    is_default: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class RoleRoutingRow(Base):
    __tablename__ = "model_routing"

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(String(64))


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(1024))
    profile_id: Mapped[str] = mapped_column(String(64), default="")
    state: Mapped[str] = mapped_column(String(32), default="QUEUED")
    page_title: Mapped[str] = mapped_column(String(256), default="")
    report: Mapped[str] = mapped_column(Text, default="")
    """FillReport 的 JSON（完成后写入）。"""

    wait_reason: Mapped[str] = mapped_column(Text, default="")
    """WAITING_HUMAN 时给用户的说明。"""

    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now)


class AgentEventRow(Base):
    __tablename__ = "agent_events"

    seq_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16), default="step")
    agent: Mapped[str] = mapped_column(String(32), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class LLMUsageRow(Base):
    """LLM 调用用量记录（FR-M5 数据源，docs/03 §5.4）。"""

    __tablename__ = "llm_usage"

    seq_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
