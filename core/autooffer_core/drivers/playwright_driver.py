"""Driver 的 Playwright 实现（Chromium，async）。

- 感知委托 W1 感知模块：DomExtractor（完整 DOM 提取）+ ScenarioDetector（场景检测）
  + SomAnnotator（截图编号标注）。
- 人类化节奏（docs/03 §3.3）：按键 30–80ms 随机间隔，动作间 300–800ms 随机停顿。
- iframe 内元素按 frame_path（W1 约定：iframe 序号链，如 "0/1"）逐层定位。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import re
from pathlib import Path
from typing import Any

import structlog
from playwright.async_api import (
    Browser,
    BrowserContext,
    FrameLocator,
    Locator,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)

from autooffer_core.errors import DriverError
from autooffer_core.perception.dom_extractor import DomExtractor
from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.perception.scenario_detector import PageEvidence, ScenarioDetector
from autooffer_core.perception.som_annotator import SomAnnotator

log = structlog.get_logger(__name__)

class PlaywrightDriver:
    """Chromium 驱动。humanize=False 时跳过节奏停顿（测试用）。"""

    def __init__(
        self,
        *,
        headless: bool = True,
        humanize: bool = True,
        key_delay_ms: tuple[int, int] = (30, 80),
        action_delay_s: tuple[float, float] = (0.3, 0.8),
        viewport: tuple[int, int] = (1280, 900),
        user_data_dir: Path | str | None = None,
        existing_context: BrowserContext | None = None,
        cdp_endpoint: str | None = None,
    ) -> None:
        self._headless = headless
        self._humanize = humanize
        self._key_delay = key_delay_ms
        self._action_delay = action_delay_s
        self._viewport = viewport
        # SystemRandom：节奏抖动非安全用途，但避开伪随机告警（S311）
        self._rng = random.SystemRandom()
        # 持久 profile 目录（launch_persistent_context，登录态跨任务保留）
        self._user_data_dir = Path(user_data_dir) if user_data_dir else None
        # 复用外部持久上下文（桌面模式共享浏览器；此时 close 只关本页）
        self._existing_context = existing_context
        # 连接用户已有的浏览器（CDP）：复用其当前打开的页面，不新建页面/窗口
        self._cdp_endpoint = cdp_endpoint
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._extractor = DomExtractor()
        self._detector = ScenarioDetector()
        self._annotator = SomAnnotator()

    # ---------- 生命周期 ----------

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page
        try:
            # 连接用户已有的浏览器：复用当前打开的页面（不新建）
            if self._cdp_endpoint is not None:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.connect_over_cdp(self._cdp_endpoint)
                contexts = self._browser.contexts
                if not contexts:
                    raise DriverError("已连接的浏览器没有可用上下文")
                self._context = contexts[0]
                pages = self._context.pages
                if not pages:
                    self._page = await self._context.new_page()
                else:
                    self._page = pages[-1]  # 最近打开的标签页
                return self._page

            # 复用外部持久上下文（桌面模式：跨任务共享登录态）
            if self._existing_context is not None:
                self._context = self._existing_context
                self._page = await self._context.new_page()
                return self._page

            self._pw = await async_playwright().start()
            if self._user_data_dir is not None:
                self._context = await self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(self._user_data_dir),
                    headless=self._headless,
                    viewport={"width": self._viewport[0], "height": self._viewport[1]},
                )
                self._page = (
                    self._context.pages[0]
                    if self._context.pages
                    else await self._context.new_page()
                )
            else:
                self._browser = await self._pw.chromium.launch(headless=self._headless)
                self._context = await self._browser.new_context(
                    viewport={"width": self._viewport[0], "height": self._viewport[1]}
                )
                self._page = await self._context.new_page()
        except PlaywrightError as exc:
            raise DriverError(f"浏览器启动失败: {exc}") from exc
        return self._page

    async def open(self, url: str) -> None:
        page = await self._ensure_page()
        # 连接用户浏览器时复用当前页面：若已在浏览某页面（可能已登录），不强制跳转
        if self._cdp_endpoint is not None and page.url and not page.url.startswith("about:"):
            log.info("driver.reuse_page", url=page.url)
            return
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except PlaywrightError as exc:
            raise DriverError(f"页面打开失败 {url}: {exc}") from exc
        log.info("driver.opened", url=url)

    async def close(self) -> None:
        # 连接用户浏览器：只断开 Playwright，不关闭用户浏览器
        if self._cdp_endpoint is not None:
            if self._pw is not None:
                await self._pw.stop()
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None
            return
        # 复用外部上下文时只关本页，保留共享浏览器与登录态
        if self._existing_context is not None:
            if self._page is not None:
                with contextlib.suppress(PlaywrightError):
                    await self._page.close()
            self._page = None
            self._context = None
            return
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None

    # ---------- 感知 ----------

    async def observe(
        self, *, with_screenshot: bool = True, scroll_full: bool = True
    ) -> PageObservation:
        page = await self._ensure_page()
        obs, meta = await self._extractor.extract_with_meta(page, scroll_full=scroll_full)

        # 场景检测：用提取时收集的页面证据（正文/遮罩文本/可填字段数）
        signals = meta.get("signals", {})
        stats = meta.get("stats", {})
        evidence = PageEvidence(
            body_text=str(signals.get("body_text", "")),
            overlay_texts=[
                str(o.get("text", "")) for o in signals.get("overlays", []) if o.get("text")
            ],
            form_field_count=int(stats.get("fillable", 0)),
        )
        scenario = self._detector.detect(obs, evidence)
        scenario = scenario.model_copy(
            update={"prefilled_ratio": obs.scenario.prefilled_ratio}
        )
        obs = obs.model_copy(update={"scenario": scenario})

        if with_screenshot:
            shot = await self.screenshot()
            try:
                annotated = self._annotator.annotate(shot, obs.elements)
            except Exception:  # 标注失败不阻塞感知，退回原始截图
                log.warning("som_annotate_failed")
                annotated = shot
            obs = obs.model_copy(update={"screenshot_som": annotated})
        return obs

    async def screenshot(self) -> bytes:
        page = await self._ensure_page()
        try:
            return await page.screenshot(type="png")
        except PlaywrightError as exc:
            raise DriverError(f"截图失败: {exc}") from exc

    # ---------- 定位 ----------

    def _locate(self, el: UIElement) -> Locator:
        if self._page is None:
            raise DriverError("浏览器未打开")
        scope: Page | FrameLocator = self._page
        if el.frame_path:
            # W1 约定：frame_path 为 iframe 序号链（如 "0/1"）；兼容选择器链
            for part in el.frame_path.replace(">>>", "/").split("/"):
                part = part.strip()
                if not part:
                    continue
                if part.isdigit():
                    scope = scope.locator("iframe").nth(int(part)).content_frame
                else:
                    scope = scope.frame_locator(part)
        return scope.locator(el.selector).first

    async def _pace(self) -> None:
        """动作间随机停顿（docs/03 §3.3 人类化节奏）。"""
        if self._humanize:
            await asyncio.sleep(self._rng.uniform(*self._action_delay))

    # ---------- 基础操作 ----------

    async def click(self, el: UIElement) -> None:
        try:
            await self._locate(el).click(timeout=5000)
        except PlaywrightError as exc:
            raise DriverError(f"点击失败 [{el.label}]: {exc}") from exc
        await self._pace()

    async def input_text(self, el: UIElement, text: str, *, humanize: bool = True) -> None:
        loc = self._locate(el)
        try:
            await loc.click(timeout=5000)
            await loc.fill("")
            if humanize and self._humanize:
                await loc.press_sequentially(
                    text, delay=self._rng.uniform(*self._key_delay)
                )
            else:
                await loc.fill(text)
        except PlaywrightError as exc:
            raise DriverError(f"输入失败 [{el.label}]: {exc}") from exc
        await self._pace()

    async def select_option(self, el: UIElement, option: str) -> None:
        try:
            await self._locate(el).select_option(label=option, timeout=5000)
        except PlaywrightError as exc:
            raise DriverError(f"选项选择失败 [{el.label}] -> {option}: {exc}") from exc
        await self._pace()

    async def upload_file(self, el: UIElement, file_path: str) -> None:
        """三种入口形态（docs/03 §3.4）：input / file_chooser / dropzone。"""
        exists = await asyncio.to_thread(lambda: Path(file_path).is_file())
        if not exists:
            raise DriverError(f"上传文件不存在: {file_path}")
        page = await self._ensure_page()
        loc = self._locate(el)

        # 形态 1：input[type=file]（可见或隐藏覆盖式）
        if el.tag == "input":
            try:
                await loc.set_input_files(file_path, timeout=5000)
                await self._pace()
                return
            except PlaywrightError as exc:
                raise DriverError(f"文件注入失败 [{el.label}]: {exc}") from exc

        # 就近探测容器内隐藏 input（覆盖式上传常见结构）
        nearby = loc.locator("xpath=ancestor::*[self::div or self::label][1]//input[@type='file']")
        try:
            if await nearby.count() > 0:
                await nearby.first.set_input_files(file_path, timeout=3000)
                await self._pace()
                return
        except PlaywrightError:
            pass

        # 形态 2：点击按钮触发系统文件选择器
        try:
            async with page.expect_file_chooser(timeout=3000) as fc_info:
                await loc.click()
            chooser = await fc_info.value
            await chooser.set_files(file_path)
            await self._pace()
            return
        except PlaywrightError:
            pass

        # 形态 3：dropzone 拖拽（构造 DataTransfer 派发 drop）
        try:
            data = await page.evaluate_handle(
                "() => new DataTransfer()"
            )
            await loc.dispatch_event("drop", {"dataTransfer": data})
            await self._pace()
            return
        except PlaywrightError as exc:
            raise DriverError(f"上传入口探测失败 [{el.label}]: {exc}") from exc

    async def scroll(self, delta_y: int) -> None:
        page = await self._ensure_page()
        await page.mouse.wheel(0, delta_y)
        await self._pace()

    async def press_key(self, key: str) -> None:
        page = await self._ensure_page()
        try:
            await page.keyboard.press(key)
        except PlaywrightError as exc:
            raise DriverError(f"按键失败 {key}: {exc}") from exc
        await self._pace()

    async def element_value(self, el: UIElement) -> str:
        loc = self._locate(el)
        try:
            # 单选/复选读"选中状态"而非 value 属性（对齐感知层约定：选中 "true"/未选 ""）。
            # browser-use #3437 的教训：读不到选中态会让智能体重复点击把状态切回去。
            if el.role in ("radio", "checkbox"):
                return await self._checked_state(loc)
            if el.tag in ("input", "textarea"):
                return await loc.input_value(timeout=3000)
            if el.tag == "select":
                selected = loc.locator("option:checked")
                if await selected.count() > 0:
                    return (await selected.first.inner_text()).strip()
                return ""
            return (await loc.inner_text(timeout=3000)).strip()
        except PlaywrightError:
            return ""

    async def _checked_state(self, loc: Locator) -> str:
        """读控件选中态：原生 input 用 is_checked；自定义组件读 aria-checked/状态类名。"""
        try:
            aria = await loc.get_attribute("aria-checked", timeout=2000)
            if aria is not None:
                return "true" if aria == "true" else ""
        except PlaywrightError:
            pass
        try:
            cls = await loc.get_attribute("class", timeout=2000) or ""
            if re.search(r"(checked|selected|active)", cls):
                return "true"
        except PlaywrightError:
            pass
        try:
            return "true" if await loc.is_checked(timeout=2000) else ""
        except PlaywrightError:
            return ""

    async def wait(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    # ---------- 扩展能力（非契约最小集，供富文本等兜底） ----------

    async def evaluate(self, script: str) -> object:
        page = await self._ensure_page()
        try:
            result: object = await page.evaluate(script)
        except PlaywrightError as exc:
            raise DriverError(f"JS 执行失败: {exc}") from exc
        return result

    async def evaluate_json(self, script: str) -> dict[str, Any]:
        raw = await self.evaluate(script)
        if isinstance(raw, dict):
            return raw
        parsed: dict[str, Any] = json.loads(str(raw))
        return parsed
