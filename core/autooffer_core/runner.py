"""AgentRunner：感知 → Planner → Actor → 执行 → Validator 的任务状态机（docs/02 §2.2）。

护栏：最大步数、区块重试上限、token 预算；超限安全终止并产出部分报告。
状态：RUNNING / WAITING_HUMAN / AWAITING_REVIEW / DONE / FAILED。
人工介入通过 human_gate 回调闭环（CLI 阻塞等待输入；服务层挂起任务等待 resume）。
"""

from __future__ import annotations

import datetime
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

import structlog
from pydantic import BaseModel

from autooffer_core.actions.models import Action, ActionBatch
from autooffer_core.agents.actor import Actor
from autooffer_core.agents.planner import Planner
from autooffer_core.agents.schemas import FlowStrategy, PlannerOutput
from autooffer_core.agents.validator import Validator
from autooffer_core.drivers.base import Driver
from autooffer_core.errors import ActionError, AutoOfferError, LLMError
from autooffer_core.llm.interfaces import ModelRouter
from autooffer_core.memory.checklist import Checklist
from autooffer_core.memory.history import HistoryLog
from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.profile.resolver import ProfileResolver
from autooffer_core.profile.schema import Profile
from autooffer_core.report import FillReport

log = structlog.get_logger(__name__)

RunState = Literal["RUNNING", "WAITING_HUMAN", "AWAITING_REVIEW", "DONE", "FAILED"]


class ExecOutcome(Protocol):
    """执行器单动作结果的最小结构（对齐 actions.executor.ExecResult）。"""

    action_type: str
    status: str
    element_index: int | None
    detail: str


class ExecutorLike(Protocol):
    async def execute_batch(
        self, batch: ActionBatch, observation: PageObservation
    ) -> list[Any]: ...


class AgentEvent(BaseModel):
    seq: int
    kind: Literal["step", "state", "report"]
    agent: str = ""
    summary: str = ""
    data: dict[str, Any] = {}


EventSink = Callable[[AgentEvent], None]
HumanGate = Callable[[str], Awaitable[None]]
"""人工介入回调：入参为原因说明，返回即视为用户已处理完毕。"""


class RunnerConfig(BaseModel):
    max_steps: int = 60
    max_section_retries: int = 3
    prefill_threshold: float = 0.4
    token_budget: int = 400_000


