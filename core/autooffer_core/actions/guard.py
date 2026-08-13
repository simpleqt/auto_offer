"""敏感动作门禁（FR-A11，docs/03 §3.3）。

click 动作的目标元素 label/文本命中敏感词（提交/确认投递/发送/支付/删除/submit
等，中英）时，转为需人工确认——默认不自动提交（docs/05 §5 行为红线）。
敏感词表可配置。
"""

from __future__ import annotations

from autooffer_core.actions.models import Action
from autooffer_core.perception.models import UIElement

DEFAULT_SENSITIVE_WORDS: tuple[str, ...] = (
    "提交",
    "确认投递",
    "确认提交",
    "立即投递",
    "发送",
    "支付",
    "删除",
    "注销",
    "submit",
    "confirm",
    "send",
    "pay",
    "delete",
    "apply now",
)


class SensitiveActionGuard:
    """敏感动作门禁。words 为 None 时使用默认词表。"""

    def __init__(self, words: list[str] | tuple[str, ...] | None = None) -> None:
        self._words = tuple(w.lower() for w in (words or DEFAULT_SENSITIVE_WORDS))

    @property
    def words(self) -> tuple[str, ...]:
        return self._words

    def hit_word(self, text: str) -> str | None:
        """返回命中的敏感词；未命中返回 None。"""
        norm = "".join(text.split()).lower()
        for w in self._words:
            if w in norm:
                return w
        return None

    def check(self, action: Action, el: UIElement | None) -> str | None:
        """检查动作是否敏感。返回命中的敏感词（需人工确认），否则 None。

        只拦截 click；其余动作类型不拦截。
        """
        if action.type != "click" or el is None:
            return None
        return self.hit_word(f"{el.label} {el.value}")
