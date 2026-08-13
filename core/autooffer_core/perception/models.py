"""感知层数据模型（契约，docs/03 §2）。"""

from typing import Literal

from pydantic import BaseModel

ElementRole = Literal[
    "input", "textarea", "select", "button", "combobox", "radio",
    "checkbox", "date", "file", "richtext", "link", "custom",
]


class UIElement(BaseModel):
    index: int
    tag: str
    role: ElementRole
    label: str
    value: str = ""
    options: list[str] | None = None
    options_truncated: bool = False
    required: bool = False
    section_id: str | None = None
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    selector: str
    """内部执行用定位符，禁止进入模型提示词。"""
    visible: bool = True
    frame_path: str | None = None
    placeholder: str | None = None
    accept: str | None = None
    """file 控件的 accept 属性，供附件匹配。"""

    input_type: str | None = None
    """input 元素的原生 type（date/month/tel/email...），供控件处理器选择填值精度。"""


class SectionInfo(BaseModel):
    id: str
    title: str
    element_start: int
    element_end: int
    """所含元素的 index 闭区间 [start, end]。"""
    repeatable: bool = False
    collapsed: bool = False


PageType = Literal[
    "form", "login", "register", "job_list", "job_detail",
    "preview", "success", "error", "unknown",
]

OverlayKind = Literal[
    "cookie_banner", "privacy_consent", "captcha", "qr_login", "generic_modal",
]


class PageScenario(BaseModel):
    page_type: PageType = "unknown"
    blocking_overlays: list[OverlayKind] = []
    signals: list[str] = []
    prefilled_ratio: float = 0.0
    """已有值的表单字段占比，超阈值提示 Planner 进入 verify_and_fix 模式。"""


class PaginationInfo(BaseModel):
    kind: Literal["single", "multi_step"] = "single"
    current_step: int | None = None
    total_steps: int | None = None
    next_button_index: int | None = None


class PageObservation(BaseModel):
    url: str
    title: str
    scenario: PageScenario = PageScenario()
    sections: list[SectionInfo] = []
    elements: list[UIElement] = []
    pagination: PaginationInfo = PaginationInfo()
    screenshot_som: bytes | None = None
    scroll_y: int = 0
    scroll_height: int = 0
    viewport_height: int = 0
