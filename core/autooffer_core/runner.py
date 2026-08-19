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
    auto_submit: bool = False
    """全部填写完成后自动点击提交按钮（用户显式开启；绕过敏感门禁但全程留痕）。"""


class AgentRunner:
    # 值形态 → 标签关键词（拦截"手机号填进体重框"类模型配错）
    _LABEL_SHAPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("mobile", ("电话", "手机", "联系", "phone", "mobile", "tel")),
        ("email", ("邮箱", "邮件", "email", "mail")),
        ("idcard", ("证件", "身份证", "idcard")),
        ("date", ("日期", "时间", "出生", "年月", "毕业", "入学", "date")),
        ("measure", ("身高", "体重", "年龄", "岁")),
    )
    _SHAPE_CN = {
        "mobile": "手机号", "email": "邮箱", "idcard": "证件号",
        "date": "日期", "range": "日期区间", "measure": "数值量（身高/体重等）",
    }
    # (标签形态, 值形态) 明确冲突 → 拦截；日期标签允许区间值（教育时间常见）
    _SHAPE_CONFLICTS = {
        ("measure", "mobile"), ("measure", "email"), ("measure", "idcard"),
        ("measure", "date"), ("measure", "range"),
        ("mobile", "email"), ("mobile", "idcard"), ("mobile", "date"),
        ("mobile", "range"),
        ("email", "idcard"), ("email", "date"), ("email", "range"),
        ("idcard", "date"), ("idcard", "range"),
        ("date", "mobile"), ("date", "email"), ("date", "idcard"),
    }

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
        self._action_log: dict[str, dict[str, Any]] = {}
        """动作指纹 → {count, value, elements}（上次执行后的元素值与页面元素数）。

        对齐本地浏览器自动化纪律：动作按"预期效果是否出现"判定成败，
        没产生效果的动作禁止原样重复（尤其下拉触发器反复点击会 toggle 收起面板）。"""
        self._absent_advances: dict[str, int] = {}
        """区块不在当前页时自动点"下一步"的次数（按区块计，防一路翻完整个向导）。"""
        self._finish_advances = 0
        """收尾前自动翻页次数（多步表单还有后续步骤时不提前结束；上限 5）。"""
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
                if self._config.auto_submit:
                    if await self._try_auto_submit():
                        self._set_state("DONE", "全部填写完成并已自动提交")
                    else:
                        self._set_state("AWAITING_REVIEW", "未找到提交按钮，等待人工提交")
                else:
                    self._set_state("AWAITING_REVIEW", "填写完成，等待用户审核提交")
        except AutoOfferError as exc:
            log.error("runner.failed", error=str(exc))
            self._set_state("FAILED", f"任务失败: {exc}")
        finally:
            report = self._build_report(url, started)
            self._emit("report", "runner", "填写报告生成", counts=report.counts())
        return report

    _SUBMIT_WORDS: tuple[str, ...] = ("提交", "确认提交", "投递", "发送申请")

    async def _try_auto_submit(self) -> bool:
        """自动提交（用户在设置中显式开启）：点击可见的提交/投递按钮。

        绕过敏感动作门禁是本功能的本意——门禁默认拦截提交正是为了把这个
        决定权留给用户；开启即授权。全程事件留痕便于回溯。
        """
        obs = await self._driver.observe(with_screenshot=False, scroll_full=False)
        target = next(
            (
                e for e in obs.elements
                if e.visible and e.role in ("button", "link")
                and any(k in (e.label or e.value) for k in self._SUBMIT_WORDS)
            ),
            None,
        )
        if target is None:
            self._emit("step", "runner", "自动提交：未找到可见的提交按钮，转人工提交")
            self._history.add("自动提交未找到提交按钮")
            return False
        self._emit(
            "step", "runner",
            f"自动提交：点击「{target.label}」（用户已开启自动提交）",
        )
        self._history.add(f"自动提交: 点击 {target.label}")
        await self._driver.click(target)
        await self._driver.wait(1.5)
        return True

    async def _main_loop(self) -> None:
        steps = 0
        initial_prefill: float | None = None
        empty_obs_streak = 0
        """连续"无可交互元素"观察的次数；页面渲染中时等待重观察（有界，防空转）。"""
        planner_llm_fails = 0
        """Planner 连续 LLM 失败次数；达到 3 次按部分完成收尾，不判任务失败。"""
        while steps < self._config.max_steps:
            steps += 1
            obs = await self._driver.observe(with_screenshot=self._vision_next)
            if self._observation_barren(obs) and empty_obs_streak < 2:
                # SPA 首屏/iframe 懒加载未就绪：等 1.5s 重观察一次，避免
                # Actor 第一轮拿到空元素表白烧重试（真实站点回归）
                empty_obs_streak += 1
                self._emit("step", "runner", "页面尚无可交互元素，等待渲染后重新观察")
                await self._driver.wait(1.5)
                obs = await self._driver.observe(with_screenshot=False)
            elif not self._observation_barren(obs):
                empty_obs_streak = 0
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
            try:
                plan = await self._planner.plan(
                    task_instruction=self._instruction,
                    observation=obs,
                    checklist_text=self._checklist.to_text(),
                    history_text=self._history.to_text(),
                    forced_verify=initial_prefill >= self._config.prefill_threshold,
                    done_sections_text=done_text,
                )
            except LLMError as exc:
                # Planner 输出异常（截断/解析失败）：稍候重试；连续失败按部分完成收尾
                planner_llm_fails += 1
                self._emit("step", "runner", f"Planner 输出异常，稍后重试: {str(exc)[:100]}")
                if planner_llm_fails >= 3:
                    counts = self._checklist.counts()
                    self._emit(
                        "step", "runner",
                        f"Planner 连续输出异常，按当前进度收尾（成功 {counts['filled']} / "
                        f"待确认 {counts['pending_confirm']} / 失败 {counts['failed']}）",
                    )
                    self._history.add("Planner 连续输出异常，按部分完成收尾")
                    return
                await self._driver.wait(1.0)
                continue
            planner_llm_fails = 0
            self._emit(
                "step", "planner", f"{plan.decision}: {plan.reason[:100]}",
                section=plan.next_section_id, url=obs.url,
                step=obs.pagination.current_step,
            )
            self._history.add(f"Planner 决策 {plan.decision}({plan.strategy}) {plan.reason}")

            if plan.decision == "finish" or plan.done:
                # 收尾前若页面还有可见的"下一步/保存并继续"：多步表单后续步骤
                # 未走完，先翻页继续（有界）；最后一步没有下一步按钮，正常结束
                if self._finish_advances < 5 and await self._try_advance(obs):
                    self._finish_advances += 1
                    self._history.add("收尾前发现下一步按钮，翻页继续后续步骤")
                    continue
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
                try:
                    await self._advance_page(obs, plan)
                except AutoOfferError as exc:
                    # Planner 想翻页但没有可见按钮：按当前进度部分完成收尾，
                    # 不判任务失败（个别区块填不上不应毁掉整份报告）
                    counts = self._checklist.counts()
                    self._emit(
                        "step", "runner",
                        f"{exc}；按当前进度收尾（成功 {counts['filled']} / "
                        f"待确认 {counts['pending_confirm']} / 失败 {counts['failed']}）",
                    )
                    self._history.add("未找到下一步按钮，按部分完成收尾")
                    return
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
                if not self._section_on_page(obs, plan):
                    # 派发的区块确实不在当前页（多步表单未到该步）：先点"下一步"推进；
                    # 没有翻页按钮则回退正常派发（全量元素兜底），由 Actor 自行判断字段
                    absent_sid = plan.next_section_id or ""
                    advances = self._absent_advances.get(absent_sid, 0)
                    if advances < 3 and await self._try_advance(obs):
                        self._absent_advances[absent_sid] = advances + 1
                        continue  # 翻页成功：外层重新观察、重新规划
                await self._run_section(obs, plan, page_key)
                continue
            raise AutoOfferError(f"未知的 Planner 决策: {plan.decision}")
        log.warning("runner.max_steps_reached", steps=steps)
        self._emit("step", "runner", f"达到最大步数护栏({self._config.max_steps})，安全终止")

    @staticmethod
    def _observation_barren(obs: PageObservation) -> bool:
        """页面是否没有任何可交互元素（可填控件或可点按钮/链接）。"""
        for e in obs.elements:
            if not e.visible:
                continue
            if e.role in ("input", "textarea", "select", "combobox", "date",
                          "custom", "richtext", "radio", "checkbox"):
                return False
            if e.role in ("button", "link"):
                return False
        return True

    # ---------- 区块子任务 ----------

    @staticmethod
    def _page_key(obs: PageObservation) -> str:
        """页面签名：URL + 分页步号。多步表单不同步骤的同名区块互不干扰。"""
        step = obs.pagination.current_step
        return f"{obs.url}|{step if step is not None else 'single'}"

    def _section_title(self, obs: PageObservation, plan: PlannerOutput) -> str:
        sec = next((s for s in obs.sections if s.id == plan.next_section_id), None)
        return sec.title if sec else (plan.next_section_id or "全部字段")

    @staticmethod
    def _section_on_page(obs: PageObservation, plan: PlannerOutput) -> bool:
        """派发区块是否在当前页：按感知分段的 id/标题匹配。

        感知层未分段（sections 为空）时一律视为在页——Planner 自拟的 s1/s2
        编号与感知 id 天然对不上，不能据此判"不在当前页"（真实站点回归：
        表单就在当前页却被误判缺页，任务一步结束）。
        """
        if not obs.sections or not plan.next_section_id:
            return True
        if any(s.id == plan.next_section_id for s in obs.sections):
            return True
        plan_titles = [sec.title for sec in plan.sections if sec.title]
        if plan.subtask_goal:
            plan_titles.append(plan.subtask_goal)
        for s in obs.sections:
            for t in plan_titles:
                if t in s.title or s.title in t:
                    return True
        return False

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
        empty_rounds = 0

        for attempt in range(1, self._config.max_section_retries + 1):
            # 重试轮不带截图：DOM 足够比对，省 ~0.8s/张的推理延迟与标注耗时
            observation = (
                obs
                if attempt == 1
                else await self._driver.observe(with_screenshot=False)
            )
            elements = self._section_elements(observation, plan.next_section_id)
            try:
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
            except LLMError as exc:
                # 模型输出超长被截断/解析失败：压缩输出重试，不判任务失败
                # （真实站点回归：整页字段多时模型试图一轮填完 → 触发长度上限）
                retry_advice = (
                    f"上轮模型输出异常（{str(exc)[:80]}）。请大幅精简："
                    "单轮 actions 不超过 8 个，字段多分多轮完成，reason 一句话。"
                )
                self._history.add(f"Actor 输出异常: {exc}")
                self._emit("step", "runner", f"Actor 输出异常，压缩后重试: {str(exc)[:100]}")
                continue
            self._emit(
                "step", "actor", (batch.summary or f"输出 {len(batch.actions)} 个动作")[:80],
                actions=[
                    {
                        "type": a.type,
                        "index": a.element_index,
                        "value": (a.value or "")[:32],
                        "reason": (a.reason or "")[:48],
                    }
                    for a in batch.actions[:12]
                ],
                url=observation.url,
                step=observation.pagination.current_step,
            )

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
                # request_profile 轮是有效推进（数据已补取），不计入空转
                empty_rounds = 0 if extra_profile else empty_rounds + 1
                if empty_rounds >= 2:
                    self._history.add(f"区块「{section_title}」连续无可执行动作，跳过该区块")
                    self._mark_section_done(
                        page_key, section_id, section_title, status="无动作可执行"
                    )
                    return
                retry_advice = "上一轮没有可执行动作，请重新审视区块元素与目标。"
                continue

            # 拦截"已执行过且无任何效果"的重复动作（防触发器反复点击死循环）
            exec_actions, repeat_blocked = self._intercept_repeats(exec_actions, observation)
            # 拦截"值与字段语义冲突"的动作并降级单日期字段上的区间动作
            exec_actions, mismatch_notes = self._adjust_semantics(exec_actions, observation)
            blocked = [*repeat_blocked, *mismatch_notes]
            if mismatch_notes:
                self._emit(
                    "step", "runner", "字段与值不匹配已拦截/降级: " + "；".join(mismatch_notes[:2])
                )
                self._history.add(f"语义拦截: {'；'.join(mismatch_notes[:2])}")
            elif repeat_blocked:
                self._emit(
                    "step", "runner", "拦截无进展的重复动作: " + "；".join(repeat_blocked[:2])
                )
                self._history.add(f"拦截重复动作: {'；'.join(repeat_blocked[:2])}")
            if not exec_actions:
                if batch.section_complete and all("目标已达成" in b for b in blocked):
                    # 动作全部已生效且 Actor 判定完成：直接登记，不算失败
                    self._mark_section_done(page_key, section_id, section_title)
                    return
                if any("已拦截" in n for n in mismatch_notes):
                    retry_advice = (
                        "上轮动作因值与字段语义不匹配被拦截（详见拦截说明，提示中已给出"
                        "正确目标元素编号）。请按元素标签逐个核对编号后重新输出，"
                        "不要凭记忆编号。"
                    )
                else:
                    retry_advice = (
                        "已拦截与之前完全相同且无进展的动作，禁止再原样输出。"
                        "若上轮点开了下拉面板，请直接 click 面板中匹配的选项元素；"
                        "自定义下拉改用带目标值的 select_option；"
                        "确实无法推进的字段输出 skip_field。"
                    )
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
                # 报错细节落审计（真实站点排障依赖：元素定位/超时原因要能离线回看）
                self._emit("step", "runner", f"动作执行失败: {str(exc)[:150]}")
                continue

            needs_human = [r for r in results if getattr(r, "status", "") == "needs_human"]

            # 执行后重新感知（视口级、无截图），读回真实页面状态
            after_obs = await self._driver.observe(with_screenshot=False, scroll_full=False)
            pairs = await self._readback_pairs(exec_actions, observation, after_obs)
            # 登记动作指纹（值 + 页面元素数），供下轮拦截无进展的重复动作
            for a, el, _exp, actual in pairs:
                fp = self._action_fingerprint(a, el)
                rec = self._action_log.get(fp) or {"count": 0, "value": "", "elements": -1}
                rec.update(count=rec["count"] + 1, value=actual,
                           elements=len(after_obs.elements))
                self._action_log[fp] = rec
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
                f"{'通过' if val.passed else '未通过'} {(batch.summary or '')[:60]}"
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
            elif val.passed and not failed_fields:
                # 动作都成功但区块没完成：明确要求推进新动作，否则模型会原样重复上一轮
                retry_advice = (
                    "上一轮动作已执行成功但区块未完成，请输出新的动作继续推进"
                    "（如点击已展开面板中的选项元素、填写剩余字段）；"
                    "系统会拦截与之前完全相同且无进展的动作。"
                )
            else:
                retry_advice = val.retry_advice or "部分字段未通过校验，请修正后重试。"
            failed_exec = [r for r in results if getattr(r, "status", "") == "failed"]
            if failed_exec:
                detail = "；".join(r.detail for r in failed_exec[:3])
                retry_advice = f"{retry_advice} | 执行器拦截: {detail}"
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

    # ---------- 重复动作拦截 ----------

    @staticmethod
    def _action_fingerprint(a: Action, el: UIElement) -> str:
        """动作指纹：类型 + 元素 selector + 目标值（模型措辞变化不影响判定）。"""
        target = a.value or ""
        if a.date is not None:
            target = f"{a.date.year}-{a.date.month or ''}"
        if a.date_range is not None:
            end = a.date_range.end
            target = (
                f"{a.date_range.start.year}-{a.date_range.start.month or ''}"
                f"~{end.year if end else 'now'}"
            )
        return f"{a.type}|{el.selector}|{target}"

    @staticmethod
    def _label_shape(label: str) -> str | None:
        """标签的值形态（手机号/邮箱/证件/日期/数值量）；命中多种或零种返回 None。"""
        hits = {
            shape
            for shape, kws in AgentRunner._LABEL_SHAPE_KEYWORDS
            if any(k in label.lower() for k in kws)
        }
        return next(iter(hits)) if len(hits) == 1 else None

    @staticmethod
    def _value_shape(value: str) -> str | None:
        """值的形态推断（保守：形态明确才返回，自由文本返回 None 不拦截）。"""
        v = value.strip()
        if not v:
            return None
        if re.fullmatch(r"1[3-9]\d{9}", v):
            return "mobile"
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.\w+", v):
            return "email"
        if re.fullmatch(r"\d{17}[\dXx]|\d{15}", v):
            return "idcard"
        if re.search(r"(19|20)\d{2}", v) and any(k in v for k in ("~", "～", "至", "—")):
            return "range"
        if re.fullmatch(r"(19|20)\d{2}[-/年.]\d{1,2}([-./月]\d{1,2}(日|号)?)?", v):
            return "date"
        return None

    def _adjust_semantics(
        self, actions: list[Action], observation: PageObservation
    ) -> tuple[list[Action], list[str]]:
        """拦截"值与目标字段语义冲突"的动作，并降级单日期字段上的区间动作。

        模型在长元素表上偶发配错编号（真实站点回归：出生日期区间填进身高框、
        手机号填进体重框）。值形态（手机号/邮箱/证件/日期）与标签语义明确冲突
        时拦截，并在提示中给出正确目标元素，帮助模型下一轮自纠。
        """
        by_index = {e.index: e for e in observation.elements}
        adjusted: list[Action] = []
        notes: list[str] = []
        for a in actions:
            el = by_index.get(a.element_index) if a.element_index is not None else None
            value_shape: str | None = None
            coerced = a
            if a.type == "set_date_range" and a.date_range is not None and el is not None:
                if a.date_range.end is None:
                    value_shape = "date"
                    if re.search(r"出生|生日", el.label or ""):
                        # 单日期字段误发区间动作（end=null）：降级为单日期，
                        # 避免在出生日期框里找"至今"选项卡死转人工
                        coerced = Action(
                            type="set_date", element_index=a.element_index,
                            date=a.date_range.start, reason=a.reason,
                        )
                        notes.append(
                            f"元素[{el.index}]{el.label}为单日期字段，"
                            "区间动作已降级为单日期填写"
                        )
                else:
                    value_shape = "range"
            elif a.type == "set_date":
                value_shape = "date"
            elif a.value is not None:
                value_shape = self._value_shape(a.value)

            label_shape = self._label_shape(el.label or "") if el is not None else None
            if (
                el is not None
                and label_shape is not None
                and value_shape is not None
                and (label_shape, value_shape) in self._SHAPE_CONFLICTS
            ):
                hint = self._find_shape_target(observation, value_shape)
                notes.append(
                    f"元素[{el.index}]{el.label}是{self._SHAPE_CN[label_shape]}字段，"
                    f"值'{(a.value or '')[:16]}'像{self._SHAPE_CN[value_shape]}，已拦截"
                    + (f"；应填入{hint}" if hint else "；请核对元素编号")
                )
                continue
            adjusted.append(coerced)
        return adjusted, notes

    @staticmethod
    def _find_shape_target(observation: PageObservation, shape: str) -> str | None:
        """在当前元素表中找与值形态匹配的目标元素（提示用），如 '#5(联系电话)'。"""
        lookup = "date" if shape == "range" else shape
        kws = dict(AgentRunner._LABEL_SHAPE_KEYWORDS).get(lookup)
        if not kws:
            return None
        for e in observation.elements:
            if e.visible and e.label and any(k in e.label.lower() for k in kws):
                return f"#{e.index}({e.label})"
        return None

    def _intercept_repeats(
        self, actions: list[Action], observation: PageObservation
    ) -> tuple[list[Action], list[str]]:
        """拦截"已执行过且无任何效果"的重复动作，返回 (放行动作, 拦截说明)。

        对齐本地浏览器自动化纪律：动作按"预期效果是否出现"判定成败；
        - 目标已达成（值已填上/选项已选中）→ 无需重复；
        - 下拉触发器/自定义控件/选项类点击：执行过一次且值未变 → 拦截
          （再点触发器只会 toggle 收起面板，真实站点死循环的根因）；
        - 其余角色：允许一次偶然失败重试，两次后页面仍无变化 → 拦截。
        """
        by_index = {e.index: e for e in observation.elements}
        allowed: list[Action] = []
        blocked: list[str] = []
        for a in actions:
            el = by_index.get(a.element_index) if a.element_index is not None else None
            if (
                a.type not in ("click", "input_text", "select_option",
                               "set_date", "set_date_range")
                or el is None
            ):
                allowed.append(a)  # scroll/wait/press_key 等允许重复
                continue
            fp = self._action_fingerprint(a, el)
            prev = self._action_log.get(fp)
            if prev is None:
                allowed.append(a)
                continue
            current = (el.value or "").strip()
            # 目标已达成（如填写值已在、单选已选中）：无需重复
            if self._check_pair(a, el, self._expected_text(a, el), current) is True:
                blocked.append(f"{a.type}[{el.index}]{el.label} 目标已达成，无需重复")
                continue
            prev_value = (prev.get("value") or "").strip()
            if el.role in ("combobox", "custom", "option"):
                if prev.get("count", 0) >= 1 and current == prev_value:
                    blocked.append(
                        f"{a.type}[{el.index}]{el.label} 已执行过且值未变"
                        "（面板可能已展开），禁止再点触发器；请点选项元素或改用带值的动作"
                    )
                    continue
            elif (
                prev.get("count", 0) >= 2
                and current == prev_value
                and len(observation.elements) == prev.get("elements", -1)
            ):
                blocked.append(
                    f"{a.type}[{el.index}]{el.label} "
                    f"已执行{prev['count']}次页面无变化，禁止原样重复"
                )
                continue
            allowed.append(a)
        return allowed, blocked

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

    async def _try_advance(self, obs: PageObservation) -> bool:
        """点击可见的"下一步/继续"按钮推进多步表单；找不到返回 False。"""
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
            return False
        action = Action(type="click", element_index=target.index, reason="进入下一步")
        await self._executor.execute_batch(ActionBatch(actions=[action]), obs)
        await self._driver.wait(1.0)
        if self._config.use_vision:
            self._vision_next = True  # 视觉模式：新页面首轮带截图辅助 Planner 裁决
        self._history.add("已点击下一步进入新页面")
        self._emit("step", "runner", "翻页: 已点击下一步")
        return True

    async def _advance_page(self, obs: PageObservation, plan: PlannerOutput) -> None:
        if not await self._try_advance(obs):
            raise AutoOfferError("Planner 要求翻页但未识别到可见的下一步按钮")

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
