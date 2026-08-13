"""控件处理器注册表：按 UIElement 特征选择 Handler（docs/03 §3.2）。

匹配顺序即优先级：级联先于普通下拉（级联 combobox 也满足下拉特征）。
"""

from __future__ import annotations

from autooffer_core.perception.models import UIElement
from autooffer_core.widgets.base import WidgetHandler
from autooffer_core.widgets.cascade import CascadeHandler
from autooffer_core.widgets.datepicker import DatePickerHandler
from autooffer_core.widgets.dropdown import DropdownHandler
from autooffer_core.widgets.radiocheck import RadioCheckHandler
from autooffer_core.widgets.richtext import RichTextHandler
from autooffer_core.widgets.upload import UploadHandler


class WidgetRegistry:
    """Handler 有序注册表。"""

    def __init__(self, handlers: list[WidgetHandler]) -> None:
        self._handlers = list(handlers)

    def handler_for(self, el: UIElement) -> WidgetHandler | None:
        for h in self._handlers:
            if h.match(el):
                return h
        return None

    @property
    def handlers(self) -> tuple[WidgetHandler, ...]:
        return tuple(self._handlers)


def default_registry() -> WidgetRegistry:
    """默认注册表（顺序即优先级）。"""
    return WidgetRegistry(
        [
            CascadeHandler(),
            DropdownHandler(),
            DatePickerHandler(),
            UploadHandler(),
            RadioCheckHandler(),
            RichTextHandler(),
        ]
    )
