"""真实场景复杂流程测试：真实 Chromium + 真实 Runner/执行器/控件处理器。

覆盖真实站点踩过的四类复杂流程（离线，无真实 LLM 依赖）：
1. 多步向导 + 自定义下拉弹层 + 原生 select + 月份日期 + 固定横幅遮挡输入框；
2. 可重复条目：点"添加"动态新增表单行后再填写（真实站点的"添加一条经历"流程）；
3. 站点预填核对（verify_and_fix）：一致跳过 / 错误纠正 / 空缺补填；
4. 顽固失败字段：连续失败自动放弃并按部分完成收尾（不无限重试、不判任务失败）。
"""

from __future__ import annotations

import pytest

from autooffer_core.agents.schemas import PlannedSection, PlannerOutput

from .conftest import build_flow_runner, flow_url


def _dispatch(sid: str, title: str, goal: str, strategy: str = "fill") -> PlannerOutput:
    return PlannerOutput(
        sections=[PlannedSection(id=sid, title=title)],
        decision="dispatch_section",
        next_section_id=sid,
        subtask_goal=goal,
        strategy=strategy,  # type: ignore[arg-type]
        reason="流程测试脚本派发",
    )


def _finish() -> PlannerOutput:
    return PlannerOutput(decision="finish", done=True, reason="全部完成")


@pytest.mark.asyncio
async def test_flow_multistep_wizard_custom_controls(flow_driver) -> None:
    """多步向导：第 1 步基本信息（遮挡输入/自定义性别下拉/月份/原生 select）→
    Planner 翻页 → 第 2 步教育经历 → 完成。程序化校验全程不调 LLM。"""
    planner_script = [
        _dispatch("s1", "基本信息", "填写基本信息"),
        PlannerOutput(decision="advance_page", reason="第 1 步完成，进入第 2 步"),
        _dispatch("s2", "教育经历", "填写教育经历"),
        _finish(),
    ]
    actor_rounds = [
        {"actions": [
            {"label": "姓名", "type": "input_text", "value": "陈志谦"},
            {"label": "手机", "type": "input_text", "value": "13800001111"},
            {"label": "性别", "type": "select_option", "value": "男"},
            {"label": "出生日期", "type": "input_text", "value": "2001-11"},
            {"label": "政治面貌", "type": "select_option", "value": "中共党员"},
        ], "complete": True, "summary": "填写基本信息"},
        {"actions": [
            {"label": "学校", "type": "input_text", "value": "杭州电子科技大学"},
            {"label": "学历", "type": "select_option", "value": "本科"},
            {"label": "入学时间", "type": "input_text", "value": "2019-09"},
        ], "complete": True, "summary": "填写教育经历"},
    ]
    events: list = []
    runner = build_flow_runner(
        flow_driver, planner_script=planner_script, actor_rounds=actor_rounds, events=events
    )
    report = await runner.run(flow_url("wizard_custom.html"))

    assert runner.state == "AWAITING_REVIEW"
    assert report.counts()["filled"] == 8  # 5 + 3 个字段全部回读通过
    assert report.counts()["failed"] == 0
    assert any("翻页" in e.summary for e in events)

    # 第 1 步字段随翻页隐藏（DOM 值已由报告回读断言），终态只断言第 2 步可见字段
    obs = await flow_driver.observe(with_screenshot=False, scroll_full=False)
    values = {e.label: e.value for e in obs.elements if e.label}
    assert values.get("学校") == "杭州电子科技大学"
    assert values.get("学历") == "本科"


