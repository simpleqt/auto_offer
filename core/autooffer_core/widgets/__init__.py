"""复杂控件处理器（W2 实现）：下拉 / 日期 / 级联 / 上传 / 单选复选 / 富文本。

每个处理器实现 WidgetHandler 协议（见 docs/03 §3.2），内部按策略链降级。
"""

from autooffer_core.widgets.base import ExecContext, FillResult, WidgetHandler
from autooffer_core.widgets.cascade import CascadeHandler
from autooffer_core.widgets.datepicker import (
    DatePickerHandler,
    format_date,
    parse_placeholder_format,
)
from autooffer_core.widgets.daterange import DateRangeHandler
from autooffer_core.widgets.dropdown import DropdownHandler
from autooffer_core.widgets.matching import match_option, normalize_text
from autooffer_core.widgets.radiocheck import RadioCheckHandler
from autooffer_core.widgets.region import split_region_chain, standardize_region
from autooffer_core.widgets.registry import WidgetRegistry, default_registry
from autooffer_core.widgets.richtext import RichTextHandler
from autooffer_core.widgets.upload import (
    UploadHandler,
    UploadTask,
    compress_image_to_spec,
    parse_attachment_spec,
)

__all__ = [
    "CascadeHandler",
    "DatePickerHandler",
    "DateRangeHandler",
    "DropdownHandler",
    "ExecContext",
    "FillResult",
    "RadioCheckHandler",
    "RichTextHandler",
    "UploadHandler",
    "UploadTask",
    "WidgetHandler",
    "WidgetRegistry",
    "compress_image_to_spec",
    "default_registry",
    "format_date",
    "match_option",
    "normalize_text",
    "parse_attachment_spec",
    "parse_placeholder_format",
    "split_region_chain",
    "standardize_region",
]
