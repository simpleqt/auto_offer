"""控件处理器基础协议（docs/03 §3.2）。

每类复杂控件一个 Handler，实现 WidgetHandler 协议，内部按策略链降级。
执行上下文 ExecContext 只携带 Driver 与节奏开关；Handler 需要页面最新状态时
自行调用 driver.observe() 刷新（弹层选项感知、上传结果校验等）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from autooffer_core.drivers.base import Driver
from autooffer_core.perception.models import UIElement


class FillResult(BaseModel):
    """控件填写结果。

    ok=False 且 needs_human=True 表示策略链穷尽且无法自动处理（如附件无法达标），
    由上层转人工确认。
    """

    ok: bool
    strategy: str = ""
    """实际生效的策略名（审计用，如 "native_select" / "panel_click"）。"""
    detail: str = ""
    needs_human: bool = False
    panel_open: bool = False
    """失败时下拉面板是否已展开（有候选或 expanded 信号），供上层选择兜底策略。"""


@dataclass(slots=True)
class ExecContext:
    """控件处理执行上下文。档案数据一律由上层注入（见 docs/03 §1.3），本包不读取档案。"""

    driver: Driver
    humanize: bool = True
    extra: dict[str, str] = field(default_factory=dict)
    """调用方附加上下文（如任务 ID），仅用于日志透传。"""


@runtime_checkable
class WidgetHandler(Protocol):
    """复杂控件处理器协议。"""

    def match(self, el: UIElement) -> bool:
        """判断本 Handler 是否接管该元素。"""
        ...

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        """按策略链把 target 填入 el 指向的控件。

        target 为 Any 的理由：契约（docs/03 §3.2）如此定义——不同控件的目标类型
        不同（str / DateYM / DateRange / UploadTask），由 Handler 内部收窄校验。
        """
        ...
