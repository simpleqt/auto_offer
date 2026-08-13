/* AutoOffer 感知层 DOM 提取脚本（契约：docs/03 §2.1）。
 *
 * 注入页面后调用 window.__autooffer_extract(opts) 返回可 JSON 序列化的提取结果。
 * opts: {
 *   maxOptions?: number     原生 select 选项截断阈值（默认 30）
 *   labelDistance?: number  邻近文本归因距离阈值 px（默认 150）
 *   maxElements?: number    单次提取元素上限（默认 2000）
 *   framePath?: string      当前 frame 链路（Python 侧处理跨域 iframe 时传入）
 *   origin?: {x, y}         当前 frame 视口原点在顶层文档中的坐标
 * }
 * 仅做通用提取与启发式标注，不含任何站点特定逻辑。
 */
(() => {
  if (window.__autooffer_extract) return; // 幂等注入

  const INTERACTIVE_SELECTOR = [
    "input:not([type=hidden])",
    "select",
    "textarea",
    "button",
    "a[href]",
    '[role="button"]',
    '[role="combobox"]',
    '[role="listbox"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="switch"]',
    '[role="textbox"]',
    '[role="spinbutton"]',
    '[role="slider"]',
    '[contenteditable]:not([contenteditable="false"])',
  ].join(",");

  const FILLABLE_ROLES = new Set([
    "input", "textarea", "select", "combobox", "date",
    "richtext", "custom", "radio", "checkbox",
  ]);
  const CUSTOM_CLASS_RE = /(select|picker|cascader|dropdown|combo)/i;
  const DATE_CLASS_RE = /(date-?picker|datetime|calendar|date-field)/i;
  const ADD_BUTTON_RE = /(添加|新增|再加一条|add\b|＋)/i;
  const NEXT_BUTTON_RE = /(下一步|保存并继续|继续填写|下一页|next step|continue)/i;
  const CARD_CLASS_RE = /(card|section|panel|module|block|group|fieldset|form-item|box)/i;
  const COLLAPSED_RE = /(collapsed|closed|folded|is-collapsed)/i;
  const STEP_ACTIVE_RE = /(active|current|is-active|processing|doing|on)\b/i;

  const cleanLabel = (t) =>
    (t || "")
      .replace(/\s+/g, " ")
      .replace(/^[\s*：:、.．]+|[\s*：:]+$/g, "")
      .trim()
      .slice(0, 60);

  const classChain = (el, depth = 3) => {
    // 控件类名常标注在包装容器上，向上取几层拼接
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && depth-- > 0) {
      if (typeof cur.className === "string") parts.push(cur.className);
      cur = cur.parentElement;
    }
    return parts.join(" ");
  };

  const isCssVisible = (el) => {
    const style = window.getComputedStyle(el);
    if (style.display === "none") return false;
    if (style.visibility === "hidden" || style.visibility === "collapse") return false;
    const rect = el.getBoundingClientRect();
    const isFile = el.tagName === "INPUT" && el.type === "file";
    if (parseFloat(style.opacity || "1") === 0 && !isFile) return false;
    if (rect.width < 1 || rect.height < 1) return isFile; // 覆盖式 file input 常 0 尺寸
    return true;
  };

  const detectRole = (el) => {
    const explicit = (el.getAttribute("role") || "").toLowerCase();
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (explicit === "combobox") return "combobox";
    if (explicit === "listbox") return "custom";
    if (explicit === "button") return "button";
    if (explicit === "checkbox" || explicit === "switch") return "checkbox";
    if (explicit === "radio") return "radio";
    if (explicit === "textbox" || explicit === "spinbutton" || explicit === "slider") {
      return "custom";
    }
    if (el.isContentEditable && tag !== "body" && tag !== "html") return "richtext";
    if (tag === "select") return "select";
    if (tag === "textarea") return "textarea";
    if (tag === "button") return "button";
    if (tag === "a") return "link";
    if (tag === "input") {
      if (type === "radio") return "radio";
      if (type === "checkbox") return "checkbox";
      if (["date", "datetime-local", "month", "time", "week"].includes(type)) return "date";
      if (type === "file") return "file";
      if (["submit", "button", "reset", "image"].includes(type)) return "button";
      const cls = classChain(el);
      // date-picker 类名同时含 "picker"，日期判定必须先于通用选择类
      if (DATE_CLASS_RE.test(cls)) return "date";
      if (CUSTOM_CLASS_RE.test(cls)) return "combobox";
      if (el.readOnly && /(select|picker|date|time)/i.test(cls)) return "combobox";
      return "input";
    }
    const cls = classChain(el);
    if (DATE_CLASS_RE.test(cls)) return "date";
    if (CUSTOM_CLASS_RE.test(cls)) return "combobox";
    return "custom";
  };

  const currentValue = (el, role) => {
    const tag = el.tagName.toLowerCase();
    if (role === "checkbox" || role === "radio") {
      const checked = el.checked === true || el.getAttribute("aria-checked") === "true";
      return checked ? "true" : "";
    }
    if (tag === "select") {
      const sel = el;
      const picked = [...sel.options].filter((o) => o.selected).map((o) => o.text.trim());
      return picked.join(", ").slice(0, 200);
    }
    if (role === "richtext") return (el.innerText || "").trim().slice(0, 200);
    if ("value" in el && typeof el.value === "string") return el.value.trim().slice(0, 200);
    return (el.innerText || "").trim().slice(0, 200);
  };

  const stableSelector = (el, doc) => {
    const unique = (sel) => {
      try {
        return doc.querySelectorAll(sel).length === 1;
      } catch {
        return false;
      }
    };
    const id = el.getAttribute("id");
    if (id) {
      const sel = `#${CSS.escape(id)}`;
      if (unique(sel)) return sel;
    }
    for (const attr of ["data-testid", "data-test", "data-cy", "data-qa", "data-field"]) {
      const v = el.getAttribute(attr);
      if (v) {
        const sel = `[${attr}="${CSS.escape(v)}"]`;
        if (unique(sel)) return sel;
      }
    }
    const name = el.getAttribute("name");
    if (name) {
      const sel = `${el.tagName.toLowerCase()}[name="${CSS.escape(name)}"]`;
      if (unique(sel)) return sel;
    }
    // 结构路径：逐级向上直到选择器在文档内唯一
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== doc.documentElement && parts.length < 6) {
      const tag = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const sameTag = [...parent.children].filter((c) => c.tagName === cur.tagName);
      const idx = sameTag.indexOf(cur) + 1;
      parts.unshift(sameTag.length > 1 ? `${tag}:nth-of-type(${idx})` : tag);
      const cand = parts.join(" > ");
      if (unique(cand)) return cand;
      cur = parent;
    }
    return parts.join(" > ");
  };

  const labelOwnText = (label, el) => {
    let t = "";
    label.childNodes.forEach((n) => {
      if (n.nodeType === 3) t += ` ${n.nodeValue}`;
      else if (n.nodeType === 1 && !n.contains(el) && !n.matches(INTERACTIVE_SELECTOR)) {
        t += ` ${n.innerText || ""}`;
      }
    });
    return t;
  };

  const overlap = (a1, a2, b1, b2) => Math.max(0, Math.min(a2, b2) - Math.max(a1, b1));

  const textNodeRect = (node) => {
    try {
      const range = node.ownerDocument.createRange();
      range.selectNodeContents(node);
      return range.getBoundingClientRect();
    } catch {
      const p = node.parentElement;
      return p ? p.getBoundingClientRect() : null;
    }
  };

  const collectTextLeaves = (node, selfEl, cb, depth) => {
    if (depth > 6 || !node) return;
    if (node.nodeType === 3) {
      const t = (node.nodeValue || "").trim();
      if (t) {
        const r = textNodeRect(node);
        if (r && r.width > 0 && r.height > 0) cb(t, r);
      }
      return;
    }
    if (node.nodeType !== 1) return;
    const el2 = node;
    if (el2 === selfEl) return;
    if (el2.contains(selfEl)) {
      el2.childNodes.forEach((k) => collectTextLeaves(k, selfEl, cb, depth + 1));
      return;
    }
    if (el2.matches && el2.matches(INTERACTIVE_SELECTOR)) return;
    if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|OPTION|OPTGROUP)$/.test(el2.tagName)) return;
    if (el2.querySelector && el2.querySelector(INTERACTIVE_SELECTOR)) return;
    if (el2.children.length === 0) {
      const t = (el2.innerText || "").trim();
      if (t) {
        const r = el2.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) cb(t, r);
      }
      return;
    }
    el2.childNodes.forEach((k) => collectTextLeaves(k, selfEl, cb, depth + 1));
  };

  const nearbyText = (el, labelDistance) => {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return { text: "", raw: "" };
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const isCheck = tag === "input" && (type === "checkbox" || type === "radio");
    let best = null;
    const consider = (rawText, r, allowRight) => {
      const text = cleanLabel(rawText);
      if (!text) return;
      const dx = Math.max(rect.left - r.right, r.left - rect.right, 0);
      const dy = Math.max(rect.top - r.bottom, r.top - rect.bottom, 0);
      const vOverlap = overlap(rect.top, rect.bottom, r.top, r.bottom);
      const hOverlap = overlap(rect.left, rect.right, r.left, r.right);
      const isLeft = r.right <= rect.left + 8 && vOverlap > 0.3 * Math.min(r.height, rect.height);
      const isAbove = r.bottom <= rect.top + 8 && hOverlap > 0;
      const isRight = allowRight && r.left >= rect.right - 4 && vOverlap > 0.3 * r.height;
      if (!isLeft && !isAbove && !isRight) return;
      const dist = Math.hypot(dx, dy);
      const limit = isRight ? 80 : labelDistance;
      if (dist <= limit && (!best || dist < best.dist)) best = { text, raw: rawText, dist };
    };
    // 左侧/上方：沿祖先链收集先前兄弟中的文本
    let node = el;
    let depth = 0;
    while (node && depth < 4) {
      let sib = node.previousSibling;
      while (sib) {
        collectTextLeaves(sib, el, (t, r) => consider(t, r, false), 0);
        sib = sib.previousSibling;
      }
      node = node.parentElement;
      depth += 1;
      if (node && /^(FORM|FIELDSET|SECTION|ARTICLE|BODY|HTML)$/.test(node.tagName)) break;
    }
    // 单选/复选：标签常在右侧
    if (isCheck) {
      let sib = el.nextSibling;
      while (sib) {
        collectTextLeaves(sib, el, (t, r) => consider(t, r, true), 0);
        sib = sib.nextSibling;
      }
    }
    return best ? { text: best.text, raw: best.raw } : { text: "", raw: "" };
  };

  const attributeLabel = (el, doc, labelDistance) => {
    if (el.id) {
      let lab = null;
      try {
        lab = doc.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      } catch {
        lab = null;
      }
      if (lab) {
        const raw = lab.innerText || "";
        const t = cleanLabel(raw);
        if (t) return { text: t, raw, source: "label-for" };
      }
    }
    const wrap = el.closest("label");
    if (wrap) {
      const raw = labelOwnText(wrap, el);
      const t = cleanLabel(raw);
      if (t) return { text: t, raw, source: "label-wrap" };
    }
    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const raw = labelledby
        .split(/\s+/)
        .map((id) => {
          const n = doc.getElementById(id);
          return n ? n.innerText || "" : "";
        })
        .join(" ");
      const t = cleanLabel(raw);
      if (t) return { text: t, raw, source: "aria-labelledby" };
    }
    const aria = el.getAttribute("aria-label");
    if (aria) {
      const t = cleanLabel(aria);
      if (t) return { text: t, raw: aria, source: "aria-label" };
    }
    const ph = el.getAttribute("placeholder") || el.getAttribute("data-placeholder");
    // 通用提示语式占位符（请输入/请选择…）语义弱于旁边的可见字段名，降级到邻近文本之后
    const genericPh =
      ph && /^(请(输入|选择|填写|上传)|please\b|select\b|enter\b|choose\b)/i.test(ph.trim());
    if (ph && !genericPh) return { text: cleanLabel(ph), raw: ph, source: "placeholder" };
    const near = nearbyText(el, labelDistance);
    if (near.text) return { text: near.text, raw: near.raw, source: "nearby" };
    if (ph) return { text: cleanLabel(ph), raw: ph, source: "placeholder" };
    return { text: "", raw: "", source: "none" };
  };

  const isRequired = (el, labelInfo) => {
    if (el.required || el.getAttribute("aria-required") === "true") return true;
    if (/\*/.test(labelInfo.raw || "")) return true;
    const wrap =
      el.closest("label") ||
      el.closest('[class*="form-item"], [class*="field"], [class*="row"], [class*="group"]');
    if (wrap) {
      const star = wrap.querySelector('[class*="required"], [class*="asterisk"], [class*="require"]');
      if (star && (star.innerText || "").includes("*")) return true;
    }
    return false;
  };

  const extractOptions = (el, role, maxOptions) => {
    let texts = [];
    if (el.tagName === "SELECT") {
      texts = [...el.options].map((o) => o.text.trim()).filter((t) => t);
    } else if (role === "custom" || role === "combobox") {
      // 已展开的 listbox 选项顺带采集
      const opts = el.querySelectorAll('[role="option"], [class*="option"], [class*="item"]');
      texts = [...opts]
        .filter((o) => o.children.length === 0)
        .map((o) => (o.innerText || "").trim())
        .filter((t) => t && t.length <= 40);
    }
    if (!texts.length) return { options: null, truncated: false };
    const truncated = texts.length > maxOptions;
    return { options: truncated ? texts.slice(0, maxOptions) : texts, truncated };
  };

  const detectSections = (doc, collected) => {
    const containers = [];
    const seen = new Set();
    const push = (c, titleEl) => {
      if (!c || seen.has(c)) return;
      seen.add(c);
      containers.push({ el: c, titleEl });
    };
    doc.querySelectorAll("fieldset").forEach((fs) => push(fs, fs.querySelector("legend")));
    doc.querySelectorAll("h1, h2, h3").forEach((h) => {
      // 标题在容器外的常见形态: <h2>教育经历</h2><div class="card">…控件…</div>
      const sib = h.nextElementSibling;
      if (
        sib &&
        !/^H[1-6]$/.test(sib.tagName) &&
        sib.querySelector &&
        sib.querySelector(INTERACTIVE_SELECTOR)
      ) {
        push(sib, h);
        return;
      }
      let cur = h.parentElement;
      let picked = null;
      for (let d = 0; cur && d < 5; d += 1, cur = cur.parentElement) {
        if (/^(FORM|BODY|HTML)$/.test(cur.tagName)) break;
        const hasControls = cur.querySelector(INTERACTIVE_SELECTOR);
        if (!hasControls) continue;
        if (CARD_CLASS_RE.test(cur.className || "") || /^(SECTION|ARTICLE|FIELDSET)$/.test(cur.tagName)) {
          picked = cur;
          break;
        }
        if (picked === null) picked = cur;
      }
      if (picked) push(picked, h);
    });
    doc
      .querySelectorAll('[class*="card"], [class*="section"], [class*="panel"], [class*="module"]')
      .forEach((c) => {
        if (c.querySelector(INTERACTIVE_SELECTOR)) push(c, null);
      });

    const sections = [];
    containers.forEach(({ el, titleEl }) => {
      const members = collected.filter((rec) => el.contains(rec.el));
      if (!members.length) return;
      let title = "";
      if (titleEl) title = cleanLabel(titleEl.innerText || "");
      if (!title) {
        const h = el.querySelector("h1, h2, h3, h4, legend");
        if (h) title = cleanLabel(h.innerText || "");
      }
      if (!title) {
        const t2 = el.querySelector('[class*="title"]');
        if (t2) title = cleanLabel(t2.innerText || "");
      }
      if (!title) {
        const strong = el.querySelector("strong, b");
        if (strong) title = cleanLabel(strong.innerText || "");
      }
      const btns = el.querySelectorAll('button, a, [role="button"], input[type="button"]');
      let repeatable = false;
      btns.forEach((b) => {
        if (ADD_BUTTON_RE.test((b.innerText || b.value || "").trim())) repeatable = true;
      });
      if (!repeatable) {
        const groups = {};
        el.querySelectorAll(":scope > *").forEach((child) => {
          if (child.querySelector && child.querySelector(INTERACTIVE_SELECTOR)) {
            const key = child.tagName + "." + (typeof child.className === "string" ? child.className : "");
            groups[key] = (groups[key] || 0) + 1;
          }
        });
        repeatable = Object.values(groups).some((c) => c >= 2);
      }
      const toggle = el.querySelector('[aria-expanded="false"]');
      const collapsed =
        COLLAPSED_RE.test(el.className || "") ||
        el.getAttribute("aria-expanded") === "false" ||
        toggle !== null;
      sections.push({ container: el, title, repeatable, collapsed, members });
    });
    return sections;
  };

  const detectPagination = (doc, collected) => {
    let total = null;
    let current = null;
    const bars = doc.querySelectorAll(
      '[class*="steps"], [class*="step-bar"], [class*="stepper"], [class*="wizard"]'
    );
    for (const bar of bars) {
      const items = [...bar.children].filter((c) => (c.innerText || "").trim());
      if (items.length >= 2 && items.length <= 12) {
        total = items.length;
        items.forEach((it, i) => {
          if (STEP_ACTIVE_RE.test(it.className || "")) current = i + 1;
        });
        break;
      }
    }
    let nextIdx = null;
    for (const rec of collected) {
      if (rec.role === "button" || rec.role === "link") {
        const t = rec.label || rec.value || "";
        if (NEXT_BUTTON_RE.test(t)) {
          nextIdx = rec.index;
          break;
        }
      }
    }
    const multi = total !== null || nextIdx !== null;
    return {
      kind: multi ? "multi_step" : "single",
      current_step: current,
      total_steps: total,
      next_button_index: nextIdx,
    };
  };

  const detectOverlays = (doc, win) => {
    const out = [];
    const candidates = new Set();
    doc
      .querySelectorAll('[role="dialog"], [role="alertdialog"], [aria-modal="true"]')
      .forEach((el) => candidates.add(el));
    doc.querySelectorAll("body > *").forEach((el) => {
      candidates.add(el);
      el.querySelectorAll(":scope > *").forEach((c) => candidates.add(c));
    });
    const vw = win.innerWidth || 1;
    const vh = win.innerHeight || 1;
    candidates.forEach((el) => {
      if (out.length >= 10) return;
      const style = win.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") return;
      if (parseFloat(style.opacity || "1") === 0) return;
      const isDialog =
        /^(dialog|alertdialog)$/.test(el.getAttribute("role") || "") ||
        el.getAttribute("aria-modal") === "true";
      const z = parseInt(style.zIndex || "0", 10) || 0;
      if (!isDialog && style.position !== "fixed" && style.position !== "absolute") return;
      if (!isDialog && z < 100) return;
      const r = el.getBoundingClientRect();
      if (r.width < 80 || r.height < 40) return;
      out.push({
        text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 300),
        z_index: z,
        tag: el.tagName.toLowerCase(),
        class_name: typeof el.className === "string" ? el.className.slice(0, 120) : "",
        id: (el.id || "").slice(0, 80),
        area_ratio: Math.min(1, (r.width * r.height) / (vw * vh)),
      });
    });
    return out;
  };

  const extractFromWindow = (win, framePath, origin, opts, out) => {
    const doc = win.document;
    const secPrefix = framePath ? `f${framePath.split("/").join("-")}-` : "";
    const frameBase = out.elements.length;
    const collected = [];

    const candidates = [...doc.querySelectorAll(INTERACTIVE_SELECTOR)];
    // 类名启发式补充纯 div 自定义控件（包装器内已有交互元素则跳过，避免重复）
    doc.querySelectorAll("[class]").forEach((el) => {
      if (candidates.length >= opts.maxElements) return;
      const cls = typeof el.className === "string" ? el.className : "";
      if (!cls || !(CUSTOM_CLASS_RE.test(cls) || DATE_CLASS_RE.test(cls))) return;
      if (el.matches(INTERACTIVE_SELECTOR)) return;
      if (el.querySelector(INTERACTIVE_SELECTOR)) return;
      if (el.children.length > 3) return;
      if (!isCssVisible(el)) return;
      candidates.push(el);
    });
    // 已展开弹层内的选项项（自定义下拉/日历面板的叶子短文本，供选项点击与面板导航）
    const PANEL_SELECTOR =
      '[class*="panel"], [class*="dropdown"], [class*="menu"], ' +
      '[class*="popover"], [class*="picker"], [role="listbox"]';
    let panelCount = 0;
    doc.querySelectorAll(PANEL_SELECTOR).forEach((panel) => {
      if (!isCssVisible(panel) || panelCount >= 60) return;
      panel.querySelectorAll("*").forEach((item) => {
        if (panelCount >= 60 || candidates.length >= opts.maxElements) return;
        if (item.children.length > 0) return;
        if (item.matches(INTERACTIVE_SELECTOR)) return;
        if (candidates.includes(item)) return;
        const t = (item.innerText || "").trim();
        if (!t || t.length > 40) return;
        if (!isCssVisible(item)) return;
        candidates.push(item);
        panelCount += 1;
      });
    });

    const seen = new Set();
    for (const el of candidates) {
      if (out.elements.length - frameBase >= opts.maxElements) break;
      if (seen.has(el)) continue;
      seen.add(el);
      const tag = el.tagName.toLowerCase();
      if (tag === "option" || tag === "optgroup") continue;
      const role = detectRole(el);
      let labelInfo = attributeLabel(el, doc, opts.labelDistance);
      // 按钮/链接的自身文本就是最可靠的标签，避免被邻近文本误归因
      if (role === "button" || role === "link") {
        const own = cleanLabel(el.innerText || el.value || "");
        if (own) labelInfo = { text: own, raw: own, source: "self-text" };
      }
      // 自定义勾选控件与弹层选项（div 叶子）的文字通常写在元素内部
      if (
        !labelInfo.text &&
        (role === "checkbox" || role === "radio" || role === "custom" || role === "combobox") &&
        tag !== "input" && tag !== "select"
      ) {
        const own = cleanLabel(el.innerText || "");
        if (own) labelInfo = { text: own, raw: own, source: "self-text" };
      }
      const { options, truncated } = extractOptions(el, role, opts.maxOptions);
      const r = el.getBoundingClientRect();
      const rec = {
        index: out.elements.length,
        tag,
        role,
        label: labelInfo.text,
        label_source: labelInfo.source,
        value: currentValue(el, role),
        options,
        options_truncated: truncated,
        required: isRequired(el, labelInfo),
        section_id: null,
        bbox: [
          Math.round(r.left + win.scrollX + origin.x),
          Math.round(r.top + win.scrollY + origin.y),
          Math.round(r.width),
          Math.round(r.height),
        ],
        selector: stableSelector(el, doc),
        visible: isCssVisible(el),
        frame_path: framePath || null,
        placeholder: el.getAttribute("placeholder") || el.getAttribute("data-placeholder") || null,
        accept: el.type === "file" ? el.getAttribute("accept") || null : null,
      };
      collected.push({ el, rec });
      out.elements.push(rec);
    }

    // 区块识别与元素归属（innermost 优先：按包含关系排序，内层后写入覆盖外层）
    const sections = detectSections(doc, collected.map((c) => ({ el: c.el, index: c.rec.index })));
    sections.sort((a, b) => {
      if (a.container.contains(b.container)) return 1;
      if (b.container.contains(a.container)) return -1;
      return 0;
    });
    sections.forEach((s) => {
      const id = `sec-${secPrefix}${out.sections.length}`;
      out.sections.push({
        id,
        title: s.title,
        repeatable: s.repeatable,
        collapsed: s.collapsed,
        frame_path: framePath || null,
      });
      s.members.forEach((m) => {
        const rec = collected.find((c) => c.el === m.el);
        if (rec) rec.rec.section_id = id; // 后写入者为更内层（containers 按发现顺序，内层通常靠后）
      });
    });

    // 分页识别（主文档优先，iframe 内结果作补充）
    const pg = detectPagination(doc, collected.map((c) => c.rec));
    if (!out.pagination || (out.pagination.kind === "single" && pg.kind === "multi_step")) {
      out.pagination = pg;
    }

    // 统计与信号
    collected.forEach((c) => {
      if (FILLABLE_ROLES.has(c.rec.role)) {
        out.stats.fillable += 1;
        if (c.rec.value) out.stats.filled += 1;
      }
      out.signals.role_counts[c.rec.role] = (out.signals.role_counts[c.rec.role] || 0) + 1;
      if (c.el.tagName === "INPUT" && c.el.type === "password") out.signals.has_password_input = true;
      if (c.rec.role === "file") out.signals.has_file_input = true;
    });

    // 同源 iframe 递归
    if (!opts.skipIframes) {
      [...doc.querySelectorAll("iframe")].forEach((fr, i) => {
        let childWin = null;
        try {
          childWin = fr.contentWindow;
          if (childWin) void childWin.document.body; // 触发同源检查
        } catch {
          childWin = null; // 跨域：交由 Python 侧按 frame 处理
        }
        if (!childWin) return;
        try {
          childWin.__autooffer_extracted = true;
          const fr2 = fr.getBoundingClientRect();
          const childOrigin = {
            x: origin.x + win.scrollX + fr2.left + (fr.clientLeft || 0),
            y: origin.y + win.scrollY + fr2.top + (fr.clientTop || 0),
          };
          const childPath = framePath ? `${framePath}/${i}` : String(i);
          extractFromWindow(childWin, childPath, childOrigin, opts, out);
        } catch {
          /* 忽略不可访问的 frame */
        }
      });
    }
  };

  window.__autooffer_extract = (opts) => {
    const options = {
      maxOptions: (opts && opts.maxOptions) || 30,
      labelDistance: (opts && opts.labelDistance) || 150,
      maxElements: (opts && opts.maxElements) || 2000,
      framePath: (opts && opts.framePath) || "",
      origin: (opts && opts.origin) || { x: 0, y: 0 },
      skipIframes: Boolean(opts && opts.skipIframes),
    };
    const out = {
      elements: [],
      sections: [],
      pagination: null,
      stats: { fillable: 0, filled: 0 },
      signals: {
        title: document.title || "",
        has_password_input: false,
        has_file_input: false,
        has_form_controls: false,
        role_counts: {},
        body_text: "",
        overlays: [],
        iframe_srcs: [],
      },
      scroll: {
        y: Math.round(window.scrollY),
        x: Math.round(window.scrollX),
        height: Math.round(document.documentElement.scrollHeight || document.body.scrollHeight || 0),
        viewport: Math.round(window.innerHeight),
      },
    };
    extractFromWindow(window, options.framePath, options.origin, options, out);
    out.signals.has_form_controls = out.stats.fillable >= 3;
    out.signals.body_text = (document.body ? document.body.innerText || "" : "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 4000);
    out.signals.overlays = detectOverlays(document, window);
    out.signals.iframe_srcs = [...document.querySelectorAll("iframe")]
      .map((f) => f.getAttribute("src") || "")
      .filter((s) => s)
      .slice(0, 20);
    if (!out.pagination) {
      out.pagination = { kind: "single", current_step: null, total_steps: null, next_button_index: null };
    }
    return out;
  };
})();
