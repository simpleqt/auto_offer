"""供各 Workstream 自测的 mock / fake 实现。

依据 docs/06 并行开发原则 #3（Mock 解耦）：
子智能体不依赖真实模型端点或真实浏览器即可自测。
"""

from autooffer_core.testing.fakes import FakeDriver, FakeLLMClient, ScriptedLLMClient
from autooffer_core.testing.sample_profile import build_sample_profile

__all__ = [
    "FakeDriver",
    "FakeLLMClient",
    "ScriptedLLMClient",
    "build_sample_profile",
]
