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
  // 与 manifest.json 版本同步：插件升级后旧脚本可能仍驻留在未刷新的页面里。
  // 安装守护按版本比较（同版本幂等；新版本可覆盖旧安装），消息处理也校验
  // 版本——旧监听器不再应答新后台的消息，避免新旧引擎同时填写同一页面。
  // 优先运行时读取（content script 有 chrome.runtime）：发版只改 manifest，
  // 不再有第二处硬编码漂移（v0.2.34 曾因漏改此常量导致全部消息拒答）
  const SCRIPT_VERSION =
    typeof chrome !== "undefined" &&
    chrome.runtime &&
    typeof chrome.runtime.getManifest === "function"
      ? chrome.runtime.getManifest().version
      : "dev";
  if (
    window.__AUTOOFFER_CONTENT__ &&
    window.__AUTOOFFER_CONTENT__.version === SCRIPT_VERSION
  ) {
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
      id: "feishu",
      name: "飞书招聘",
      urlPattern: /(?:^|\.)feishu\.cn$/i,
      confidence: 0.92,
      indicators: ["[class*='ud-formily-item']", "[class*='applyFormModule']"],
      containerSelector: ".ud-formily-item",
      labelSelector: ".ud-formily-item-label label,[class*='ud-formily-item-label'],label",
      sectionSelector: "[class*='applyFormModuleWrapper-title'],[class*='module-title'],h2,h3,h4",
      repeatItemSelector: "[class*='apply-form-array-card'],[class*='register-form-group-wrapper']",
    },
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
      indicators: [".ant-form-item", "[class*='application-form']", "[class*='questionnaire']", "[class*='schema-form']", "[class*='apply-field']"],
      containerSelector: ".ant-form-item,[class*='form-item'],[class*='apply-field'],[class*='field-wrapper'],[class*='question-item'],[class*='schema-form-item']",
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
    学院: ["院系", "所属学院", "学院名称"],
    专业: ["所学专业", "专业名称"],
    现居住城市: ["当前居住地", "现居城市", "居住城市", "现居住地"],
    籍贯: ["祖籍", "家乡"],
    政治面貌: ["政治状态"],
    民族: ["族别", "民族成分", "少数民族"],
    是否全日制: ["全日制", "全日制情况", "教育形式"],
    是否统招: ["统招", "统招情况", "招生形式"],
    学制: ["修业年限", "基本学制", "学制年限"],
    婚姻状况: ["婚姻", "婚否", "婚姻状态"],
    意向岗位: [
      "应聘岗位", "期望岗位", "求职岗位", "意向职位", "期望职位", "申请岗位",
      "期望从事职业", "从事职业", "期望工作", "应聘职位",
    ],
    期望城市: ["期望工作城市", "意向城市", "希望工作地", "期望工作地点"],
    期望薪资: ["期望薪资范围", "薪资要求", "期望年薪", "年薪范围"],
    "期望月薪(税前)": ["期望月薪", "期望月薪（税前）", "月薪(税前)", "期望月薪范围", "税前期望月薪"],
    "现月薪(税前)": ["现月薪", "目前月薪", "当前月薪", "现月薪（税前）", "上月薪资"],
    期望从事行业: ["期望行业", "意向行业", "期望行业方向", "希望从事行业"],
    国籍: ["nationality", "国家", "国籍（国家或地区）", "证件签发国家/地区", "签发国家/地区", "证件签发地"],
    工作年限: ["工作年数", "参加工作年限", "年限", "工作经历年限"],
    项目职务: ["项目角色", "担任角色", "项目职责", "项目内职务", "课题角色"],
    项目名称: ["科研项目名称", "课题名称", "项目课题名称"],
    项目链接: ["项目地址", "项目主页", "项目网址", "项目URL", "仓库地址", "github地址", "GitHub 地址", "作品链接"],
    项目描述: ["描述", "项目简介", "项目详情", "项目内容", "课题描述", "研究内容"],
    项目成果: ["项目业绩", "成果", "项目成绩", "课题成果"],
    工作内容: ["工作描述", "职位描述", "工作职责", "工作内容描述"],
    自我评价: ["自我描述", "个人评价", "自我介绍"],
    专业技能: ["技能特长", "IT技能", "计算机技能"],
    开始时间: ["入学时间", "入学年份", "入学年月", "起始时间", "从何时开始"],
    结束时间: ["毕业时间", "毕业年份", "毕业年月", "终止时间", "到何时结束"],
    接受工作地调剂: ["接受调剂", "是否接受调剂", "工作地调剂", "是否接受工作地调动"],
    可到岗时间: ["到岗时间", "入职时间", "最快到岗", "预计入职时间"],
    外语水平: ["掌握程度", "熟练程度"],
    奖惩名称: ["获奖名称", "奖项名称", "奖励名称", "荣誉奖项", "所获奖项", "奖惩项目", "获奖项", "奖项"],
    奖励等级: ["获奖等级", "奖项等级", "奖励级别", "奖惩级别", "获奖级别"],
    奖惩时间: ["获奖时间", "获得时间", "取得时间", "奖励时间", "获奖年月"],
    奖惩描述: ["获奖描述", "奖项描述", "获奖情况", "奖惩说明", "描述"],
  };

  // 家庭域字段：只允许家庭类档案条目匹配（反之亦然）。
  const FAMILY_FIELD_RE = /家庭|亲属|父母|父亲|母亲|配偶|紧急联系|家人|家况/;
  const FAMILY_CATEGORY_RE = /家庭|紧急联系/;

  // 科研域字段：只允许科研类档案条目匹配（反之亦然）。
  // 科研与工程项目条目的标签几乎相同（项目名称/项目职务/描述），按标签分不开，
  // 必须按模块标题硬隔离：普通「项目经历」模块不得吃掉科研条目，反之亦然。
  const RESEARCH_FIELD_RE = /科研|课题/;
  const RESEARCH_CATEGORY_RE = /科研|课题/;

  // 奖惩域字段：获奖模块与项目模块都可能有裸「描述」字段，按模块标题硬隔离。
  const AWARD_FIELD_RE = /获奖|奖惩|荣誉|奖学金/;
  const AWARD_CATEGORY_RE = /奖惩|获奖/;

  // 教育域字段：入学/毕业时间是教育专属叫法，而档案里 教育/实习/工作/项目/科研
  // 五类条目都有 开始时间/结束时间（星网真站实测：实习的 2026-04 被填进教育块
  // 的入学时间）—— 入学/毕业类标签必须按模块标题与教育条目硬配对。
  const EDUCATION_FIELD_RE =
    /入学|毕业|就读|在校|学制|学历|学位|学校|院校|专业|学院|院系|班级|成绩|GPA|导师|教育/;
  const EDUCATION_CATEGORY_RE = /教育|学业|学历|在校/;

  // 值形状检测（用于「值/标签语义冲突」硬否决）。
  const VALUE_SHAPES = [
    ["phone", (v) => /^1[3-9]\d{9}$/.test(v)],
    ["email", (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)],
    ["idcard", (v) => /^\d{17}[\dXx]$/.test(v)],
    ["date", (v) => /^\d{4}(-\d{1,2}){0,2}$/.test(v)],
    ["url", (v) => /^https?:\/\/\S+$/.test(v)],
  ];
  const LABEL_SHAPE_RE = {
    phone: /电话|手机|联系|mobile|phone/i,
    email: /邮箱|邮件|e-?mail/i,
    idcard: /身份证|证件号/,
    date: /日期|时间|出生|年月|毕业|入职/,
    // 链接类标签（刻意不含裸「地址」：通讯/居住地址是文本，不是 URL）
    url: /链接|网址|项目地址|仓库|主页|github|url|link/i,
  };
  const URL_RE = /https?:\/\/[^\s，；,;）)"'》]+/;

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

  /**
   * 部分自绘组件（如北森 Phoenix 单选）的手势监听挂在内部 wrapper 上，
   * 只响应带坐标的完整指针序列（pointerdown/up），普通合成 click 无效。
   */
  function dispatchPointerSeq(el) {
    if (!el || el.nodeType !== 1) {
      return false;
    }
    el.scrollIntoView({ block: "center", inline: "nearest" });
    const r = el.getBoundingClientRect();
    const init = {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      pointerId: 1,
      pointerType: "mouse",
      isPrimary: true,
      button: 0,
      clientX: r.x + r.width / 2,
      clientY: r.y + r.height / 2,
    };
    try {
      el.dispatchEvent(new PointerEvent("pointerdown", init));
      el.dispatchEvent(new MouseEvent("mousedown", init));
      el.dispatchEvent(new PointerEvent("pointerup", init));
      el.dispatchEvent(new MouseEvent("mouseup", init));
      el.dispatchEvent(new MouseEvent("click", init));
      return true;
    } catch (err) {
      return false;
    }
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
    // ASCII 大小写不敏感：档案值「30k」要能对上选项「20-30K」
    const fold = (s) => (/[a-z]/i.test(s) ? s.toLowerCase() : s);
    const lf = fold(l);
    const rf = fold(r);
    if (lf === rf || lf.includes(rf) || rf.includes(lf)) {
      return true;
    }
    // 年/月/日单位剥离后比对：级联下拉选项「2001年」要能对上日期值
    // 「2001-03-18」的前缀。仅当一侧带年/月/日单位时启用，且前缀长度≥2
    // （防止「3日」之类单数字前缀误配「30-40K」）。
    if (/[年月日]/.test(l) || /[年月日]/.test(r)) {
      const stripUnits = (s) => s.replace(/年|月|日/g, "");
      const lu = stripUnits(lf);
      const ru = stripUnits(rf);
      return (
        Boolean(lu) &&
        Boolean(ru) &&
        (lu === ru ||
          (lu.length >= 2 && ru.startsWith(lu)) ||
          (ru.length >= 2 && lu.startsWith(ru)))
      );
    }
    return false;
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

  function inferFieldLabel(el, container, labelSelector, containerSelector) {
    // 0) 飞书 formily：行元素自带 data-form-field-i18n-name（最可靠标签源）
    const i18nRow = el.closest("[data-form-field-i18n-name]");
    if (i18nRow) {
      const i18nName = norm(i18nRow.getAttribute("data-form-field-i18n-name"), 60);
      if (i18nName) {
        return i18nName;
      }
    }
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
        // label 属于其他表单行（爬到公共祖先时抓到别人的 label）；
        // 判据：二者无嵌套关系、且 label 所在行内还有其他控件（如勾选行）。
        // 行定位在选择器 miss 时回退通用行链（自研库的行类名不在适配器名单里）
        if (container) {
          try {
            const genericRow = '.form-group,[class*="form-item"],[class*="field"],[class*="question"]';
            let labelRow = null;
            if (containerSelector) {
              labelRow = labelEl.closest(containerSelector);
            }
            if (!labelRow) {
              labelRow = labelEl.closest(genericRow);
            }
            // [class*="form-item"] 会子串命中 label 自身类名（aui-form-item__label），
            // 定位到标签元素时向上取真正的表单行
            if (
              labelRow &&
              labelRow.parentElement &&
              labelRow.matches(labelSelector || LABEL_SELECTOR)
            ) {
              labelRow = labelRow.parentElement;
            }
            if (
              labelRow &&
              labelRow !== container &&
              !labelRow.contains(container) &&
              !container.contains(labelRow)
            ) {
              const otherCtrl = labelRow.querySelector(
                'input,select,textarea,[role="combobox"],[role="radio"],[role="checkbox"],[contenteditable="true"]'
              );
              if (otherCtrl && otherCtrl !== el && !otherCtrl.contains(el)) {
                continue;
              }
            }
          } catch {
            /* 非法选择器时跳过该检查 */
          }
        }
        const text = norm(labelEl.textContent, 80);
        // 纯数字/+数字（如手机区号 +86）不是字段标签
        if (text && text.length <= 40 && !/^[+\d\s().-]+$/.test(text)) {
          return text;
        }
      }
      // 4) 容器直接子文本节点（自定义控件常见：文本 + 控件并列）
      const own = ownText(node);
      if (own && own.length >= 2 && own.length <= 30) {
        return own;
      }
    }
    // 4.5) 容器行首行文本（Moka apply-field 等：标签是行内首行裸 DIV 文本）
    if (container) {
      const first = (container.innerText || "").split("\n").map((s) => s.trim()).find(Boolean);
      if (
        first &&
        first.length >= 2 &&
        first.length <= 12 &&
        !/^[+\d\s().-]+$/.test(first) &&
        !/请输入|请选择|请填写/.test(first)
      ) {
        return norm(first, 30);
      }
    }
    // 4.6) 组合控件继承：本行无标签且是可编辑文本输入，紧邻前一行是
    // 「带标签 + 选择类控件」时继承其标签——覆盖「区号下拉+号码输入」
    // 「国籍下拉+证件号输入」等前缀组合行（跨组件库通用，无站点代码）。
    {
      const isFreeText =
        el instanceof HTMLInputElement &&
        !el.readOnly &&
        !["radio", "checkbox", "file"].includes(el.type || "text");
      if (isFreeText && container) {
        // 逐级向上找前兄弟行（容器可能是行内包装层），取第一个
        // 「有标签文本 + 含选择类控件」的行
        let node = container;
        for (let hop = 0; node && hop < 3; hop += 1, node = node.parentElement) {
          const sib = node.previousElementSibling;
          if (!sib || !sib.querySelector) {
            continue;
          }
          const lab = sib.querySelector(labelSelector || LABEL_SELECTOR);
          const labText = lab ? norm(lab.textContent, 40) : "";
          const sibIsChoiceRow = sib.querySelector(
            'input[readonly],select,[role="combobox"],[class*="select"]'
          );
          if (labText && sibIsChoiceRow && !/^[+\d\s().-]+$/.test(labText)) {
            return labText;
          }
        }
      }
    }
    // 5) placeholder 兜底（去掉「请输入/请选择/请填写」前缀后仍可作标签）
    const ph = el.getAttribute("placeholder");
    if (ph) {
      const stripped = ph.replace(/^请(输入|选择|填写)/, "").trim();
      if (stripped.length >= 2 && !/^[+\d\s().-]+$/.test(stripped)) {
        return norm(stripped, 60);
      }
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
    /^(基本信息|个人信息|求职意向|教育经历|实习经历|工作经历|项目经历|科研项目经历|科研经历|科研情况|语言能力|外语能力|专业技能|计算机技能|证书|奖惩情况|家庭情况|家庭成员|其他信息|附加信息|自我评价|自我描述|论文著作|专利成果|作品|获奖|荣誉奖项|荣誉情况|所获荣誉)$/;
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
    // 上限 18：数组卡片（教育经历等）比普通字段多嵌 3-4 层（飞书 formily array-card）
    for (let depth = 0; node && depth < 18; depth += 1, node = node.parentElement) {
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
    // 表单里的 search 型输入基本是选择器的搜索框（飞书 formily Select）
    if (el.tagName === "INPUT" && (el.getAttribute("type") || "") === "search") {
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
      const label = inferFieldLabel(el, container, labelSelector, containerSelector);
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
        // 手机区号类前缀选择器：触发器为空或纯 +数字，且正文输入框另有其人
        const trig = norm(el.value || el.textContent, 12);
        if (!trig || /^[+]\d{1,3}$/.test(trig)) {
          const row = container || el.parentElement;
          if (row && row !== document.body) {
            const siblings = [
              ...row.querySelectorAll('input:not([type="hidden"])'),
            ].filter((x) => x !== el && x.offsetParent && x.type !== "file");
            if (siblings.length > 0) {
              continue;
            }
            // 跨行组合（华为 AUI 等）：区号下拉一行、无标签号码输入框在紧邻下一行。
            // 仅限显式 +数字 区号——空触发器的普通下拉随处可见，不能因下一行
            // 恰好是文本框就误杀（zhiye 学历下拉→毕业院校输入框即此反例）。
            if (/^[+]\d{1,3}$/.test(trig)) {
              const nextRow = neighborRow(row, "next");
              const nextInput = nextRow
                ? nextRow.querySelector('input:not([type="hidden"]):not([readonly])')
                : null;
              if (nextInput && nextInput.offsetParent) {
                continue;
              }
            }
          }
        }
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
          '[class*="selection-item"],[class*="selected-item"],[class*="selectItem"],[class*="selected"]:not([class*="unselected"])'
        );
        // Phoenix 等组件会把选中值写进内嵌 input 的 value
        currentValue = norm(el.value || (sel ? sel.textContent : ""), 80);
      } else {
        currentValue = norm(el.value || "", 80);
      }

      const selectOptions =
        tag === "select"
          ? Array.from(el.options || [])
              .map((o) => norm(o.textContent, 40))
              .filter((t) => t && t !== "请选择")
          : null;
      const optionText = selectOptions ? norm(selectOptions.join(" "), 160) : "";

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
        // native select 的逐项选项文本（供 AI 映射/选选项通道；含空格的
        // 英文多词选项不被拆散——optionText 按空白切分会把
        // "Bachelor Degree" 拆成两个伪选项）
        options: selectOptions || undefined,
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

  /** 扁平档案 → 匹配条目。repeat 段带 itemIndex 供多条目区块配对（与补块上限一致取 8）。 */
  function buildEntries(flatProfile) {
    const entries = [];
    for (const section of (flatProfile && flatProfile.sections) || []) {
      if (section.kind === "repeat") {
        const items = (section.items || []).slice(0, 8);
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
    const labelText = [field.label, field.nearbyText, field.placeholder, field.optionText].join(" ");
    // 链接类字段不接受长文本：URL 埋在描述里也不能反向倾倒进链接栏
    if (
      LABEL_SHAPE_RE.url.test(labelText) &&
      typeof entry.value === "string" &&
      entry.value.length > 30 &&
      !URL_RE.test(entry.value)
    ) {
      return true;
    }
    const shape = valueShape(entry.value);
    if (!shape) {
      return false;
    }
    const labelShape = Object.keys(LABEL_SHAPE_RE).find((k) => LABEL_SHAPE_RE[k].test(labelText));
    return Boolean(labelShape) && labelShape !== shape;
  }

  /** 域硬否决（家庭/科研/奖惩/教育）与控件值形否决。
   *  规则通道与 AI 映射直通共用：LLM 错映射（如把项目描述配到科研描述）
   *  也由同一道闸拦下，教育/科研/奖惩/家庭隔离对 AI 结果同样生效。 */
  function domainConflict(field, entry) {
    const fieldText = [field.label, field.nearbyText, field.section, field.optionText].join(" ");
    // 家庭域双向硬约束
    const fieldFamily = FAMILY_FIELD_RE.test(fieldText);
    const entryFamily = FAMILY_CATEGORY_RE.test(entry.category);
    if (fieldFamily !== entryFamily && (fieldFamily || entryFamily)) {
      return true;
    }
    // 科研域双向硬约束（科研/工程项目标签相同，按模块标题隔离）
    const fieldResearch = RESEARCH_FIELD_RE.test(fieldText);
    const entryResearch = RESEARCH_CATEGORY_RE.test(entry.category);
    if (fieldResearch !== entryResearch && (fieldResearch || entryResearch)) {
      return true;
    }
    // 奖惩域双向硬约束（获奖/项目模块都可能裸标「描述」，按模块标题隔离）
    const fieldAward = AWARD_FIELD_RE.test(fieldText);
    const entryAward = AWARD_CATEGORY_RE.test(entry.category);
    if (fieldAward !== entryAward && (fieldAward || entryAward)) {
      return true;
    }
    // 教育域硬约束：入学/毕业/学校等教育专属标签只能配教育条目。
    // 档案里 教育/实习/项目/科研 五类条目都带 开始/结束时间，星网真站实测
    // 实习的 2026-04 曾被填进教育块入学时间。字段侧只看 label+nearbyText
    // （section 标题页面随意起，基准页把户口所在地也放在「教育经历」区下，
    // 泛化「开始时间」字段的区块归属交给 occurrence 配对处理）
    if (
      EDUCATION_FIELD_RE.test(`${field.label || ""} ${field.nearbyText || ""}`) &&
      !EDUCATION_CATEGORY_RE.test(entry.category)
    ) {
      return true;
    }
    // 下拉类控件不吃自由文本强形状值：手机号/邮箱/身份证/URL 不可能出现在选项里
    if (field.kind === "custom-choice" || field.kind === "select") {
      const vs = valueShape(entry.value);
      if (vs === "phone" || vs === "email" || vs === "idcard" || vs === "url") {
        return true;
      }
    }
    return false;
  }

  function scoreField(field, entry) {
    const fieldText = [field.label, field.nearbyText, field.section, field.optionText].join(" ");
    if (/上传|附件|照片|证件照|简历附件/.test(fieldText)) {
      return 0;
    }
    if (domainConflict(field, entry)) {
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

  /** 预填纠偏用的宽松值比较：紧凑文本相等，或（日期类）剥离非数字后相等。 */
  const sameLooseValue = (a, b) => {
    const x = compact(a);
    const y = compact(b);
    if (!x || !y) {
      return false;
    }
    if (x === y) {
      return true;
    }
    const na = String(a);
    const nb = String(b);
    if (/(19|20)\d{2}/.test(na) && /(19|20)\d{2}/.test(nb)) {
      return na.replace(/[^\d]/g, "") === nb.replace(/[^\d]/g, "");
    }
    return false;
  };

  function buildPlan(fields, entries, mapping, options) {
    const candidates = [];
    // 区间字段预配对：页面把起止合并为同标签的两个输入（如飞书「起止时间」），
    // 与档案的 开始时间/结束时间 按区块分组顺序一一对应（第 k 组 ↔ 第 k 条经历）
    const RANGE_FIELD_RE = /^(起止时间|起止日期|时间区间|时间段)$/;
    const rangeHandled = new Set();
    const rangeFields = fields
      .map((f, fi) => ({ f, fi }))
      .filter((x) => RANGE_FIELD_RE.test(x.f.label || "") && !x.f.currentValue);
    if (rangeFields.length >= 2) {
      const bySection = new Map();
      for (const x of rangeFields) {
        const key = x.f.section || "";
        if (!bySection.has(key)) {
          bySection.set(key, []);
        }
        bySection.get(key).push(x);
      }
      for (const [, group] of bySection) {
        const startEntries = new Map(); // itemIndex -> entryIndex
        const endEntries = new Map();
        const flatSection = compact(group[0].f.section || "");
        entries.forEach((e, ei) => {
          const cat = compact(e.category || "");
          // 等价：全等，或双方都是科研（站点叫「科研项目经历」、档案叫「科研经历」）
          const same = cat === flatSection ||
            (RESEARCH_CATEGORY_RE.test(cat) && RESEARCH_CATEGORY_RE.test(flatSection));
          if (!same) {
            return;
          }
          if (/^开始/.test(e.label || "")) {
            startEntries.set(e.itemIndex, ei);
          } else if (/^结束/.test(e.label || "")) {
            endEntries.set(e.itemIndex, ei);
          }
        });
        // 配对顺序：优先按 placeholder/旁注文本分类（开始/结束线索），
        // 无法分类时回退扫描序交替假设（start,end,start,end…）
        const hints = group.map((x) =>
          /开始|起始|从/.test(`${x.f.placeholder || ""} ${x.f.nearbyText || ""}`)
            ? "start"
            : /结束|止|至|到/.test(`${x.f.placeholder || ""} ${x.f.nearbyText || ""}`)
              ? "end"
              : ""
        );
        let order = group.map((_, i) => i);
        if (hints.every((h) => h) && hints.filter((h) => h === "start").length ===
              hints.filter((h) => h === "end").length) {
          order = [
            ...hints.map((h, i) => (h === "start" ? i : -1)).filter((i) => i >= 0),
            ...hints.map((h, i) => (h === "end" ? i : -1)).filter((i) => i >= 0),
          ];
        }
        const itemIdxs = [...startEntries.keys()].sort((a, b) => a - b);
        itemIdxs.forEach((idx, k) => {
          const fStart = group[order[k * 2] ?? k * 2];
          const fEnd = group[order[k * 2 + 1] ?? k * 2 + 1];
          const eiStart = startEntries.get(idx);
          const eiEnd = endEntries.get(idx);
          if (fStart && eiStart !== undefined) {
            candidates.push({ fi: fStart.fi, ei: eiStart, score: 90 });
            rangeHandled.add(fStart.fi);
          }
          if (fEnd && eiEnd !== undefined) {
            candidates.push({ fi: fEnd.fi, ei: eiEnd, score: 90 });
            rangeHandled.add(fEnd.fi);
          }
        });
      }
    }
    for (let fi = 0; fi < fields.length; fi += 1) {
      const field = fields[fi];
      if (rangeHandled.has(fi)) {
        continue;
      }
      // AI 映射直通：页面标签 → 档案标签。域否决与值形否决照常生效——
      // AI 结果只是「建议配对」，错配（跨域/值形冲突）与规则通道同罪同罚。
      const mappedLabel = mapping && field.label ? mapping[field.label] : null;
      if (mappedLabel) {
        // repeat 多段：第 N 个同标签字段配第 N 条档案条目（第 2 段实习
        // 不再永远吃第 1 条档案内容）；无对应 occurrence 时回退第一条
        const cands = [];
        entries.forEach((e, ei) => {
          if (e.label === mappedLabel) {
            cands.push({ e, ei });
          }
        });
        const occ = field.occurrenceIndex || 0;
        let pick =
          cands.find((x) => x.e.itemIndex === occ) ||
          (occ === 0 ? cands.find((x) => x.e.itemIndex == null) : null) ||
          cands[0];
        if (
          pick &&
          !domainConflict(field, pick.e) &&
          !shapeConflict(field, pick.e) &&
          !field.currentValue
        ) {
          candidates.push({ fi, ei: pick.ei, score: 999 });
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
        let threshold = field.currentValue ? SCORE_THRESHOLD_PREFILLED : SCORE_THRESHOLD;
        // 纠偏：预填值与档案不一致（多为站点解析简历产生的乱配预填）时按普通阈值覆盖，
        // 值一致则不写（本就正确）。options.correctPrefilled=false 可关。
        // 「一致」按宽松口径：日期格式差异（1999年3月 vs 1999-03）不算不一致，
        // 否则会把语义相同的值重写一遍还标 corrected 误导报告。
        if (
          field.currentValue &&
          threshold === SCORE_THRESHOLD_PREFILLED &&
          options && options.correctPrefilled !== false &&
          !sameLooseValue(String(entry.value), String(field.currentValue))
        ) {
          threshold = SCORE_THRESHOLD;
        }
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

    // 合并填充：站点项目条目没有「项目链接」字段时，把档案里的项目地址
    // 追加进描述文本（信息不丢，站点侧可点击复制的纯文本）。
    {
      const DESC_LABEL_RE =
        /^(项目描述|工作内容|职责|工作职责|实习职责|项目详情|项目内容|描述)$/;
      for (const item of plan) {
        const cat = String(item.entry.category || "");
        if (
          item.entry.itemIndex == null ||
          !DESC_LABEL_RE.test(item.entry.label || "") ||
          !/经历$/.test(cat)
        ) {
          continue;
        }
        // 站点已有链接字段命中时不合并
        const hasLinkField = plan.some(
          (x) =>
            x.entry.category === item.entry.category &&
            x.entry.itemIndex === item.entry.itemIndex &&
            /^(项目链接|项目地址|项目主页)$/.test(x.entry.label || "")
        );
        if (hasLinkField) {
          continue;
        }
        for (const e of entries) {
          if (
            e.category === item.entry.category &&
            e.itemIndex === item.entry.itemIndex &&
            !usedEntries.has(e) &&
            /^(项目链接)$/.test(e.label || "") &&
            e.value
          ) {
            const desc = String(item.entry.value || "").trim();
            // 单行控件（input）会被浏览器剥掉换行，用空格连接；多行控件保留换行
            const el = item.field.element;
            const joiner =
              el instanceof HTMLTextAreaElement ||
              (el && el.isContentEditable) ||
              (el instanceof HTMLElement && el.getAttribute("role") === "textbox")
                ? "\n"
                : " ";
            const tail = `项目地址：${e.value}`;
            item.entry = {
              ...item.entry,
              value: desc ? `${desc}${joiner}${tail}` : tail,
            };
            break;
          }
        }
      }
    }
    return { plan, usedFields };
  }

  // ---------- 自定义下拉 ----------

  /** 找相邻表单行：容器可能是行内 content/label 包装层（如 aui-form-item__content），
   *  本级无兄弟时逐级向上（最多3跳）再取 prev/next 兄弟。 */
  function neighborRow(container, dir, hops = 3) {
    let node = container;
    for (let i = 0; node && i < hops; i += 1) {
      const sib = dir === "prev" ? node.previousElementSibling : node.nextElementSibling;
      if (sib) {
        return sib;
      }
      node = node.parentElement;
    }
    return null;
  }

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
   *  phoenix-unmodeled-layer 小条，真面板（下拉/日历）都在 200px+。
   *  宽度门槛 36：性别等两字选项面板仅 ~50px 宽，不能按宽度误杀。 */
  function findPopupLayers() {
    const layers = [];
    for (const el of document.querySelectorAll(PANEL_SELECTOR)) {
      if (!isVisible(el)) {
        continue;
      }
      const r = el.getBoundingClientRect();
      if (r.width < 36 || r.height < 60) {
        continue;
      }
      // 北森 phoenix 每个字段控件里都常驻一个"伪弹层"包装（phoenix-unmodeled-layer，
      // 全部可见），上百个假层会污染 [0]/[length-1] 索引、搜索引擎框与宿主判定
      //（星网真站实测）—— 只排除字段容器内非浮动定位的层
      if (
        el.closest(
          '.ant-form-item,.el-form-item,.form-item,[class*="formItem"],[class*="FormItem"]'
        )
      ) {
        if (getComputedStyle(el).position === "static") {
          continue;
        }
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
    // 通用内容指纹：不看组件库类名——浮层文本含「YYYY年M月」且带星期表头
    // （连续5个以上曜日字符）或 20+ 日期格，即认定为日历面板。
    // 覆盖自研组件库（如华为 AUI 的 aui-popover 不在任何类名名单里）。
    const floating = document.querySelectorAll(
      '[class*="pop"],[class*="picker"],[class*="calendar"],[class*="layer"],[class*="dropdown"]'
    );
    for (const el of floating) {
      if (!isVisible(el)) {
        continue;
      }
      const st = getComputedStyle(el);
      if (!["fixed", "absolute"].includes(st.position)) {
        continue;
      }
      const r = el.getBoundingClientRect();
      if (r.width < 120 || r.height < 80) {
        continue;
      }
      const text = norm(el.textContent, 400);
      if (!/(\d{4})\s*年\s*(\d{1,2})\s*月/.test(text) && !/(\d{4})\s*年/.test(text)) {
        continue;
      }
      const compact = text.replace(/\s+/g, "");
      const weekdayHeader = /[日一二三四五六]{5,}/.test(compact);
      const cellCount = el.querySelectorAll(
        'td,[class*="cell"],[class*="day"],[class*="date"]'
      ).length;
      // 月面板特征：≥8 个「N月」叶子格（年月连写文本可能不出现）
      const monthLike = Array.from(el.querySelectorAll("td,span,div,a")).filter(
        (n) => n.children.length === 0 && isVisible(n) && /^\d{1,2}月$/.test(norm(n.textContent, 8))
      ).length;
      if (weekdayHeader || cellCount >= 20 || monthLike >= 8) {
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

  /** 月面板（纯年月选择器）：含 ≥8 个「N月」格。Phoenix/antd 的 MonthPicker。 */
  function detectMonthPanel(panel) {
    return Array.from(
      panel.querySelectorAll('[class*="month-panel-month"],[class*="month"],td,[class*="cell"]')
    ).filter((n) => {
      // 排除头部装饰（如 phoenix-calendar-month-select 也显示「9月」但不是格子）
      const cls = String(n.className || "");
      if (/(select|btn|head|header|nav)/i.test(cls)) {
        return false;
      }
      return isVisible(n) && /^\d{1,2}月$/.test(norm(n.textContent, 8));
    });
  }

  /** 月面板年读数：优先面板自身的年元素（Phoenix month-panel-year-select 显示「2026x」）。 */
  function readMonthPanelYear(panel) {
    const yEl = panel.querySelector('[class*="month-panel-year"]');
    if (yEl) {
      const m = norm(yEl.textContent, 12).match(/(\d{4})/);
      if (m) {
        return Number(m[1]);
      }
    }
    const m2 = norm(panel.textContent, 400).match(/(\d{4})\s*年/);
    return m2 ? Number(m2[1]) : null;
  }

  /** 月面板翻年：候选箭头逐个试，年读数变化才算成功（同一面板常渲染两套箭头）。 */
  async function clickMonthPanelYearArrow(panel, kind) {
    const before = readMonthPanelYear(panel);
    for (const sel of [`[class*="month-panel-${kind}-year"]`, `[class*="${kind}-year"]`]) {
      for (const btn of Array.from(panel.querySelectorAll(sel)).filter(isVisible)) {
        dispatchPointerSeq(btn); // Phoenix 手势监听在 pointerdown，普通合成 click 不触发
        await sleep(200);
        const after = readMonthPanelYear(panel);
        if (after !== null && after !== before) {
          return true;
        }
      }
    }
    return false;
  }

  async function clickCalendarArrow(panel, kind, unit) {
    // 优先单位专属箭头（prev-year/prev-month，覆盖 ant 的 *-btn 与 AUI 的裸类名），
    // 无单位区分的库退化为单箭头按月翻
    let btn = panel.querySelector(`[class*="${kind}-${unit}"]`);
    if (!btn) {
      btn = panel.querySelector(
        `[class*="${kind}-year-btn"],[class*="${kind}-month-btn"],[class*="${kind}"]`
      );
    }
    if (btn) {
      dispatchPointerSeq(btn); // Phoenix 手势监听在 pointerdown
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

    // 触发点击：优先输入框本身（多数库监听在 input 上），
    // 无面板再补点包装层（部分库监听在 wrapper）
    const trigger =
      field.element instanceof HTMLInputElement && !field.element.disabled
        ? field.element
        : field.element.closest('[class*="select"],[class*="date"],[class*="picker"]') ||
          field.element;
    clickActionElement(trigger);
    await sleep(320);
    if (!findCalendarPanel()) {
      const wrap = trigger.closest('[class*="date"],[class*="picker"],[class*="select"]');
      if (wrap && wrap !== trigger) {
        clickActionElement(wrap);
        await sleep(320);
      }
    }
    let panel = findCalendarPanel();
    if (window.__AO_DEBUG__) {
      console.log("[ao] date", field.label, "panel:", panel ? (panel.className || "").toString().slice(0, 40) : null);
    }
    if (!panel) {
      return { ok: false, reason: "日历面板未出现" };
    }

    // 月面板模式（纯年月选择器）：翻年到目标年后直接点「N月」格。
    // 值带日也走此路径——月面板上日格不存在，日无意义。
    {
      const mpCells = detectMonthPanel(panel);
      if (mpCells.length >= 8 && month !== null) {
        let guard = 0;
        while (guard < 30) {
          guard += 1;
          const fresh = findCalendarPanel();
          if (fresh) {
            panel = fresh;
          }
          const y = readMonthPanelYear(panel);
          if (y === null || y === year) {
            break;
          }
          const moved = await clickMonthPanelYearArrow(panel, y > year ? "prev" : "next");
          if (!moved) {
            break;
          }
          await sleep(120);
        }
        const y2 = readMonthPanelYear(panel);
        if (y2 !== year) {
          return { ok: false, reason: `月面板年未到位(${y2 ?? "?"})` };
        }
        const freshCells = detectMonthPanel(panel);
        const cell = freshCells.find((c) => {
          const t = norm(c.textContent, 8);
          return t === `${month}月` || t === `${String(month).padStart(2, "0")}月`;
        });
        if (!cell) {
          return { ok: false, reason: `月格 ${month} 未找到` };
        }
        dispatchPointerSeq(cell);
        await sleep(220);
        return { ok: true };
      }
    }

    let guard = 0;
    const maxSteps = 240;
    // 日历（带日格）+ 纯年月值：以 1 日代填（组件需要具体日期，
    // 否则会停在当前默认月——如「2027-06」被显示成 2027-09-06）
    const effDay = day === null && detectMonthPanel(panel).length < 8 ? 1 : day;
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
      const ymOk = cur[0] === year && (effDay === null || cur[1] === month);
      if (ymOk) {
        break;
      }
      if (cur[0] !== year) {
        await clickCalendarArrow(panel, cur[0] > year ? "prev" : "next", "year");
      } else {
        await clickCalendarArrow(panel, cur[1] > month ? "prev" : "next", "month");
      }
      guard += 1;
      await sleep(110);
    }
    const finalPanel = findCalendarPanel() || panel;
    const finalYm = readCalendarYm(finalPanel);
    if (!finalYm || finalYm[0] !== year || (effDay !== null && finalYm[1] !== month)) {
      return { ok: false, reason: `年月导航未到位(${finalYm ? finalYm.join("-") : "?"})` };
    }

    if (effDay === null) {
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
      dispatchPointerSeq(monCell);
      await sleep(180);
      return { ok: true };
    }
    // 日格：文本以目标日数字开头（部分日历混排农历，如「13十四」）。
    // ^N(\D|$) 防止 3 误配 13。
    const dayPat = new RegExp(`^\\s*${effDay}(\\D|$)`);
    // 排除跨月灰格（phoenix 的 next/prev-month-btn-day 等）：9 月面板里文本「1」
    // 的第一格常是 10 月 1 日灰格，误点会得到错误的月份值。
    const inMonth = (n) => {
      for (let e = n; e && e !== finalPanel; e = e.parentElement) {
        const cls = String(e.className || "");
        if (/next-month|prev-month|outside|other-|muted|disabled/i.test(cls)) {
          return false;
        }
      }
      return true;
    };
    const dayNodes = Array.from(
      finalPanel.querySelectorAll('td,[class*="cell"],[class*="day"],[class*="date"]')
    ).filter((n) => dayPat.test(norm(n.textContent, 12)) && isVisible(n));
    const target =
      dayNodes.find(inMonth) ||
      dayNodes[0] ||
      findVisibleChoiceOptions(finalPanel).find((o) => dayPat.test(norm(o.textContent, 12)));
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
        dispatchPointerSeq(monCell);
        await sleep(180);
        return { ok: true };
      }
      return { ok: false, reason: `日格 ${effDay} 未找到` };
    }
    dispatchPointerSeq(target);
    await sleep(180);
    return { ok: true };
  }

  /**
   * 级联面板逐层下钻：值是多层串（如「四川省德阳市」），首层选项只是值的
   * 前缀 → 点开该层，面板原地刷新出下层选项，逐层消耗剩余文本。
   * 返回 null 表示不是级联场景（无前缀选项），交回上层走搜索降级。
   */
  async function drillCascadeChoice(value) {
    // 全程在 norm 空间操作（与 choiceTextMatches 同口径），避免原始串与压缩串长度错位
    let remaining = norm(String(value), 40);
    for (let hop = 0; hop < 4; hop += 1) {
      const layers = findPopupLayers();
      if (!layers.length) {
        return null;
      }
      const opts = findVisibleChoiceOptions(null).filter((o) =>
        layers.some((l) => l.contains(o))
      );
      if (!opts.length) {
        return null;
      }
      const target = norm(remaining, 40);
      const exact = opts.find((o) => {
        const t = norm(o.textContent, 40);
        // 前缀选项（省）只负责展开下层，不算完成——完整值在下一层
        if (target.startsWith(t) && target.length - t.length >= 2) {
          return false;
        }
        return choiceTextMatches(t, target);
      });
      if (exact) {
        clickOptionIcon(exact); // 级联叶子也要打图标热区（新版组件监听在 icon-container）
        await sleep(320);
        // 级联面板同样是「选择+确定」两段式：叶子选中后补点确定（面板已自动关则跳过）
        await confirmPanelIfOpen(exact);
        return { ok: true };
      }
      // 前缀选项：选项文本是剩余值的开头，且点完还有 ≥2 字符的下层
      const prefix = opts
        .map((o) => ({ o, t: norm(o.textContent, 40) }))
        .filter((x) => x.t.length >= 2 && target.startsWith(x.t) && target.length - x.t.length >= 2)
        .sort((a, b) => b.t.length - a.t.length)[0];
      if (!prefix) {
        return null;
      }
      // 点击热区双保险：先打图标（新版组件），层内容未变再补打文本（旧版热区）
      const layerBefore = norm(
        ((findPopupLayers().find((l) => l.contains(prefix.o)) || {}).textContent || ""),
        200
      );
      clickOptionIcon(prefix.o);
      await sleep(800); // 等层切换渲染（面包屑/子列表）
      let layerNow = "";
      const layersNow = findPopupLayers();
      if (layersNow.length) {
        layerNow = norm(
          (layersNow.find((l) => l.contains(prefix.o)) || layersNow[layersNow.length - 1])
            .textContent || "",
          200
        );
      }
      if (layerNow === layerBefore && layersNow.length) {
        dispatchPointerSeq(prefix.o);
        await sleep(800);
      }
      remaining = remaining.slice(prefix.t.length);
    }
    return null;
  }

  /**
   * 日期策略链尾：面板操作全部失败时退回直接键入格式串——
   * 可编辑 input 的库（phoenix-select--editable 等）会自行解析。
   * 依次尝试 YYYY-MM[-DD] / YYYY/MM / YYYY年M月，均无效返回 null。
   */
  async function tryDirectDateInput(field, value) {
    const m = String(value).match(/^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/);
    if (!m) {
      return null;
    }
    const el = field.element;
    if (!(el instanceof HTMLInputElement) || el.readOnly || el.disabled) {
      return null;
    }
    const p2 = (n) => String(n).padStart(2, "0");
    const [, y, mo, d] = m;
    const formats = d
      ? [`${y}-${p2(mo)}-${p2(d)}`, `${y}/${p2(mo)}/${p2(d)}`, `${y}年${mo}月${d}日`]
      : [`${y}-${p2(mo)}`, `${y}/${p2(mo)}`, `${y}年${mo}月`];
    for (const fmt of formats) {
      setNativeValue(el, fmt);
      await sleep(320);
      const v = norm(el.value, 30);
      if (/\d{4}/.test(v) && v) {
        return { ok: true };
      }
    }
    setNativeValue(el, "");
    return null;
  }

  /**
   * 选项点击：优先打行内「图标容器」（北森新版把监听挂在左侧 icon-container 上，
   * 点右侧文本是兄弟节点、冒泡不经过监听者）。从选项元素向上找含图标的行容器。
   */
  function clickOptionIcon(opt) {
    let node = opt;
    for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
      const icon = node.querySelector('[class*="icon-container"],[class*="icon"],svg');
      if (icon) {
        // 北森 phoenix 把 onClick 绑在 icon 容器的内层 svg 上，事件只向上冒泡，
        // 点容器本身永远够不到处理器 —— 必须打最内层热区（实测星网真站）
        const inner = icon.querySelector("svg") || icon;
        dispatchPointerSeq(inner);
        return true;
      }
      if (node.matches('[class*="list-item-container"],li')) {
        break;
      }
    }
    dispatchPointerSeq(opt);
    return false;
  }

  /**
   * 两段式面板：选后面板未关 → 点「确定」提交（北森 constant-main 面板
   * 是「选择+确定」两段式，不点确定值不落控件）。按钮热区冗余尝试：
   * content 深层 → 逐层外容器，点到面板关闭为止。
   */
  async function confirmPanelIfOpen(opt) {
    const layers = findPopupLayers();
    const host = layers.find((l) => (opt ? l.contains(opt) : false)) || layers[layers.length - 1];
    if (!host) {
      return;
    }
    const confirms = [...host.querySelectorAll("button,[class*=button],[class*=btn],div,span")]
      .filter((b) => b.children.length <= 2 && isVisible(b))
      .filter((b) => /^(确定|确认|OK)$/.test(norm(b.textContent, 8)))
      // 禁用态跳过（选中未落时按钮常为灰）
      .filter((b) => {
        const cls = String(b.className || "");
        return !b.disabled && !/disabled/i.test(cls) && b.getAttribute("aria-disabled") !== "true";
      });
    if (!confirms.length) {
      // 全部禁用：等 600ms 后重找一次（选中状态落地有时差）
      await sleep(600);
      const retryHost = findPopupLayers().find((l) => (opt ? l.contains(opt) : false)) || findPopupLayers()[0];
      if (!retryHost) {
        return;
      }
      confirms.push(
        ...[...retryHost.querySelectorAll("button,[class*=button],[class*=btn],div,span")]
          .filter((b) => b.children.length <= 2 && isVisible(b))
          .filter((b) => /^(确定|确认|OK)$/.test(norm(b.textContent, 8)))
          .filter((b) => {
            const cls = String(b.className || "");
            return !b.disabled && !/disabled/i.test(cls) && b.getAttribute("aria-disabled") !== "true";
          })
      );
      if (!confirms.length) {
        return;
      }
    }
    // 同链去重后向每个按钮的最深可见后代派发：真实点击命中的永远是最内层
    // 元素再向上冒泡，而北森 phoenix 把 onClick 绑在 phoenix-button__wraper
    // 内层（容器无处理器），从容器直接派发够不到（星网真站实测）
    const deepestIn = (btn) => {
      let best = btn;
      let bestDepth = 0;
      for (const d of btn.querySelectorAll("*")) {
        if (!isVisible(d)) {
          continue;
        }
        let depth = 0;
        for (let n = d; n && n !== btn; n = n.parentElement) {
          depth += 1;
        }
        if (depth > bestDepth) {
          best = d;
          bestDepth = depth;
        }
      }
      return best;
    };
    const uniq = confirms.filter((b, i) => !confirms.some((o, j) => j !== i && o.contains(b)));
    for (const btn of uniq.slice(0, 4)) {
      dispatchPointerSeq(deepestIn(btn));
      await sleep(450);
      if (findPopupLayers().length === 0) {
        return; // 面板已关 = 提交成功
      }
    }
  }

  async function clickChoiceOption(opt) {
    clickOptionIcon(opt);
    await sleep(320);
    await confirmPanelIfOpen(opt);
  }

  /**
   * 面板内搜索选择：area 级联等带搜索框的面板（「请在左侧选择地区」类），
   * 直接搜索值的最末级（如「德阳」）→ 过滤结果里点匹配项（icon 热区）→ 点确定。
   * 导航式面板点树只翻层不选中，搜索结果才是可选叶子。
   */
  async function searchPanelAndPick(value) {
    const layers = findPopupLayers();
    const search = layers
      .map((l) => l.querySelector('input:not([type="hidden"])'))
      .find(Boolean);
    if (!search || search.readOnly) {
      return null;
    }
    // 取值的最末级行政名：四川省德阳市 → 德阳
    const compactVal = norm(String(value), 40);
    const tokens = compactVal
      .split(/省|市|自治区|特别行政区/)
      .map((t) => t.trim())
      .filter((t) => t.length >= 2);
    // 关键词候选：最末级优先；地区库常不含镇/街道级（星网真站籍贯「马祖镇」搜不到），
    // 逐级降级到上一级行政区，降级命中时以 trust 标记跳过整串回读校验
    const kws = [tokens[tokens.length - 1], ...tokens.slice(0, -1).reverse()]
      .filter(Boolean)
      .filter((t, i, a) => a.indexOf(t) === i);
    if (!kws.length) {
      return null;
    }
    let pick = null;
    let usedKw = null;
    let degraded = false;
    const findPick = (kw) => {
      const layers2 = findPopupLayers();
      const host = layers2.find((l) => l.contains(search)) || layers2[layers2.length - 1];
      if (!host) {
        return null;
      }
      const cands = [...host.querySelectorAll("div,span")].filter(
        (e) =>
          isVisible(e) &&
          (e.textContent || "").includes(kw) &&
          (e.textContent || "").trim().length <= 20 &&
          (e.textContent || "").trim().length > 0
      );
      // 结果行以面积最大的行容器优先（文本可能被高亮 <mark> 拆开，行容器才是热区祖先）
      return cands.sort((a, b) => a.textContent.length - b.textContent.length)[0] || null;
    };
    for (const kw of kws) {
      setNativeValue(search, kw);
      // 搜索结果异步渲染（实测 ~1.2s+）：轮询等结果出现，避免固定等待不够
      pick = null;
      for (let i = 0; i < 6; i += 1) {
        await sleep(500);
        pick = findPick(kw);
        if (pick) {
          break;
        }
      }
      if (pick) {
        usedKw = kw;
        degraded = kw !== kws[0];
        break;
      }
    }
    if (!pick) {
      setNativeValue(search, "");
      return null;
    }
    clickOptionIcon(pick);
    await sleep(600);
    // 选中确认：面板「已选 N/1」计数为 0 说明结果项没选上（时序/首次点击未达）——
    // 重试一次（元素被 React 重建时重新查找）。注意计数格式「已选地区0/1」，
    // 分子是斜杠前的数字（旧正则抓到分母会误判已选中）
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const hostNow = findPopupLayers().find((l) => l.contains(pick));
      if (!hostNow) {
        break; // 面板已关（选中即提交型）
      }
      const m = (hostNow.textContent || "").match(/已选[^0-9]{0,8}(\d+)\s*\/\s*\d+/);
      if (!m || Number(m[1]) > 0) {
        break; // 无计数（普通面板）或已选中
      }
      const still = pick.isConnected ? pick : null;
      const again = still || [...hostNow.querySelectorAll("div,span")]
        .filter((e) => isVisible(e) && (e.textContent || "").includes(usedKw) && (e.textContent || "").trim().length <= 20)
        .sort((a, b) => a.textContent.length - b.textContent.length)[0];
      if (!again) {
        break;
      }
      clickOptionIcon(again);
      await sleep(550);
    }
    await confirmPanelIfOpen(pick);
    // 降级命中（镇级搜不到落在区县）：站点可表达的最深层级，回读必然与整串
    // 档案值不一致 —— trust 跳过严格校验，避免把「已尽力填对」误报为失败
    if (degraded) {
      return { ok: true, trust: true, via: `面板搜索(${usedKw})` };
    }
    return { ok: true, via: "面板搜索" };
  }

  /**
   * 并排级联选择器：同一下拉组里省/市/区县是平行的多个 select（长虹
   * cascader-plugins-wrap 模式），上级选中后下级才加载选项、区县 select
   * 可能动态出现。逐个 select 用「值剩余前缀」挑最长匹配选项；全部选完
   * 以组合值做整体校验（单 select 回读只含一层必然不一致）。
   * 不适用（非并排结构）返回 null 走原路径。
   */
  async function tryFillParallelCascade(field, value) {
    const holder =
      field.container ||
      (field.element instanceof Element
        ? field.element.closest(".ant-form-item, [class*='form-item'], [class*='field']")
        : null);
    if (!holder) {
      return null;
    }
    const selectsOf = () =>
      Array.from(holder.querySelectorAll(".ant-select, [class*='select--single'], select"))
        .filter((s) => isVisible(s) && s.tagName !== "SELECT")
        .map((s) => ({
          root: s,
          read: () => {
            const v = s.querySelector(
              '[class*="selection-selected"], [class*="selection__rendered"]'
            );
            const t = v ? norm(v.textContent, 24) : "";
            return /^(请选择|请输入)?$/.test(t) ? "" : t;
          },
        }));
    let selects = selectsOf();
    if (selects.length < 2) {
      return null; // 普通单 select：不是并排级联
    }
    // 已选层拼起来是值前缀 → 从剩余段继续；完全对不上则从头重选
    let combined = selects.map((x) => x.read()).filter(Boolean).join("");
    let remaining = norm(String(value), 60);
    if (combined && remaining.startsWith(combined)) {
      remaining = remaining.slice(combined.length);
      if (!remaining) {
        return { ok: true, trust: true, via: "并排级联" }; // 已完整（幂等重跑）
      }
    }
    let moved = false;
    for (let round = 0; round < 5; round += 1) {
      selects = selectsOf();
      const target = selects.find((x) => !x.read());
      if (!target || !remaining) {
        break;
      }
      await closeStalePanels();
      const trig =
        target.root.querySelector('[class*="selection"], [class*="selector"]') || target.root;
      clickActionElement(trig);
      let layers = [];
      for (let i = 0; i < 6 && layers.length === 0; i += 1) {
        await sleep(220);
        layers = findPopupLayers().filter((l) => l.querySelector("li, [class*='option']"));
      }
      if (layers.length === 0) {
        break;
      }
      const menu = layers[layers.length - 1];
      const opts = Array.from(menu.querySelectorAll("li, [class*='option']")).filter(isVisible);
      const scored = opts
        .map((o) => ({ o, t: norm(o.textContent, 20) }))
        .filter((x) => x.t.length >= 2 && remaining.startsWith(x.t))
        .sort((a, b) => b.t.length - a.t.length);
      if (scored.length === 0) {
        await closeStalePanels();
        break; // 值在这一层没有对应选项（如镇级）：止步于站点可表达层级
      }
      clickActionElement(scored[0].o);
      moved = true;
      await sleep(420);
      remaining = remaining.slice(scored[0].t.length);
      await closeStalePanels();
      await sleep(160);
    }
    if (!moved && !combined) {
      return null; // 一层都没选上：交回原路径（可能只是普通下拉长得像）
    }
    const finalAll = selectsOf()
      .map((x) => x.read())
      .filter(Boolean)
      .join("");
    const expect = norm(String(value), 60);
    // 组合值是档案值的逐层前缀即视为成功（站点层级数可能少于档案粒度）
    if (finalAll && (expect.startsWith(finalAll) || norm(finalAll, 60) === expect)) {
      return { ok: true, trust: true, via: "并排级联" };
    }
    return { ok: false, reason: `并排级联未选全(${finalAll.slice(0, 16)})` };
  }

  /**
   * 内联搜索型下拉（长虹学校库）：搜索框在 select 控件内部（antd
   * ant-select-search__field），面板里没有输入框——searchPanelAndPick 找
   * 不到。键入值过滤选项后点匹配项，失败清词不留污染。
   */
  async function tryInlineSearchSelect(field, value) {
    const holder =
      field.container ||
      (field.element instanceof Element
        ? field.element.closest(".ant-form-item, [class*='form-item'], [class*='field']")
        : null);
    if (!holder) {
      return null;
    }
    // 仅可搜索型 select（antd 根节点带 show-search）；普通下拉也带隐藏的
    // search__field 节点，误触发会把值打进非搜索框（长虹真站实测）
    if (
      !holder.querySelector('[class*="select"][class*="show-search"], [class*="select"][class*="search"]')
    ) {
      return null;
    }
    // 确定性开面板：先清残留面板（上游路径可能已把本面板关掉、或留着
    // 别家面板让 aria-expanded 误判），再点自己的触发器，最后找搜索框
    //（antd 搜索框在面板打开前是 display:none，必须先开后查）
    const trig = holder.querySelector('[class*="select-selection"], [class*="selector"]');
    const findSearch = () =>
      Array.from(
        holder.querySelectorAll('input[class*="search__field"], input[class*="search-input"]')
      ).find((i) => isVisible(i) && !i.readOnly && !i.disabled);
    await closeStalePanels();
    let search = findSearch();
    if (!search && trig) {
      clickActionElement(trig);
      await sleep(320);
      search = findSearch();
    }
    if (!search) {
      await closeStalePanels();
      return null;
    }
    search.focus();
    const kw = norm(String(value), 24);
    if (!kw) {
      return null;
    }
    // 不走 setNativeValue：它结尾派发 blur 会让 antd 立即收起下拉
    //（长虹学校库实测：输入完成面板就没了），这里只发 input
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    if (desc && desc.set) {
      desc.set.call(search, kw);
    } else {
      search.value = kw;
    }
    search.dispatchEvent(new Event("input", { bubbles: true }));
    await sleep(900);
    // 过滤后常只剩一行选项（「使用X作为我的学校"），面板高度 <60px 会被
    // findPopupLayers 的通用阈值筛掉 —— 这里用轻量探测器只看可见性
    const layers = [...document.querySelectorAll('[class*="select-dropdown"], [role="listbox"]')]
      .filter((l) => isVisible(l) && l.getBoundingClientRect().height >= 20)
      .filter((l) => l.querySelector("li, [class*='option']"));
    if (layers.length === 0) {
      setNativeValue(search, "");
      await closeStalePanels();
      return null;
    }
    const menu = layers[layers.length - 1];
    const opts = Array.from(menu.querySelectorAll("li, [class*='option']")).filter(isVisible);
    // 优先精确等值，其次最短文本（过滤结果常带「使用X作为我的学校」辅助项）
    const hit = opts
      .map((o) => ({ o, t: norm(o.textContent, 30) }))
      .filter((x) => x.t === kw || x.t.includes(kw) || kw.includes(x.t))
      .sort((a, b) => (a.t === kw ? 0 : 1) - (b.t === kw ? 0 : 1) || a.t.length - b.t.length)[0];
    if (!hit) {
      setNativeValue(search, "");
      await closeStalePanels();
      return null;
    }
    clickActionElement(hit);
    await sleep(400);
    await closeStalePanels();
    // 校验：展示值应与档案值一致（词序无关由回读口径兜底）
    const shown = holder.querySelector('[class*="selection-selected"]');
    const shownText = shown ? norm(shown.textContent, 30) : "";
    if (shownText && (shownText.includes(kw) || kw.includes(shownText))) {
      return { ok: true, via: "内联搜索" };
    }
    return { ok: true, trust: true, via: "内联搜索" };
  }

  async function tryFillCustomChoiceField(field, value) {
    const el = field.element;
    const container = findChoiceFieldContainer(el, field.container);
    container.scrollIntoView({ block: "center", inline: "nearest" });
    // 上一字段遗留的弹层先清掉：不清的话点本字段的触发器可能被旧面板
    // 拦截（antd 关旧开新有竞态），或把旧面板的选项当成自己的
    await closeStalePanels();
    clickActionElement(el instanceof Element ? el : container);
    // 自研组件库弹层有过渡动画（AUI ~300ms opacity）：先耐心等面板出现，
    // 不能在动画期间误判「未打开」去补点 wrapper——那会把已开的面板点成关闭
    for (let i = 0; i < 5 && findPopupLayers().length === 0; i += 1) {
      await sleep(220);
    }
    if (findPopupLayers().length === 0) {
      const wrapper =
        el instanceof Element
          ? el.closest('[class*="select"],[class*="picker"],[class*="combo"]')
          : null;
      if (wrapper && wrapper !== el) {
        clickActionElement(wrapper);
        for (let i = 0; i < 4 && findPopupLayers().length === 0; i += 1) {
          await sleep(250);
        }
      }
    }

    let options = findVisibleChoiceOptions(container);
    const findChoiceMatch = (opts) =>
      opts.find(
        (opt) =>
          choiceTextMatches(norm(opt.textContent, 60), value) ||
          choiceTextMatches(opt.getAttribute("aria-label") || "", value)
      );
    let matched = findChoiceMatch(options);
    if (!matched) {
      // 选项懒加载时序：面板已开但列表异步渲染（北森籍贯省列表 ~1.5s 后才出现，
      // 第一时间只能收到右侧「已选地区」栏）。带重试重收，也识别「选项是值前缀」
      // 的级联场景（说明列表已就绪，交给下钻逻辑处理）。
      const valText = norm(String(value), 40);
      for (let i = 0; i < 3; i += 1) {
        await sleep(550);
        options = findVisibleChoiceOptions(container);
        matched = findChoiceMatch(options);
        if (matched) {
          break;
        }
        const prefixReady = options.some((o) => {
          const t = norm(o.textContent, 40);
          return t.length >= 2 && valText.startsWith(t) && valText.length - t.length >= 2;
        });
        if (prefixReady) {
          break;
        }
      }
    }
    if (window.__AO_DEBUG__) {
      console.log(
        "[ao] choice", field.label, "layers:", findPopupLayers().length,
        "opts:", options.slice(0, 6).map((o) => norm(o.textContent, 10)),
        "val:", String(value).slice(0, 12)
      );
    }
    if (matched) {
      // 包含匹配可能只命中多层值的首层（值「四川省德阳市」匹配选项「四川省」）——
      // 点它但视为级联展开，继续在下层找完整值；单层选中则原样返回成功。
      const single = norm(matched.textContent, 40);
      const multi = norm(String(value), 40);
      if (multi.startsWith(single) && multi.length - single.length >= 2) {
        const drilled = await drillCascadeChoice(value);
        if (drilled) {
          return drilled;
        }
        // 导航式级联面板（点树只翻层不选中）：走「搜索末级→点结果→确定」
        const searched = await searchPanelAndPick(value);
        if (searched) {
          return searched;
        }
      }
      await clickChoiceOption(matched);
      return { ok: true };
    }

    // 级联下钻：整串无匹配（首层选项不含值的任何包含关系时上面的 find 不命中）
    const cascaded = await drillCascadeChoice(value);
    if (cascaded) {
      return cascaded;
    }

    // 面板搜索：带搜索框的级联面板（省市区树导航式）直接搜末级点结果
    const searched = await searchPanelAndPick(value);
    if (searched) {
      return searched;
    }

    // 内联搜索型 select（长虹学校库）：搜索框在控件内部而非面板里，
    // 默认选项只有第一页，键入值过滤后点匹配项
    const inlineSearched = await tryInlineSearchSelect(field, value);
    if (inlineSearched) {
      return inlineSearched;
    }

    // 多值拆分：值是顿号/分号分隔的多个候选（如「英语 CET-4、英语 CET-6」），
    // 每个 token 都能在当前面板找到选项才逐个点选（多选标签控件）；
    // 任一 token 无对应选项则不碰，避免在单选控件上误点多个。
    const tokens = String(value)
      .split(/[、;；]/)
      .map((t) => t.trim())
      .filter((t) => t.length >= 2);
    if (tokens.length >= 2) {
      const picks = tokens
        .map((tk) => options.find((o) => choiceTextMatches(norm(o.textContent, 40), tk)))
        .filter(Boolean);
      if (picks.length === tokens.length) {
        for (const p of picks) {
          clickOptionIcon(p);
          await sleep(340);
        }
        await confirmPanelIfOpen(picks[0]); // 多选全部点完后再统一提交
        return { ok: true };
      }
    }

    // 降级：向内层搜索框注入后重试（带搜索的自定义下拉）。
    // readonly 触发器不是搜索框（纯下拉），注入只会污染显示值，跳过。
    const rawSearch =
      el instanceof HTMLInputElement
        ? el
        : container.querySelector?.('input:not([type="hidden"]),textarea,[contenteditable="true"]');
    const searchInput =
      rawSearch && !(rawSearch instanceof HTMLInputElement && rawSearch.readOnly)
        ? rawSearch
        : null;
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
        await clickChoiceOption(retryMatched);
        return { ok: true };
      }
    }
    return { ok: false, reason: "面板已展开但未匹配到选项" };
  }

  // ---------- 填写与校验 ----------

  /** 元素失效时按 区块+标签+控件类型+occurrence 重定位（React 重渲染）。
   *  occurrenceIndex 必须参与：repeat 多区块里同标签字段有多份，
   *  只按标签重绑会把第 1 段的字段绑到第 2 段的元素上（跨块串值）。 */
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
          (f.section || "") === (field.section || "") &&
          (f.occurrenceIndex || 0) === (field.occurrenceIndex || 0) &&
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
        const group =
          field.groupEl || el.closest('[class*="radio-group"],[class*="checkbox-group"]');
        const groupChecked = () => (group ? norm(readGroupCheckedText(group), 30) : "");
        clickActionElement(matched);
        await sleep(180);
        let checked = groupChecked();
        if (!choiceTextMatches(checked, entry.value)) {
          // 合成 click 对部分自绘组无效（如 Phoenix 单选监听在内部 wrapper）：
          // 对内部节点补发完整指针序列，逐个核对选中态
          const inners = matched.querySelectorAll(
            '[class*="__wrapper"],[class*="__label"],[class*="__text"],' +
              '[class*="__circle"],[class*="__box"]'
          );
          for (const inner of Array.from(inners).slice(0, 3)) {
            dispatchPointerSeq(inner);
            await sleep(200);
            checked = groupChecked();
            if (choiceTextMatches(checked, entry.value)) {
              break;
            }
          }
        }
        if (choiceTextMatches(checked, entry.value)) {
          return { ok: true };
        }
        if (!checked) {
          // 组件不暴露选中态标记，无法核验，按已执行处理（保持旧行为）
          return { ok: true, trust: true };
        }
        return { ok: false, reason: `选中态异常: ${checked.slice(0, 20)}` };
      }
      if (field.kind === "radio" || field.kind === "checkbox") {
        const ok = setCheckboxOrRadio(el, entry.value);
        return ok ? { ok: true } : { ok: false, reason: "未找到匹配选项" };
      }
      if (field.kind === "select") {
        const matched = setSelectValue(el, entry.value);
        // 无匹配时不落值（给 select 设不存在的值等于清空选择），
        // 如实报失败走选项收割 → AI 选选项兜底
        return matched
          ? { ok: true }
          : { ok: false, reason: "未匹配到选项" };
      }
      if (field.kind === "native-date") {
        const type = (el.getAttribute("type") || "").toLowerCase();
        setNativeValue(el, normalizeDateValue(entry.value, type));
        return { ok: true };
      }
      if (field.kind === "custom-choice") {
        // 并排级联（长虹 cascader-plugins-wrap）：省/市/区是同一表单项下
        // 平行的多个 select，选完上级下级才加载选项（甚至动态出现第三个）。
        // 逐级用「值前缀」选层，整串值不再塞给第一个 select
        const parallel = await tryFillParallelCascade(field, entry.value);
        if (parallel) {
          return parallel;
        }
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
          // 策略链尾：面板全败后退回直接键入（可编辑 input 的库会自行解析）
          const direct = await tryDirectDateInput(field, entry.value);
          if (direct) {
            return direct;
          }
          // 级联/日历半途失败后面板常停在中间层：关掉再交收割/AI 轮，
          // 不让残留面板污染后续字段的选项搜索
          await closePopupLayers();
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
      // 逐层扩大范围：search 外壳 → 表单行容器（飞书 selectItem 在 search 的兄弟节点）
      const scopes = [
        findChoiceFieldContainer(el.parentElement || el, null),
        field.container,
        el.closest('[class*="formily-item"],[class*="form-item"],[class*="field"]'),
      ];
      for (const scope of scopes) {
        if (!scope) {
          continue;
        }
        const display = scope.querySelector(
          '[class*="selection-item"],[class*="selected-item"],[class*="selectItem"],[class*="selected"]:not([class*="unselected"])'
        );
        // Phoenix：选中值显示在 ul.phoenix-select__content 的普通 li（inputWrapper 是搜索框）
        const liDisplay = scope.querySelector(
          'ul[class*="content"] > li:not([class*="input"])'
        );
        const text = norm(
          el.value ||
            (display ? display.textContent : "") ||
            (liDisplay ? liDisplay.textContent : ""),
          60
        );
        if (text && !/^请选择|^请输入/.test(text)) {
          return text;
        }
      }
      const wrapper = scopes[0];
      return norm((wrapper && wrapper.textContent) || "", 60);
    }
    if (el.isContentEditable) {
      return norm(el.textContent, 400);
    }
    // 回读上限要大于常见长文本（自我评价/项目描述 100+ 字），否则校验恒假
    return norm(el.value || "", 400);
  }

  // ---------- repeat 多区块（教育经历自动补块；项目/工作经历只填现存块） ----------

  const REPEAT_ADD_RULES = [
    {
      category: /教育经历/,
      anchor: /^学校名称$|学校|院校/,
      btn: /添加.*教育|新增.*教育/,
      btnScoped: /^(添加|新增|\+)$/,
    },
    {
      // (?<!科研)：站点模块叫「科研项目经历」时归科研规则管，项目规则不得越界
      category: /(?<!科研)项目经历/,
      anchor: /^项目名称$/,
      scope: /项目/,
      scopeNot: /科研/,
      btn: /添加.*项目|新增.*项目/,
      btnScoped: /^(添加|新增|\+)$/,
    },
    {
      category: /工作经历|实习经历/,
      anchor: /公司|单位|企业/,
      scope: /工作|实习/,
      btn: /添加.*工作|新增.*工作|添加.*实习/,
      btnScoped: /^(添加|新增|\+)$/,
    },
    {
      category: /科研/,
      anchor: /^项目名称$|科研项目名称|课题名称/,
      scope: /科研/,
      btn: /添加.*科研|新增.*科研/,
      btnScoped: /^(添加|新增|\+)$/,
    },
    {
      // 获奖情况模块：锚点按站点习惯「获奖名称/奖惩名称」都认
      category: /奖惩|获奖/,
      anchor: /奖惩名称|获奖名称|奖项名称|奖励名称/,
      btn: /添加.*(奖|荣誉)|新增.*(奖|荣誉)/,
      btnScoped: /^(添加|新增|\+)$/,
    },
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

  /**
   * 区块内添加按钮（飞书等：按钮文案是区块里裸的「添加」，须按标题圈定范围，
   * 否则会误点其他模块的添加按钮）。
   */
  function findScopedAddButton(categoryRe, btnRe) {
    const titles = Array.from(
      document.querySelectorAll("[class*='title'],[class*='Title'],h2,h3,h4")
    ).filter((e) => isVisible(e) && categoryRe.test(norm(e.textContent, 20)));
    for (const t of titles) {
      let module = t.parentElement;
      for (let i = 0; i < 7 && module; i += 1, module = module.parentElement) {
        // 容器已跨多个模块（含多个已知区块标题）说明爬过头，停止
        // （先于搜索，防误点相邻模块按钮；只认 SECTION_TITLE_RE 防工具提示类误伤）
        if (
          Array.from(module.querySelectorAll("[class*='title'],[class*='Title'],h2,h3,h4")).filter(
            (e) => isVisible(e) && SECTION_TITLE_RE.test((e.textContent || "").trim())
          ).length > 1
        ) {
          break;
        }
        const btns = Array.from(module.querySelectorAll("button,a,span,div")).filter((el) => {
          const hasTextualChild = Array.from(el.children).some((c) => norm(c.textContent, 5));
          if (hasTextualChild || !isVisible(el)) {
            return false;
          }
          const txt = norm(el.textContent, 14);
          return btnRe.test(txt) && txt.length <= 6;
        });
        if (btns.length) {
          return btns[0];
        }
      }
    }
    return null;
  }

  function countAnchorFields(rule) {
    return scanFields(detectSiteAdapter()).fields.filter((f) => {
      if (!rule.anchor.test(f.label || "")) {
        return false;
      }
      // 科研与项目模块的锚点标签可能相同（都叫「项目名称」）：
      // 有模块标题时按 scope 圈定，防止两个模块互相计入对方的块数
      const sec = f.section || "";
      if (rule.scope && sec && !rule.scope.test(sec)) {
        return false;
      }
      if (rule.scopeNot && rule.scopeNot.test(sec)) {
        return false;
      }
      return true;
    }).length;
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

  /** 档案条目多于页面区块时点「添加XX经历」补足（教育/项目/工作实习，最多补到 8 块）。
   *  支持初始零区块的模块（飞书项目/工作经历默认空，需点添加才出现字段）。 */
  async function ensureRepeatBlocks(flatProfile, options) {
    if (options && options.noAddBlocks) {
      return;
    }
    // 总时长上限：站点点击无响应（上限提示浮层等）时不再耗满每击 7s 等待
    const deadline = Date.now() + 25000;
    const cheapCount = () => document.querySelectorAll(CONTROL_SELECTOR).length;
    for (const section of (flatProfile && flatProfile.sections) || []) {
      if (section.kind !== "repeat") {
        continue;
      }
      const need = (section.items || []).length;
      if (need < 1) {
        continue;
      }
      const rule = REPEAT_ADD_RULES.find((r) => r.category.test(section.title));
      if (!rule) {
        continue;
      }
      // 上限 8：科研+工程混合的项目档案常超过 4 条；每次点击都有锚点增长校验兜底
      const target = Math.min(need, 8);
      for (let clicks = 0; clicks < target + 2; clicks += 1) {
        if (Date.now() > deadline) {
          break;
        }
        const blocks = countAnchorFields(rule);
        if (blocks >= target) {
          break;
        }
        const btn = findAddButton(rule.btn) || findScopedAddButton(rule.category, rule.btnScoped);
        if (!btn) {
          break;
        }
        // 增长等待前置轻量检查：控件总数没变就不做全页扫描
        //（countAnchorFields 每次都是全量 querySelectorAll+标签推断，长表单上
        // 150ms 一轮会阻塞主线程）
        const beforeTotal = cheapCount();
        const grewFast = () => cheapCount() !== beforeTotal && countAnchorFields(rule) > blocks;
        clickActionElement(btn);
        let grew = await waitFor(grewFast, 3500);
        if (!grew) {
          // 部分自绘按钮（飞书 ud）不认合成 click：补发指针序列再等一次
          dispatchPointerSeq(btn);
          grew = await waitFor(grewFast, 3500);
        }
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

  /** 关闭打开的弹层面板（模拟外部点击）——级联下钻半途失败后面板停在
   *  中间层，不关会让后续字段的面板搜索在错误层级进行。 */
  async function closePopupLayers() {
    document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    document.body.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    await sleep(150);
  }

  /** 收割固定选项字段的选项清单（native select 直接读；自定义下拉取新出现的弹层）。 */
  /** 清掉遗留弹层（上一字段收割/填写失败的 dropdown 可能还开着）。
   *  antd v3 对合成 body 点击不认账，必须补发 Escape；面板清不干净时，
   *  后续字段的收割会扫到别人的选项（长虹真站：学校下拉收到「无经验/1年」）。 */
  async function closeStalePanels() {
    for (let i = 0; i < 3 && findPopupLayers().length > 0; i += 1) {
      const active = document.activeElement;
      if (active) {
        active.dispatchEvent(
          new KeyboardEvent("keydown", { key: "Escape", keyCode: 27, bubbles: true })
        );
      }
      document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      document.body.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      await sleep(220);
    }
  }

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
      await closeStalePanels();
      // 点自己的触发器开面板，优先收割「新出现」的层：antd 每个组件有独立
      // dropdown 节点常驻 body（display:none），点新触发器时旧节点可能还没
      // 关闭，全量收割会把上一字段的选项算进来
      const before = findPopupLayers();
      const beforeSig = before.map((l) => norm(l.textContent, 60)).join("|");
      clickActionElement(trigger);
      await sleep(400);
      const all = findPopupLayers();
      let layers = all.filter((l) => !before.includes(l));
      if (layers.length === 0) {
        const afterSig = all.map((l) => norm(l.textContent, 60)).join("|");
        // 同节点重渲染（antd 复用 dropdown DOM）或无关闭监听的自绘面板
        //（基准页 fixture：面板只随选中移除，Escape/外点均无效）——
        // 内容变了、或清理后仍有面板开着，都按「本字段的面板」兜底收割
        if (afterSig !== beforeSig || all.length > 0) {
          layers = all;
        }
      }
      // 噪声过滤：功能按钮/日期回显 + 日历格特征（纯数字日格、N月月格）——
      // 它们不是可选业务选项，混进 AI 选选项会把日期字段填成数字
      const noise =
        /^(请选择|删除|全部|确定|取消)$|^\d{4}-\d{1,2}(-\d{1,2})?$|^\d{1,2}$|^\d{1,2}月(份)?$/;
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
      await closeStalePanels();
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

  // ---------- 主入口（多步向导：逐页填写，有界翻页，累积报告） ----------

  /** 可见且不像提交的「下一步」类按钮（多步向导推进用）。
   *  命中词保守（下一步/保存并继续），带 提交/投递/发送 字样的一律不碰。 */
  function findWizardNextButton() {
    const BLOCK_RE = /提交|投递|发送|上传|登录|注册|支付/;
    for (const el of document.querySelectorAll('button,a,[role="button"]')) {
      if (!isVisible(el)) {
        continue;
      }
      const t = norm(el.textContent, 12);
      if (!t || BLOCK_RE.test(t)) {
        continue;
      }
      if (/下一步|保存并继续|继续下一步/.test(t) || /^next$/i.test(compact(t))) {
        return el;
      }
    }
    return null;
  }

  /** 页面签名：可见控件 标签#occurrence 序列——翻页后无变化说明被必填
   *  校验拦住，停止推进（防同页死循环重填）。 */
  function pageSignature() {
    return scanFields(detectSiteAdapter())
      .fields.filter((f) => f.label)
      .map((f) => `${f.section || ""}|${f.label}#${f.occurrenceIndex || 0}`)
      .join(";");
  }

  function mergeFragments(frags) {
    const first = frags[0];
    const sum = (key) =>
      frags.reduce((acc, f) => acc + ((f.counts && f.counts[key]) || 0), 0);
    const uniqBy = (arr, keyFn) => {
      const seen = new Set();
      const out = [];
      for (const x of arr) {
        const k = keyFn(x);
        if (!seen.has(k)) {
          seen.add(k);
          out.push(x);
        }
      }
      return out;
    };
    return {
      site: first.site,
      pageTitle:
        frags.map((f) => f.pageTitle).filter(Boolean).pop() || first.pageTitle,
      url: first.url,
      counts: { filled: sum("filled"), failed: sum("failed"), skipped: sum("skipped") },
      filled: frags.flatMap((f) => f.filled || []),
      failed: frags.flatMap((f) => f.failed || []),
      skipped: frags.flatMap((f) => f.skipped || []),
      unmatched: frags.flatMap((f) => f.unmatched || []),
      formErrors: uniqBy(frags.flatMap((f) => f.formErrors || []), (t) => t),
      optionFields: uniqBy(frags.flatMap((f) => f.optionFields || []), (f) => f.label),
      uploadCount: frags.reduce((acc, f) => acc + (f.uploadCount || 0), 0),
    };
  }

  async function autofill(flatProfile, options) {
    const frags = [];
    const maxPages = 5; // 有界：防「下一步」误识别导致一路翻穿站点
    for (let page = 0; page < maxPages; page += 1) {
      frags.push(await fillOnePage(flatProfile, options));
      if (options && options.noAdvance) {
        break;
      }
      const next = findWizardNextButton();
      if (!next) {
        break;
      }
      const sigBefore = pageSignature();
      clickActionElement(next);
      await sleep(700);
      if (pageSignature() === sigBefore) {
        break;
      }
    }
    return mergeFragments(frags);
  }

  async function fillOnePage(flatProfile, options) {
    const adapter = detectSiteAdapter();
    await ensureRepeatBlocks(flatProfile, options);
    const { fields, uploads } = scanFields(adapter);
    const entries = buildEntries(flatProfile);
    const mapping = (options && options.mapping) || null;
    const { plan, usedFields } = buildPlan(fields, entries, mapping, options);
    // AI 选选项覆盖：字段标签（或 标签#occurrence）→ 选中的选项值。
    // repeat 多区块同标签字段必须按 occurrence 区分，否则 AI 为第 2 段
    // 「学历」挑的选项会同时写进 3 段；裸 label 键保留兼容旧调用方。
    const overrides = (options && options.overrides) || {};
    const overrideFor = (field) => {
      const occKey = `${field.label}#${field.occurrenceIndex || 0}`;
      if (Object.prototype.hasOwnProperty.call(overrides, occKey)) {
        return overrides[occKey];
      }
      return overrides[field.label];
    };
    for (const item of plan) {
      const ov = overrideFor(item.field);
      if (ov) {
        item.entry = { ...item.entry, value: String(ov) };
      }
    }

    const filled = [];
    const failed = [];
    // 日期归一（比较口径）：年/月/日统一补零再去分隔符——
    // "2024-3-5" 与站点回读 "2024-03-05" 必须归到同一形态，否则校验恒假
    const normDate = (s) =>
      String(s)
        .replace(/(\d{4})年(\d{1,2})月(?:(\d{1,2})日?)?/g, (_, y, mo, d) =>
          d ? `${y}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}` : `${y}-${mo.padStart(2, "0")}`
        )
        .replace(/(\d{4})-(\d{1,2})(?:-(\d{1,2}))?/g, (_, y, mo, d) =>
          d ? `${y}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}` : `${y}-${mo.padStart(2, "0")}`
        )
        .replace(/-/g, "");
    // 回读校验统一口径（主循环与自愈回路共用）。期望值上限与 readBack 的
    // 400 对齐——期望值截 260 而回读 400 时，260~400 字长文本恒判失败
    const verifyReadBack = (item, expectValue) => {
      refreshField(item, adapter);
      let v = readBack(item.field);
      if (
        v.includes(expectValue) ||
        norm(expectValue, 400) === v ||
        norm(expectValue) === v ||
        normDate(v).includes(normDate(expectValue))
      ) {
        return true;
      }
      // 选项文本词序无关（如搜索结果「德阳市 四川省」对档案「四川省德阳市」）：
      // 去分隔后字符多重集一致即视为同一选项
      if (item.field.kind === "custom-choice" && v) {
        // 级联/搜索面板提交后控件只显示叶子名（成华区），档案存全路径
        //（四川省成都市成华区）—— 期望值以回读值结尾即视为一致（星网真站实测）
        if (norm(expectValue).endsWith(norm(v)) && norm(v).length >= 2) {
          return true;
        }
        const bag = (s) =>
          norm(s, 80)
            .replace(/[\s,，、/·]/g, "")
            .split("")
            .sort()
            .join("");
        if (bag(v) === bag(expectValue)) {
          return true;
        }
      }
      return false;
    };
    const execAndVerify = async (item) => {
      const wasPrefilled = Boolean(item.field.currentValue && item.field.currentValue.length > 0);
      const result = await fillOne(item, adapter);
      // checkbox 真校验：回读 checked 态与期望布尔核对（不再免检计已填）
      const computeVerified = () => {
        if (item.field.kind === "checkbox") {
          refreshField(item, adapter);
          const should = ["true", "yes", "是", "1", "checked", "on", "接受", "同意"].includes(
            String(item.entry.value == null ? "" : item.entry.value).trim().toLowerCase()
          );
          const v = readBack(item.field);
          return should ? v === "是" : v === "";
        }
        return result.trust || verifyReadBack(item, String(item.entry.value));
      };
      let verified = computeVerified();
      // 文本类回读竞态：React 提交有延迟，稍候重读一次
      if (!verified && result.ok) {
        await sleep(280);
        verified = computeVerified();
      }
      return { result, verified, wasPrefilled };
    };
    for (const item of plan) {
      const { result, verified, wasPrefilled } = await execAndVerify(item);
      const label = item.field.label || item.field.nearbyText || "(无标签)";
      // occurrence 随行携带：background 合并报告/AI 选选项按 label#occurrence
      // 区分 repeat 多区块的同标签字段（不再互相覆盖）
      if (result.ok && verified) {
        filled.push({
          label, field: label,
          occurrence: item.field.occurrenceIndex || 0,
          value: String(item.entry.value).slice(0, 60),
          ...(result.via ? { via: result.via } : {}),
          // 纠偏：覆盖了站点解析预填的乱值（原值与档案不一致）
          ...(wasPrefilled ? { corrected: true, oldValue: String(item.field.currentValue).slice(0, 40) } : {}),
        });
      } else if (result.ok) {
        failed.push({
          label, field: label,
          occurrence: item.field.occurrenceIndex || 0,
          value: item.entry.value,
          reason: "已执行但回读不一致",
        });
      } else {
        const row = {
          label,
          field: label,
          occurrence: item.field.occurrenceIndex || 0,
          value: item.entry.value,
          reason: result.reason || "执行失败",
        };
        // 选项未匹配类失败：收割选项清单，供 AI 选选项通道二段使用。
        // 日期形状的值跳过——日历链失败后面板里是日格/月格（"13"、"6月"），
        // 不是选项，混进 AI 选选项会让日期被填成数字
        const isDateValue = /^\d{4}(-\d{1,2}){0,2}$/.test(String(item.entry.value || ""));
        if (/未匹配到选项/.test(row.reason) && item.field.kind !== "radio" && !isDateValue) {
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

    // ---------- 复查-自愈回路 ----------
    // 首轮失败/回读不一致的字段重扫重试一轮：React 重渲染、面板时序、
    // 草稿恢复都可能让第二次成功（上限一轮，防止在死控件上空转）。
    if (failed.length > 0 && !(options && options.noSelfHeal)) {
      await sleep(500);
      const retryKeys = new Set(
        failed.map((r) => `${r.field}#${r.occurrence || 0}`)
      );
      const freshScan = scanFields(adapter);
      // 首轮搜索降级可能把值留在 input 里但组件未接收——重试字段无视 currentValue，
      // 否则「值一致跳过」会让自愈误判已成功
      for (const f of freshScan.fields) {
        if (retryKeys.has(`${f.label}#${f.occurrenceIndex || 0}`)) {
          f.currentValue = "";
        }
      }
      const freshPlan = buildPlan(
        freshScan.fields,
        buildEntries(flatProfile),
        mapping,
        options
      ).plan;
      // override 键形如 标签#occurrence（裸 label 键对全部同标签项生效，兼容旧调用）
      for (const [ovKey, ovVal] of Object.entries(overrides)) {
        const hashAt = ovKey.lastIndexOf("#");
        const isOccKey = hashAt > 0 && /^\d+$/.test(ovKey.slice(hashAt + 1));
        const ovLabel = isOccKey ? ovKey.slice(0, hashAt) : ovKey;
        const ovOcc = isOccKey ? Number(ovKey.slice(hashAt + 1)) : null;
        const it = freshPlan.find(
          (p) =>
            p.field.label === ovLabel &&
            (ovOcc == null || (p.field.occurrenceIndex || 0) === ovOcc)
        );
        if (it) {
          it.entry = { ...it.entry, value: String(ovVal) };
        }
      }
      const healedLabels = new Set();
      for (const item of freshPlan) {
        const key = `${item.field.label}#${item.field.occurrenceIndex || 0}`;
        if (!retryKeys.has(key)) {
          continue;
        }
        const { result, verified } = await execAndVerify(item);
        if (result.ok && verified) {
          healedLabels.add(key);
          filled.push({
            label: item.field.label,
            field: item.field.label,
            value: String(item.entry.value).slice(0, 60),
            via: "自愈重试",
          });
        }
      }
      for (let i = failed.length - 1; i >= 0; i -= 1) {
        const r = failed[i];
        if (healedLabels.has(`${r.field}#${r.occurrence || 0}`)) {
          failed.splice(i, 1);
        }
      }
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
            kind: f.kind || "",
            placeholder: String((f.element && f.element.placeholder) || "").slice(0, 30),
            options: (Array.isArray(f.options) && f.options.length
              ? f.options
              : String(f.optionText || "")
                  .split(/[\s,，、]+/)
                  .filter(Boolean)
            ).slice(0, 20),
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
          Array.isArray(f.options) && f.options.length
            ? f.options
            : String(f.optionText).split(/[\s,，、]+/).filter(Boolean)
        );
      }
    }
    for (const r of failed) {
      if (r.options) {
        addOptField(r.label, r.options);
      }
    }

    // 页面校验错误提示（填写后表单自己标红的反馈，供界面展示与人工核查）
    const formErrors = [];
    for (const el of document.querySelectorAll(
      '[class*="error"],[class*="invalid"],[class*="form-item-error"]'
    )) {
      if (!isVisible(el) || formErrors.length >= 10) {
        continue;
      }
      const t = norm(el.textContent, 60);
      if (
        t.length >= 4 &&
        t.length <= 60 &&
        !formErrors.includes(t) &&
        /请|必填|必选|不能为空|格式|错误|无效|不正确|至少|超过/.test(t)
      ) {
        formErrors.push(t);
      }
    }

    return {
      site: adapter ? { id: adapter.id, name: adapter.name, confidence: adapter.confidence } : null,
      counts: { filled: filled.length, failed: failed.length, skipped: skipped.length },
      filled,
      failed,
      skipped,
      unmatched,
      formErrors,
      optionFields,
      // 页面上传控件数：background 据此决定是否需要下载附件字节（无上传框的
      // 页面不再白下载 5×8MB 转Base64）
      uploadCount: uploads.length,
      // 供 background 上报投递记录（服务端按 URL 去重更新）
      pageTitle: document.title,
      url: location.href,
    };
  }

  // ---------- 暴露 ----------

  window.__AUTOOFFER_CONTENT__ = {
    version: SCRIPT_VERSION,
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
      // 版本校验：插件升级后驻留在旧页面里的旧引擎不再应答新后台的消息
      if (msg && msg.version && msg.version !== SCRIPT_VERSION) {
        return undefined;
      }
      if (msg && msg.type === "autooffer:probe") {
        // 帧探测：本帧可扫描的可见字段数（background 据此决定往哪些帧派填报）
        try {
          const count = scanFields(detectSiteAdapter()).fields.filter(
            (f) => f.element && f.element.isConnected
          ).length;
          sendResponse({ fields: count });
        } catch {
          sendResponse({ fields: 0 });
        }
        return undefined;
      }
      if (msg && msg.type === "autooffer:fill") {
        autofill(msg.profile || {}, {
          mapping: msg.mapping || null,
          overrides: msg.overrides || null,
          attachments: msg.attachments || null,
          noAddBlocks: msg.noAddBlocks || false,
          noAdvance: msg.noAdvance || false,
          noSelfHeal: msg.noSelfHeal || false,
        })
          .then(sendResponse)
          .catch((err) => sendResponse({ error: String((err && err.message) || err) }));
        return true; // 异步响应
      }
      return undefined;
    });
  }
})();
