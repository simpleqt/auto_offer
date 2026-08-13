"""动作模型与执行注册。"""

from autooffer_core.actions.executor import ActionExecutor, ExecResult, ExecStatus
from autooffer_core.actions.guard import DEFAULT_SENSITIVE_WORDS, SensitiveActionGuard
from autooffer_core.actions.models import Action, ActionBatch, ActionType

__all__ = [
    "DEFAULT_SENSITIVE_WORDS",
    "Action",
    "ActionBatch",
    "ActionExecutor",
    "ActionType",
    "ExecResult",
    "ExecStatus",
    "SensitiveActionGuard",
]
