"""动作契约（docs/03 §3.1）。

模型（LLM）只输出动作 JSON，动作通过 element_index 引用感知层元素编号；
执行器将编号映射回 UIElement.selector 执行。模型永远不输出坐标或选择器，
这是对中小规模模型最稳的接口。
"""

from typing import Literal

from pydantic import BaseModel

from autooffer_core.profile.schema import DateRange, DateYM

ActionType = Literal[
    "input_text",      # 在输入框中输入文本
    "click",           # 点击（按钮/单选/复选/链接等）
    "select_option",   # 选择下拉选项（原生或自定义）
    "set_date",        # 设置单个日期
    "set_date_range",  # 设置日期区间（实习/项目起止）
    "upload_file",     # 上传附件（简历/证件照等）
    "scroll",          # 滚动页面
    "press_key",       # 按键（Enter/Tab/Escape 等）
    "wait",            # 等待（页面加载/解析）
    "done",            # 子任务/整体完成
    "ask_user",        # 需要人工介入（验证码/登录/授权）
    "request_profile", # 按需补取档案字段（见 docs/03 §1.3）
    "skip_field",      # 档案无值，记入待确认清单，禁止编造
]


class Action(BaseModel):
    type: ActionType
    element_index: int | None = None
    """目标元素编号（引用 PageObservation.elements[].index）。"""

    value: str | None = None
    """input_text / select_option 的目标值。"""

    date: DateYM | None = None
    date_range: DateRange | None = None
    attachment_label: str | None = None
    """upload_file：引用档案附件的用途标签（如"中文简历"）。"""

    profile_paths: list[str] | None = None
    """request_profile：请求的档案字段路径（如 ["extended.personality.hobbies"]）。"""

    reason: str = ""
    """一句话说明本动作意图（审计用，必填）。"""


class ActionBatch(BaseModel):
    """Actor 一轮输出的一批动作。

    约定：批内动作互不影响页面结构（纯填写可批量）；
    会改变页面结构的动作（展开下拉/切换步骤/添加条目）必须单步发出。
    """

    actions: list[Action]
    section_complete: bool = False
    """Actor 判断当前区块子任务是否已完成。"""

    summary: str = ""
    """本轮动作的一句话摘要（写入审计/事件流）。"""
