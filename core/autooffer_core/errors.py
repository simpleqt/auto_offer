"""异常层次（契约，docs/05-开发规范.md §1.1）。

所有 AutoOffer 抛出的异常必须继承 AutoOfferError，
便于上层（Runner/服务层）统一捕获与分类处理。
"""


class AutoOfferError(Exception):
    """AutoOffer 全部自定义异常的基类。"""


class PerceptionError(AutoOfferError):
    """感知模块错误（DOM 提取失败、页面不可解析等）。"""


class ActionError(AutoOfferError):
    """动作执行错误（控件处理器失败、定位失效等）。"""


class LLMError(AutoOfferError):
    """LLM 调用错误（网络、鉴权、结构化输出校验失败等）。"""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProfileError(AutoOfferError):
    """档案模块错误（解析失败、schema 校验失败等）。"""


class DriverError(AutoOfferError):
    """执行环境驱动错误（浏览器崩溃、页面导航失败等）。"""
