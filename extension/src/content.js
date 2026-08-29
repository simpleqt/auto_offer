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

  // 面板（下拉/弹层/选择器/日历）。选项常渲染在 body 下的 portal 里。
  const PANEL_SELECTOR = [
    '[role="listbox"]',
    ".common-unmodeled-layer",
    '[class*="unmodeled-layer"]',
    '[class*="select-dropdown"]',
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
      indicators: [".ant-form-item", ".ant-select", ".form-item--phoenix", ".phoenix-select", ".phoenix-radio", '[class*="form-item"]'],
      containerSelector: ".ant-form-item,.el-form-item,.form-item--phoenix,.form-item,.form-item,[class*='formItem'],[class*='FormItem'],[class*='field'],[class*='Field']",
      labelSelector: ".ant-form-item-label,.el-form-item__label,.form-item__text,label,[class*='label'],[class*='Label'],[class*='formLabel']",
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
    意向岗位: [
      "应聘岗位", "期望岗位", "求职岗位", "意向职位", "期望职位", "申请岗位",
      "期望从事职业", "从事职业", "期望工作", "应聘职位",
    ],
    期望城市: ["期望工作城市", "意向城市", "希望工作地", "期望工作地点"],
    期望薪资: ["期望薪资范围", "薪资要求", "期望年薪", "年薪范围"],
    "期望月薪(税前)": ["期望月薪", "期望月薪（税前）", "月薪(税前)", "期望月薪范围", "税前期望月薪"],
    "现月薪(税前)": ["现月薪", "目前月薪", "当前月薪", "现月薪（税前）", "上月薪资"],
    期望从事行业: ["期望行业", "意向行业", "期望行业方向", "希望从事行业"],
    国籍: ["nationality", "国家", "国籍（国家或地区）"],
    工作年限: ["工作年数", "参加工作年限", "年限", "工作经历年限"],
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

  // 已知区块标题（Phoenix 等自研框架的标题是无语义类名的裸 DIV，按文本识别）
  const SECTION_TITLE_RE =
    /^(基本信息|个人信息|求职意向|教育经历|实习经历|工作经历|项目经历|语言能力|外语能力|专业技能|计算机技能|证书|奖惩情况|家庭情况|家庭成员|其他信息|附加信息|自我评价|自我描述|论文著作|专利成果)$/;
  let sectionTitleCache = null;

  function collectSectionTitles() {
    const titles = [];
    for (const el of document.querySelectorAll("h2,h3,h4,section,div,span")) {
      if (el.children.length > 0) {
        continue;
      }
      const t = norm(el.textContent, 12);
      if (SECTION_TITLE_RE.test(t) && isVisible(el)) {
        if (el.closest('[class*="anchor" i],nav')) {
          continue; // 锚点导航不算
        }
        titles.push({ el, text: t });
      }
    }
    return titles;
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
    // 兜底：按已知标题文本识别（样式组件无语义类名）
    if (!sectionTitleCache) {
      sectionTitleCache = collectSectionTitles();
    }
    let bestTitle = "";
    for (const t of sectionTitleCache) {
      if (t.el.isConnected && t.el.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) {
        bestTitle = t.text;
      }
    }
    return bestTitle;
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

  /** 文件输入常以 opacity:0 隐藏在可见上传区内，用「可见祖先」判断。 */
  function hasVisibleAncestor(el, hops = 5) {
    let node = el.parentElement;
    while (node && hops > 0) {
      if (isVisible(node)) {
        return true;
      }
      node = node.parentElement;
      hops -= 1;
    }
    return false;
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
    const labelCounts = new Map(); // 同区块同标签出现序号（repeat 多区块配对用）
    sectionTitleCache = null; // 页面重渲染后标题元素可能失效，重扫时重建

    let controls = [];
    try {
      controls = Array.from(document.querySelectorAll(CONTROL_SELECTOR));
    } catch {
      controls = [];
    }

    for (const el of controls) {
      if (el.disabled) {
        continue;
      }
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute("type") || "").toLowerCase();

      // 文件输入宽松可见性（本身常 opacity:0，只要求在可见上传区内）
      if (tag === "input" && (type === "file" || UPLOAD_RE.test(el.accept || ""))) {
        if (uploads.length < 10 && hasVisibleAncestor(el)) {
          uploads.push(el);
        }
        continue;
      }
      if (!isVisible(el)) {
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
        // Phoenix 等组件会把选中值写进内嵌 input 的 value
        currentValue = norm(el.value || (sel ? sel.textContent : ""), 80);
      } else {
        currentValue = norm(el.value || "", 80);
      }

      const optionText =
        tag === "select"
          ? norm(Array.from(el.options || []).map((o) => o.textContent).join(" "), 160)
          : "";

      // occurrence 按「区块+标签」计数：不同区块（工作/项目经历）各自从 0 起
      const labelKey = `${section}|${kind}|${label}`;
      const occurrenceIndex = labelCounts.get(labelKey) || 0;
      labelCounts.set(labelKey, occurrenceIndex + 1);

      fields.push({
        element: el,
        container,
        label,
        section,
        nearbyText,
        optionText,
        currentValue,
        kind,
        occurrenceIndex,
        required: Boolean(container && container.querySelector(".ant-form-item-required,[class*='required'],[required]")),
      });
    }
    /**
     * 自绘单选/复选组扫描（北森 Phoenix 等无原生 input 的组件）。
     * 容器类名含 radio-group/checkbox-group，选项为带短文本的子项；
     * 含原生 input 的组走通用控件路径，此处跳过避免重复。
     */
    const seenGroups = new Set();
    for (const group of document.querySelectorAll('[class*="radio-group"],[class*="checkbox-group"]')) {
      if (!isVisible(group) || seenGroups.has(group)) {
        continue;
      }
      if (group.parentElement && group.parentElement.closest('[class*="radio-group"],[class*="checkbox-group"]')) {
        continue;
      }
      if (group.querySelector('input[type="radio"],input[type="checkbox"]')) {
        continue;
      }
      seenGroups.add(group);
      const items = Array.from(group.children).filter((c) => {
        const t = norm(c.textContent, 30);
        return isVisible(c) && t && t.length <= 20;
      });
      if (items.length < 2) {
        continue;
      }
      const row =
        group.closest('[class*="form-item"],[class*="field"],.form-group') || group.parentElement;
      // [class*="form-item"] 会子串命中 form-item__control 等内层，向上取最外层
      let outer = row;
      for (let i = 0; i < 5 && outer.parentElement; i += 1) {
        if (String(outer.parentElement.className || "").includes("form-item")) {
          outer = outer.parentElement;
        } else {
          break;
        }
      }
      const rowOuter = outer;
      let label = "";
      const titleEl =
        rowOuter &&
        (rowOuter.querySelector('[class*="__title"]') ||
          rowOuter.querySelector('[class*="-label"],label'));
      if (titleEl && !titleEl.contains(group)) {
        label = norm(titleEl.textContent, 60);
      }
      fields.push({
        element: items[0],
        items,
        groupEl: group,
        container: rowOuter,
        label,
        section: findSectionText(group, sectionSelector),
        nearbyText: norm(rowOuter ? rowOuter.textContent : group.textContent, 160),
        optionText: items.map((i) => norm(i.textContent, 10)).join(" "),
        currentValue: readGroupCheckedText(group),
        kind: "custom-group",
        required: Boolean(rowOuter && rowOuter.querySelector("[class*='required'],[required]")),
      });
    }
    return { fields, uploads };
  }

  /** 自绘组当前选中项文本（无选中返回空串）。 */
  function readGroupCheckedText(group) {
    const checked = group.querySelector('[class*="checked"],[class*="selected"],[class*="active"]');
    return checked ? norm(checked.textContent, 40) : "";
  }

  // ---------- 档案条目 ----------

  /** 扁平档案 → 匹配条目。repeat 段带 itemIndex 供多条目区块配对（每段上限 4 条）。 */
  function buildEntries(flatProfile) {
    const entries = [];
    for (const section of (flatProfile && flatProfile.sections) || []) {
      if (section.kind === "repeat") {
        const items = (section.items || []).slice(0, 4);
        items.forEach((item, itemIndex) => {
          for (const [label, value] of Object.entries(item)) {
            pushEntry(entries, label, value, section.title, itemIndex);
          }
        });
      } else {
        for (const [label, value] of Object.entries(section.values || {})) {
          pushEntry(entries, label, value, section.title, 0);
        }
      }
    }
    return entries;
  }

  function pushEntry(entries, label, value, category, itemIndex) {
    const stringValue = value == null ? "" : String(value).trim();
    if (!stringValue) {
      return;
    }
    entries.push({
      label,
      value: stringValue,
      category,
      itemIndex,
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

  function buildPlan(fields, entries, mapping) {
    const candidates = [];
    for (let fi = 0; fi < fields.length; fi += 1) {
      const field = fields[fi];
      // AI 映射直通：页面标签 → 档案标签（仍过值形否决保险）
      const mappedLabel = mapping && field.label ? mapping[field.label] : null;
      if (mappedLabel) {
        const ei = entries.findIndex((e) => e.label === mappedLabel);
        if (ei >= 0 && !shapeConflict(field, entries[ei]) && !field.currentValue) {
          candidates.push({ fi, ei, score: 999 });
          continue;
        }
      }
      for (let ei = 0; ei < entries.length; ei += 1) {
        const entry = entries[ei];
        let score = scoreField(field, entry);
        // repeat 多区块：第 N 个同标签字段优先配第 N 条档案条目
        if (score > 0 && field.occurrenceIndex === entry.itemIndex) {
          score += 6;
        }
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

  /** 收集当前可见弹层（portal 渲染的下拉/日历/级联）。
   *  高度门槛 60：Phoenix 会把每个 select 触发器也渲染成 32px 的
   *  phoenix-unmodeled-layer 小条，真面板（下拉/日历）都在 200px+。 */
  function findPopupLayers() {
    const layers = [];
    for (const el of document.querySelectorAll(PANEL_SELECTOR)) {
      if (!isVisible(el)) {
        continue;
      }
      const r = el.getBoundingClientRect();
      if (r.width < 60 || r.height < 60) {
        continue;
      }
      // 跳过嵌套层：祖先弹层已覆盖
      if (layers.some((x) => x.contains(el))) {
        continue;
      }
      layers.push(el);
    }
    return layers;
  }

  /**
   * 收集叶子选项：无文本子节点的元素（图标 svg/i 不算文本）。
   * 兜底覆盖无语义类名的自定义面板（如北森学历下拉的裸 div 选项）。
   */
  function collectLeafOptions(root, out, seen) {
    let count = 0;
    for (const el of root.querySelectorAll("*")) {
      if (count > 400 || seen.has(el) || !isVisible(el)) {
        continue;
      }
      const hasTextualChild = Array.from(el.children).some(
        (c) => norm(c.textContent, 10).length > 0
      );
      if (hasTextualChild) {
        continue;
      }
      const text = norm(el.textContent, 40);
      if (!text || text.length > 25) {
        continue;
      }
      const r = el.getBoundingClientRect();
      if (r.height === 0 || r.height > 60 || r.width === 0) {
        continue;
      }
      seen.add(el);
      out.push(el);
      count += 1;
    }
  }

  /** 收集可见选项：语义选择器优先，弹层叶子兜底，最后容器内叶子（内联下拉）。 */
  function findVisibleChoiceOptions(container) {
    const found = [];
    const seen = new Set();
    const semantic = [
      '[role="option"]',
      "[aria-selected]",
      '[class*="option"]',
      '[class*="area-text-label"]',
      "li",
      ".ant-select-item-option",
      ".el-select-dropdown__item",
      ".arco-select-option",
      ".t-select-option",
    ].join(",");
    const roots = [container, ...findPopupLayers()];
    for (const root of roots) {
      if (!root) {
        continue;
      }
      let nodes = [];
      try {
        nodes = root.querySelectorAll(semantic);
      } catch {
        continue;
      }
      for (const node of nodes) {
        if (seen.has(node) || !isVisible(node)) {
          continue;
        }
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
    for (const layer of findPopupLayers()) {
      collectLeafOptions(layer, found, seen);
    }
    if (container) {
      collectLeafOptions(container, found, seen);
    }
    return found;
  }

  // ---------- 日历日期（北森 Phoenix / 通用年月箭头导航） ----------

  function findCalendarPanel() {
    const candidates = document.querySelectorAll(
      '.common-unmodeled-layer,[class*="calendar"],[class*="picker-dropdown"],[role="listbox"]'
    );
    for (const el of candidates) {
      if (!isVisible(el)) {
        continue;
      }
      const text = norm(el.textContent, 400);
      if (/(\d{4})\s*年\s*(\d{1,2})\s*月/.test(text) && el.querySelector('[class*="year-btn"],[class*="month-btn"],td,[class*="cell"],[class*="day"]')) {
        return el;
      }
    }
    return null;
  }

  function readCalendarYm(panel) {
    const t = norm(panel.textContent, 400);
    const m = t.match(/(\d{4})\s*年\s*(\d{1,2})\s*月/);
    return m ? [Number(m[1]), Number(m[2])] : null;
  }

  async function clickCalendarArrow(panel, kind) {
    const btn = panel.querySelector(`[class*="${kind}-year-btn"],[class*="${kind}-month-btn"]`);
    if (btn) {
      clickActionElement(btn);
      await sleep(140);
    }
  }

  /**
   * 日历控件填日期：年/月箭头导航到位后点日格。
   * value 形如 YYYY / YYYY-MM / YYYY-MM-DD。
   */
  async function tryFillDatePicker(field, value) {
    const m = String(value).match(/^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/);
    if (!m) {
      return { ok: false, reason: "非日期值" };
    }
    const year = Number(m[1]);
    const month = m[2] ? Number(m[2]) : null;
    const day = m[3] ? Number(m[3]) : null;

    const trigger =
      field.element.closest('[class*="select"],[class*="date"],[class*="picker"]') || field.element;
    clickActionElement(trigger);
    await sleep(320);
    let panel = findCalendarPanel();
    if (!panel) {
      return { ok: false, reason: "日历面板未出现" };
    }

    let guard = 0;
    const maxSteps = 240;
    while (guard < maxSteps) {
      const fresh = findCalendarPanel();
      if (fresh) {
        panel = fresh;
      }
      const cur = readCalendarYm(panel);
      if (!cur) {
        break;
      }
      // 纯月份选择器只需年份到位（月份直接点格子）；日历需年月均到位
      const ymOk = cur[0] === year && (day === null || cur[1] === month);
      if (ymOk) {
        break;
      }
      if (cur[0] !== year) {
        await clickCalendarArrow(panel, cur[0] > year ? "prev" : "next");
      } else {
        await clickCalendarArrow(panel, cur[1] > month ? "prev" : "next");
      }
      guard += 1;
      await sleep(110);
    }
    const finalPanel = findCalendarPanel() || panel;
    const finalYm = readCalendarYm(finalPanel);
    if (!finalYm || finalYm[0] !== year || (day !== null && finalYm[1] !== month)) {
      return { ok: false, reason: `年月导航未到位(${finalYm ? finalYm.join("-") : "?"})` };
    }

    if (day === null) {
      // 纯月份选择器：点月格（文本「9月」样式）
      const monCell = findVisibleChoiceOptions(finalPanel).find((o) => {
        const t = norm(o.textContent, 8);
        return (
          t === `${month}月` ||
          t === `${String(month).padStart(2, "0")}月` ||
          (/month/i.test(String(o.className)) && t === String(month))
        );
      });
      if (!monCell) {
        return { ok: false, reason: `月格 ${month} 未找到` };
      }
      clickActionElement(monCell);
      await sleep(180);
      return { ok: true };
    }
    // 日格：叶子文本恰为日期数字（优先 td/cell/day 语义节点）
    const dayNodes = Array.from(
      finalPanel.querySelectorAll('td,[class*="cell"],[class*="day"],[class*="date"]')
    ).filter((n) => norm(n.textContent, 6) === String(day) && isVisible(n));
    const target =
      dayNodes[0] ||
      findVisibleChoiceOptions(finalPanel).find((o) => norm(o.textContent, 6) === String(day));
    if (!target) {
      // 降级：值带日但控件是纯月份选择器 → 点月格
      const monCell = findVisibleChoiceOptions(finalPanel).find((o) => {
        const t = norm(o.textContent, 8);
        return (
          t === `${month}月` ||
          t === `${String(month).padStart(2, "0")}月` ||
          (/month/i.test(String(o.className)) && t === String(month))
        );
      });
      if (monCell) {
        clickActionElement(monCell);
        await sleep(180);
        return { ok: true };
      }
      return { ok: false, reason: `日格 ${day} 未找到` };
    }
    clickActionElement(target);
    await sleep(180);
    return { ok: true };
  }

  async function tryFillCustomChoiceField(field, value) {
    const el = field.element;
    const container = findChoiceFieldContainer(el, field.container);
    container.scrollIntoView({ block: "center", inline: "nearest" });
    clickActionElement(el instanceof Element ? el : container);
    await sleep(260);
    // 面板未出现时补点选择器包装层（点 form-item 容器会触发外部点击关闭）
    if (findPopupLayers().length === 0) {
      const wrapper =
        el instanceof Element
          ? el.closest('[class*="select"],[class*="picker"],[class*="combo"]')
          : null;
      if (wrapper && wrapper !== el) {
        clickActionElement(wrapper);
        await sleep(260);
      }
    }

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

  /** 元素失效时按 标签+控件类型 重定位（React 重渲染）。 */
  function refreshField(item, adapter) {
    const field = item.field;
    if (!field.element || field.element.isConnected) {
      return field;
    }
    const fresh = scanFields(adapter)
      .fields.filter(
        (f) =>
          f.kind === field.kind &&
          f.label === field.label &&
          f.element &&
          f.element.isConnected
      )
      .pop();
    if (fresh) {
      item.field = fresh;
      return fresh;
    }
    return field;
  }

  /** 找「至今」类自绘开关：全页收集可见候选，按与字段的几何距离取最近。 */
  function findSiblingToggle(field, text) {
    const anchor = field.element && field.element.isConnected ? field.element : field.container;
    if (!anchor) {
      return null;
    }
    const ar = anchor.getBoundingClientRect();
    let best = null;
    let bestDist = Number.MAX_VALUE;
    for (const el of document.querySelectorAll(
      '[class*="checkbox"],[class*="toggle"],[class*="switch"]'
    )) {
      if (!isVisible(el) || !norm(el.textContent, 20).includes(text)) {
        continue;
      }
      const r = el.getBoundingClientRect();
      const dist = Math.abs(r.top + r.height / 2 - (ar.top + ar.height / 2)) +
        Math.abs(r.left + r.width / 2 - (ar.left + ar.width / 2));
      if (dist < bestDist) {
        bestDist = dist;
        best = el;
      }
    }
    return best;
  }

  async function fillOne(item, adapter) {
    const entry = item.entry;
    try {
      const field = refreshField(item, adapter);
      const el = field.element;
      if (!el || !el.isConnected) {
        return { ok: false, reason: "元素已失效(页面重渲染)" };
      }
      if (field.kind === "custom-group") {
        const items = field.items || [];
        const matched = items.find((it) =>
          choiceTextMatches(norm(it.textContent, 30), entry.value)
        );
        if (!matched) {
          return { ok: false, reason: "选项组中未找到匹配项" };
        }
        clickActionElement(matched);
        await sleep(140);
        return { ok: true };
      }
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
        // 「至今」：结束时间类字段的伴随开关（自绘 checkbox）；已勾选则跳过（幂等）
        if (norm(entry.value, 6) === "至今") {
          const toggle = findSiblingToggle(field, "至今");
          if (toggle) {
            const cls = String(toggle.className || "");
            const alreadyOn =
              /checked|active|selected/i.test(cls) ||
              toggle.getAttribute("aria-checked") === "true" ||
              Boolean(toggle.querySelector('[class*="checked"],[class*="active"]'));
            if (alreadyOn) {
              return { ok: true, trust: true };
            }
            clickActionElement(toggle);
            await sleep(220);
            return { ok: true, trust: true };
          }
        }
        // 日期形状的值先走日历控件（年月导航 + 日格/月格），失败再退回普通下拉路径
        if (/^\d{4}(-\d{1,2}){0,2}$/.test(entry.value)) {
          const cal = await tryFillDatePicker(field, entry.value);
          if (cal.ok) {
            return cal;
          }
          const choice = await tryFillCustomChoiceField(field, entry.value);
          if (choice.ok) {
            return choice;
          }
          return { ok: false, reason: `日历:${cal.reason}；下拉:${choice.reason}` };
        }
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
    if (field.kind === "custom-group") {
      return readGroupCheckedText(field.groupEl || el.closest('[class*="radio-group"],[class*="checkbox-group"]'));
    }
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
      return norm(el.textContent, 400);
    }
    // 回读上限要大于常见长文本（自我评价/项目描述 100+ 字），否则校验恒假
    return norm(el.value || "", 400);
  }

  // ---------- repeat 多区块（教育经历自动补块；项目/工作经历只填现存块） ----------

  const REPEAT_ADD_RULES = [
    { category: /教育经历/, anchor: /学校|院校/, btn: /添加.*教育|新增.*教育/ },
  ];

  function findAddButton(re) {
    return Array.from(document.querySelectorAll("button,a,span,div")).find((el) => {
      const hasTextualChild = Array.from(el.children).some((c) => norm(c.textContent, 5));
      if (hasTextualChild || !isVisible(el)) {
        return false;
      }
      const t = norm(el.textContent, 14);
      return re.test(t) && t.length <= 12;
    });
  }

  function countAnchorFields(rule) {
    return scanFields(detectSiteAdapter()).fields.filter((f) =>
      rule.anchor.test(f.label || "")
    ).length;
  }

  async function waitFor(predicate, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (predicate()) {
        return true;
      }
      await sleep(150);
    }
    return predicate();
  }

  /** 档案条目多于页面区块时点「添加XX经历」补足（仅教育经历，最多补 3 块）。 */
  async function ensureRepeatBlocks(flatProfile, options) {
    if (options && options.noAddBlocks) {
      return;
    }
    for (const section of (flatProfile && flatProfile.sections) || []) {
      if (section.kind !== "repeat") {
        continue;
      }
      const need = (section.items || []).length;
      if (need <= 1) {
        continue;
      }
      const rule = REPEAT_ADD_RULES.find((r) => r.category.test(section.title));
      if (!rule) {
        continue;
      }
      for (let added = 0; added < Math.min(need - 1, 3); added += 1) {
        const blocks = countAnchorFields(rule);
        if (blocks >= need) {
          break;
        }
        const btn = findAddButton(rule.btn);
        if (!btn) {
          break;
        }
        clickActionElement(btn);
        const grew = await waitFor(() => countAnchorFields(rule) > blocks, 3500);
        if (!grew) {
          break;
        }
        await sleep(250);
      }
    }
  }

  /** 找面板内的滚动容器（虚拟列表常在 200-300px 高的内层滚动）。 */
  function findScroller(layer) {
    if (layer.scrollHeight > layer.clientHeight + 10) {
      return layer;
    }
    for (const c of layer.querySelectorAll("*")) {
      if (c.scrollHeight > c.clientHeight + 10 && c.clientHeight > 40) {
        return c;
      }
    }
    return null;
  }

  /** 逐屏滚动收割选项（虚拟滚动列表只渲染可视区）。 */
  async function sweepLayerOptions(layer, out, seen) {
    const scroller = findScroller(layer);
    if (!scroller) {
      collectLeafOptions(layer, out, seen);
      return;
    }
    const step = Math.max(60, Math.floor(scroller.clientHeight * 0.8));
    for (const y of [0, step, step * 2, step * 3, step * 4, step * 5, step * 6]) {
      if (y > scroller.scrollHeight) {
        break;
      }
      scroller.scrollTop = y;
      await sleep(140); // 等虚拟列表渲染（重页面需要更久）
      collectLeafOptions(layer, out, seen);
    }
    // 第二程兜底：首程虚拟行未渲染完时补收
    for (let y = scroller.scrollHeight; y >= 0; y -= step) {
      scroller.scrollTop = y;
      await sleep(120);
      collectLeafOptions(layer, out, seen);
    }
    scroller.scrollTop = 0;
    await sleep(80);
  }

  /** 收割固定选项字段的选项清单（native select 直接读；自定义下拉取新出现的弹层）。 */
  async function harvestFieldOptions(field) {
    try {
      if (field.kind === "select") {
        return Array.from(field.element.options || [])
          .map((o) => norm(o.textContent, 30))
          .filter((t) => t && t !== "请选择");
      }
      if (field.kind !== "custom-choice") {
        return [];
      }
      const trigger =
        field.element.closest('[class*="select"],[class*="picker"]') || field.element;
      // 清空搜索词（失败尝试可能把选项过滤隐藏）
      if (field.element instanceof HTMLInputElement && field.element.value) {
        setNativeValue(field.element, "");
        await sleep(150);
      }
      // 失败尝试后面板往往仍开着：直接收割，避免再点触发器把面板关掉
      let layers = findPopupLayers();
      if (layers.length === 0) {
        clickActionElement(trigger);
        await sleep(300);
        layers = findPopupLayers();
      }
      const noise = /^(请选择|删除|全部|确定|取消)$|^\d{4}-\d{1,2}(-\d{1,2})?$/;
      const nodes = [];
      const seen = new Set();
      for (const layer of layers) {
        await sweepLayerOptions(layer, nodes, seen);
      }
      const opts = [];
      const seenText = new Set();
      for (const node of nodes) {
        const t = norm(node.textContent, 40);
        if (t && t.length <= 25 && !noise.test(t) && !seenText.has(t)) {
          seenText.add(t);
          opts.push(t);
        }
      }
      // 关面板：模拟外部点击
      document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      document.body.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      await sleep(150);
      return opts;
    } catch {
      return [];
    }
  }

  // ---------- 附件上传（File 构造 + DataTransfer 注入） ----------

  const FILE_MIME = {
    pdf: "application/pdf",
    doc: "application/msword",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    xls: "application/vnd.ms-excel",
    xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ppt: "application/vnd.ms-powerpoint",
    pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    png: "image/png",
    gif: "image/gif",
    txt: "text/plain",
    md: "text/markdown",
    html: "text/html",
    htm: "text/html",
  };

  function b64ToFile(b64, filename) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) {
      arr[i] = bin.charCodeAt(i);
    }
    const ext = (filename.split(".").pop() || "").toLowerCase();
    return new File([arr], filename, { type: FILE_MIME[ext] || "application/octet-stream" });
  }

  /** 按字段文本挑选档案附件（简历/证件照/成绩单…，中英文再细分）。 */
  function pickAttachment(fieldText, attachments) {
    let best = null;
    let bestScore = 0;
    for (const a of attachments) {
      if (!a.b64) {
        continue;
      }
      let s = 0;
      if (/简历/.test(fieldText) && a.kind === "resume") s += 5;
      if (/证件照|照片/.test(fieldText) && a.kind === "photo") s += 5;
      if (/成绩单/.test(fieldText) && a.kind === "transcript") s += 5;
      if (/证书/.test(fieldText) && a.kind === "certificate") s += 5;
      if (/作品集/.test(fieldText) && a.kind === "portfolio") s += 5;
      if (/英文|english/i.test(fieldText) && a.language === "en") s += 2;
      if (/中文|中文简历/.test(fieldText) && a.language === "zh") s += 1;
      if (s > bestScore) {
        bestScore = s;
        best = a;
      }
    }
    return bestScore >= 5 ? best : null;
  }

  async function fillUploads(uploads, attachments, adapter) {
    const results = [];
    if (!Array.isArray(attachments) || attachments.length === 0 || uploads.length === 0) {
      return results;
    }
    const { containerSelector: cs } = getAdapterSelectors(adapter);
    for (const up of uploads) {
      let row = findContainer(up, cs) || up.closest("label") || up;
      // [class*="form-item"] 会子串命中内层容器，向上取最外层表单行
      while (
        row.parentElement &&
        String(row.parentElement.className || "").includes("form-item")
      ) {
        row = row.parentElement;
      }
      const fieldText = norm(row.textContent, 80);
      const picked = pickAttachment(fieldText, attachments);
      if (!picked) {
        results.push({ label: fieldText || "附件", ok: false, reason: "无匹配附件" });
        continue;
      }
      try {
        const file = b64ToFile(picked.b64, picked.filename);
        const dt = new DataTransfer();
        dt.items.add(file);
        up.files = dt.files;
        up.dispatchEvent(new Event("input", { bubbles: true }));
        up.dispatchEvent(new Event("change", { bubbles: true }));
        results.push({ label: fieldText || "附件", ok: true, value: picked.filename });
      } catch (err) {
        results.push({
          label: fieldText || "附件",
          ok: false,
          reason: String((err && err.message) || err).slice(0, 80),
        });
      }
      await sleep(250);
    }
    return results;
  }

  // ---------- 主入口 ----------

  async function autofill(flatProfile, options) {
    const adapter = detectSiteAdapter();
    await ensureRepeatBlocks(flatProfile, options);
    const { fields, uploads } = scanFields(adapter);
    const entries = buildEntries(flatProfile);
    const mapping = (options && options.mapping) || null;
    const { plan, usedFields } = buildPlan(fields, entries, mapping);
    // AI 选选项覆盖：字段标签 → 选中的选项值
    const overrides = (options && options.overrides) || {};
    for (const item of plan) {
      const ov = overrides[item.field.label];
      if (ov) {
        item.entry = { ...item.entry, value: String(ov) };
      }
    }

    const filled = [];
    const failed = [];
    const normDate = (s) =>
      String(s)
        .replace(/(\d{4})年(\d{1,2})月(?:(\d{1,2})日?)?/g, (_, y, mo, d) =>
          d ? `${y}-${mo}-${d}` : `${y}-${mo}`
        )
        .replace(/-/g, "");
    for (const item of plan) {
      const result = await fillOne(item, adapter);
      refreshField(item, adapter);
      let readBackValue = readBack(item.field);
      let verified =
        item.field.kind === "checkbox" ||
        item.field.kind === "custom-group" ||
        result.trust ||
        readBackValue.includes(String(item.entry.value)) ||
        normDate(readBackValue).includes(normDate(item.entry.value));
      // 文本类回读竞态：React 提交有延迟，稍候重读一次
      if (!verified && result.ok) {
        await sleep(280);
        refreshField(item, adapter);
        readBackValue = readBack(item.field);
        verified =
          readBackValue.includes(String(item.entry.value)) ||
          normDate(readBackValue).includes(normDate(item.entry.value));
      }
      const label = item.field.label || item.field.nearbyText || "(无标签)";
      if (result.ok && verified) {
        filled.push({ label, field: label, value: String(item.entry.value).slice(0, 60) });
      } else if (result.ok) {
        failed.push({ label, field: label, value: item.entry.value, reason: "已执行但回读不一致" });
      } else {
        const row = {
          label,
          field: label,
          value: item.entry.value,
          reason: result.reason || "执行失败",
        };
        // 选项未匹配类失败：收割选项清单，供 AI 选选项通道二段使用
        if (/未匹配到选项/.test(row.reason) && item.field.kind !== "radio") {
          let opts = await harvestFieldOptions(item.field);
          if (opts.length > 0 && opts.length < 30) {
            // 虚拟列表首收常不全：面板已渲染后再收一次合并
            await sleep(400);
            const more = await harvestFieldOptions(item.field);
            opts = Array.from(new Set([...opts, ...more]));
          }
          if (opts.length > 1) {
            row.options = opts.slice(0, 60);
          }
        }
        failed.push(row);
      }
      await sleep(30);
    }

    const skipped = [];
    const unmatched = [];
    for (let i = 0; i < fields.length; i += 1) {
      if (usedFields.has(i)) {
        continue;
      }
      const f = fields[i];
      const label = f.label || f.nearbyText || "(无标签)";
      if (f.currentValue) {
        skipped.push({ field: label, reason: "已有值，跳过" });
      } else {
        skipped.push({ field: label, reason: "无匹配档案字段" });
        // 供 AI 映射通道二次补填（只带标签/选项文本，不带任何值）
        if (label !== "(无标签)" && unmatched.length < 60) {
          unmatched.push({
            label,
            section: f.section || "",
            options: String(f.optionText || "")
              .split(/[\s,，、]+/)
              .filter(Boolean)
              .slice(0, 20),
          });
        }
      }
    }
    const { containerSelector: cs } = getAdapterSelectors(adapter);
    const hasAttachments = Array.isArray(options && options.attachments) && options.attachments.length > 0;
    if (!hasAttachments) {
      for (const up of uploads) {
        let row = findContainer(up, cs) || up.closest("label") || up;
        while (
          row.parentElement &&
          String(row.parentElement.className || "").includes("form-item")
        ) {
          row = row.parentElement;
        }
        skipped.push({ field: norm(row.textContent, 60) || "附件", reason: "附件需手动上传" });
      }
    } else {
      const uploadRows = await fillUploads(uploads, options.attachments, adapter);
      for (const r of uploadRows) {
        if (r.ok) {
          filled.push({ label: r.label, field: r.label, value: r.value, via: "附件" });
        } else {
          skipped.push({ field: r.label, reason: r.reason || "附件上传失败" });
        }
      }
    }

    // 固定选项字段上报（供 AI 选选项通道）：native select 直接读，
    // 自定义下拉沿用失败时收割到的选项清单
    const optionFields = [];
    const seenOptLabels = new Set();
    const addOptField = (label, options) => {
      if (
        label &&
        !seenOptLabels.has(label) &&
        Array.isArray(options) &&
        options.length > 1 &&
        optionFields.length < 40
      ) {
        seenOptLabels.add(label);
        optionFields.push({ label, options: options.slice(0, 60) });
      }
    };
    for (const f of fields) {
      if (f.kind === "select" && f.optionText && f.optionText.length > 1) {
        addOptField(
          f.label,
          String(f.optionText).split(/[\s,，、]+/).filter(Boolean)
        );
      }
    }
    for (const r of failed) {
      if (r.options) {
        addOptField(r.label, r.options);
      }
    }

    return {
      site: adapter ? { id: adapter.id, name: adapter.name, confidence: adapter.confidence } : null,
      counts: { filled: filled.length, failed: failed.length, skipped: skipped.length },
      filled,
      failed,
      skipped,
      unmatched,
      optionFields,
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
    tryFillDatePicker,
    harvestFieldOptions,
  };

  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg && msg.type === "autooffer:fill") {
        autofill(msg.profile || {}, {
          mapping: msg.mapping || null,
          overrides: msg.overrides || null,
          attachments: msg.attachments || null,
        })
          .then(sendResponse)
          .catch((err) => sendResponse({ error: String((err && err.message) || err) }));
        return true; // 异步响应
      }
      return undefined;
    });
  }
})();
