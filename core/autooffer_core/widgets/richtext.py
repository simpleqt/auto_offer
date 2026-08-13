"""富文本控件处理器（docs/03 §3.2）。

策略链：contenteditable 聚焦后键入 → 编辑器 API 注入兜底
（Quill/TinyMCE 等通过驱动层 evaluate 注入 innerHTML 并派发 input 事件）。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import structlog

from autooffer_core.errors import ActionError
from autooffer_core.perception.models import UIElement
from autooffer_core.widgets.base import ExecContext, FillResult

log = structlog.get_logger(__name__)


@runtime_checkable
class JSEvaluator(Protocol):
    """驱动层可选能力：执行 JS（PlaywrightDriver 实现；FakeDriver 不具备）。"""

    async def evaluate(self, script: str) -> object: ...


class RichTextHandler:
    """富文本（contenteditable / Quill / TinyMCE）。"""

    def match(self, el: UIElement) -> bool:
        return el.role == "richtext"

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        if not isinstance(target, str):
            raise ActionError(f"富文本目标必须为字符串: {target!r} (元素[{el.index}]{el.label})")

        # 策略 1：聚焦后键入
        try:
            await ctx.driver.click(el)
            await ctx.driver.input_text(el, target, humanize=ctx.humanize)
            got = await ctx.driver.element_value(el)
            if target[:10] in got:
                return FillResult(ok=True, strategy="type", detail=f"{len(target)}字")
        except Exception as exc:
            log.info("richtext.type_failed", label=el.label, error=str(exc))

        # 策略 2：编辑器 API / innerHTML 注入兜底
        if isinstance(ctx.driver, JSEvaluator):
            script = (
                "(() => {"
                f"const el = document.querySelector({el.selector!r});"
                "if (!el) return 'missing';"
                "if (window.Quill && el.__quill) { el.__quill.setText("
                f"{target!r}); return 'quill'; }}"
                "el.focus();"
                f"el.innerHTML = {target!r}.replace(/\\n/g, '<br>');"
                "el.dispatchEvent(new Event('input', {bubbles: true}));"
                "return 'dom';"
                ")()"
            )
            try:
                result = await ctx.driver.evaluate(script)
            except Exception as exc:
                log.warning("richtext.inject_failed", label=el.label, error=str(exc))
            else:
                if result != "missing":
                    return FillResult(
                        ok=True, strategy=f"inject:{result}", detail=f"{len(target)}字"
                    )

        return FillResult(
            ok=False, strategy="exhausted", detail=f"富文本填写失败: {el.label}", needs_human=True
        )
