/**
 * AutoOffer 内容脚本 —— 规则直填引擎（M1）。
 *
 * 设计参考 OpenJobAutofill (MIT, reference/OpenJobAutofill)：
 * - 站点适配器（SITE_ADAPTERS）提供容器/标签/区块选择器；
 * - 本地标签评分（textMatchScore）+ 硬否决（上传类/家庭域/值形冲突），
 *   高于阈值才写入，零 LLM；
 * - React 受控输入用原型 setter 注入（setNativeValue）派发 input/change/blur；
 * - 自定义下拉三段降级：点开 → 全局(含 portal)找可见选项 → 文本匹配点击 →
 *   回退向内层搜索框注入后重试。
 *
 * 另移植 Playwright 路线验证过的两条经验：
 * - 值形/标签语义冲突硬否决（手机号形状的值禁止写入身高/日期类标签）；
 * - 面板选择器覆盖 portal 渲染的弹层（ant/el/bd-layer 等）。
 *
 * 测试入口：window.__AUTOOFFER_CONTENT__.autofill(flatProfile) —— 供
 * Playwright 直接注入调用，不依赖 chrome.runtime。
 */

(() => {
  "use strict";
  if (window.__AUTOOFFER_CONTENT__) {
    return; // 已注入（scripting.executeScript 重复调用幂等）
  }

  // ---------- 常量 ----------

  const CONTROL_SELECTOR = [
    'input:not([type="hidden"]):not([type="submit"]):not([type="button"])',
    'input[type="button"][role="combobox"]',
    "textarea",
    "select",
    '[contenteditable="true"]',
    '[role="textbox"]',
    '[role="combobox"]',
    '[role="radio"]',
    '[role="checkbox"]',
  ].join(",");

  // 面板（下拉/弹层/选择器）。选项常渲染在 body 下的 portal 里。
  const PANEL_SELECTOR = [
    '[role="listbox"]',
    '[class*="select-dropdown"]',
    '[class*="select-dropdown-hidden"]',
    '[class*="cascader"]',
    '[class*="picker-dropdown"]',
    '[class*="dropdown"]',
    '[class*="popover"]',
    '[class*="popup"]',
    '[class*="popup"] [class*="menu"]',
    ".bd-layer",
    '[class*="bd-layer"]',
    '[class*="option-container"]',
  ].join(",");

  const LABEL_SELECTOR = [
    ".ant-form-item-label",
    ".el-form-item__label",
    ".kuma-label",
    '[class*="field-label"]',
    '[class*="form-label"]',
    '[class*="question-title"]',
    '[class*="question-label"]',
    "label",
    '[class*="label"]',
  ].join(",");

  const SECTION_SELECTOR = [
    ".ant-card-head-title",
    ".el-card__header",
    '[class*="module-title"]',
    '[class*="section-title"]',
    '[class*="block-title"]',
    "h2",
    "h3",
    "h4",
  ].join(",");

  const UPLOAD_RE = /上传|附件|照片|证件照|简历附件|头像|证件照片/;

  const SITE_ADAPTERS = [
    {
      id: "zhiye",
      name: "智易/北森 ATS",
      urlPattern: /(?:^|\.)(?:zhiye\.com|beisen\.com|italent\.cn|italentx\.cn|italentx\.com)$/i,
      confidence: 0.94,
      indicators: [".ant-form-item", ".ant-select", '[class*="form-item"]', '[class*="formItem"]', '[class*="bs-"]'],
      containerSelector: ".ant-form-item,.el-form-item,.form-item,[class*='formItem'],[class*='FormItem'],[class*='field'],[class*='Field']",
      labelSelector: ".ant-form-item-label,.el-form-item__label,label,[class*='label'],[class*='Label'],[class*='formLabel']",
      sectionSelector: ".ant-card-head-title,.el-card__header,.form-section-title,[class*='sectionTitle'],[class*='module-title'],h2,h3,h4",
      repeatItemSelector: ".ant-card,.ant-collapse-item,.el-card,[class*='list-item'],[class*='resume-item'],[class*='record-item']",
    },
    {
      id: "moka",
      name: "Moka 招聘",
      urlPattern: /(?:^|\.)(?:mokahr|moka)\.com$/i,
      confidence: 0.9,
      indicators: [".ant-form-item", "[class*='application-form']", "[class*='questionnaire']", "[class*='schema-form']"],
      containerSelector: ".ant-form-item,[class*='form-item'],[class*='field-wrapper'],[class*='question-item'],[class*='schema-form-item']",
      labelSelector: ".ant-form-item-label,label,[class*='field-label'],[class*='question-label'],[class*='question-title']",
      sectionSelector: ".ant-card-head-title,[class*='module-title'],[class*='questionnaire-title'],[class*='block-title'],h2,h3,h4",
      repeatItemSelector: ".ant-card,[class*='resume-item'],[class*='experience-item'],[class*='list-item'],[class*='card-item']",
    },
    {
      id: "nowcoder",
      name: "牛客网申",
      urlPattern: /(?:^|\.)nowcoder\.com$/i,
      confidence: 0.84,
      indicators: [".ant-form-item", "[class*='questionnaire']", "[class*='resume-module']"],
      containerSelector: ".ant-form-item,[class*='form-item'],[class*='question-item'],[class*='resume-field']",
      labelSelector: ".ant-form-item-label,label,[class*='field-label'],[class*='question-title']",
      sectionSelector: ".ant-card-head-title,[class*='module-title'],[class*='questionnaire-title'],h2,h3,h4",
      repeatItemSelector: ".ant-card,[class*='resume-item'],[class*='list-item']",
    },
    {
      id: "zhaopin",
      name: "智联招聘",
      urlPattern: /(?:^|\.)zhaopin\.com$/i,
      confidence: 0.83,
      indicators: [".ant-form-item", "[class*='resume-edit']", "[class*='questionnaire']"],
      containerSelector: ".ant-form-item,[class*='form-item'],[class*='resume-field'],[class*='field-row']",
      labelSelector: ".ant-form-item-label,label,[class*='field-label']",
      sectionSelector: ".ant-card-head-title,[class*='module-title'],[class*='resume-title'],h2,h3,h4",
      repeatItemSelector: ".ant-card,[class*='resume-module'],[class*='resume-item'],[class*='list-item']",
    },
    // 无 URL 特征时的框架兜底
    {
      id: "ant-design",
      name: "Ant Design 表单",
      confidence: 0.78,
      indicators: [".ant-form-item", ".ant-select", ".ant-radio-wrapper"],
      containerSelector: ".ant-form-item,[class*='ant-form-item']",
      labelSelector: ".ant-form-item-label,label,.ant-checkbox-wrapper,.ant-radio-wrapper",
      sectionSelector: ".ant-card-head-title,.ant-collapse-header,h2,h3,h4",
      repeatItemSelector: ".ant-card,.ant-collapse-item,[class*='list-item']",
    },
    {
      id: "element-ui",
      name: "Element UI 表单",
      confidence: 0.76,
      indicators: [".el-form-item", ".el-select", ".el-radio"],
      containerSelector: ".el-form-item,[class*='el-form-item']",
      labelSelector: ".el-form-item__label,label,.el-checkbox,.el-radio",
      sectionSelector: ".el-card__header,.el-collapse-item__header,h2,h3,h4",
      repeatItemSelector: ".el-card,.el-collapse-item,[class*='list-item']",
    },
    {
      id: "generic",
      name: "通用表单",
      confidence: 0.6,
      indicators: ["form"],
      containerSelector: ".form-group,.form-item,.field,[class*='form-item']",
      labelSelector: "label,[class*='label']",
      sectionSelector: "fieldset legend,h2,h3,h4",
      repeatItemSelector: "[class*='list-item'],[class*='card']",
    },
  ];

  // 档案标签别名（扁平档案标签 → 页面常见叫法）。评分时一并参与匹配。
  const LABEL_ALIASES = {
    姓名: ["真实姓名", "名字", "称呼"],
    手机号码: ["电话", "手机", "联系方式", "联系电话", "手机号", "mobile", "phone"],
    电子邮箱: ["邮箱", "邮件", "E-mail", "email", "电子邮件"],
    出生日期: ["出生年月", "生日"],
    身份证号: ["证件号码", "身份证号码", "证件号"],
    性别: ["男女性别"],
    学历: ["最高学历", "文化程度", "最高全日制学历"],
    学校: ["毕业院校", "院校", "学校名称", "毕业学校"],
    专业: ["所学专业", "专业名称"],
    现居住城市: ["当前居住地", "现居城市", "居住城市", "现居住地"],
    籍贯: ["祖籍", "家乡"],
    政治面貌: ["政治状态"],
    意向岗位: ["应聘岗位", "期望岗位", "求职岗位", "意向职位", "期望职位", "申请岗位"],
    期望城市: ["期望工作城市", "意向城市", "希望工作地"],
    期望薪资: ["期望薪资范围", "薪资要求", "期望年薪", "年薪范围"],
    自我评价: ["自我描述", "个人评价", "自我介绍"],
    专业技能: ["技能特长", "IT技能", "计算机技能"],
    开始时间: ["起始时间", "从何时开始"],
    结束时间: ["终止时间", "到何时结束"],
    接受工作地调剂: ["接受调剂", "是否接受调剂", "工作地调剂", "是否接受工作地调动"],
    可到岗时间: ["到岗时间", "入职时间", "最快到岗", "预计入职时间"],
    外语水平: ["掌握程度", "熟练程度"],
  };

  // 家庭域字段：只允许家庭类档案条目匹配（反之亦然）。
  const FAMILY_FIELD_RE = /家庭|亲属|父母|父亲|母亲|配偶|紧急联系|家人|家况/;
  const FAMILY_CATEGORY_RE = /家庭|紧急联系/;

  // 值形状检测（用于「值/标签语义冲突」硬否决）。
  const VALUE_SHAPES = [
    ["phone", (v) => /^1[3-9]\d{9}$/.test(v)],
    ["email", (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)],
    ["idcard", (v) => /^\d{17}[\dXx]$/.test(v)],
    ["date", (v) => /^\d{4}(-\d{1,2}){0,2}$/.test(v)],
  ];
  const LABEL_SHAPE_RE = {
    phone: /电话|手机|联系|mobile|phone/i,
    email: /邮箱|邮件|e-?mail/i,
    idcard: /身份证|证件号/,
    date: /日期|时间|出生|年月|毕业|入职/,
  };

  // ---------- 基础工具 ----------

  const norm = (v, max = 260) => {
    const t = String(v == null ? "" : v)
      .replace(/\s+/g, " ")
      .replace(/\u00a0/g, " ")
      .trim();
    return t.length > max ? `${t.slice(0, max)}...` : t;
  };

  const compact = (v) =>
    norm(v, 900)
      .replace(/[\s|*＊:：,，.。;；()（）[\]【】<>《》"'“”‘’/\\-]/g, "")
      .toLowerCase();

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function isVisible(el) {
    if (!el || el.nodeType !== 1) {
      return false;
    }
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0;
  }

  /** OJA 文本匹配分：5=全等 / 4=包含 / ≤3=词元重合数。 */
  function textMatchScore(source, target) {
    const s = compact(source);
    const t = compact(target);
    if (!s || !t) {
      return 0;
    }
    if (s === t) {
      return 5;
    }
    if (s.includes(t) || t.includes(s)) {
      return 4;
    }
    const split = (x) =>
      x.split(/[\s|*＊:：,，.。;；()（）[\]【】<>《》"'“”‘’/\\-]+/).filter((w) => w.length > 1);
    const sTokens = new Set(split(s));
    let overlap = 0;
    for (const token of split(t)) {
      if (sTokens.has(token)) {
        overlap += 1;
      }
    }
    return Math.min(3, overlap);
  }

  function clickActionElement(el) {
    if (!el || el.nodeType !== 1) {
      return false;
    }
    el.scrollIntoView({ block: "center", inline: "nearest" });
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
    el.click();
    return true;
  }

  // ---------- 站点识别 ----------

  function detectSiteAdapter() {
    const hostname = location.hostname || "";
    const href = location.href || "";
    let best = null;
    for (const adapter of SITE_ADAPTERS) {
      let score = 0;
      const urlMatched = adapter.urlPattern && (adapter.urlPattern.test(hostname) || adapter.urlPattern.test(href));
      if (urlMatched) {
        score += 70;
      }
      for (const indicator of adapter.indicators || []) {
        try {
          if (document.querySelector(indicator)) {
            score += 8;
          }
        } catch {
          /* 非法选择器忽略 */
        }
      }
      if (score > 0) {
        const base =
          adapter.urlPattern && !urlMatched ? Math.min(adapter.confidence, 0.62) : adapter.confidence;
        const confidence = Math.min(0.99, base + score / 100);
        if (!best || confidence > best.confidence) {
          best = { ...adapter, confidence };
        }
      }
    }
    return best || SITE_ADAPTERS[SITE_ADAPTERS.length - 1];
  }

  // ---------- 原生值注入（React 受控输入） ----------

  function setNativeValue(el, value) {
    const stringValue = value == null ? "" : String(value);
    const proto =
      el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : el instanceof HTMLSelectElement
          ? HTMLSelectElement.prototype
          : el instanceof HTMLInputElement
            ? HTMLInputElement.prototype
            : null;
    const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, "value") : null;
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, stringValue);
    } else {
      el.value = stringValue;
    }
    if (el instanceof HTMLInputElement) {
      el.setAttribute("value", stringValue);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function setContentEditableValue(el, value) {
    el.focus();
    el.textContent = value == null ? "" : String(value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  const normChoice = (v) => compact(v);
  function choiceTextMatches(label, target) {
    const l = normChoice(label);
    const r = normChoice(target);
    if (!l || !r) {
      return false;
    }
    return l === r || l.includes(r) || r.includes(l);
  }

  function setSelectValue(el, value) {
    const stringValue = String(value == null ? "" : value).trim();
    const target = normChoice(stringValue);
    const matched = Array.from(el.options || []).find((opt) => {
      const v = norm(opt.value || "", 120);
      const t = norm(opt.textContent || "", 120);
      return (
        opt.value === stringValue ||
        t === stringValue ||
        normChoice(v) === target ||
        normChoice(t) === target ||
        (t.length > 1 && t.includes(stringValue)) ||
        (stringValue.length > 1 && stringValue.includes(t))
      );
    });
    if (matched) {
      setNativeValue(el, matched.value);
      return true;
    }
    setNativeValue(el, stringValue);
    return false;
  }

  function setCheckboxOrRadio(el, value) {
    if (el instanceof HTMLInputElement && el.type === "radio") {
      const target = normChoice(value);
      const group = el.name
        ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`))
        : [el];
      const matched = group.find((radio) => {
        const labelText = getRadioLabelText(radio);
        return choiceTextMatches(labelText, target) || choiceTextMatches(radio.value || "", target);
      });
      if (matched && !matched.checked) {
        clickActionElement(matched);
        matched.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return Boolean(matched);
    }
    const normalized = String(value == null ? "" : value).trim().toLowerCase();
    const shouldCheck = ["true", "yes", "是", "1", "checked", "on", "接受", "同意"].includes(normalized);
    if (el.checked !== shouldCheck) {
      el.checked = shouldCheck;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return true;
  }

  function getRadioLabelText(radio) {
    const label = radio.closest("label") || radio.parentElement;
    const wrapper = radio.closest('[class*="radio"]');
    return norm((wrapper && wrapper.textContent) || (label && label.textContent) || radio.value || "", 60);
  }

  /** 扫描期读取分组当前选中项文本（无选中返回空串）。 */
  function readCheckedLabel(el, kind) {
    if (kind === "radio" && el.name) {
      const checked = document.querySelector(
        `input[type="radio"][name="${CSS.escape(el.name)}"]:checked`
      );
      return checked ? getRadioLabelText(checked) : "";
    }
    if (kind === "checkbox") {
      return el.checked ? getRadioLabelText(el) : "";
    }
    return el.checked ? getRadioLabelText(el) : "";
  }

  /** 日期值规范化：2024-6 → 2024-06（type=date/month 需要补零）。 */
  function normalizeDateValue(value, inputType) {
    const m = String(value || "").match(/^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$/);
    if (!m) {
      return String(value == null ? "" : value);
    }
    const [, y, mo, d] = m;
    if (inputType === "month") {
      return `${y}-${String(mo).padStart(2, "0")}`;
    }
    if (d) {
      return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    }
    return inputType === "date" ? `${y}-${String(mo).padStart(2, "0")}-01` : `${y}-${String(mo).padStart(2, "0")}`;
  }

  // ---------- 字段扫描 ----------

  function getAdapterSelectors(adapter) {
    return {
      containerSelector: adapter?.containerSelector || "",
      sectionSelector: adapter?.sectionSelector || SECTION_SELECTOR,
    };
  }

  function findContainer(el, containerSelector) {
    if (containerSelector) {
      try {
        const c = el.closest(containerSelector);
        if (c) {
          return c;
        }
      } catch {
        /* 非法选择器忽略 */
      }
    }
    // 兜底链不包含裸 label：单选/复选的选项 label 会抢在表单行之前命中
    return el.closest('.form-group,[class*="form-item"],[class*="field"],[class*="question"]');
  }

  function inferFieldLabel(el, container, labelSelector) {
    // 1) label[for=id]
    if (el.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (byFor) {
        return norm(byFor.textContent, 80);
      }
    }
    // 2) aria-label
    const aria = el.getAttribute("aria-label");
    if (aria) {
      return norm(aria, 80);
    }
    // 3) 容器内标签元素（排除包含控件自身的选项 label，如单选的「男/女」）
    let node = container;
    for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
      let labelEls = [];
      try {
        labelEls = Array.from(node.querySelectorAll(labelSelector || LABEL_SELECTOR));
      } catch {
        labelEls = [];
      }
      for (const labelEl of labelEls) {
        // 选项 label（内含单选/复选输入）不是字段标签；控件自身的 label 同理
        if (
          labelEl.contains(el) ||
          labelEl.querySelector('input[type="radio"],input[type="checkbox"],[role="radio"],[role="checkbox"]')
        ) {
          continue;
        }
        const text = norm(labelEl.textContent, 80);
        if (text && text.length <= 40) {
          return text;
        }
      }
      // 4) 容器直接子文本节点（自定义控件常见：文本 + 控件并列）
      const own = ownText(node);
      if (own && own.length >= 2 && own.length <= 30) {
        return own;
      }
    }
    // 5) placeholder 兜底
    const ph = el.getAttribute("placeholder");
    if (ph && !/请输入|请选择|请填写/.test(ph)) {
      return norm(ph, 60);
    }
    return "";
  }

  function ownText(node) {
    let text = "";
    for (const child of node.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent || "";
      }
    }
    return norm(text, 60);
  }

  /** 最近区块标题：自内向外，取「文档顺序在字段之前」的最后一个标题。 */
  function findSectionText(el, sectionSelector) {
    let node = el.parentElement;
    for (let depth = 0; node && depth < 12; depth += 1, node = node.parentElement) {
      let headers = [];
      try {
        headers = Array.from(node.querySelectorAll(sectionSelector));
      } catch {
        break;
      }
      let best = "";
      for (const h of headers) {
        if (!isVisible(h) || !h.textContent) {
          continue;
        }
        if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) {
          best = norm(h.textContent, 60);
        }
      }
      if (best) {
        return best;
      }
    }
    return "";
  }

  function isCustomChoiceControl(el, container) {
    if (el.getAttribute("role") === "combobox") {
      return true;
    }
    if (/select|picker|dropdown|combobox|cascader/i.test(String(el.className || ""))) {
      return true;
    }
    // 向上浅层探测（Ant/Element 的内嵌 input 常无特征类名）
    let node = el;
    for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
      if (/select|picker|dropdown|combobox|cascader/i.test(String(node.className || ""))) {
        return true;
      }
    }
    const probe = container || el;
    return /select|picker|dropdown|combobox|cascader/i.test(String(probe.className || ""));
  }

  /**
   * 扫描页面可填字段。
   * 返回 { fields, uploads }；fields 含 label/section/nearbyText/control 元数据。
   */
  function scanFields(adapter) {
    const { containerSelector, sectionSelector } = getAdapterSelectors(adapter);
    const labelSelector = adapter?.labelSelector || LABEL_SELECTOR;
    const fields = [];
    const uploads = [];
    const seenRadioGroups = new Set();

    let controls = [];
    try {
      controls = Array.from(document.querySelectorAll(CONTROL_SELECTOR));
    } catch {
      controls = [];
    }

    for (const el of controls) {
      if (!isVisible(el) || el.disabled) {
        continue;
      }
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute("type") || "").toLowerCase();

      if (tag === "input" && (type === "file" || UPLOAD_RE.test(el.accept || ""))) {
        uploads.push(el);
        continue;
      }
      if (tag === "input" && ["button", "submit", "reset", "image", "hidden"].includes(type)) {
        continue;
      }

      // 单选/复选按组聚合为一个字段（仅同名分组去重，无名复选各自独立）
      if (tag === "input" && (type === "radio" || type === "checkbox")) {
        if (el.name) {
          if (seenRadioGroups.has(el.name)) {
            continue;
          }
          seenRadioGroups.add(el.name);
        }
      }

      const container = findContainer(el, containerSelector);
      const label = inferFieldLabel(el, container, labelSelector);
      const section = findSectionText(el, sectionSelector);
      const nearbyText = norm(container ? container.textContent : el.placeholder || "", 160);

      let kind = "text";
      if (tag === "textarea" || el.isContentEditable || el.getAttribute("role") === "textbox") {
        kind = "text";
      } else if (tag === "select") {
        kind = "select";
      } else if (tag === "input" && type === "radio") {
        kind = "radio";
      } else if (tag === "input" && type === "checkbox") {
        kind = "checkbox";
      } else if (tag === "input" && (type === "date" || type === "month")) {
        kind = "native-date";
      } else if (isCustomChoiceControl(el, container)) {
        kind = "custom-choice";
      }

      // 已有值只认「真实选中/已填」的内容，标签文本不算（否则会抬高写入阈值）
      let currentValue = "";
      if (tag === "select") {
        // 占位选项（value 为空，如「请选择」）不算已有值
        currentValue = el.value
          ? norm(
              el.selectedOptions && el.selectedOptions[0]
                ? el.selectedOptions[0].textContent
                : "",
              80
            )
          : "";
      } else if (kind === "radio" || kind === "checkbox") {
        currentValue = readCheckedLabel(el, kind);
      } else if (kind === "custom-choice") {
        const sel = (container || el).querySelector(
          '[class*="selection-item"],[class*="selected-item"],[class*="selected"]:not([class*="unselected"])'
        );
        currentValue = norm(sel ? sel.textContent : "", 80);
      } else {
        currentValue = norm(el.value || "", 80);
      }

      const optionText =
        tag === "select"
          ? norm(Array.from(el.options || []).map((o) => o.textContent).join(" "), 160)
          : "";

      fields.push({
        element: el,
        container,
        label,
        section,
        nearbyText,
        optionText,
        currentValue,
        kind,
        required: Boolean(container && container.querySelector(".ant-form-item-required,[class*='required'],[required]")),
      });
    }
    return { fields, uploads };
  }

  // ---------- 档案条目 ----------

  /** 扁平档案 → 匹配条目。M1 只取 repeat 段第一条（多条为 M3 范围）。 */
  function buildEntries(flatProfile) {
    const entries = [];
    for (const section of (flatProfile && flatProfile.sections) || []) {
      if (section.kind === "repeat") {
        const item = (section.items || [])[0];
        if (!item) {
          continue;
        }
        for (const [label, value] of Object.entries(item)) {
          pushEntry(entries, label, value, section.title);
        }
      } else {
        for (const [label, value] of Object.entries(section.values || {})) {
          pushEntry(entries, label, value, section.title);
        }
      }
    }
    return entries;
  }

  function pushEntry(entries, label, value, category) {
    const stringValue = value == null ? "" : String(value).trim();
    if (!stringValue) {
      return;
    }
    entries.push({
      label,
      value: stringValue,
      category,
      aliases: LABEL_ALIASES[label] || [],
    });
  }

  // ---------- 评分 ----------

  function valueShape(v) {
    for (const [shape, test] of VALUE_SHAPES) {
      if (test(v)) {
        return shape;
      }
    }
    return "";
  }

  /** 值/标签语义冲突硬否决：手机号形状的值遇到日期/邮箱类标签等。 */
  function shapeConflict(field, entry) {
    const shape = valueShape(entry.value);
    if (!shape) {
      return false;
    }
    const labelText = [field.label, field.nearbyText, field.placeholder, field.optionText].join(" ");
    const labelShape = Object.keys(LABEL_SHAPE_RE).find((k) => LABEL_SHAPE_RE[k].test(labelText));
    return Boolean(labelShape) && labelShape !== shape;
  }

  function scoreField(field, entry) {
    const fieldText = [field.label, field.nearbyText, field.section, field.optionText].join(" ");
    if (/上传|附件|照片|证件照|简历附件/.test(fieldText)) {
      return 0;
    }
    // 家庭域双向硬约束
    const fieldFamily = FAMILY_FIELD_RE.test(fieldText);
    const entryFamily = FAMILY_CATEGORY_RE.test(entry.category);
    if (fieldFamily !== entryFamily && (fieldFamily || entryFamily)) {
      return 0;
    }
    if (shapeConflict(field, entry)) {
      return 0;
    }

    let direct = 0;
    direct = Math.max(direct, textMatchScore(field.label, entry.label));
    direct = Math.max(direct, textMatchScore(fieldText, entry.label));
    for (const alias of entry.aliases || []) {
      direct = Math.max(direct, textMatchScore(field.label, alias));
    }
    if (direct <= 0) {
      return 0;
    }

    let score = direct * 10;
    if (direct === 5) {
      score += 6; // 标签全等直通：无区块上下文也能过阈值
    }
    if (compact(field.section) === compact(entry.category)) {
      score += 4;
    }
    score += textMatchScore(field.nearbyText, entry.category) * 2;
    if (field.required) {
      score += 2;
    }
    if (field.currentValue && field.currentValue.length > 0) {
      score -= 5;
    }
    // 日期值写日期类标签加分
    if (/时间|日期|出生|年月/.test(fieldText) && valueShape(entry.value) === "date") {
      score += 3;
    }
    return score;
  }

  const SCORE_THRESHOLD = 55;
  const SCORE_THRESHOLD_PREFILLED = 84;

  function buildPlan(fields, entries) {
    const candidates = [];
    for (let fi = 0; fi < fields.length; fi += 1) {
      const field = fields[fi];
      for (let ei = 0; ei < entries.length; ei += 1) {
        const entry = entries[ei];
        const score = scoreField(field, entry);
        const threshold = field.currentValue ? SCORE_THRESHOLD_PREFILLED : SCORE_THRESHOLD;
        if (score >= threshold) {
          candidates.push({ fi, ei, score });
        }
      }
    }
    candidates.sort((a, b) => b.score - a.score);
    const usedFields = new Set();
    const usedEntries = new Set();
    const plan = [];
    for (const c of candidates) {
      if (usedFields.has(c.fi) || usedEntries.has(c.ei)) {
        continue;
      }
      usedFields.add(c.fi);
      usedEntries.add(c.ei);
      plan.push({ field: fields[c.fi], entry: entries[c.ei], score: c.score });
    }
    return { plan, usedFields };
  }

  // ---------- 自定义下拉 ----------

  function findChoiceFieldContainer(el, container) {
    let node = container || el;
    for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
      if (
        node.matches?.("[role='combobox'],[role='listbox'],[class*='select'],[class*='picker'],[class*='dropdown'],label") ||
        /select|picker|dropdown|combobox|cascader/i.test(String(node.className || ""))
      ) {
        return node;
      }
    }
    return container || el.parentElement || el;
  }

  /** 收集可见选项：容器内优先，随后全局 portal 面板。 */
  function findVisibleChoiceOptions(container) {
    const found = [];
    const seen = new Set();
    const roots = [container, document.body];
    for (const root of roots) {
      if (!root) {
        continue;
      }
      let nodes = [];
      try {
        nodes = root.querySelectorAll(
          '[role="option"],[aria-selected],[class*="option"],li,.ant-select-item-option,.el-select-dropdown__item,.arco-select-option,.t-select-option'
        );
      } catch {
        continue;
      }
      for (const node of nodes) {
        if (seen.has(node) || !isVisible(node)) {
          continue;
        }
        // 必须位于可见面板（或无面板祖先）内，避免命中隐藏下拉模板
        const panel = node.closest(PANEL_SELECTOR);
        if (panel && !isVisible(panel)) {
          continue;
        }
        const text = norm(node.textContent, 60);
        if (!text || text.length > 40) {
          continue;
        }
        const rect = node.getBoundingClientRect();
        if (rect.height === 0 || rect.height > 80) {
          continue;
        }
        seen.add(node);
        found.push(node);
      }
    }
    return found;
  }

  async function tryFillCustomChoiceField(field, value) {
    const el = field.element;
    const container = findChoiceFieldContainer(el, field.container);
    container.scrollIntoView({ block: "center", inline: "nearest" });
    clickActionElement(el instanceof Element ? el : container);
    if (container !== el) {
      clickActionElement(container);
    }
    await sleep(220);

    const options = findVisibleChoiceOptions(container);
    const matched = options.find(
      (opt) =>
        choiceTextMatches(norm(opt.textContent, 60), value) ||
        choiceTextMatches(opt.getAttribute("aria-label") || "", value)
    );
    if (matched) {
      clickActionElement(matched);
      await sleep(120);
      return { ok: true };
    }

    // 降级：向内层搜索框注入后重试（带搜索的自定义下拉）
    const searchInput =
      el instanceof HTMLInputElement
        ? el
        : container.querySelector?.('input:not([type="hidden"]),textarea,[contenteditable="true"]');
    if (searchInput) {
      setNativeValue(searchInput, value);
      await sleep(160);
      const retryOptions = findVisibleChoiceOptions(container);
      const retryMatched = retryOptions.find(
        (opt) =>
          choiceTextMatches(norm(opt.textContent, 60), value) ||
          choiceTextMatches(opt.getAttribute("aria-label") || "", value)
      );
      if (retryMatched) {
        clickActionElement(retryMatched);
        await sleep(120);
        return { ok: true };
      }
    }
    return { ok: false, reason: "面板已展开但未匹配到选项" };
  }

  // ---------- 填写与校验 ----------

  async function fillOne(item) {
    const { field, entry } = item;
    const el = field.element;
    try {
      if (field.kind === "radio" || field.kind === "checkbox") {
        const ok = setCheckboxOrRadio(el, entry.value);
        return ok ? { ok: true } : { ok: false, reason: "未找到匹配选项" };
      }
      if (field.kind === "select") {
        setSelectValue(el, entry.value);
        return { ok: true };
      }
      if (field.kind === "native-date") {
        const type = (el.getAttribute("type") || "").toLowerCase();
        setNativeValue(el, normalizeDateValue(entry.value, type));
        return { ok: true };
      }
      if (field.kind === "custom-choice") {
        return await tryFillCustomChoiceField(field, entry.value);
      }
      if (el.isContentEditable || el.getAttribute("role") === "textbox") {
        setContentEditableValue(el, entry.value);
        return { ok: true };
      }
      setNativeValue(el, entry.value);
      return { ok: true };
    } catch (err) {
      return { ok: false, reason: String((err && err.message) || err).slice(0, 120) };
    }
  }

  function readBack(field) {
    const el = field.element;
    if (field.kind === "radio") {
      const group = el.name
        ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`))
        : [el];
      const checked = group.find((r) => r.checked);
      return checked ? getRadioLabelText(checked) : "";
    }
    if (field.kind === "checkbox") {
      return el.checked ? "是" : "";
    }
    if (field.kind === "select") {
      return norm(el.selectedOptions && el.selectedOptions[0] ? el.selectedOptions[0].textContent : "", 60);
    }
    if (field.kind === "custom-choice") {
      // 值可能在：内嵌 input.value、展示元素文本、或选择器容器文本
      // 注意从父级开始找：输入框自身类名常含 "select"，会误匹配到自身
      const wrapper = findChoiceFieldContainer(el.parentElement || el, null);
      const display =
        wrapper &&
        wrapper.querySelector(
          '[class*="selection-item"],[class*="selected-item"],[class*="selected"]:not([class*="unselected"])'
        );
      return norm(
        el.value || (display ? display.textContent : "") || (wrapper ? wrapper.textContent : ""),
        60
      );
    }
    if (el.isContentEditable) {
      return norm(el.textContent, 60);
    }
    return norm(el.value || "", 60);
  }

  // ---------- 主入口 ----------

  async function autofill(flatProfile) {
    const adapter = detectSiteAdapter();
    const { fields, uploads } = scanFields(adapter);
    const entries = buildEntries(flatProfile);
    const { plan, usedFields } = buildPlan(fields, entries);

    const filled = [];
    const failed = [];
    for (const item of plan) {
      const result = await fillOne(item);
      const readBackValue = readBack(item.field);
      const label = item.field.label || item.field.nearbyText || "(无标签)";
      if (result.ok && (readBackValue.includes(String(item.entry.value)) || item.field.kind === "checkbox")) {
        filled.push({ label, field: label, value: String(item.entry.value).slice(0, 60) });
      } else if (result.ok) {
        failed.push({ label, field: label, value: item.entry.value, reason: "已执行但回读不一致" });
      } else {
        failed.push({ label, field: label, value: item.entry.value, reason: result.reason || "执行失败" });
      }
      await sleep(30);
    }

    const skipped = [];
    for (let i = 0; i < fields.length; i += 1) {
      if (usedFields.has(i)) {
        continue;
      }
      const f = fields[i];
      const label = f.label || f.nearbyText || "(无标签)";
      skipped.push({ field: label, reason: f.currentValue ? "已有值，跳过" : "无匹配档案字段" });
    }
    for (const up of uploads) {
      const { containerSelector: cs } = getAdapterSelectors(adapter);
      const row = findContainer(up, cs) || up.closest("label") || up;
      skipped.push({ field: norm(row.textContent, 60) || "附件", reason: "附件需手动上传" });
    }

    return {
      site: adapter ? { id: adapter.id, name: adapter.name, confidence: adapter.confidence } : null,
      counts: { filled: filled.length, failed: failed.length, skipped: skipped.length },
      filled,
      failed,
      skipped,
    };
  }

  // ---------- 暴露 ----------

  window.__AUTOOFFER_CONTENT__ = {
    autofill,
    detectSiteAdapter,
    scanFields,
    buildEntries,
    buildPlan,
    scoreField,
  };

  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg && msg.type === "autooffer:fill") {
        autofill(msg.profile || {})
          .then(sendResponse)
          .catch((err) => sendResponse({ error: String((err && err.message) || err) }));
        return true; // 异步响应
      }
      return undefined;
    });
  }
})();
