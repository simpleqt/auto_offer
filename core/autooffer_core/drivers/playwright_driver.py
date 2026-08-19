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

# 页内按文本点击可见叶子节点（弹层选项兜底）：感知层提取不到选项（嵌套结构/
# 未知面板类名/传送门渲染）时，在全文可见短文本叶子中按目标精确匹配并点击。
# 命中优先级：高 z-index 定位容器的叶子 > 弹层类名容器内的叶子 > 其它（取 DOM
# 靠后者，弹层常渲染在尾部）；combobox 触发器内部的展示文本降权（避免点到已选值）。
_CLICK_TEXT_JS = """
(arg) => {
  const targets = (arg.texts || []).map((t) => String(t).replace(/\\s+/g, ''));
  if (!targets.length) return null;
  const norm = (s) => String(s || '').replace(/\\s+/g, '');
  const visible = (el) => {
    const st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' ||
        st.visibility === 'collapse') return false;
    if (parseFloat(st.opacity || '1') === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.height < 80;
  };
  const POPUP_HINT = '[class*="popup"], [class*="dropdown"], [class*="menu"], ' +
    '[class*="popover"], [class*="panel"], [class*="picker"], [class*="select"], ' +
    '[class*="cascader"], [class*="option"], [role="listbox"], [role="option"]';
  const hits = [];
  for (const el of document.querySelectorAll('*')) {
    // 候选：纯文本叶子，或"自有文本节点 + 图标等无文本子元素"的选项
    // （<li>共青团员<i class=icon/></li> 形态：叶子规则匹配不到，需看直接文本节点）
    let t = norm(el.children.length === 0 ? el.innerText : '');
    if (!t) {
      let own = '';
      for (const n of el.childNodes) {
        if (n.nodeType === 3) own += n.nodeValue || '';
      }
      t = norm(own);
      if (t && norm(el.innerText) !== t) t = '';  // 含其它子元素文本的容器不算，防误配
    }
    if (!t || t.length > 40 || targets.indexOf(t) === -1) continue;
    if (!visible(el)) continue;
    let score = 0;
    if (el.closest(POPUP_HINT)) score += 100;
    let a = el.parentElement;
    while (a && a !== document.body) {
      const st = window.getComputedStyle(a);
      const z = parseInt(st.zIndex, 10);
      if ((st.position === 'absolute' || st.position === 'fixed') && !isNaN(z) && z >= 10) {
        score += 200;
        break;
      }
      a = a.parentElement;
    }
    if (el.closest('[role="combobox"]')) score -= 50;
    hits.push({ el: el, score: score, order: hits.length });
  }
  if (!hits.length) return null;
  hits.sort((x, y) => (y.score - x.score) || (y.order - x.order));
  const el = hits[0].el;
  el.scrollIntoView({ block: 'center' });
  el.click();
  return norm(el.innerText);
}
"""