@pytest.mark.asyncio
async def test_flow_repeatable_entry_add_then_fill(flow_driver) -> None:
    """可重复条目：先点"添加教育经历"（结构变化动作单发），下一轮在新行内填写。
    回归真实站点"点击添加一条经历"死循环场景：结构动作单独成轮后必须推进。"""
    planner_script = [
        _dispatch("s1", "教育经历", "添加并填写一条教育经历"),
        _finish(),
    ]
    actor_rounds = [
        {"actions": [
            {"label": "添加教育经历", "type": "click"},
        ], "complete": False, "summary": "添加一条教育经历"},
        {"actions": [
            {"label": "学校", "type": "input_text", "value": "宁波大学"},
            {"label": "学历", "type": "select_option", "value": "本科"},
            {"label": "开始时间", "type": "input_text", "value": "2018-09"},
            {"label": "结束时间", "type": "input_text", "value": "2022-06"},
        ], "complete": True, "summary": "填写新添加的教育经历"},
    ]
    events: list = []
    runner = build_flow_runner(
        flow_driver, planner_script=planner_script, actor_rounds=actor_rounds, events=events
    )
    report = await runner.run(flow_url("repeatable_entries.html"))

    assert runner.state == "AWAITING_REVIEW"
    # 4 个字段 + "添加"结构点击本身也记入 filled（值为"(点击)"）
    assert report.counts()["filled"] == 5
    assert report.counts()["failed"] == 0

    obs = await flow_driver.observe(with_screenshot=False, scroll_full=False)
    values = {e.label: e.value for e in obs.elements if e.label}
    assert values.get("学校") == "宁波大学"
    assert values.get("学历") == "本科"
    assert values.get("开始时间") == "2018-09"
    assert values.get("结束时间") == "2022-06"


@pytest.mark.asyncio
async def test_flow_verify_and_fix_prefilled(flow_driver) -> None:
    """站点预填核对模式：姓名一致（不输出动作，值保持原样）、邮箱纠错、城市补填。"""
    planner_script = [
        _dispatch("s1", "基本信息", "核对已预填的基本信息", strategy="verify_and_fix"),
        _finish(),
    ]
    actor_rounds = [
        {"actions": [
            {"label": "邮箱", "type": "input_text", "value": "chenzhiqian@qq.com"},
            {"label": "城市", "type": "input_text", "value": "杭州"},
        ], "complete": True, "summary": "纠正邮箱并补填城市"},
    ]
    runner = build_flow_runner(
        flow_driver, planner_script=planner_script, actor_rounds=actor_rounds, events=[]
    )
    report = await runner.run(flow_url("prefilled_verify.html"))

    assert runner.state == "AWAITING_REVIEW"
    counts = report.counts()
    assert counts["filled"] == 2  # 邮箱 + 城市
    assert counts["failed"] == 0

    obs = await flow_driver.observe(with_screenshot=False, scroll_full=False)
    values = {e.label: e.value for e in obs.elements if e.label}
    assert values.get("姓名") == "陈志谦"          # 一致字段未被触碰
    assert values.get("邮箱") == "chenzhiqian@qq.com"  # 错误已纠正
    assert values.get("城市") == "杭州"              # 空缺已补填


@pytest.mark.asyncio
async def test_flow_stubborn_field_abandoned_partial_finish(flow_driver) -> None:
    """顽固失败字段（站点脚本反复清空输入）：连续失败自动放弃记待确认，
    区块按部分完成收尾，任务不失败、不无限重试。"""
    planner_script = [
        _dispatch("s1", "基本信息", "填写基本信息"),
        _finish(),
    ]
    idcard_step = {"label": "证件号", "type": "input_text", "value": "330106200111130011"}
    actor_rounds = [
        {"actions": [
            {"label": "姓名", "type": "input_text", "value": "陈志谦"},
            idcard_step,
        ], "complete": True, "summary": "填写姓名与证件号"},
        {"actions": [
            {"label": "姓名", "type": "input_text", "value": "陈志谦"},
            idcard_step,
        ], "complete": True, "summary": "重试证件号"},
    ]
    events: list = []
    runner = build_flow_runner(
        flow_driver, planner_script=planner_script, actor_rounds=actor_rounds, events=events
    )
    report = await runner.run(flow_url("abandon_partial.html"))

    assert runner.state == "AWAITING_REVIEW"  # 不判 FAILED
    counts = report.counts()
    assert counts["filled"] >= 1              # 姓名成功
    assert counts["pending_confirm"] >= 1     # 证件号放弃记待确认
    assert any("部分字段已放弃" in e.summary for e in events)

    obs = await flow_driver.observe(with_screenshot=False, scroll_full=False)
    values = {e.label: e.value for e in obs.elements if e.label}
    assert values.get("证件号") == ""          # 站点清空后未被反复重填
