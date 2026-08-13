"""动作执行器（docs/03 §3.1/§3.3）。

接收 Action/ActionBatch，把 element_index 映射到当前 PageObservation 中元素的
selector，经 Driver 执行；click 执行前先过敏感动作门禁（FR-A11）。
复杂控件（下拉/日期/区间/上传/单选复选/富文本）委托 WidgetRegistry 的 Handler。
模型层只接触 element_index，index → selector 的映射只发生在本包内部。
执行失败抛 ActionError 并带动作与元素上下文。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import structlog
from pydantic import BaseModel

from autooffer_core.actions.guard import SensitiveActionGuard
from autooffer_core.actions.models import Action, ActionBatch
from autooffer_core.drivers.base import Driver
from autooffer_core.errors import ActionError
from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.widgets.base import ExecContext, FillResult
from autooffer_core.widgets.daterange import DateRangeHandler
from autooffer_core.widgets.registry import WidgetRegistry, default_registry
from autooffer_core.widgets.upload import UploadHandler, UploadTask, parse_attachment_spec

log = structlog.get_logger(__name__)

ExecStatus = Literal["ok", "needs_human", "skipped", "delegated"]


class ExecResult(BaseModel):
    """单动作执行结果（审计事件流数据源）。"""

    action_type: str
    status: ExecStatus
    element_index: int | None = None
    detail: str = ""
    strategy: str = ""


class ActionExecutor:
    """动作执行器。

    attachments: attachment_label → 本机文件路径 的映射，由上层（Runner）从档案
    注入；本包不读取档案（docs/03 §1.3 按需注入原则）。
    """

    def __init__(
        self,
        driver: Driver,
        *,
        registry: WidgetRegistry | None = None,
        guard: SensitiveActionGuard | None = None,
        attachments: Mapping[str, str] | None = None,
        humanize: bool = True,
    ) -> None:
        self._driver = driver
        self._registry = registry or default_registry()
        self._guard = guard or SensitiveActionGuard()
        self._attachments = dict(attachments or {})
        self._humanize = humanize
        self._date_range = DateRangeHandler()
        self._upload = UploadHandler()

    # ---------- 入口 ----------

    async def execute(self, action: Action, observation: PageObservation) -> ExecResult:
        """执行单个动作；失败抛 ActionError（带动作与元素上下文）。"""
        log.info("action.exec", action_type=action.type, element_index=action.element_index,
                 reason=action.reason)
        try:
            return await self._dispatch(action, observation)
        except ActionError:
            raise
        except Exception as exc:
            raise ActionError(
                f"动作执行失败: {action.type} (元素 {action.element_index}, {action.reason}): {exc}"
            ) from exc

    async def execute_batch(
        self, batch: ActionBatch, observation: PageObservation
    ) -> list[ExecResult]:
        """顺序执行一批动作；遇 needs_human 中断（后续动作依赖人工结论）。"""
        results: list[ExecResult] = []
        for action in batch.actions:
            res = await self.execute(action, observation)
            results.append(res)
            if res.status == "needs_human":
                log.info("action.batch_interrupted", reason=res.detail)
                break
        return results

    # ---------- 分发 ----------

    async def _dispatch(self, action: Action, observation: PageObservation) -> ExecResult:
        t = action.type
        if t in ("done", "ask_user", "request_profile", "skip_field"):
            status: ExecStatus = "needs_human" if t == "ask_user" else (
                "skipped" if t == "skip_field" else "delegated"
            )
            return ExecResult(
                action_type=t, status=status, element_index=action.element_index,
                detail=action.reason,
            )

        if t == "scroll":
            has_num = action.value is not None and action.value.lstrip("-").isdigit()
            delta = int(action.value) if has_num and action.value else 600
            await self._driver.scroll(delta)
            return ExecResult(action_type=t, status="ok", detail=str(delta))
        if t == "press_key":
            key = action.value or "Enter"
            await self._driver.press_key(key)
            return ExecResult(action_type=t, status="ok", detail=key)
        if t == "wait":
            seconds = float(action.value) if action.value else 1.0
            await self._driver.wait(seconds)
            return ExecResult(action_type=t, status="ok", detail=f"{seconds}s")

        el = self._resolve(action, observation)
        ctx = ExecContext(driver=self._driver, humanize=self._humanize)

        if t == "input_text":
            if action.value is None:
                raise ActionError(f"input_text 缺少 value (元素[{el.index}]{el.label})")
            if el.role == "richtext":
                return await self._via_handler(el, action.value, ctx, t)
            await self._driver.input_text(el, action.value, humanize=self._humanize)
            return ExecResult(action_type=t, status="ok", element_index=el.index)

        if t == "click":
            hit = self._guard.check(action, el)
            if hit is not None:
                log.info("action.guarded", element_index=el.index, word=hit, label=el.label)
                return ExecResult(
                    action_type=t, status="needs_human", element_index=el.index,
                    detail=f"敏感动作待人工确认（命中'{hit}'）: {el.label}",
                )
            if el.role in ("radio", "checkbox") and action.value:
                return await self._via_handler(el, action.value, ctx, t)
            await self._driver.click(el)
            return ExecResult(action_type=t, status="ok", element_index=el.index)

        if t == "select_option":
            if action.value is None:
                raise ActionError(f"select_option 缺少 value (元素[{el.index}]{el.label})")
            return await self._via_handler(el, action.value, ctx, t)

        if t == "set_date":
            if action.date is None:
                raise ActionError(f"set_date 缺少 date (元素[{el.index}]{el.label})")
            return await self._via_handler(el, action.date, ctx, t)

        if t == "set_date_range":
            if action.date_range is None:
                raise ActionError(f"set_date_range 缺少 date_range (元素[{el.index}]{el.label})")
            res = await self._date_range.fill(el, action.date_range, ctx)
            return self._from_fill(t, el, res)

        if t == "upload_file":
            path = self._resolve_attachment(action)
            spec = parse_attachment_spec(el.accept, el.label)
            res = await self._upload.fill(el, UploadTask(path=path, spec=spec), ctx)
            return self._from_fill(t, el, res)

        raise ActionError(f"未知动作类型: {t}")

    # ---------- 内部 ----------

    @staticmethod
    def _resolve(action: Action, observation: PageObservation) -> UIElement:
        """element_index → 当前观察中的元素（模型层不接触 selector）。"""
        if action.element_index is None:
            raise ActionError(f"动作 {action.type} 缺少 element_index")
        for el in observation.elements:
            if el.index == action.element_index:
                return el
        raise ActionError(
            f"元素编号 {action.element_index} 不在当前观察中"
            f"（共 {len(observation.elements)} 个元素，动作 {action.type}: {action.reason}）"
        )

    def _resolve_attachment(self, action: Action) -> str:
        label = action.attachment_label
        if not label:
            raise ActionError("upload_file 缺少 attachment_label")
        path = self._attachments.get(label)
        if path is None:
            raise ActionError(
                f"档案中未找到附件标签: {label}（可用: {sorted(self._attachments)}）"
            )
        return path

    async def _via_handler(
        self, el: UIElement, target: object, ctx: ExecContext, action_type: str
    ) -> ExecResult:
        handler = self._registry.handler_for(el)
        if handler is None:
            raise ActionError(f"无控件处理器接管: role={el.role} (元素[{el.index}]{el.label})")
        res = await handler.fill(el, target, ctx)
        return self._from_fill(action_type, el, res)

    @staticmethod
    def _from_fill(action_type: str, el: UIElement, res: FillResult) -> ExecResult:
        if res.ok:
            return ExecResult(
                action_type=action_type, status="ok", element_index=el.index,
                detail=res.detail, strategy=res.strategy,
            )
        if res.needs_human:
            return ExecResult(
                action_type=action_type, status="needs_human", element_index=el.index,
                detail=res.detail, strategy=res.strategy,
            )
        raise ActionError(f"控件填写失败 (元素[{el.index}]{el.label}): {res.detail}")
