"""测试替身：FakeDriver 与 FakeLLMClient / ScriptedLLMClient。

- FakeDriver：在内存中维护一份 PageObservation，记录所有执行过的动作，
  用于驱动多智能体循环、控件处理器的单元测试，无需真实浏览器。
- FakeLLMClient：返回固定响应；ScriptedLLMClient：按脚本顺序返回响应。
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from autooffer_core.llm.interfaces import ChatMessage, LLMResponse, LLMUsage
from autooffer_core.perception.models import PageObservation, UIElement


def _usage(prompt: str) -> LLMUsage:
    n = len(prompt) // 4
    return LLMUsage(prompt_tokens=n, completion_tokens=10, total_tokens=n + 10)


class FakeDriver:
    """内存版 Driver。observation 可由测试直接替换以推进"页面变化"。"""

    def __init__(self, observation: PageObservation | None = None) -> None:
        self.observation = observation or PageObservation(url="about:blank", title="")
        self.calls: list[tuple[str, object]] = []  # 动作调用流水
        self.opened_url: str | None = None
        self.values: dict[int, str] = {}  # element_index -> 已输入的值
        self.closed = False

    # ---- 测试辅助 ----
    def set_observation(self, obs: PageObservation) -> None:
        self.observation = obs

    # ---- Driver 接口 ----
    async def open(self, url: str) -> None:
        self.opened_url = url
        self.observation.url = url
        self.calls.append(("open", url))

    async def observe(self, *, with_screenshot: bool = True) -> PageObservation:
        self.calls.append(("observe", with_screenshot))
        return self.observation

    def _find(self, el: UIElement) -> UIElement:
        return el

    async def click(self, el: UIElement) -> None:
        self.calls.append(("click", el.index))

    async def input_text(self, el: UIElement, text: str, *, humanize: bool = True) -> None:
        self.values[el.index] = text
        self.calls.append(("input_text", (el.index, text)))

    async def select_option(self, el: UIElement, option: str) -> None:
        self.values[el.index] = option
        self.calls.append(("select_option", (el.index, option)))

    async def upload_file(self, el: UIElement, file_path: str) -> None:
        self.calls.append(("upload_file", (el.index, file_path)))

    async def scroll(self, delta_y: int) -> None:
        self.calls.append(("scroll", delta_y))

    async def press_key(self, key: str) -> None:
        self.calls.append(("press_key", key))

    async def screenshot(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n"  # 最小占位

    async def element_value(self, el: UIElement) -> str:
        return self.values.get(el.index, "")

    async def wait(self, seconds: float) -> None:
        self.calls.append(("wait", seconds))

    async def close(self) -> None:
        self.closed = True
        self.calls.append(("close", None))


class FakeLLMClient:
    """固定响应 LLM。response 可为字符串或 BaseModel。"""

    supports_vision: bool = False

    def __init__(self, response: str | BaseModel = "") -> None:
        self.response = response
        self.messages_seen: list[list[ChatMessage]] = []

    async def complete(self, messages: list[ChatMessage]) -> LLMResponse:
        self.messages_seen.append(messages)
        text = self.response if isinstance(self.response, str) else self.response.model_dump_json()
        return LLMResponse(text=text, usage=_usage(messages[-1].content if messages else ""))

    async def complete_json(
        self, messages: list[ChatMessage], schema: type[BaseModel]
    ) -> BaseModel:
        self.messages_seen.append(messages)
        if isinstance(self.response, BaseModel):
            return self.response
        if isinstance(self.response, str):
            return schema.model_validate_json(self.response)
        raise TypeError("FakeLLMClient.response 无法解析为目标 schema")


class ScriptedLLMClient:
    """按脚本顺序返回响应；脚本元素为 (文本) 或 (BaseModel)。耗尽后复用最后一个。"""

    supports_vision: bool = False

    def __init__(
        self,
        script: list[str | BaseModel],
        on_json: Callable[[type[BaseModel], str | BaseModel], BaseModel] | None = None,
    ) -> None:
        self.script = script
        self.on_json = on_json
        self.calls = 0
        self.messages_seen: list[list[ChatMessage]] = []

    def _next(self) -> str | BaseModel:
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return item

    async def complete(self, messages: list[ChatMessage]) -> LLMResponse:
        self.messages_seen.append(messages)
        item = self._next()
        text = item if isinstance(item, str) else item.model_dump_json()
        return LLMResponse(text=text, usage=_usage(messages[-1].content if messages else ""))

    async def complete_json(
        self, messages: list[ChatMessage], schema: type[BaseModel]
    ) -> BaseModel:
        self.messages_seen.append(messages)
        item = self._next()
        if self.on_json is not None:
            return self.on_json(schema, item)
        if isinstance(item, BaseModel):
            return item
        return schema.model_validate_json(item)
