"""API 请求/响应模型。api_key 只入不出（响应一律用 key_hint 掩码）。"""

from __future__ import annotations

from typing import Any, Literal

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


class ApplicationReportIn(BaseModel):
    """插件填写完成后的投递记录上报。"""

    url: str
    profile_id: str = ""
    page_title: str = ""
    company: str = ""
    position: str = ""
    fields_filled: int = 0
    fields_failed: int = 0
    fields_pending: int = 0
    note: str | None = None


class LogsIn(BaseModel):
    """插件运行日志上报：条目写入本地 app.log（logger=extension），与 exe 日志同文件。"""

    entries: list[Any] = []
    """宽松类型：非字典/空消息条目由处理器跳过，不让上报方因格式被 422 拒绝。"""


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


class AppSettings(BaseModel):
    """应用设置（界面「设置」页）：浏览器连接模式与启动行为。"""

    browser_mode: Literal["managed", "cdp"] = "managed"
    """managed=软件自控持久浏览器；cdp=连接用户已有的 Chrome/Edge。"""

    cdp_endpoint: str = ""
    """browser_mode=cdp 时的远程调试端点，如 http://127.0.0.1:9222。"""

    minimize_on_startup: bool = False
    """主窗口启动后自动最小化。"""

    auto_submit: bool = False
    """全部步骤填写完成后自动点击提交按钮（默认关闭，提交由用户人工完成）。"""

    service_port: int = Field(default=8765, ge=1024, le=65535)
    """本地服务监听端口（默认 8765），端口冲突时可自行更换。

    修改后需重启软件生效；换端口后浏览器插件弹窗里的「服务地址」
    也要同步改成 http://127.0.0.1:<新端口>。
    """


class MappingFieldIn(BaseModel):
    """待映射的页面字段（仅标签/区块/选项文本，不含任何值）。"""

    label: str
    section: str | None = None
    options: list[str] = []


class MappingIn(BaseModel):
    profile_id: str
    fields: list[MappingFieldIn] = []


class MappingMatchOut(BaseModel):
    field_label: str
    profile_label: str
    confidence: float


class MappingOut(BaseModel):
    """AI 字段映射结果：页面标签 → 档案标签。"""

    matches: list[MappingMatchOut] = []


class OptionPickIn(BaseModel):
    """固定选项字段：页面选项 + 档案值（值会进 LLM，与简历解析同信任域）。"""

    label: str
    options: list[str] = []
    value: str = ""


class OptionMatchIn(BaseModel):
    picks: list[OptionPickIn] = []


class OptionChoiceOut(BaseModel):
    label: str
    option: str
    confidence: float


class OptionMatchOut(BaseModel):
    choices: list[OptionChoiceOut] = []
