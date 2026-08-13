"""DOM 提取器：在 Playwright Page 上注入 dom_extract.js，产出 PageObservation。

长页面按视口分段滚动感知，跨视口元素按 (frame_path, selector) 去重合并。
bbox 统一为文档绝对坐标（CSS px），供 SoM 标注在整页截图上定位。
"""

from __future__ import annotations

import importlib.resources
from typing import Any, Literal

import structlog
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from autooffer_core.errors import PerceptionError
from autooffer_core.perception.models import (
    PageObservation,
    PaginationInfo,
    SectionInfo,
    UIElement,
)

logger = structlog.get_logger(__name__)

_JS_RESOURCE = "dom_extract.js"
_EVAL_EXPR = "window.__autooffer_extract({})"
_MAX_SCROLL_STEPS = 30


def _load_js() -> str:
    ref = importlib.resources.files("autooffer_core.perception").joinpath(_JS_RESOURCE)
    return ref.read_text(encoding="utf-8")


class DomExtractor:
    """在 Playwright Page 上执行 DOM 提取并解析为 PageObservation。"""

    def __init__(self, *, scroll_step_ratio: float = 0.9) -> None:
        self._js = _load_js()
        self._scroll_step_ratio = scroll_step_ratio

    async def extract(
        self, page: Page, *, scroll_full: bool = True, max_scroll_steps: int = _MAX_SCROLL_STEPS
    ) -> PageObservation:
        """执行一轮完整感知。scroll_full=False 时只感知当前视口。"""
        observation, _meta = await self.extract_with_meta(
            page, scroll_full=scroll_full, max_scroll_steps=max_scroll_steps
        )
        return observation

    async def extract_with_meta(
        self, page: Page, *, scroll_full: bool = True, max_scroll_steps: int = _MAX_SCROLL_STEPS
    ) -> tuple[PageObservation, dict[str, Any]]:
        """感知并返回 (PageObservation, 原始 meta)。

        meta 中的 signals（body_text/overlays/密码框等）供场景检测器使用，
        这些证据不属于 PageObservation 契约。
        """
        await self._inject(page)
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        meta: dict[str, Any] | None = None
        steps = max_scroll_steps if scroll_full else 1
        for _ in range(steps):
            raw = await self._run_extract(page)
            if raw is None:
                break
            meta = raw
            for el in raw.get("elements", []):
                key = (str(el.get("frame_path") or ""), str(el.get("selector") or ""))
                if key not in merged:
                    merged[key] = el
            scroll = raw.get("scroll", {})
            y = int(scroll.get("y", 0))
            vh = int(scroll.get("viewport", 0))
            height = int(scroll.get("height", 0))
            if not scroll_full or vh <= 0 or y + vh >= height - 2:
                break
            await page.mouse.wheel(0, int(vh * self._scroll_step_ratio))
            await page.wait_for_timeout(120)
        if meta is None:
            raise PerceptionError("dom_extract.js 执行失败，未返回数据")
        await self._scroll_top(page)
        observation = self._build_observation(meta, merged, url=page.url)
        logger.info(
            "dom_extracted",
            url=observation.url,
            elements=len(observation.elements),
            sections=len(observation.sections),
            prefilled_ratio=round(observation.scenario.prefilled_ratio, 3),
        )
        return observation, meta

    async def _inject(self, page: Page) -> None:
        try:
            await page.evaluate(self._js)
        except PlaywrightError as exc:
            raise PerceptionError(f"注入 dom_extract.js 失败: {exc}") from exc

    async def _run_extract(self, page: Page) -> dict[str, Any] | None:
        try:
            raw: Any = await page.evaluate(_EVAL_EXPR)
        except PlaywrightError as exc:
            logger.warning("dom_extract_eval_failed", error=str(exc))
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    async def _scroll_top(self, page: Page) -> None:
        try:
            await page.evaluate("window.scrollTo(0, 0)")
        except PlaywrightError:
            logger.warning("scroll_top_failed")

    def _build_observation(
        self,
        meta: dict[str, Any],
        merged: dict[tuple[str, str], dict[str, Any]],
        *,
        url: str = "",
    ) -> PageObservation:
        elements: list[UIElement] = []
        for idx, raw in enumerate(merged.values()):
            bbox_raw = raw.get("bbox") or [0, 0, 0, 0]
            bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
            elements.append(
                UIElement(
                    index=idx,
                    tag=str(raw.get("tag") or ""),
                    role=raw.get("role") or "custom",
                    label=str(raw.get("label") or ""),
                    value=str(raw.get("value") or ""),
                    options=raw.get("options"),
                    options_truncated=bool(raw.get("options_truncated", False)),
                    required=bool(raw.get("required", False)),
                    section_id=raw.get("section_id"),
                    bbox=bbox,
                    selector=str(raw.get("selector") or ""),
                    visible=bool(raw.get("visible", True)),
                    frame_path=raw.get("frame_path"),
                    placeholder=raw.get("placeholder"),
                    accept=raw.get("accept"),
                )
            )
        sections = self._build_sections(meta.get("sections", []), elements)
        pagination = self._build_pagination(
            meta.get("pagination") or {}, meta.get("elements", []), elements
        )
        scroll = meta.get("scroll", {})
        signals = meta.get("signals", {})
        return PageObservation(
            url=url,
            title=str(signals.get("title") or ""),
            sections=sections,
            elements=elements,
            pagination=pagination,
            scroll_y=int(scroll.get("y", 0)),
            scroll_height=int(scroll.get("height", 0)),
            viewport_height=int(scroll.get("viewport", 0)),
            scenario=self._build_prefilled(meta),
        )

    def _build_sections(
        self, raw_sections: list[dict[str, Any]], elements: list[UIElement]
    ) -> list[SectionInfo]:
        sections: list[SectionInfo] = []
        for raw in raw_sections:
            sid = str(raw.get("id") or "")
            idxs = [e.index for e in elements if e.section_id == sid]
            if not idxs:
                continue
            sections.append(
                SectionInfo(
                    id=sid,
                    title=str(raw.get("title") or ""),
                    element_start=min(idxs),
                    element_end=max(idxs),
                    repeatable=bool(raw.get("repeatable", False)),
                    collapsed=bool(raw.get("collapsed", False)),
                )
            )
        return sections

    def _build_pagination(
        self,
        raw: dict[str, Any],
        last_round_elements: list[dict[str, Any]],
        elements: list[UIElement],
    ) -> PaginationInfo:
        kind: Literal["single", "multi_step"] = (
            "multi_step" if raw.get("kind") == "multi_step" else "single"
        )
        # JS 的 next_button_index 是"本轮提取"内的编号；合并去重后需按
        # (frame_path, selector) 键映射回全局元素编号。
        mapped: int | None = None
        next_idx = raw.get("next_button_index")
        if isinstance(next_idx, int) and 0 <= next_idx < len(last_round_elements):
            raw_el = last_round_elements[next_idx]
            key = (
                str(raw_el.get("frame_path") or ""),
                str(raw_el.get("selector") or ""),
            )
            for el in elements:
                if (str(el.frame_path or ""), el.selector) == key:
                    mapped = el.index
                    break
        current = raw.get("current_step")
        total = raw.get("total_steps")
        return PaginationInfo(
            kind=kind,
            current_step=int(current) if isinstance(current, int) else None,
            total_steps=int(total) if isinstance(total, int) else None,
            next_button_index=mapped,
        )

    def _build_prefilled(self, meta: dict[str, Any]) -> Any:
        from autooffer_core.perception.models import PageScenario

        stats = meta.get("stats", {})
        fillable = int(stats.get("fillable", 0))
        filled = int(stats.get("filled", 0))
        ratio = (filled / fillable) if fillable > 0 else 0.0
        return PageScenario(prefilled_ratio=ratio)
