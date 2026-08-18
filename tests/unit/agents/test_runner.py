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
