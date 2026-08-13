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
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted(actor_script),
        "validator": scripted(validator_script),
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
async def test_runner_section_retry_then_fail_recorded() -> None:
    driver = FakeDriver(make_observation())
    profile = build_sample_profile()

    planner_script = [
        PlannerOutput(decision="dispatch_section", next_section_id="s1",
                      subtask_goal="填写基本信息", reason="派发"),
        PlannerOutput(decision="finish", done=True, reason="放弃该区块后结束"),
    ]
    actor_batch = ActionBatch(
        actions=[Action(type="input_text", element_index=0, value="张三", reason="填姓名")],
        section_complete=True, summary="尝试填写",
    )
    failed_validation = ValidatorOutput(
        passed=False,
        field_results=[FieldCheck(label="姓名", expected="张三", actual="", passed=False)],
        retry_advice="请重试",
    )
    router = FakeRouter({
        "planner": scripted(planner_script),
        "actor": scripted([actor_batch]),
        "validator": scripted([failed_validation]),
    })
    runner = AgentRunner(
        task_id="t3", task_instruction="x", driver=driver, router=router,
        executor=ActionExecutor(driver), profile=profile,
        config=RunnerConfig(max_section_retries=2),
    )
    report = await runner.run("https://example.com/apply")
    # 区块重试用尽后记入失败清单，任务不中断
    labels = [f.label for f in report.fields]
    assert any("区块:基本信息" in label for label in labels)
    assert report.counts()["failed"] >= 1


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
