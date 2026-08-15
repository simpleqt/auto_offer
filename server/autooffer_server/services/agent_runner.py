"""真实执行体：把 Agent Core 的 AgentRunner 适配为调度器的 TaskRunner。

桌面（有头）模式复用共享持久浏览器（登录态跨任务保留）；无头模式（测试/CI）每任务独立。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

log = structlog.get_logger(__name__)

if TYPE_CHECKING:  # 避免循环导入
    from autooffer_server.context import AppContext


class AgentTaskRunner:
    """调度器 → Agent Core 的适配层。"""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def run(
        self,
        *,
        task_id: str,
        url: str,
        profile_id: str,
        on_event: Any,
        human_gate: Any,
    ) -> dict[str, Any]:
        from autooffer_core.actions.executor import ActionExecutor
        from autooffer_core.applications import ApplicationStore
        from autooffer_core.profile.schema import Profile
        from autooffer_core.runner import AgentRunner

        payload = await self._ctx.repo.get_profile(profile_id)
        if payload is None:
            raise LookupError(f"档案不存在: {profile_id}")
        profile = Profile.model_validate(payload)

        async def _record_usage(record: Any) -> None:
            """把每次 LLM 调用写入 llm_usage 表（FR-M5 数据源）。"""
            await self._ctx.repo.add_llm_usage(
                {
                    "task_id": task_id,
                    "model": record.model,
                    "prompt_tokens": record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                    "total_tokens": record.total_tokens,
                    "latency_ms": record.latency_ms,
                    "success": int(record.success),
                    "error": record.error,
                }
            )

        router = await self._ctx.build_router(usage_sink=_record_usage)

        # 浏览器模式优先级：界面设置（settings.json）> 启动参数（config）
        settings = self._ctx.settings.get()
        browser_mode = settings.get("browser_mode", "managed")
        cdp_endpoint = settings.get("cdp_endpoint") or self._ctx.config.cdp_endpoint

        # 连接用户已有浏览器（CDP）：直接操作当前打开的页面，不新建页面
        if browser_mode == "cdp" and cdp_endpoint:
            from autooffer_core.drivers.playwright_driver import PlaywrightDriver

            driver = PlaywrightDriver(headless=False, cdp_endpoint=str(cdp_endpoint))
        # 软件自控共享浏览器（保留登录态）；无头模式每任务独立
        elif self._ctx.shared_browser is not None:
            driver = await self._ctx.shared_browser.new_driver()
        else:
            from autooffer_core.drivers.playwright_driver import PlaywrightDriver

            driver = PlaywrightDriver(headless=True)

        attachments = {a.label: a.path for a in profile.attachments}
        runner = AgentRunner(
            task_id=task_id,
            task_instruction="自动填写这份简历/求职表单；填完等待用户审核，不要提交。",
            driver=driver,
            router=router,
            executor=ActionExecutor(driver, attachments=attachments),
            profile=profile,
            on_event=on_event,
            human_gate=human_gate,
        )
        try:
            report = await runner.run(url)
        finally:
            # 共享模式只关本任务的页（保留共享浏览器）；无头模式整体释放
            await driver.close()

        # 填写完成自动登记投递列表
        store = ApplicationStore(self._ctx.config.data_dir / "applications.json")
        record = store.add_from_report(report, page_title=report.page_title)
        log.info("agent_runner.application_recorded", task_id=task_id, record_id=record.id)

        result: dict[str, Any] = report.model_dump()
        result["application_id"] = record.id
        return result
