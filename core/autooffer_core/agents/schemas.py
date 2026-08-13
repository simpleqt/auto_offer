"""三个智能体的 LLM 输出契约（docs/02 §2.1、docs/03 §4.3）。

- PlannerOutput：Planner 的任务拆分 / 下一子任务 / 推进 / 流程策略 / 完成判定。
- Actor 输出直接使用契约 `autooffer_core.actions.models.ActionBatch`，不在此重复定义。
- ValidatorOutput：Validator 的单字段级校验结果与重试建议。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ChecklistStatus = Literal["pending", "filled", "failed", "pending_confirm"]
"""区块/字段级状态（memory/checklist 与 FillReport 的桥梁）。"""

SectionDecision = Literal[
    "dispatch_section",  # 派发一个区块子任务给 Actor
    "advance_page",      # 多步表单：点击"下一步"推进
    "wait_human",        # 需要人工介入（登录/验证码/授权等）
    "finish",            # 全部区块完成，结束任务（默认不自动提交）
    "fail",              # 无法继续，任务失败
]

FlowStrategy = Literal[
    "fill",               # 正常填写
    "verify_and_fix",     # 页面大量预填（简历解析/历史带出/草稿恢复）→ 逐区块核对
    "locate_apply_entry", # 职位列表/详情页 → 定位申请入口
]


class PlannedSection(BaseModel):
    """Planner 维护的区块级子任务（与感知层 SectionInfo 对齐）。"""

    id: str
    title: str
    repeatable: bool = False
    status: ChecklistStatus = "pending"


class PlannerOutput(BaseModel):
    """Planner 一轮决策的结构化输出。"""

    sections: list[PlannedSection] = []
    """全量区块计划（含状态），Runner 据此同步全局 checklist。"""

    decision: SectionDecision
    next_section_id: str | None = None
    """decision=dispatch_section 时要执行的区块 id。"""

    subtask_goal: str = ""
    """派给 Actor 的子任务目标（一句话，含填写范围与注意事项）。"""

    strategy: FlowStrategy = "fill"
    wait_human_reason: str | None = None
    """decision=wait_human 时给用户的说明。"""

    done: bool = False
    """完成判定：所有必填区块均已填写/核对完成。"""

    reason: str = ""
    """决策理由（审计用）。"""


class FieldCheck(BaseModel):
    """单个字段的回读校验结果。"""

    label: str
    expected: str | None = None
    actual: str | None = None
    passed: bool = True
    note: str | None = None


class ValidatorOutput(BaseModel):
    """Validator 对一个区块子任务的校验结论。"""

    passed: bool
    section_complete: bool = False
    """该区块子任务是否可判定完成。"""

    field_results: list[FieldCheck] = []
    retry_advice: str | None = None
    """未通过时给 Actor 的换策略建议（如"日期改直接键入"）。"""

    failure_reason: str | None = None
    """失败原因（记入报告与审计）。"""


class WriterOutput(BaseModel):
    """Writer Agent 的开放题回答（FR-A8）。"""

    answer: str
    used_qa_bank: bool = False
    """是否命中了问答知识库。"""

    note: str = ""
