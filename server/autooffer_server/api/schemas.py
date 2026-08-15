"""API 请求/响应模型。api_key 只入不出（响应一律用 key_hint 掩码）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EndpointIn(BaseModel):
    id: str
    name: str = ""
    base_url: str
    model: str
    api_key: str | None = None
    """新增/更新时传入；不回显。留空表示保留原有 key。"""

    temperature: float = 0.1
    max_tokens: int = 4096
    timeout_s: int = 600
    max_concurrency: int = 4
    extra_body: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class EndpointOut(BaseModel):
    id: str
    name: str
    base_url: str
    model: str
    key_hint: str
    temperature: float
    max_tokens: int
    timeout_s: int
    max_concurrency: int
    extra_body: dict[str, Any]
    supports_vision: bool | None
    is_default: bool


class RoutingIn(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)
    """角色 → 端点 id；未配置的角色回落默认端点。"""


class ProfileIn(BaseModel):
    payload: dict[str, Any]
    """完整 Profile 的 JSON。"""


class ProfileSummary(BaseModel):
    id: str
    label: str
    updated_at: str
    name: str = ""
    attachments: int = 0


class TaskIn(BaseModel):
    url: str
    profile_id: str
    options: dict[str, Any] = Field(default_factory=dict)


class TaskOut(BaseModel):
    id: str
    url: str
    profile_id: str
    state: str
    page_title: str = ""
    wait_reason: str = ""
    report: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""


class ApplicationStatusIn(BaseModel):
    status: str
    note: str | None = None


class UsageAggregate(BaseModel):
    """单条用量聚合（按模型或按任务）。"""

    calls: int = 0
    failed: int = 0
    failure_rate: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    avg_latency_ms: int = 0


class ModelUsage(UsageAggregate):
    model: str


class TaskUsage(UsageAggregate):
    task_id: str


class UsageReport(BaseModel):
    """模型调用统计（FR-M5）：按模型 + 按任务聚合。"""

    by_model: list[ModelUsage] = []
    by_task: list[TaskUsage] = []
