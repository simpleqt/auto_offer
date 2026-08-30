"""AutoOffer 智能体核心包（autooffer-core）。

独立的浏览器简历表单自动填写引擎，不依赖服务层/界面层，可单独以 CLI 运行。

包结构（契约见 docs/03-详细设计.md）：
- agents/      Planner / Actor / Validator / Writer 多智能体
- perception/  感知模块（DOM 提取、SoM 标注、场景检测）
- actions/     动作模型与执行注册
- widgets/     复杂控件处理器（下拉/日期/级联/上传等）
- drivers/     执行环境驱动抽象（Playwright 为默认实现）
- llm/         LLM 客户端、模型角色路由、能力探测
- profile/     档案 schema、简历解析、按需注入解析器
- memory/      任务记忆与 checklist
- testing/     供各 Workstream 自测的 mock/fake 实现
"""

__version__ = "0.2.14"

from autooffer_core.errors import (
    ActionError,
    AutoOfferError,
    LLMError,
    PerceptionError,
    ProfileError,
)

__all__ = [
    "__version__",
    "ActionError",
    "AutoOfferError",
    "LLMError",
    "PerceptionError",
    "ProfileError",
]
