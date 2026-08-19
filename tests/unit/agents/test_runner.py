"""AgentRunner 状态机单元测试：FakeDriver + 脚本化 LLM + 真实 ActionExecutor。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from autooffer_core.actions.executor import ActionExecutor
from autooffer_core.actions.models import Action, ActionBatch
from autooffer_core.agents.schemas import (
    FieldCheck,
    PlannedSection,
    PlannerOutput,
    ValidatorOutput,
)
from autooffer_core.llm.interfaces import LLMClient, Role
from autooffer_core.perception.models import PageObservation, SectionInfo, UIElement
from autooffer_core.runner import AgentRunner, RunnerConfig
from autooffer_core.testing import FakeDriver, ScriptedLLMClient, build_sample_profile


class FakeRouter:
    """按角色返回预置脚本客户端。"""

    def __init__(self, clients: dict[Role, LLMClient]) -> None:
        self._clients = clients

    def get(self, role: Role) -> LLMClient:
        return self._clients[role]

    def default(self) -> LLMClient:
        return next(iter(self._clients.values()))


def make_observation() -> PageObservation:
    return PageObservation(
        url="https://example.com/apply",
        title="示例申请表",
        sections=[
            SectionInfo(id="s1", title="基本信息", element_start=0, element_end=1),
        ],
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#name"),
            UIElement(index=1, tag="input", role="input", label="邮箱", selector="#email"),
        ],
    )


def scripted(items: list[BaseModel]) -> ScriptedLLMClient:
    return ScriptedLLMClient(list(items))


@pytest.mark.asyncio
async def test_runner_happy_path_fill_and_finish() -> None:
    driver = FakeDriver(make_observation())
    profile = build_sample_profile()

    planner_script = [
        PlannerOutput(
            sections=[PlannedSection(id="s1", title="基本信息")],
            decision="dispatch_section",
            next_section_id="s1",
            subtask_goal="填写基本信息",
            reason="先填基本信息",
        ),
        PlannerOutput(
            sections=[PlannedSection(id="s1", title="基本信息", status="filled")],
            decision="finish",
            done=True,
            reason="全部完成",
        ),
    ]
    actor_script = [
        ActionBatch(
            actions=[
                Action(type="input_text", element_index=0, value="张三", reason="填姓名"),
                Action(type="input_text", element_index=1,
                       value="zhangsan@example.com", reason="填邮箱"),
            ],
            section_complete=True,
            summary="填写姓名与邮箱",
        ),
    ]
    validator_script = [
        ValidatorOutput(
            passed=True,
            section_complete=True,
            field_results=[
                FieldCheck(label="姓名", expected="张三", actual="张三", passed=True),
                FieldCheck(label="邮箱", expected="zhangsan@example.com",
                           actual="zhangsan@example.com", passed=True),
            ],
        ),
    ]
    validator_client = scripted(validator_script)
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted(actor_script),
        "validator": validator_client,
    })
    events = []
    runner = AgentRunner(
        task_id="t1",
        task_instruction="填写这份申请表",
        driver=driver,
        router=router,
        executor=ActionExecutor(driver),
        profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    assert runner.state == "AWAITING_REVIEW"
    assert driver.opened_url == "https://example.com/apply"
    assert driver.values[0] == "张三"  # 真实执行器写入 FakeDriver
    assert report.counts()["filled"] == 2
    assert report.counts()["failed"] == 0
    # 程序化校验：文本字段比对不走 LLM，Validator 未被调用
    assert validator_client.calls == 0
    kinds = [e.kind for e in events]
    assert "report" in kinds and "state" in kinds


@pytest.mark.asyncio
async def test_runner_wait_human_on_login(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = FakeDriver(make_observation())
    profile = build_sample_profile()
    gate_calls: list[str] = []

    async def gate(reason: str) -> None:
        gate_calls.append(reason)

    planner_script = [
        PlannerOutput(decision="wait_human", wait_human_reason="检测到登录页，请手动登录",
                      reason="登录墙"),
        PlannerOutput(decision="finish", done=True, reason="用户处理后完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(actions=[])]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    runner = AgentRunner(
        task_id="t2", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile, human_gate=gate,
    )
    await runner.run("https://example.com/login-first")
    assert gate_calls == ["检测到登录页，请手动登录"]
    assert runner.state == "AWAITING_REVIEW"


@pytest.mark.asyncio
async def test_runner_radio_fail_abandoned_not_loop() -> None:
    """单选点击后选中态读不到 → 程序化校验失败 → 连续失败自动放弃，不无限重试。"""
    radio_obs = PageObservation(
        url="https://example.com/apply",
        title="示例申请表",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="radio", label="男", selector="#male"),
        ],
    )
    driver = FakeDriver(radio_obs)
    profile = build_sample_profile()

    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="选择性别", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="结束后"),
    ]
    # FakeDriver.click 不改变 values → 回读选中态恒为空 → 程序化校验必失败
    actor_batch = ActionBatch(
        actions=[Action(type="click", element_index=0, reason="选择男")],
        section_complete=True, summary="选择性别",
    )
    validator_client = scripted([ValidatorOutput(passed=True)])
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([actor_batch]),
        "validator": validator_client,
    })
    runner = AgentRunner(
        task_id="t3", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        config=RunnerConfig(max_section_retries=3),
    )
    report = await runner.run("https://example.com/apply")
    # 字段连续失败达到阈值后放弃（记待确认），任务不中断、Validator LLM 未被调用
    assert report.counts()["pending_confirm"] >= 1
    assert validator_client.calls == 0
    assert runner.state == "AWAITING_REVIEW"


@pytest.mark.asyncio
async def test_runner_done_section_not_redispatched() -> None:
    """区块完成后 Planner 再派发同一区块应被跳过（防死循环）。"""
    driver = FakeDriver(make_observation())
    profile = build_sample_profile()
    dispatch = PlannerOutput(decision="dispatch_section", next_section_id="s1",
                             subtask_goal="填写基本信息", reason="派发")
    # Planner 永远想派 s1：第一次执行成功后，后续派发应被硬跳
    router = FakeRouter({
        "planner": scripted([dispatch]),
        "actor": scripted([ActionBatch(
            actions=[], section_complete=True, summary="完成",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t5", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        config=RunnerConfig(max_steps=5),
        on_event=events.append,
    )
    await runner.run("https://example.com/apply")
    summaries = [e.summary for e in events]
    assert any("跳过已处理区块" in s for s in summaries)
    # 反复重派同一区块达到上限后自动收尾，不再烧完剩余步数
    assert any("被反复重派" in s for s in summaries)
    assert runner.state == "AWAITING_REVIEW"


@pytest.mark.asyncio
async def test_runner_deterministic_date_validation() -> None:
    """日期字段程序化校验：2024-07 与 2024/7 等价，不需要 LLM。"""
    date_obs = PageObservation(
        url="https://example.com/apply",
        title="示例",
        sections=[SectionInfo(id="s1", title="教育经历", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="date", label="入学时间",
                      selector="#d", input_type="month"),
        ],
    )

    class DateDriver(FakeDriver):
        async def element_value(self, el: UIElement) -> str:
            return "2024/7"  # 站点回显格式与期望 2024-07 不同但等价

    driver = DateDriver(date_obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填日期", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    actor_batch = ActionBatch(
        actions=[Action(type="input_text", element_index=0, value="2024-07",
                        reason="填入学时间")],
        section_complete=True, summary="填日期",
    )
    validator_client = scripted([ValidatorOutput(passed=True)])
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([actor_batch]),
        "validator": validator_client,
    })
    runner = AgentRunner(
        task_id="t6", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
    )
    report = await runner.run("https://example.com/apply")
    assert report.counts()["filled"] >= 1
    assert report.counts()["failed"] == 0
    assert validator_client.calls == 0


@pytest.mark.asyncio
async def test_runner_reobserves_when_page_barren() -> None:
    """首屏观察无可交互元素（SPA 渲染中）：等待重观察，不白烧 Actor 重试轮。"""
    real_obs = make_observation()
    empty_obs = PageObservation(url="https://example.com/apply", title="加载中", elements=[])

    class SlowRenderDriver(FakeDriver):
        def __init__(self) -> None:
            super().__init__(empty_obs)
            self.observation = empty_obs

        async def observe(self, *, with_screenshot: bool = True, scroll_full: bool = True):
            self.calls.append(("observe", with_screenshot, scroll_full))
            # 第 1 次观察空（渲染中），其后返回真实表单
            if len([c for c in self.calls if c[0] == "observe"]) == 1:
                return empty_obs
            self.observation = real_obs
            return real_obs

    driver = SlowRenderDriver()
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写姓名",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t13", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    # 重观察后正常派发填写；等待渲染的动作确实发生
    assert report.counts()["filled"] >= 1
    assert any("重新观察" in e.summary for e in events)
    assert any(c == ("wait", 1.5) for c in driver.calls)
    # Planner 首次决策即拿到非空页面（没有浪费在空页面上）
    planner_events = [e.summary for e in events if e.agent == "planner"]
    assert planner_events[0].startswith("dispatch_section")


@pytest.mark.asyncio
async def test_runner_actor_llm_truncation_retries_not_fail() -> None:
    """Actor 输出超长被截断（LLMError）：压缩重试，不判任务失败。

    回归（真实站点）：整页字段多时模型试图一轮填完 → 触发长度上限 →
    "Could not parse response content as the length limit was reached"
    曾直接把任务置为 FAILED。
    """
    from autooffer_core.errors import LLMError

    class FlakyActorClient(ScriptedLLMClient):
        def __init__(self, good: ActionBatch) -> None:
            super().__init__([good])
            self.raised = False

        async def complete_json(self, messages, schema):  # type: ignore[no-untyped-def]
            if not self.raised:
                self.raised = True
                raise LLMError(
                    "LLM 调用失败: Could not parse response content "
                    "as the length limit was reached"
                )
            return await super().complete_json(messages, schema)

    driver = FakeDriver(make_observation())
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": FlakyActorClient(ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写姓名",
        )),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t14", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    assert runner.state == "AWAITING_REVIEW"  # 不再 FAILED
    assert report.counts()["filled"] >= 1      # 重试后成功填写
    assert any("Actor 输出异常" in e.summary for e in events)


@pytest.mark.asyncio
async def test_runner_planner_llm_failure_recovers() -> None:
    """Planner 单次 LLM 失败：稍候重试后继续；连续 3 次才按部分完成收尾。"""
    from autooffer_core.errors import LLMError

    class FlakyPlannerClient(ScriptedLLMClient):
        def __init__(self, script: list) -> None:
            super().__init__(list(script))
            self.raised = False

        async def complete_json(self, messages, schema):  # type: ignore[no-untyped-def]
            if not self.raised:
                self.raised = True
                raise LLMError("LLM 调用失败: 超时")
            return await super().complete_json(messages, schema)

    driver = FakeDriver(make_observation())
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": FlakyPlannerClient(planner_script),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写姓名",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t15", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    assert runner.state == "AWAITING_REVIEW"
    assert report.counts()["filled"] >= 1
    assert any("Planner 输出异常" in e.summary for e in events)


@pytest.mark.asyncio
async def test_runner_blocks_value_label_mismatch() -> None:
    """值-标签语义守卫：手机号填进"体重(公斤)"被拦截，并提示正确目标元素。

    回归（真实站点）：模型在长元素表上配错编号——出生日期区间填进身高框、
    手机号填进体重框。守卫按值形态（手机号/邮箱/证件/日期）拦截明确冲突，
    提示给出正确目标（#N(联系电话)）帮助下一轮自纠。
    """
    mismatch_obs = PageObservation(
        url="https://example.com/apply",
        title="基本信息",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=2)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="体重(公斤)", selector="#w"),
            UIElement(index=1, tag="input", role="input", label="联系电话", selector="#tel"),
            UIElement(index=2, tag="input", role="input", label="邮箱", selector="#mail"),
        ],
    )
    driver = FakeDriver(mismatch_obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    actor_batch = ActionBatch(
        actions=[
            Action(type="input_text", element_index=0, value="18881048355", reason="填电话"),
            Action(type="input_text", element_index=1, value="18881048355", reason="填电话"),
            Action(type="input_text", element_index=2, value="a@b.com", reason="填邮箱"),
        ],
        section_complete=True, summary="填写联系信息",
    )
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([actor_batch]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t16", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    # 手机号进体重框被拦截；电话与邮箱正常填写
    assert driver.values.get(0, "") == ""
    assert driver.values[1] == "18881048355"
    assert driver.values[2] == "a@b.com"
    assert report.counts()["filled"] == 2
    mismatch_events = [e.summary for e in events if "字段与值不匹配" in e.summary]
    assert mismatch_events, "应产生语义拦截事件"
    assert "#1(联系电话)" in mismatch_events[0]  # 提示给出正确目标


@pytest.mark.asyncio
async def test_runner_coerces_daterange_on_birth_field() -> None:
    """出生日期误发 set_date_range（end=null）：自动降级为单日期，不再找"至今"。"""
    from autooffer_core.profile.schema import DateYM

    birth_obs = PageObservation(
        url="https://example.com/apply",
        title="基本信息",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="date", label="出生日期",
                      selector="#birth", input_type="month"),
        ],
    )
    driver = FakeDriver(birth_obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写出生日期", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    actor_batch = ActionBatch(
        actions=[Action(
            type="set_date_range", element_index=0,
            date_range={"start": {"year": 2001, "month": 11}, "end": None},
            reason="填写出生日期",
        )],
        section_complete=True, summary="填出生日期",
    )
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([actor_batch]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t17", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    # 降级为单日期后正常填写并通过校验，任务不挂起等人工
    assert driver.values.get(0, "").startswith("2001-11") or driver.values.get(0, "") != ""
    assert report.counts()["filled"] == 1
    assert runner.state == "AWAITING_REVIEW"
    assert any("降级为单日期" in e.summary for e in events)
    assert DateYM(year=2001, month=11).year == 2001  # DateYM 可用性占位断言


@pytest.mark.asyncio
async def test_runner_finish_advances_wizard_before_ending() -> None:
    """Planner 判定 finish 时页面还有"下一步"：先翻页走完向导再结束。

    回归（真实站点）：基本信息填完后直接收尾退出，后续步骤（教育/工作经历）
    完全没填——用户要求走完全部步骤。
    """
    step1 = PageObservation(
        url="https://example.com/apply",
        title="向导",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#name"),
            UIElement(index=1, tag="button", role="button", label="下一步", selector="#next"),
        ],
    )
    step2 = PageObservation(
        url="https://example.com/apply",
        title="向导",
        sections=[SectionInfo(id="s2", title="教育经历", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="学校", selector="#school"),
        ],
    )

    class PagedDriver(FakeDriver):
        def __init__(self) -> None:
            super().__init__(step1)
            self._pages = [step1, step2]
            self._n = 0

        async def observe(self, *, with_screenshot: bool = True, scroll_full: bool = True):
            self.calls.append(("observe", with_screenshot, scroll_full))
            return self._pages[min(self._n, len(self._pages) - 1)]

        def next_page(self) -> None:
            self._n += 1

    driver = PagedDriver()
    orig_click = driver.click

    async def click(el):  # type: ignore[no-untyped-def]
        if el.index == 1:
            driver.next_page()  # 点下一步切换到第 2 页
        return await orig_click(el)

    driver.click = click  # type: ignore[assignment]
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="第 1 步完成"),
        PlannerOutput(decision="dispatch_section", next_section_id="s2",
                      subtask_goal="填写教育经历", reason="派发第 2 页"),
        PlannerOutput(decision="finish", done=True, reason="全部完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t18", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    # 第 1 页完成后没有直接结束：点了下一步，第 2 页的学校也填上了
    assert ("click", 1) in driver.calls
    assert driver.values.get(0) in ("张三", "某某大学")
    assert report.counts()["filled"] >= 2
    assert any("翻页" in e.summary for e in events)


@pytest.mark.asyncio
async def test_runner_auto_submit_when_enabled() -> None:
    """开启自动提交：全部填写完成后点击提交按钮（绕过敏感门禁），状态 DONE。"""
    submit_obs = PageObservation(
        url="https://example.com/apply",
        title="表单",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=1)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#name"),
            UIElement(index=1, tag="button", role="button", label="提交申请", selector="#submit"),
        ],
    )
    driver = FakeDriver(submit_obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t19", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        config=RunnerConfig(auto_submit=True),
        on_event=events.append,
    )
    await runner.run("https://example.com/apply")

    assert ("click", 1) in driver.calls  # 点了提交按钮（不经过门禁）
    assert runner.state == "DONE"
    assert any("自动提交" in e.summary for e in events)


@pytest.mark.asyncio
async def test_runner_auto_submit_off_keeps_review_state() -> None:
    """默认不自动提交：保持 AWAITING_REVIEW，绝不点击提交按钮。"""
    submit_obs = PageObservation(
        url="https://example.com/apply",
        title="表单",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#name"),
            UIElement(index=1, tag="button", role="button", label="提交申请", selector="#submit"),
        ],
    )
    driver = FakeDriver(submit_obs)
    profile = build_sample_profile()
    router = FakeRouter({
        "planner": scripted([
            PlannerOutput(decision="dispatch_section", next_section_id="s1",
                          subtask_goal="填写", reason="派发"),
            PlannerOutput(decision="finish", done=True, reason="完成"),
        ]),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    runner = AgentRunner(
        task_id="t20", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
    )
    await runner.run("https://example.com/apply")

    assert ("click", 1) not in driver.calls
    assert runner.state == "AWAITING_REVIEW"


@pytest.mark.asyncio
async def test_runner_advance_without_button_finishes_partial() -> None:
    """Planner 要翻页但无可见下一步按钮：按部分完成收尾，不判任务失败。

    回归（真实站点）：s1 填完后 Planner 误判 advance_page，找不到按钮直接把
    任务置为 FAILED，整份报告作废——违反"部分完成收尾"原则。
    """
    driver = FakeDriver(make_observation())
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="advance_page", reason="进入下一页"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写姓名",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t12", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    assert runner.state == "AWAITING_REVIEW"  # 不再 FAILED
    assert report.counts()["filled"] >= 1      # 已填字段保留在报告中
    assert any("按当前进度收尾" in e.summary for e in events)


@pytest.mark.asyncio
async def test_runner_max_steps_guardrail() -> None:
    driver = FakeDriver(make_observation())
    profile = build_sample_profile()
    # Planner 永远派发同一区块 → 靠 max_steps 护栏终止
    loop_plan = PlannerOutput(decision="dispatch_section", next_section_id="s1",
                              subtask_goal="填写", reason="循环")
    router = FakeRouter({
        "planner": scripted([loop_plan]),
        "actor": scripted([ActionBatch(actions=[], section_complete=False)]),
        "validator": scripted([ValidatorOutput(passed=False, retry_advice="重试")]),
    })
    runner = AgentRunner(
        task_id="t4", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        config=RunnerConfig(max_steps=3, max_section_retries=1),
    )
    report = await runner.run("https://example.com/apply")
    assert runner.state == "AWAITING_REVIEW"  # 安全终止仍产出报告
    assert report.task_id == "t4"


@pytest.mark.asyncio
async def test_runner_intercepts_repeated_combobox_click() -> None:
    """同一自定义下拉触发器反复点击（真实站点死循环）必须被拦截。

    回归：Actor 连续输出"点击类型选择框"裸 click，每次都执行成功（校验 passed）
    但控件值始终为空，无任何机制阻止重复——现在动作指纹登记后，值未变的
    触发器重复点击直接拦截，逼模型换动作（点选项/带值动作/skip）。
    """
    loop_obs = PageObservation(
        url="https://example.com/apply",
        title="示例",
        sections=[SectionInfo(id="s1", title="工作经历", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="div", role="combobox", label="类型", selector="#type"),
        ],
    )
    driver = FakeDriver(loop_obs)  # click 不改变任何状态 → 控件值恒空
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="选择类型", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    actor_batch = ActionBatch(
        actions=[Action(type="click", element_index=0, reason="点开类型下拉")],
        section_complete=False, summary="点击类型选择框",
    )
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([actor_batch]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t7", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        config=RunnerConfig(max_section_retries=3),
        on_event=events.append,
    )
    await runner.run("https://example.com/apply")

    summaries = [e.summary for e in events]
    assert any("拦截无进展的重复动作" in s for s in summaries)
    # 触发器只被真实点击一次，之后的重复输出全部被拦截
    assert driver.calls.count(("click", 0)) == 1
    assert runner.state == "AWAITING_REVIEW"
    # 审计落盘补齐：actor 事件带原始动作与页面信息
    actor_events = [e for e in events if e.agent == "actor"]
    assert actor_events[0].data["actions"][0]["type"] == "click"
    assert actor_events[0].data["actions"][0]["index"] == 0
    assert actor_events[0].data["url"]


@pytest.mark.asyncio
async def test_runner_advances_when_section_absent() -> None:
    """派发的区块不在当前页（多步表单未到该步）：自动点"下一步"翻页推进。"""
    wizard_obs = PageObservation(
        url="https://example.com/apply",
        title="向导",
        sections=[SectionInfo(id="s1", title="基本信息", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#name"),
            UIElement(index=1, tag="button", role="button", label="保存并下一步", selector="#next"),
        ],
    )
    driver = FakeDriver(wizard_obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s2",
                      subtask_goal="填写教育背景", reason="顺序派发下一区块"),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(actions=[])]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t8", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    await runner.run("https://example.com/apply")

    # s2 不在当前页：自动点击了可见的"保存并下一步"按钮
    assert ("click", 1) in driver.calls
    assert any("翻页" in e.summary for e in events)
    assert runner.state == "AWAITING_REVIEW"


@pytest.mark.asyncio
async def test_runner_no_sections_fallback_dispatch() -> None:
    """感知层未分段（sections 为空）时必须正常派发，不能判"区块不在当前页"。

    回归（真实站点）：Planner 自拟 s1/s2 编号与感知分段 id 对不上，曾导致
    表单明明在当前页却被记待确认、任务一步结束。
    """
    flat_obs = PageObservation(
        url="https://example.com/apply",
        title="表单",
        sections=[],
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#name"),
        ],
    )
    driver = FakeDriver(flat_obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(
            sections=[PlannedSection(id="s1", title="基本信息")],
            decision="dispatch_section", next_section_id="s1",
            subtask_goal="填写基本信息", reason="开始填写",
        ),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="张三",
                            reason="填姓名")],
            section_complete=True, summary="填写姓名",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t9", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    report = await runner.run("https://example.com/apply")

    # 正常派发并填写，绝不出现"不在当前页面"误判
    assert driver.values[0] == "张三"
    assert not any("不在当前页面" in e.summary for e in events)
    assert report.counts()["filled"] >= 1


@pytest.mark.asyncio
async def test_runner_absent_section_without_button_falls_back() -> None:
    """区块确实不在当前页且没有翻页按钮：回退正常派发，不直接记待确认杀死任务。"""
    step1_obs = PageObservation(
        url="https://example.com/apply",
        title="向导第1步",
        sections=[SectionInfo(id="sec-1", title="基本信息", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="姓名", selector="#name"),
        ],
    )
    driver = FakeDriver(step1_obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(
            sections=[PlannedSection(id="s1", title="基本信息"),
                      PlannedSection(id="s2", title="教育背景")],
            decision="dispatch_section", next_section_id="s2",
            subtask_goal="填写教育背景", reason="顺序派发",
        ),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(actions=[], section_complete=False)]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    events = []
    runner = AgentRunner(
        task_id="t10", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        on_event=events.append,
    )
    await runner.run("https://example.com/apply")

    # 无翻页按钮 → 回退派发：Actor 被调用（空动作轮兜底收尾），任务正常结束
    summaries = [e.summary for e in events]
    assert any(e.agent == "actor" for e in events)
    assert not any("不在当前页面" in s for s in summaries)
    assert runner.state == "AWAITING_REVIEW"


@pytest.mark.asyncio
async def test_runner_section_title_match_dispatches() -> None:
    """派发区块标题与感知分段标题吻合（id 不同）时按在页处理，正常派发。"""
    obs = PageObservation(
        url="https://example.com/apply",
        title="表单",
        sections=[SectionInfo(id="sec-edu", title="教育背景", element_start=0, element_end=0)],
        elements=[
            UIElement(index=0, tag="input", role="input", label="学校名称", selector="#school"),
        ],
    )
    driver = FakeDriver(obs)
    profile = build_sample_profile()
    planner_script = [
        PlannerOutput(
            sections=[PlannedSection(id="s2", title="教育背景")],
            decision="dispatch_section", next_section_id="s2",
            subtask_goal="填写教育背景", reason="派发教育背景",
        ),
        PlannerOutput(decision="finish", done=True, reason="完成"),
    ]
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([ActionBatch(
            actions=[Action(type="input_text", element_index=0, value="某某大学",
                            reason="填学校")],
            section_complete=True, summary="填写学校",
        )]),
        "validator": scripted([ValidatorOutput(passed=True)]),
    })
    runner = AgentRunner(
        task_id="t11", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
    )
    await runner.run("https://example.com/apply")

    assert driver.values[0] == "某某大学"  # 正常派发填写，未走翻页分支
    assert not any(c == ("click", 1) for c in driver.calls)