class AgentRunner:
    def __init__(
        self,
        *,
        task_id: str,
        task_instruction: str,
        driver: Driver,
        router: ModelRouter,
        executor: ExecutorLike,
        profile: Profile,
        resolver: ProfileResolver | None = None,
        config: RunnerConfig | None = None,
        on_event: EventSink | None = None,
        human_gate: HumanGate | None = None,
    ) -> None:
        self._task_id = task_id
        self._instruction = task_instruction
        self._driver = driver
        self._executor = executor
        self._profile = profile
        self._resolver = resolver or ProfileResolver()
        self._config = config or RunnerConfig()
        self._on_event = on_event
        self._human_gate = human_gate
        self._planner = Planner(router.get("planner"),
                                prefill_threshold=self._config.prefill_threshold)
        self._actor = Actor(router.get("actor"))
        self._validator = Validator(router.get("validator"))
        self._checklist = Checklist()
        self._history = HistoryLog()
        self._catalog = self._resolver.catalog(profile)
        self._seq = 0
        self._last_title = ""
        self.state: RunState = "RUNNING"

    # ---------- 事件 ----------

    def _emit(self, kind: Literal["step", "state", "report"], agent: str,
              summary: str, **data: Any) -> None:
        self._seq += 1
        event = AgentEvent(seq=self._seq, kind=kind, agent=agent, summary=summary, data=data)
        if self._on_event is not None:
            self._on_event(event)
        log.info("runner.event", kind=kind, agent=agent, summary=summary[:120])

    def _set_state(self, state: RunState, reason: str = "") -> None:
        self.state = state
        self._emit("state", "runner", reason or state, state=state)

    # ---------- 人工介入 ----------

    async def _wait_human(self, reason: str) -> None:
        self._set_state("WAITING_HUMAN", reason)
        if self._human_gate is None:
            raise AutoOfferError(f"需要人工介入但未配置 human_gate: {reason}")
        await self._human_gate(reason)
        self._set_state("RUNNING", "人工处理完成，继续执行")

    # ---------- 主循环 ----------

    async def run(self, url: str) -> FillReport:
        started = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            await self._driver.open(url)
            await self._main_loop()
            if self.state == "RUNNING":
                self._set_state("AWAITING_REVIEW", "填写完成，等待用户审核提交")
        except AutoOfferError as exc:
            log.error("runner.failed", error=str(exc))
            self._set_state("FAILED", f"任务失败: {exc}")
        finally:
            report = self._build_report(url, started)
            self._emit("report", "runner", "填写报告生成", counts=report.counts())
        return report

    async def _main_loop(self) -> None:
        steps = 0
        initial_prefill: float | None = None
        while steps < self._config.max_steps:
            steps += 1
            obs = await self._driver.observe()
            self._last_title = obs.title or self._last_title
            if initial_prefill is None:
                # 只按首轮观察判定核对模式：智能体自己填的字段不算"站点预填"
                initial_prefill = obs.scenario.prefilled_ratio
            plan = await self._planner.plan(
                task_instruction=self._instruction,
                observation=obs,
                checklist_text=self._checklist.to_text(),
                history_text=self._history.to_text(),
                forced_verify=initial_prefill >= self._config.prefill_threshold,
            )
            self._emit("step", "planner", f"{plan.decision}: {plan.reason[:100]}")
            self._history.add(f"Planner 决策 {plan.decision}({plan.strategy}) {plan.reason}")

            if plan.decision == "finish" or plan.done:
                return
            if plan.decision == "fail":
                raise AutoOfferError(f"Planner 判定无法继续: {plan.reason}")
            if plan.decision == "wait_human":
                await self._wait_human(plan.wait_human_reason or "需要人工处理")
                continue
            if plan.decision == "advance_page":
                await self._advance_page(obs, plan)
                continue
            if plan.decision == "dispatch_section":
                await self._run_section(obs, plan)
                continue
            raise AutoOfferError(f"未知的 Planner 决策: {plan.decision}")
        log.warning("runner.max_steps_reached", steps=steps)
        self._emit("step", "runner", f"达到最大步数护栏({self._config.max_steps})，安全终止")

    # ---------- 区块子任务 ----------

    def _section_elements(
        self, obs: PageObservation, section_id: str | None
    ) -> list[UIElement]:
        sec = next((s for s in obs.sections if s.id == section_id), None)
        if sec is None:
            return [e for e in obs.elements if e.visible]
        return [
            e for e in obs.elements
            if sec.element_start <= e.index <= sec.element_end and e.visible
        ]

    async def _run_section(self, obs: PageObservation, plan: PlannerOutput) -> None:
        sec = next((s for s in obs.sections if s.id == plan.next_section_id), None)
        section_title = sec.title if sec else (plan.next_section_id or "全部字段")
        goal = plan.subtask_goal or f"填写区块「{section_title}」"
        slice_values = self._resolver.slice_for_section(self._profile, section_title)
        extra_profile: dict[str, Any] | None = None
        retry_advice: str | None = None
        strategy: FlowStrategy = plan.strategy

        for attempt in range(1, self._config.max_section_retries + 1):
            observation = obs if attempt == 1 else await self._driver.observe()
            elements = self._section_elements(observation, plan.next_section_id)
            batch = await self._actor.act(
                goal=goal,
                mode=strategy,
                observation=observation,
                section_elements=elements,
                catalog=self._catalog,
                slice_values=slice_values,
                extra_profile=extra_profile,
                history_text=self._history.to_text(),
                retry_advice=retry_advice,
            )
            self._emit("step", "actor", batch.summary or f"输出 {len(batch.actions)} 个动作")

            # 特殊动作前置处理
            extra_profile = await self._handle_meta_actions(batch, section_title)
            if any(a.type == "ask_user" for a in batch.actions):
                reason = next(a.reason for a in batch.actions if a.type == "ask_user")
                await self._wait_human(reason or "Actor 请求人工介入")
                continue

            exec_actions = [a for a in batch.actions
                            if a.type not in ("request_profile", "skip_field", "done")]
            if not exec_actions:
                if batch.section_complete:
                    return
                retry_advice = "上一轮没有可执行动作，请重新审视区块元素与目标。"
                continue

            try:
                results = await self._executor.execute_batch(
                    ActionBatch(actions=exec_actions, section_complete=batch.section_complete,
                                summary=batch.summary),
                    observation,
                )
            except ActionError as exc:
                retry_advice = f"动作执行报错：{exc}。请换一种策略。"
                self._history.add(f"执行失败: {exc}")
                continue

            needs_human = [r for r in results if getattr(r, "status", "") == "needs_human"]

            expected_text, readback_text = await self._readback(exec_actions, observation)
            val = await self._validator.validate(
                goal=goal, expected_text=expected_text, readback_text=readback_text
            )
            self._emit("step", "validator",
                       f"passed={val.passed} complete={val.section_complete}")
            for fr in val.field_results:
                self._checklist.upsert(
                    fr.label,
                    section_title=section_title,
                    status="filled" if fr.passed else "failed",
                    value=fr.actual,
                    note=fr.note,
                )
            self._history.add(
                f"区块「{section_title}」第{attempt}次: "
                f"{'通过' if val.passed else '未通过'} {batch.summary}"
            )
            if needs_human:
                # 回读与 checklist 已更新，再交人工（敏感按钮确认等）
                await self._wait_human(f"敏感操作需确认: {needs_human[0].detail}")
                continue
            if val.passed and (val.section_complete or batch.section_complete):
                return
            retry_advice = val.retry_advice or "部分字段未通过校验，请修正后重试。"
        log.warning("runner.section_exhausted", section=section_title)
        self._checklist.upsert(
            f"区块:{section_title}", section_title=section_title,
            status="failed", note="重试次数用尽",
        )

    async def _handle_meta_actions(
        self, batch: ActionBatch, section_title: str
    ) -> dict[str, Any] | None:
        extra: dict[str, Any] | None = None
        for action in batch.actions:
            if action.type == "request_profile" and action.profile_paths:
                values, restricted = self._resolver.resolve(
                    self._profile, action.profile_paths
                )
                extra = values or None
                if restricted:
                    await self._wait_human(
                        "表单需要受限敏感字段（如身份证号），请在界面确认是否提供: "
                        + ", ".join(restricted)
                    )
            elif action.type == "skip_field":
                self._checklist.upsert(
                    action.reason or "未知字段",
                    section_title=section_title,
                    status="pending_confirm",
                    note="档案缺失，待用户补充",
                )
        return extra

    async def _readback(
        self, actions: list[Action], obs: PageObservation
    ) -> tuple[str, str]:
        by_index = {e.index: e for e in obs.elements}
        expected_lines: list[str] = []
        readback_lines: list[str] = []
        for a in actions:
            if a.element_index is None or a.element_index not in by_index:
                continue
            el = by_index[a.element_index]
            target = a.value
            if a.date is not None:
                target = f"{a.date.year}-{a.date.month or ''}"
            if a.date_range is not None:
                end = a.date_range.end
                target = (
                    f"{a.date_range.start.year}-{a.date_range.start.month or ''}"
                    f" ~ {end.year if end else '至今'}"
                )
            if a.attachment_label:
                target = a.attachment_label
            if target is None and a.type == "click":
                target = "(点击)"
            expected_lines.append(f"{el.label}: {target}")
            try:
                actual = await self._driver.element_value(el)
            except AutoOfferError:
                actual = "(回读失败)"
            readback_lines.append(f"{el.label}: {actual}")
        return "\n".join(expected_lines), "\n".join(readback_lines)

    async def _advance_page(self, obs: PageObservation, plan: PlannerOutput) -> None:
        idx = obs.pagination.next_button_index
        if idx is None:
            raise AutoOfferError("Planner 要求翻页但未识别到下一步按钮")
        action = Action(type="click", element_index=idx, reason="进入下一步")
        await self._executor.execute_batch(ActionBatch(actions=[action]), obs)
        await self._driver.wait(1.0)
        self._history.add("已点击下一步进入新页面")
        self._emit("step", "runner", "翻页: 已点击下一步")

    # ---------- 报告 ----------

    def _build_report(self, url: str, started_at: str) -> FillReport:
        usage_tokens = 0
        for role in ("planner", "actor", "validator"):
            client = getattr(self, "_" + role, None)
            total = getattr(getattr(client, "_llm", None), "total_usage", None)
            if total is not None:
                usage_tokens += total.total_tokens
        return FillReport(
            task_id=self._task_id,
            url=url,
            page_title=self._last_title,
            profile_id=self._profile.id,
            fields=self._checklist.to_report_fields(),
            started_at=started_at,
            finished_at=datetime.datetime.now().isoformat(timespec="seconds"),
            total_tokens=usage_tokens,
            note=f"最终状态: {self.state}",
        )


class RunnerError(LLMError):
    """保留：细分 Runner 异常时使用。"""
