"""AgentRunner：感知 → Planner → Actor → 执行 → Validator 的任务状态机（docs/02 §2.2）。

护栏：最大步数、区块重试上限、token 预算；超限安全终止并产出部分报告。
状态：RUNNING / WAITING_HUMAN / AWAITING_REVIEW / DONE / FAILED。
人工介入通过 human_gate 回调闭环（CLI 阻塞等待输入；服务层挂起任务等待 resume）。
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

import structlog
from pydantic import BaseModel

from autooffer_core.actions.models import Action, ActionBatch
from autooffer_core.agents.actor import Actor
from autooffer_core.agents.planner import Planner
from autooffer_core.agents.schemas import FieldCheck, FlowStrategy, PlannerOutput, ValidatorOutput
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
    field_abandon_after: int = 2
    """同一字段连续失败达到该次数后放弃（记待确认），不再反复重试。"""
    use_vision: bool = False
    """是否给 LLM 附 SoM 截图。默认纯 DOM 模式（对齐本地浏览器自动化实现：
    状态内联进元素表，无需视觉模型即可判定控件状态）。"""


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
        self._done_sections: dict[str, dict[str, tuple[str, str]]] = {}
        """页面签名 → {区块id: (标题, 状态)}（已完成/部分字段已放弃/重试用尽）。

        跨页不串（多步表单同名区块各自独立）。所有「已处理」状态都硬跳过重派，
        防止 Planner 对失败区块无限重派形成空转循环。
        """
        self._skip_counts: dict[str, int] = {}
        """同区块被硬跳过的次数（page|sid 计数）；达到上限自动按部分完成收尾。"""
        self._field_failures: dict[str, int] = {}
        """字段级失败计数：连续失败达到阈值后放弃该字段，不再反复重试。"""
        self._vision_next = self._config.use_vision
        """下一轮观察是否带截图。默认纯 DOM（use_vision=False）恒不带图。"""
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
            obs = await self._driver.observe(with_screenshot=self._vision_next)
            self._vision_next = False
            if self._config.use_vision and obs.scenario.page_type == "unknown":
                # 仅视觉模式下：规则识别不出页面类型时，下一轮带截图辅助 Planner 裁决
                self._vision_next = True
            self._last_title = obs.title or self._last_title
            if initial_prefill is None:
                # 只按首轮观察判定核对模式：智能体自己填的字段不算"站点预填"
                initial_prefill = obs.scenario.prefilled_ratio
            page_key = self._page_key(obs)
            done_here = self._done_sections.get(page_key, {})
            done_text = "、".join(
                f"{sid}《{title}》（{status}，勿再派发，剩余字段已记待确认）"
                for sid, (title, status) in done_here.items()
            )
            plan = await self._planner.plan(
                task_instruction=self._instruction,
                observation=obs,
                checklist_text=self._checklist.to_text(),
                history_text=self._history.to_text(),
                forced_verify=initial_prefill >= self._config.prefill_threshold,
                done_sections_text=done_text,
            )
            self._emit("step", "planner", f"{plan.decision}: {plan.reason[:100]}")
            self._history.add(f"Planner 决策 {plan.decision}({plan.strategy}) {plan.reason}")

            if plan.decision == "finish" or plan.done:
                return
            if plan.decision == "fail":
                # 兜底：只要已有字段填写成功或已记入待确认，就按「部分完成」正常结束，
                # 不因个别字段填不上而让整个任务失败。
                counts = self._checklist.counts()
                if counts["filled"] > 0 or counts["pending_confirm"] > 0:
                    self._emit(
                        "step", "runner",
                        f"部分字段未填，已跳过并结束（成功 {counts['filled']} / "
                        f"待确认 {counts['pending_confirm']} / 失败 {counts['failed']}）",
                    )
                    self._history.add("Planner 判定 fail，但有字段已填写，降级为部分完成")
                    return
                raise AutoOfferError(f"Planner 判定无法继续: {plan.reason}")
            if plan.decision == "wait_human":
                await self._wait_human(plan.wait_human_reason or "需要人工处理")
                continue
            if plan.decision == "advance_page":
                await self._advance_page(obs, plan)
                continue
            if plan.decision == "dispatch_section":
                sid = plan.next_section_id or ""
                if sid in done_here:
                    title, status = done_here[sid]
                    key = f"{page_key}|{sid}"
                    self._skip_counts[key] = self._skip_counts.get(key, 0) + 1
                    self._emit("step", "runner", f"跳过已处理区块「{title}」（{status}）")
                    self._history.add(f"区块「{title}」已处理过（{status}），跳过重派")
                    if self._skip_counts[key] >= 3:
                        # Planner 无视提示反复重派同一区块：按部分完成收尾，
                        # 不再让「派发→跳过」空转烧掉剩余步数
                        counts = self._checklist.counts()
                        self._emit(
                            "step", "runner",
                            f"区块「{title}」被反复重派，自动结束（成功 {counts['filled']} / "
                            f"待确认 {counts['pending_confirm']} / 失败 {counts['failed']}）",
                        )
                        self._history.add("Planner 反复重派已处理区块，按部分完成收尾")
                        return
                    continue
                await self._run_section(obs, plan, page_key)
                continue
            raise AutoOfferError(f"未知的 Planner 决策: {plan.decision}")
        log.warning("runner.max_steps_reached", steps=steps)
        self._emit("step", "runner", f"达到最大步数护栏({self._config.max_steps})，安全终止")

    # ---------- 区块子任务 ----------

    @staticmethod
    def _page_key(obs: PageObservation) -> str:
        """页面签名：URL + 分页步号。多步表单不同步骤的同名区块互不干扰。"""
        step = obs.pagination.current_step
        return f"{obs.url}|{step if step is not None else 'single'}"

    def _section_title(self, obs: PageObservation, plan: PlannerOutput) -> str:
        sec = next((s for s in obs.sections if s.id == plan.next_section_id), None)
        return sec.title if sec else (plan.next_section_id or "全部字段")

    def _mark_section_done(
        self, page_key: str, section_id: str, section_title: str, status: str = "已完成"
    ) -> None:
        """区块处理结果登记（按页面签名），供 Planner 派发前跳过与提示词注入。

        status 如实描述（已完成/部分字段已放弃/重试用尽），让 Planner 知道
        该区块已处理过、剩余字段已记待确认，不要再派发。
        """
        self._done_sections.setdefault(page_key, {})[section_id or section_title] = (
            section_title,
            status,
        )

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

    async def _run_section(
        self, obs: PageObservation, plan: PlannerOutput, page_key: str
    ) -> None:
        section_title = self._section_title(obs, plan)
        section_id = plan.next_section_id or section_title
        goal = plan.subtask_goal or f"填写区块「{section_title}」"
        slice_values = self._resolver.slice_for_section(self._profile, section_title)
        extra_profile: dict[str, Any] | None = None
        retry_advice: str | None = None
        strategy: FlowStrategy = plan.strategy

        for attempt in range(1, self._config.max_section_retries + 1):
            # 重试轮不带截图：DOM 足够比对，省 ~0.8s/张的推理延迟与标注耗时
            observation = (
                obs
                if attempt == 1
                else await self._driver.observe(with_screenshot=False)
            )
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
            extra_profile = await self._handle_meta_actions(batch, section_title, observation)
            if any(a.type == "ask_user" for a in batch.actions):
                reason = next(a.reason for a in batch.actions if a.type == "ask_user")
                await self._wait_human(reason or "Actor 请求人工介入")
                continue

            exec_actions = [a for a in batch.actions
                            if a.type not in ("request_profile", "skip_field", "done")]
            if not exec_actions:
                if batch.section_complete:
                    self._mark_section_done(page_key, section_id, section_title)
                    return
                # 全是 skip_field（档案无数据）→ 重试无意义，直接结束该区块
                if batch.actions and all(a.type == "skip_field" for a in batch.actions):
                    log.info("runner.section_unfillable", section=section_title)
                    self._history.add(f"区块「{section_title}」档案缺失，已记入待确认")
                    self._mark_section_done(page_key, section_id, section_title)
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

            # 执行后重新感知（视口级、无截图），读回真实页面状态
            after_obs = await self._driver.observe(with_screenshot=False, scroll_full=False)
            pairs = await self._readback_pairs(exec_actions, observation, after_obs)
            val = await self._validate_or_llm(goal, pairs, batch.section_complete)

            failed_fields = [fr for fr in val.field_results if not fr.passed]
            summary = f"passed={val.passed} complete={val.section_complete}"
            if failed_fields:
                detail = "；".join(
                    f"{fr.label}: 期望'{fr.expected}' 实际'{fr.actual}'" for fr in failed_fields[:5]
                )
                summary += f" | 未通过: {detail}"
            if val.retry_advice:
                summary += f" | 建议: {val.retry_advice}"
            self._emit("step", "validator", summary, failed_fields=[
                {"label": fr.label, "expected": fr.expected, "actual": fr.actual, "note": fr.note}
                for fr in failed_fields
            ])

            # 更新字段失败计数并写 checklist；连续失败达到阈值 → 放弃（记待确认，不再重试）
            abandoned_this_round: set[str] = set()
            for fr in val.field_results:
                if fr.passed:
                    self._field_failures.pop(fr.label, None)
                    self._checklist.upsert(
                        fr.label, section_title=section_title,
                        status="filled", value=fr.actual, note=fr.note,
                    )
                else:
                    self._field_failures[fr.label] = self._field_failures.get(fr.label, 0) + 1
                    if self._field_failures[fr.label] >= self._config.field_abandon_after:
                        abandoned_this_round.add(fr.label)
                        self._checklist.upsert(
                            fr.label, section_title=section_title,
                            status="pending_confirm", value=fr.actual,
                            note="多次尝试失败，已放弃",
                        )
                    else:
                        self._checklist.upsert(
                            fr.label, section_title=section_title,
                            status="failed", value=fr.actual, note=fr.note,
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
                self._mark_section_done(page_key, section_id, section_title)
                return

            # 若本轮失败字段已全部放弃（无新失败项），不再空转重试，直接结束该区块
            if abandoned_this_round and not any(
                fr.label not in abandoned_this_round for fr in failed_fields
            ):
                self._emit(
                    "step", "runner",
                    f"区块「{section_title}」部分字段已放弃，结束本区块继续后续",
                )
                self._mark_section_done(
                    page_key, section_id, section_title, status="部分字段已放弃"
                )
                return

            if abandoned_this_round:
                retry_advice = (
                    "以下字段已多次尝试失败，请改用 skip_field 跳过、不要再填写："
                    f"{'、'.join(sorted(abandoned_this_round))}。继续填写其余字段。"
                )
            else:
                retry_advice = val.retry_advice or "部分字段未通过校验，请修正后重试。"
        log.warning("runner.section_exhausted", section=section_title)
        self._checklist.upsert(
            f"区块:{section_title}", section_title=section_title,
            status="failed", note="重试次数用尽",
        )
        self._mark_section_done(page_key, section_id, section_title, status="重试用尽")

    async def _handle_meta_actions(
        self, batch: ActionBatch, section_title: str, obs: PageObservation
    ) -> dict[str, Any] | None:
        by_index = {e.index: e for e in obs.elements}
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
                # 用元素 label 做键，避免每轮 reason 措辞不同导致重复记录
                el = by_index.get(action.element_index) if action.element_index else None
                label = (el.label if el else "") or (action.reason or "未知字段")[:24]
                self._checklist.upsert(
                    label,
                    section_title=section_title,
                    status="pending_confirm",
                    note="档案缺失，待用户补充",
                )
        return extra

    # ---------- 回读与校验 ----------

    @staticmethod
    def _expected_text(a: Action, el: UIElement) -> str:
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
        return target or ""

    async def _readback_pairs(
        self, actions: list[Action], obs: PageObservation, after_obs: PageObservation
    ) -> list[tuple[Action, UIElement, str, str]]:
        """回读为结构化 (动作, 元素, 期望, 实际) 列表。

        动作的 element_index 是执行前 obs 的编号；执行可能改变结构（index 位移），
        因此优先按 selector 在 after_obs 中找回执行后元素。视口外元素不在
        after_obs 时回退用原元素按 selector 直读（元素定位不依赖观察列表），
        不再误判"执行后未找到元素"。
        """
        by_index = {e.index: e for e in obs.elements}
        by_selector = {e.selector: e for e in after_obs.elements}
        pairs: list[tuple[Action, UIElement, str, str]] = []
        for a in actions:
            if a.element_index is None or a.element_index not in by_index:
                continue
            el = by_index[a.element_index]
            expected = self._expected_text(a, el)
            read_el = by_selector.get(el.selector, el)
            try:
                actual = await self._driver.element_value(read_el)
            except AutoOfferError:
                actual = "(回读失败)"
            pairs.append((a, el, expected, actual))
        return pairs

    async def _validate_or_llm(
        self, goal: str, pairs: list[tuple[Action, UIElement, str, str]],
        actor_section_complete: bool,
    ) -> ValidatorOutput:
        """表单字段的校验优先程序化（字符串/日期/选中态比对，零 LLM 调用）。

        只有存在无法程序化判定的动作（回读失败、未知动作类型）才退回 LLM 校验。
        """
        checks: list[tuple[str, str, str, bool | None]] = []  # (label, expected, actual, passed)
        for a, el, expected, actual in pairs:
            checks.append((el.label or a.reason[:24], expected, actual,
                           self._check_pair(a, el, expected, actual)))
        if any(c[3] is None for c in checks):
            expected_text = "\n".join(f"{label}: {exp}" for label, exp, _, _ in checks)
            readback_text = "\n".join(f"{label}: {act}" for label, _, act, _ in checks)
            return await self._validator.validate(
                goal=goal, expected_text=expected_text, readback_text=readback_text
            )
        field_results = [
            FieldCheck(label=label, expected=exp, actual=act, passed=bool(p))
            for label, exp, act, p in checks
        ]
        failed = [fr for fr in field_results if not fr.passed]
        retry_advice: str | None = None
        if failed:
            parts: list[str] = []
            for a, el, _exp, act in pairs:
                fr = next((f for f in failed if f.label == (el.label or a.reason[:24])), None)
                if fr is None:
                    continue
                if not act.strip() and el.role in ("combobox", "custom"):
                    # 自定义下拉常见两步交互：点开展开面板 → 点选项文本
                    parts.append(
                        f"{fr.label} 为自定义控件且回读为空：先 click 展开下拉面板，"
                        "等下一轮再 click 选项文本（不要用 input_text 直接键入）"
                    )
                else:
                    parts.append(f"{fr.label} 期望'{fr.expected}'实际'{fr.actual}'")
            retry_advice = "；".join(parts[:5]) + "。请重试或换策略。"
        return ValidatorOutput(
            passed=not failed,
            section_complete=actor_section_complete and not failed,
            field_results=field_results,
            retry_advice=retry_advice,
        )

    @staticmethod
    def _check_pair(a: Action, el: UIElement, expected: str, actual: str) -> bool | None:
        """单动作程序化判定；None 表示无法判定（需 LLM）。"""
        if actual == "(回读失败)":
            return None
        t = a.type
        if t == "input_text":
            # 日期类输入框（input[type=date/month] 或角色 date）按日期等价比较
            if el.role == "date" or el.input_type in ("date", "month"):
                return AgentRunner._dates_equal(expected, actual)
            return AgentRunner._values_equal(expected, actual)
        if t == "select_option":
            return bool(actual.strip()) and AgentRunner._values_equal(expected, actual)
        if t == "set_date":
            return AgentRunner._dates_equal(expected, actual)
        if t == "set_date_range":
            if " ~ " in expected and " ~ " in actual:
                es, as_ = expected.split(" ~ ", 1), actual.split(" ~ ", 1)
                return (AgentRunner._dates_equal(es[0], as_[0])
                        and (as_[1] == "至今" or AgentRunner._dates_equal(es[1], as_[1])))
            return AgentRunner._values_equal(expected, actual)
        if t == "click":
            if el.role == "radio":
                return actual == "true"  # 感知层约定：选中 "true"/未选 ""
            if el.role in ("combobox", "custom") and expected and expected != "(点击)":
                # 带目标值的自定义控件点击（如下拉选值）：回读非空且包含期望才算数。
                # 只点开面板时回读为空 → 判未通过，驱动 Actor 下一轮点选项文本。
                return bool(actual.strip()) and AgentRunner._values_equal(expected, actual)
            return True  # 复选/按钮等结构动作，点击即成功
        return None  # 未知类型交 LLM

    @staticmethod
    def _values_equal(expected: str, actual: str) -> bool:
        def norm(s: str) -> str:
            return " ".join(str(s).split()).lower()

        e, a = norm(expected), norm(actual)
        return e == a or (e != "" and e in a)

    @staticmethod
    def _dates_equal(expected: str, actual: str) -> bool:
        """日期等价比较：2024-07 / 2024/7 / 2024年7月 视为一致。"""

        def parts(s: str) -> tuple[int, ...] | None:
            m = re.match(r"^(\d{4})[^\d]+(\d{1,2})(?:[^\d]+(\d{1,2}))?", s.strip())
            if not m:
                return None
            vals = (int(m.group(1)), int(m.group(2)))
            return vals + (int(m.group(3)),) if m.group(3) else vals

        ep, ap = parts(expected), parts(actual)
        if ep is None or ap is None:
            return AgentRunner._values_equal(expected, actual)
        return ep == ap

    async def _advance_page(self, obs: PageObservation, plan: PlannerOutput) -> None:
        idx = obs.pagination.next_button_index
        by_index = {e.index: e for e in obs.elements}
        target = by_index.get(idx) if idx is not None else None
        if target is None or not target.visible:
            # 兜底：在可见按钮/链接中按文本重新定位（多步表单隐藏步骤按钮仍在 DOM）
            target = next(
                (
                    e for e in obs.elements
                    if e.visible and e.role in ("button", "link")
                    and any(k in (e.label or e.value) for k in ("下一步", "继续", "保存并", "next"))
                ),
                None,
            )
        if target is None:
            raise AutoOfferError("Planner 要求翻页但未识别到可见的下一步按钮")
        action = Action(type="click", element_index=target.index, reason="进入下一步")
        await self._executor.execute_batch(ActionBatch(actions=[action]), obs)
        await self._driver.wait(1.0)
        if self._config.use_vision:
            self._vision_next = True  # 视觉模式：新页面首轮带截图辅助 Planner 裁决
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
