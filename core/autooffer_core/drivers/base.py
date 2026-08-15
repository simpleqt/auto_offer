"""执行环境驱动抽象（契约，docs/02 §5、docs/03 §3）。

感知/执行层抽象为 Driver 接口，浏览器（Playwright）为默认实现；
预留纯视觉桌面 Driver（截图 + 坐标）扩展点。

Driver 面向智能体层暴露的是"观察页面"与"执行基础操作"两类能力。
所有定位均通过 UIElement.selector（感知时生成），智能体/模型层不接触坐标。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from autooffer_core.perception.models import PageObservation, UIElement


@runtime_checkable
class Driver(Protocol):
    """受控浏览/操作环境接口。

    实现方需保证：所有方法为协程；发生不可恢复错误时抛 DriverError。
    """

    async def open(self, url: str) -> None:
        """打开目标 URL（必要时启动浏览器/上下文）。"""
        ...

    async def observe(
        self, *, with_screenshot: bool = True, scroll_full: bool = True
    ) -> PageObservation:
        """感知当前页面，返回结构化观察（含可选 SoM 截图）。

        scroll_full=False 时只感知当前视口、不滚动页面（上传结果轮询等场景用）。
        """
        ...

    async def click(self, el: UIElement) -> None:
        """点击元素。"""
        ...

    async def input_text(self, el: UIElement, text: str, *, humanize: bool = True) -> None:
        """在输入框输入文本。humanize 控制是否使用人类化按键节奏。"""
        ...

    async def select_option(self, el: UIElement, option: str) -> None:
        """对原生 select 选择指定选项（按可见文本）。"""
        ...

    async def upload_file(self, el: UIElement, file_path: str) -> None:
        """对文件控件上传本地文件。"""
        ...

    async def scroll(self, delta_y: int) -> None:
        """滚动页面指定像素（正向下）。"""
        ...

    async def press_key(self, key: str) -> None:
        """按键（如 "Enter" / "Tab" / "Escape"）。"""
        ...

    async def screenshot(self) -> bytes:
        """当前视口截图（PNG 字节）。"""
        ...

    async def element_value(self, el: UIElement) -> str:
        """回读元素当前值（供 Validator 校验）。"""
        ...

    async def wait(self, seconds: float) -> None:
        """等待指定秒数。"""
        ...

    async def close(self) -> None:
        """关闭并释放资源。"""
        ...
