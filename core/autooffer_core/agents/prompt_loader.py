"""提示词模板加载与紧凑文本格式化。

提示词文本只存在于 prompts/ 目录下的 Jinja2 模板（docs/05 §1.1）；
本模块只负责加载模板与把结构化数据格式化为紧凑文本（元素表/场景行），
不产生任何提示词语句。
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from autooffer_core.perception.models import PageObservation, PageScenario, UIElement

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# 模板均为纯文本提示词（.j2，非 HTML），不存在 HTML 注入场景，
# 故对 html/xml 之外的模板显式不做转义。
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=select_autoescape(enabled_extensions=("html", "htm", "xml")),
)


def render_prompt(template_name: str, **context: object) -> str:
    """渲染 prompts/ 下的指定模板。"""
    return _ENV.get_template(template_name).render(**context)


def format_elements(elements: list[UIElement], *, max_options: int = 10) -> str:
    """把区块元素渲染为紧凑文本表（每行一个元素）。

    只暴露 element_index 与语义信息；selector 属于内部定位符，绝不进入提示词。
    控件状态（禁用/已展开/只读）内联为标记，对齐 ARIA 快照模式——
    模型无需截图即可"看见"状态。
    """
    lines: list[str] = []
    for el in elements:
        parts = [f"#{el.index}", el.role, el.label or "(无标签)"]
        if el.required:
            parts.append("必填")
        if el.disabled:
            parts.append("禁用")
        if el.expanded is True:
            parts.append("已展开")
        if el.readonly:
            parts.append("只读")
        if el.placeholder:
            parts.append(f'占位:"{el.placeholder}"')
        if el.value:
            parts.append(f'当前值:"{el.value}"')
        if el.options:
            opts = el.options[:max_options]
            suffix = "…(截断)" if el.options_truncated or len(el.options) > max_options else ""
            parts.append(f"选项:[{'|'.join(opts)}{suffix}]")
        if el.role == "file" and el.accept:
            parts.append(f"接受格式:{el.accept}")
        if not el.visible:
            parts.append("不可见")
        lines.append(" ".join(parts))
    return "\n".join(lines) if lines else "(本区块暂无可交互元素)"


def format_scenario(scenario: PageScenario) -> str:
    """场景检测结果的一行式摘要，供 Planner 决策。"""
    overlays = ",".join(scenario.blocking_overlays) if scenario.blocking_overlays else "无"
    signals = "；".join(scenario.signals) if scenario.signals else "无"
    return (
        f"页面类型={scenario.page_type}；阻断遮罩={overlays}；"
        f"预填比例={scenario.prefilled_ratio:.0%}；命中信号={signals}"
    )


def format_observation_overview(obs: PageObservation) -> str:
    """页面区块结构概览（供 Planner；不含元素明细，明细留给 Actor）。"""
    if not obs.sections:
        return "(未识别到区块)"
    lines = []
    for s in obs.sections:
        flags: list[str] = []
        if s.repeatable:
            flags.append("可重复")
        if s.collapsed:
            flags.append("已折叠")
        flag_text = f" ({', '.join(flags)})" if flags else ""
        lines.append(f"- {s.id} 《{s.title}》 元素#{s.element_start}-#{s.element_end}{flag_text}")
    pagination = obs.pagination
    if pagination.kind == "multi_step":
        step_text = ""
        if pagination.current_step is not None and pagination.total_steps is not None:
            step_text = f"，当前第 {pagination.current_step}/{pagination.total_steps} 步"
        next_text = (
            f"，下一步按钮=#{pagination.next_button_index}"
            if pagination.next_button_index is not None
            else ""
        )
        lines.append(f"分页：多步表单{step_text}{next_text}")
    return "\n".join(lines)
