"""感知模块：DOM 提取、SoM 标注、区块识别、场景检测。"""

from autooffer_core.errors import PerceptionError
from autooffer_core.perception.dom_extractor import DomExtractor
from autooffer_core.perception.models import (
    ElementRole,
    OverlayKind,
    PageObservation,
    PageScenario,
    PageType,
    PaginationInfo,
    SectionInfo,
    UIElement,
)
from autooffer_core.perception.scenario_detector import PageEvidence, ScenarioDetector
from autooffer_core.perception.scenario_rules import DEFAULT_RULES, ScenarioRule
from autooffer_core.perception.som_annotator import SomAnnotator

__all__ = [
    "DEFAULT_RULES",
    "DomExtractor",
    "ElementRole",
    "OverlayKind",
    "PageEvidence",
    "PageObservation",
    "PageScenario",
    "PageType",
    "PaginationInfo",
    "PerceptionError",
    "ScenarioDetector",
    "ScenarioRule",
    "SectionInfo",
    "SomAnnotator",
    "UIElement",
]