# 页内按 label 邻近度消歧：选择器命中多个可见元素时，挑与目标 label 文本
# 相邻（label 包含/label.for/共同近祖 ≤6 层）的那个——与人工找"姓名"输入框
# 的方式一致。返回候选在 querySelectorAll 中的原始索引；无法判定返回 null。
_LABEL_DISAMBIGUATE_JS = """
(arg) => {
  const wanted = String(arg.label || '').trim();
  if (!wanted) return null;
  const nodes = Array.from(document.querySelectorAll(arg.sel));
  if (nodes.length < 2) return null;
  const visible = [];
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    const r = n.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const st = window.getComputedStyle(n);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    visible.push({ n: n, i: i });
  }
  if (visible.length === 0) return null;
  const norm = (s) => String(s || '').replace(/\\s+/g, '');
  const target = norm(wanted);
  const labelEls = [];
  for (const le of document.querySelectorAll('label')) {
    if (norm(le.textContent).indexOf(target) !== -1) labelEls.push(le);
  }
  if (labelEls.length === 0) {
    // 无 <label>：退而求其次，找文本与目标吻合（前缀包含）的短叶子元素
    for (const e of document.querySelectorAll('*')) {
      if (e.children.length === 0) {
        const t = norm(e.textContent);
        if (t && t.length <= 30 &&
            (t === target || t.indexOf(target) === 0 ||
             (target.indexOf(t) === 0 && t.length >= 2))) {
          labelEls.push(e);
          if (labelEls.length > 60) break;
        }
      }
    }
  }
  if (labelEls.length === 0) return null;
  const related = (ctrl) => {
    for (const le of labelEls) {
      if (le.contains(ctrl) || ctrl.contains(le)) return true;
      if (le.htmlFor) {
        const c = document.getElementById(le.htmlFor);
        if (c && (c === ctrl || c.contains(ctrl))) return true;
      }
      let a = ctrl.parentElement, hops = 0;
      while (a && hops < 6) {
        if (a.contains(le)) return true;
        a = a.parentElement; hops++;
      }
    }
    return false;
  };
  const hits = visible.filter((v) => related(v.n));
  if (hits.length === 0) return null;
  return hits[0].i;
}
"""


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

    async def _locate(self, el: UIElement) -> Locator:
        """定位元素并对齐本地浏览器自动化纪律：动手前确认唯一性。

        - count == 0：选择器在 DOM 结构变化后可能已失效。盲目重试同一选择器
          会卡死或点错；直接抛 DriverError，迫使上层重新观察页面再决策。
        - count > 1：先尝试 .filter(visible=True) 收紧（Playwright async API
          公开能力），仅保留可见元素以排除隐藏的占位/模板；收紧后仍 >1 则
          记录 structlog warning（含 selector 与 count）并回退 .first，
          保持兼容、不中断任务（错误的选择器总比卡死强，且留下日志供排查）。
        - count == 1：唯一命中，正常返回。

        返回值始终是单元素 Locator（.first），便于上层直接 click/fill，不破坏
        既有契约。注意 count() 反映当前 DOM 快照、不阻塞等待——定位失效多因
        页面已变更，与其久等不如直接报错让上层重新观察。
        """
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
        base = scope.locator(el.selector)
        try:
            count = await base.count()
        except PlaywrightError as exc:
            # count 本身也可能因页面导航/上下文销毁失败：等同定位失效处理
            raise DriverError(f"元素定位失败 [{el.label}]: {exc}") from exc

        if count == 0:
            raise DriverError(
                "元素未找到（选择器可能已失效，请重新观察页面）"
                f" [{el.label}] selector={el.selector!r}"
            )
        if count == 1:
            return base.first

        # count > 1：用可见性收紧，尽量排掉隐藏占位/模板节点
        narrowed = base.filter(visible=True)
        try:
            narrowed_count = await narrowed.count()
        except PlaywrightError:
            narrowed_count = count  # 收紧失败则按未收紧处理，避免二次抛错

        if narrowed_count == 1:
            return narrowed.first
        if narrowed_count == 0:
            # 收紧后全不可见——说明匹配到的都是隐藏节点。仍回退首个原始命中，
            # 但与 count>1 一致地记 warning，交由上层决策（可能是选择器过宽）。
            narrowed = base
            narrowed_count = count
        # 仍歧义：按 label 邻近度在页内挑出目标元素（人工找控件的语义方式）。
        # 挑不中才回退 .first——错误选择器配合执行器预检会快速失败并留下日志。
        if el.label and el.frame_path is None:
            picked = await self._pick_by_label(el.selector, el.label)
            if picked is not None:
                log.info(
                    "driver.locate_label_disambiguated",
                    selector=el.selector,
                    label=el.label,
                    picked=picked,
                    count=narrowed_count,
                )
                return base.nth(picked)
        log.warning(
            "driver.locate_ambiguous",
            selector=el.selector,
            label=el.label,
            count=count,
            narrowed_count=narrowed_count,
        )
        return narrowed.first

    async def _pick_by_label(self, selector: str, label: str) -> int | None:
        """页内 label 邻近度消歧；返回候选原始索引，无法判定/出错返回 None。

        尽力而为的辅助路径：任何异常（页面导航中、evaluate 不可用等）都静默
        回退到调用方 .first 兜底——消歧失败后必有 locate_ambiguous warning 留痕。
        """
        if self._page is None:
            return None
        try:
            res = await self._page.evaluate(
                _LABEL_DISAMBIGUATE_JS, {"sel": selector, "label": label}
            )
            return int(res) if isinstance(res, (int, float)) else None
        except Exception:  # noqa: BLE001
            return None

    async def _pace(self) -> None:
        """动作间随机停顿（docs/03 §3.3 人类化节奏）。"""
        if self._humanize:
            await asyncio.sleep(self._rng.uniform(*self._action_delay))

    # ---------- 基础操作 ----------

    async def click(self, el: UIElement) -> None:
        try:
            loc = await self._locate(el)
            try:
                await loc.click(timeout=5000)
            except PlaywrightError as exc:
                # 浮层/横幅拦截指针事件：force 绕过动作性检查重试一次
                # （点击坐标落点不受遮挡影响，语义目标仍是该元素）
                log.info("driver.click_force_retry", label=el.label, error=str(exc)[:80])
                await loc.click(timeout=2000, force=True)
        except PlaywrightError as exc:
            raise DriverError(f"点击失败 [{el.label}]: {exc}") from exc
        await self._pace()

    async def input_text(self, el: UIElement, text: str, *, humanize: bool = True) -> None:
        loc = await self._locate(el)
        try:
            try:
                # 点击只为聚焦（模拟人工先点再输）；fill 自带聚焦，被浮层遮挡时
                # 没必要耗满长超时——1.5s 等不到就直接跳过点击进入填写
                await loc.click(timeout=1500)
            except PlaywrightError as exc:
                # 点击被浮层拦截：fill 自带聚焦（不经过指针命中检测），跳过点击直接填
                log.info("driver.input_skip_click", label=el.label, error=str(exc)[:80])
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
            loc = await self._locate(el)
            await loc.select_option(label=option, timeout=5000)
        except PlaywrightError as exc:
            raise DriverError(f"选项选择失败 [{el.label}] -> {option}: {exc}") from exc
        await self._pace()

    async def upload_file(self, el: UIElement, file_path: str) -> None:
        """三种入口形态（docs/03 §3.4）：input / file_chooser / dropzone。"""
        exists = await asyncio.to_thread(lambda: Path(file_path).is_file())
        if not exists:
            raise DriverError(f"上传文件不存在: {file_path}")
        page = await self._ensure_page()
        loc = await self._locate(el)

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
        loc = await self._locate(el)
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

    async def click_visible_text(self, texts: list[str]) -> str | None:
        """按文本点击可见叶子节点，返回命中文本；未命中返回 None。

        弹层选项兜底：自定义下拉面板已展开但感知层提取不到选项（嵌套结构、
        传送门渲染、面板类名不在提取提示内）时，直接在页面可见短文本叶子里
        精确匹配目标并点击。点击的是叶子节点，事件冒泡到选项处理器。
        """
        if self._page is None:
            raise DriverError("浏览器未打开")
        try:
            res = await self._page.evaluate(_CLICK_TEXT_JS, {"texts": texts})
        except PlaywrightError as exc:
            raise DriverError(f"文本点击失败: {exc}") from exc
        if res:
            await self._pace()
        return str(res) if res else None

    async def element_state(self, el: UIElement) -> dict[str, Any]:
        """动作后最便宜的"状态验证"查询（对齐本地实现的 locator 状态查询模式）。

        返回 {"checked": str, "disabled": bool, "expanded": bool|None}：
        - checked：复用 _checked_state，选中 "true"/未选 ""（与 element_value 对齐）。
        - disabled：读 aria-disabled 优先（自定义组件常用），回退原生 disabled 属性；
          任一为 "true"/真即判禁用，便于 Actor 在执行前预检并跳过。
        - expanded：读 aria-expanded，"true"->True、"false"->False、缺失/异常->None。

        全部用短超时读取，任一读取异常返回该字段的"安全默认值"（不抛错），
        让 Validator 拿到尽力而为的快照，而不是因单个属性读取失败中断校验循环。
        """
        loc = await self._locate(el)
        return {
            "checked": await self._checked_state(loc),
            "disabled": await self._disabled_state(loc),
            "expanded": await self._expanded_state(loc),
        }

    async def _disabled_state(self, loc: Locator) -> bool:
        """读禁用态：aria-disabled 优先（自定义组件），回退原生 disabled。"""
        try:
            aria = await loc.get_attribute("aria-disabled", timeout=2000)
            if aria is not None:
                # aria-disabled="true"/"True" 等均按真处理；其余视为未禁用
                return aria.strip().lower() == "true"
        except PlaywrightError:
            pass
        try:
            native = await loc.get_attribute("disabled", timeout=2000)
            # 原生 disabled：属性存在即禁用（"" 也算）
            return native is not None
        except PlaywrightError:
            return False

    async def _expanded_state(self, loc: Locator) -> bool | None:
        """读展开态 aria-expanded：true/false/缺失(None)。"""
        try:
            aria = await loc.get_attribute("aria-expanded", timeout=2000)
        except PlaywrightError:
            return None
        if aria is None:
            return None
        lowered = aria.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        return None

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
