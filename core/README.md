# AutoOffer Core（autooffer_core）

简历自动填写智能体的核心引擎，独立于服务层与界面层，可单独以 CLI 或代码引用运行。

## 职责

实现「感知 — 规划 — 执行 — 校验」的智能体循环，负责把一份结构化个人档案填写进任意招聘网站的简历表单。

## 公共接口

| 模块 | 职责 |
| --- | --- |
| `autooffer_core.runner` | `AgentRunner`：智能体主循环状态机（Planner → Actor → Validator） |
| `autooffer_core.profile` | `Profile` 档案模型、简历解析（`parse_resume`）、按需注入（`ProfileResolver`） |
| `autooffer_core.perception` | DOM 提取、label 归因、SoM 标注、站点场景检测 |
| `autooffer_core.actions` | 动作模型（`Action` / `ActionBatch`）与执行器、敏感动作门禁 |
| `autooffer_core.widgets` | 复杂控件处理器：下拉 / 日期 / 日期区间 / 级联 / 上传 / 单选复选 / 富文本 |
| `autooffer_core.drivers` | 执行环境驱动抽象，`PlaywrightDriver` 为默认实现 |
| `autooffer_core.llm` | `LLMClient` 封装、`ModelRouter` 角色路由、端点能力探测 |
| `autooffer_core.memory` | 任务记忆、字段 checklist、历史折叠 |
| `autooffer_core.report` | `FillReport` 填写报告契约 |
| `autooffer_core.applications` | 投递记录列表（本机 JSON 存储） |
| `autooffer_core.testing` | 供各层自测的 mock/fake（`FakeLLMClient`、`FakeDriver`、示例档案） |

核心类型与接口签名以 `docs/03-详细设计.md` 为契约，变更需评审并同步文档。

## 单独测试

```bash
pip install -e ".[dev]"
python -m pytest tests/unit -q              # 离线单元测试（无需模型/浏览器）
python -m pytest tests/integration -q       # 感知/控件集成测试（需 Chromium）
python -m pytest tests -m llm -q            # 基准表单集端到端（需真实模型端点，CI 默认跳过）
```

ruff 与 mypy：`ruff check core` / `mypy`（core 包 strict）。
