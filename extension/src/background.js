/**
 * AutoOffer 后台 Service Worker（MV3）。
 *
 * 职责：
 * 1. 代理本地服务访问（http://127.0.0.1:8765）—— 拿档案列表 / 扁平档案。
 *    在 SW 中 fetch，配合已授权的 host permission 不受页面 CORS 约束，
 *    且内容脚本永远不直接接触本地服务。
 * 2. 两段式填写编排：
 *    第一段 本地规则直填（零 LLM）；
 *    第二段 未命中的字段走 AI 标签映射（仅标签），固定选项字段走
 *    AI 选选项（含值，与简历解析同信任域），附件经字节下载注入。
 * 3. 本地留痕：最近 20 次填写记录存 chrome.storage.local。
 */

const DEFAULT_API = "http://127.0.0.1:8765";
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const AO_LOG_MAX = 300;

/** 插件运行日志：环形缓冲存 chrome.storage.local（aoLog），弹窗可查看/复制；
 *  同时实时上报本地服务 /api/v1/logs，与 exe 日志汇入同一 app.log（失败静默）。 */
async function aoLog(level, msg, extra = undefined) {
  const entry = { level, msg, ...(extra || {}) };
  try {
    const ts = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const stamped = {
      ts: `${ts.getFullYear()}-${pad(ts.getMonth() + 1)}-${pad(ts.getDate())} ` +
          `${pad(ts.getHours())}:${pad(ts.getMinutes())}:${pad(ts.getSeconds())}`,
      ...entry,
    };
    const { aoLog: entries = [] } = await chrome.storage.local.get("aoLog");
    entries.unshift(stamped);
    await chrome.storage.local.set({ aoLog: entries.slice(0, AO_LOG_MAX) });
  } catch {
    /* 日志自身绝不影响主流程 */
  }
  try {
    const base = await apiBase();
    fetchJson(
      `${base}/api/v1/logs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: [entry] }),
      },
      5000
    ).catch(() => {});
  } catch {
    /* 本地应用未启动时静默跳过 */
  }
}

async function apiBase() {
  const { aoApiBase } = await chrome.storage.local.get("aoApiBase");
  return aoApiBase || DEFAULT_API;
}

async function fetchJson(url, init = undefined, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { ...init, signal: controller.signal });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

function bufToB64(buffer) {
  const bytes = new Uint8Array(buffer);
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

async function fetchAttachments(base, profileId, attachments) {
  const out = [];
  for (let i = 0; i < attachments.length && i < 5; i += 1) {
    const meta = attachments[i];
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      // meta.index 是档案附件列表下标（服务端扁平化只带默认简历时与循环序号不同）
      const idx = Number.isInteger(meta.index) ? meta.index : i;
      const resp = await fetch(
        `${base}/api/v1/profiles/${encodeURIComponent(profileId)}/attachments/${idx}`,
        { signal: controller.signal }
      );
      if (!resp.ok) {
        continue;
      }
      const buf = await resp.arrayBuffer();
      if (buf.byteLength > MAX_ATTACHMENT_BYTES) {
        continue;
      }
      out.push({
        kind: meta.kind,
        label: meta.label,
        filename: meta.filename,
        language: meta.language || null,
        b64: bufToB64(buf),
      });
    } catch {
      /* 单个附件失败不影响整体 */
    } finally {
      clearTimeout(timer);
    }
  }
  return out;
}

/** 扁平档案 → 标签首值映射（供选选项通道查值）。 */
function flatValueMap(flat) {
  const map = {};
  const put = (k, v) => {
    if (k && !(k in map) && v != null && String(v)) {
      map[k] = String(v);
    }
  };
  for (const s of (flat && flat.sections) || []) {
    if (s.kind === "simple") {
      for (const [k, v] of Object.entries(s.values || {})) {
        put(k, v);
      }
    } else {
      for (const item of (s.items || []).slice(0, 1)) {
        for (const [k, v] of Object.entries(item)) {
          put(k, v);
        }
      }
    }
  }
  return map;
}

async function handleStatus() {
  const base = await apiBase();
  try {
    const health = await fetchJson(`${base}/api/v1/system/health`);
    const profiles = await fetchJson(`${base}/api/v1/profiles`);
    return {
      ok: true,
      base,
      version: health.version,
      profiles: (profiles || []).map((p) => ({
        id: p.id,
        label: p.label,
        name: p.name,
        completeness: typeof p.completeness === "number" ? p.completeness : null,
      })),
    };
  } catch (err) {
    return { ok: false, base, error: String((err && err.message) || err) };
  }
}

async function runFillPass(tabId, flat, options, frameIds) {
  // 逐帧派发：iframe 渲染的表单（整页或分区）各自填报后合并报告。
  // 单帧（绝大多数站点）时行为与原先一致。
  const targets = frameIds && frameIds.length ? frameIds : [0];
  const version = chrome.runtime.getManifest().version;
  let primary = null;
  for (const frameId of targets) {
    const report = await chrome.tabs.sendMessage(
      tabId,
      { type: "autooffer:fill", version, profile: flat, ...options },
      { frameId }
    );
    if (!report || report.error) {
      throw new Error((report && report.error) || "内容脚本未返回报告");
    }
    primary = primary ? mergeReports(primary, report, { crossFrame: true }) : report;
  }
  return primary;
}

/** 枚举标签页里「有表单字段」的帧（顶层 + iframe）。
 *  webNavigation 不可用或全部探测失败时退回顶层。 */
async function fillableFrames(tabId) {
  let frames = [{ frameId: 0 }];
  try {
    const all = await chrome.webNavigation.getAllFrames({ tabId });
    if (Array.isArray(all) && all.length > 0) {
      frames = all.map((f) => ({ frameId: f.frameId }));
    }
  } catch {
    /* 无 webNavigation 权限时退回顶层 */
  }
  const version = chrome.runtime.getManifest().version;
  const out = [];
  for (const { frameId } of frames) {
    try {
      const probe = await chrome.tabs.sendMessage(
        tabId,
        { type: "autooffer:probe", version },
        { frameId }
      );
      if (probe && probe.fields > 0) {
        out.push(frameId);
      }
    } catch {
      /* 该帧无内容脚本（无权限/非 http）——跳过 */
    }
  }
  return out.length > 0 ? out : [0];
}

function mergeReports(primary, secondary, opts) {
  // 第二段只统计「新增」的填写：按 label#occurrence 去重——repeat 多区块的
  // 同标签字段（第 2 段教育的「学校名称」）不再被第一段的同名行吃掉。
  // 跨帧合并（iframe 各自独立表单）不去重：不同帧的同名字段是不同字段。
  const crossFrame = Boolean(opts && opts.crossFrame);
  const keyOf = (r) => `${r.field || r.label}#${r.occurrence || 0}`;
  const filledKeys = new Set(primary.filled.map(keyOf));
  const newFilled = crossFrame
    ? secondary.filled
    : secondary.filled.filter((r) => !filledKeys.has(keyOf(r)));
  const newFailed = crossFrame
    ? secondary.failed
    : secondary.failed.filter((r) => !filledKeys.has(keyOf(r)));
  // skipped 取两段并集（field+reason 去重）：第二段整体覆盖会丢掉第一段的
  // 「已有值，跳过」——那是弹窗填充率公式的分子来源
  const seenSkip = new Set();
  const skipped = [];
  for (const r of [...primary.skipped, ...secondary.skipped]) {
    const k = `${r.field}#${r.reason}`;
    if (!seenSkip.has(k)) {
      seenSkip.add(k);
      skipped.push(r);
    }
  }
  return {
    site: primary.site || secondary.site,
    // 页面元信息随第一段报告透传（投递上报要靠 pageTitle 提取公司名）
    pageTitle: primary.pageTitle || secondary.pageTitle,
    url: primary.url || secondary.url,
    counts: {
      filled: primary.counts.filled + newFilled.length,
      failed: primary.counts.failed + newFailed.length,
      skipped: skipped.length,
    },
    filled: [...primary.filled, ...newFilled],
    failed: [...primary.failed, ...newFailed],
    skipped,
    unmatched: crossFrame
      ? [...(primary.unmatched || []), ...(secondary.unmatched || [])]
      : secondary.unmatched || [],
    optionFields: crossFrame
      ? [...(primary.optionFields || []), ...(secondary.optionFields || [])]
      : secondary.optionFields || [],
    // 页面校验提示以最新一轮为准（第二段填得更全，标红更真），为空回退第一段；
    // 跨帧合并取并集
    formErrors: crossFrame
      ? [...new Set([...(primary.formErrors || []), ...(secondary.formErrors || [])])]
      : (secondary.formErrors && secondary.formErrors.length
          ? secondary.formErrors
          : primary.formErrors) || [],
    uploadCount: ((primary.uploadCount || 0) + (secondary.uploadCount || 0)) || undefined,
  };
}

/** 组装 AI 选选项请求：选项未匹配的失败字段 + 映射命中但值不贴选项的字段。
 *  restrictedValues：受限敏感字段的值集合（身份证号/家庭电话等）——这些值
 *  禁止进入 option-match 请求（LLM prompt），命中即丢弃该项。 */
function buildOptionPicks(first, mapping, values, restrictedValues) {
  const picks = [];
  const seen = new Set(); // label#occurrence 键（失败行回路）
  const seenPlain = new Set(); // 裸 label 键（映射回路）
  const blocked = (value) => {
    const v = String(value == null ? "" : value).trim();
    return (
      (restrictedValues && restrictedValues.has(v)) ||
      /^\d{17}[\dXx]|\d{15}$/.test(v) // 身份证形状兜底（无论来源）
    );
  };
  const optionsByLabel = new Map(
    ((first && first.optionFields) || []).map((f) => [f.label, f.options])
  );
  const looseMatch = (value, option) => {
    const v = String(value || "");
    const o = String(option || "");
    return v === o || v.includes(o) || o.includes(v.slice(0, 8));
  };
  for (const row of (first && first.failed) || []) {
    const key = `${row.label}#${row.occurrence || 0}`;
    if (row.options && row.options.length > 1 && !seen.has(key) && !blocked(row.value)) {
      seen.add(key);
      picks.push({
        label: row.label,
        occurrence: row.occurrence || 0,
        options: row.options,
        value: row.value,
      });
    }
  }
  for (const [fieldLabel, profileLabel] of Object.entries(mapping || {})) {
    if (seen.has(fieldLabel) || seenPlain.has(fieldLabel)) {
      continue;
    }
    const options = optionsByLabel.get(fieldLabel);
    const value = values[profileLabel];
    if (options && options.length > 1 && value && !options.some((o) => looseMatch(value, o))) {
      if (!blocked(value)) {
        // 映射回路拿不到 occurrence（值只知首条），保持裸 label 语义：
        // 此类多为全局单值字段（民族/薪资/排名），无多段歧义
        seenPlain.add(fieldLabel);
        picks.push({ label: fieldLabel, options, value });
      }
    }
  }
  // 回读不一致的固定选项字段（规则直填路径）：值与选项对不上时交给 AI 重挑，
  // 例如档案「前10%」对选项「年级前5%/前10%/前20%」
  for (const row of (first && first.failed) || []) {
    const key = `${row.label}#${row.occurrence || 0}`;
    if (seen.has(key) || !/回读不一致/.test(row.reason || "")) {
      continue;
    }
    const options = optionsByLabel.get(row.label);
    const value = row.value || values[row.label];
    if (options && options.length > 1 && value && !options.some((o) => looseMatch(value, o))) {
      if (!blocked(value)) {
        seen.add(key);
        picks.push({ label: row.label, occurrence: row.occurrence || 0, options, value });
      }
    }
  }
  return picks;
}

/** 受限敏感字段的值集合（flat.restrictedLabels 标记的字段取值）：
 *  这些值不进 option-match 请求（LLM prompt）——「值不出本机」契约。 */
function restrictedValueSet(flat, values) {
  const set = new Set();
  for (const label of (flat && flat.restrictedLabels) || []) {
    const v = values[label];
    if (v) {
      set.add(String(v).trim());
    }
  }
  return set;
}

/** 同页并发互斥：弹窗与快捷键（或连按 Alt+F）并发触发两次填写会交错
 *  操作同一 DOM（各自开面板/点添加按钮），结果不可预测。 */
const inflightTabs = new Set();

async function handleAutofill(msg) {
  if (inflightTabs.has(msg.tabId)) {
    throw new Error("该页面正在填写中，请等本次完成后再触发");
  }
  inflightTabs.add(msg.tabId);
  try {
    return await runAutofill(msg);
  } finally {
    inflightTabs.delete(msg.tabId);
  }
}

async function runAutofill(msg) {
  const base = await apiBase();
  const tabId = msg.tabId;
  if (!tabId) {
    throw new Error("缺少目标标签页");
  }
  const sensitive = msg.sensitive ? 1 : 0;
  const setProgress = (text) =>
    chrome.storage.local
      .set({ aoProgress: { text, ts: Date.now() } })
      .catch(() => {});
  await aoLog("info", "fill.start", {
    url: msg.url || "",
    profile: msg.profileId,
    sensitive,
  });
  await setProgress("拉取档案…");
  const flat = await fetchJson(
    `${base}/api/v1/profiles/${encodeURIComponent(msg.profileId)}/flat?sensitive=${sensitive}`
  );
  await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    files: ["src/content.js"],
  });
  // 帧探测：iframe 渲染的表单（整页内嵌投递页）也能填；
  // 全帧无可填字段时退回顶层重试（探测可能早于渲染完成）
  let frames = await fillableFrames(tabId);

  // 第一段：本地规则直填（零 LLM）
  await setProgress("规则直填…");
  let report = await runFillPass(tabId, flat, {}, frames);
  if (
    frames.length === 1 &&
    frames[0] === 0 &&
    report.counts &&
    report.counts.filled + report.counts.failed === 0
  ) {
    const retryFrames = await fillableFrames(tabId);
    if (retryFrames.length > 1 || retryFrames[0] !== 0) {
      frames = retryFrames;
      report = await runFillPass(tabId, flat, {}, frames);
    }
  }
  await aoLog("info", "fill.pass1", {
    filled: report.counts ? report.counts.filled : 0,
    failed: report.counts ? report.counts.failed : 0,
    site: report.site ? report.site.name : "",
  });

  const values = flatValueMap(flat);
  const restrictedValues = restrictedValueSet(flat, values);
  try {
    // 二段-1：AI 标签映射（仅标签，不含任何值）
    const unmatched = report.unmatched || [];
    const mapping = {};
    if (unmatched.length > 0 && msg.aiMapping !== false) {
      await setProgress(`AI 映射 ${unmatched.length} 个字段…（本地模型较慢，请稍候）`);
      const mappingResp = await fetchJson(
        `${base}/api/v1/mapping`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile_id: msg.profileId, fields: unmatched }),
        },
        180000
      );
      for (const m of (mappingResp && mappingResp.matches) || []) {
        mapping[m.field_label] = m.profile_label;
      }
      await aoLog("info", "fill.mapping", {
        unmatched: unmatched.length,
        matched: Object.keys(mapping).length,
      });
    }

    // 二段-2：附件字节下载（插件侧 DataTransfer 注入）。
    // 按需下载：第一段报告的上传控件数 > 0 才拉字节——无上传框的页面
    // 不再白下载最多 5×8MB 转 Base64
    let attachments = [];
    const uploadCount = Number(report.uploadCount) || 0;
    if (
      uploadCount > 0 &&
      Array.isArray(flat.attachments) &&
      flat.attachments.length > 0 &&
      msg.uploadAttachments !== false
    ) {
      attachments = await fetchAttachments(base, msg.profileId, flat.attachments);
      await aoLog("info", "fill.attachments", { fetched: attachments.length });
    }

    const secondBase = {};
    if (Object.keys(mapping).length > 0) {
      secondBase.mapping = mapping;
    }
    if (attachments.length > 0) {
      secondBase.attachments = attachments;
    }
    if (Object.keys(secondBase).length > 0) {
      const second = await runFillPass(tabId, flat, secondBase, frames);
      // via 标注只认 AI：mapping 命中该字段才标「ai」——第二遍同样会跑
      // 规则引擎，规则补上的行不再是 AI 的功劳
      const mappingKeys = new Set(Object.keys(mapping));
      for (const row of second.filled) {
        if (!row.via && mappingKeys.has(row.field || row.label)) {
          row.via = "ai";
        }
      }
      report = mergeReports(report, second);
    }

    // 二段-3：AI 选选项循环（级联选择器逐层下钻，最多 3 轮）。
    // 每轮：失败字段收割选项 → AI 挑选项 → override 补填 → 级联展开出新选项再下一轮。
    if (msg.aiMapping !== false) {
      for (let round = 0; round < 3; round += 1) {
        const picks = buildOptionPicks(report, round === 0 ? mapping : {}, values, restrictedValues);
        if (picks.length === 0) {
          break;
        }
        await setProgress(`AI 选选项（第 ${round + 1} 轮，${picks.length} 项）…`);
        let overrides = {};
        try {
          const choiceResp = await fetchJson(
            `${base}/api/v1/option-match`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              // profile_id 供服务端校验 value 确属该档案（防本机其它进程
              // 借此端点白嫖 LLM 打任意 prompt）
              body: JSON.stringify({ picks, profile_id: msg.profileId || "" }),
            },
            120000
          );
          for (const c of (choiceResp && choiceResp.choices) || []) {
            // occurrence 键：AI 为第 N 段同标签字段挑的选项只落到第 N 段
            overrides[
              typeof c.occurrence === "number"
                ? `${c.label}#${c.occurrence}`
                : c.label
            ] = c.option;
          }
        } catch (err) {
          report.mappingError = String((err && err.message) || err);
          break;
        }
        if (Object.keys(overrides).length === 0) {
          break;
        }
        const second = await runFillPass(tabId, flat, { overrides }, frames);
        const ovLabels = new Set(
          Object.keys(overrides).map((k) => (k.includes("#") ? k.split("#")[0] : k))
        );
        for (const row of second.filled) {
          if (!row.via && ovLabels.has(row.field || row.label)) {
            row.via = "ai";
          }
        }
        report = mergeReports(report, second);
      }
    }
  } catch (err) {
    report.mappingError = String((err && err.message) || err);
    await aoLog("error", "fill.stage2_error", { error: report.mappingError });
  }

  const { aoHistory = [] } = await chrome.storage.local.get("aoHistory");
  await setProgress("");
  aoHistory.unshift({
    ts: Date.now(),
    url: msg.url || "",
    site: report.site || null,
    counts: report.counts || null,
  });
  await chrome.storage.local.set({ aoHistory: aoHistory.slice(0, 20) });
  await aoLog("info", "fill.done", {
    url: msg.url || "",
    filled: report.counts ? report.counts.filled : 0,
    failed: report.counts ? report.counts.failed : 0,
    skipped: report.counts ? report.counts.skipped : 0,
  });

  // 上报投递记录到本地应用（服务端同 URL 的 filled 记录去重更新；失败不影响填写）
  try {
    const pos = (report.filled || []).find((r) => /岗位|职位/.test(r.label || ""));
    const appRec = await fetchJson(
      `${base}/api/v1/applications`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: msg.url || report.url || "",
          profile_id: msg.profileId || "",
          page_title: report.pageTitle || "",
          position: pos ? String(pos.value || "").slice(0, 40) : "",
          fields_filled: (report.counts && report.counts.filled) || 0,
          fields_failed: (report.counts && report.counts.failed) || 0,
          fields_pending: (report.counts && report.counts.skipped) || 0,
          note: "插件填写",
        }),
      },
      15000
    );
    await aoLog("info", "application.reported", {
      id: appRec && appRec.id,
      company: appRec && appRec.company,
    });
  } catch (err) {
    await aoLog("error", "application.report_failed", {
      error: String((err && err.message) || err),
    });
  }
  return report;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "ao:status") {
        sendResponse(await handleStatus());
      } else if (msg.type === "ao:autofill") {
        sendResponse(await handleAutofill(msg));
      } else if (msg.type === "ao:log.clear") {
        await chrome.storage.local.set({ aoLog: [] });
        sendResponse({ cleared: true });
      } else {
        sendResponse({ error: `未知消息类型: ${msg.type}` });
      }
    } catch (err) {
      const text = String((err && err.message) || err);
      aoLog("error", "fill.fatal", { error: text });
      sendResponse({ error: text });
    }
  })();
  return true; // 异步响应
});

// 快捷键（默认 Alt+F）：用弹窗里上次选定的档案直接填当前页，免开弹窗。
// 站点源权限沿用弹窗授权时的按需授予；未授权/未选档案时静默记日志。
if (chrome.commands && chrome.commands.onCommand) {
  chrome.commands.onCommand.addListener(async (command) => {
    if (command !== "fill-now") {
      return;
    }
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id || !tab.url || !/^https?:/i.test(tab.url)) {
      await aoLog("warn", "fill.hotkey_skip", { reason: "页面不可注入" });
      return;
    }
    const { aoProfileId } = await chrome.storage.local.get("aoProfileId");
    if (!aoProfileId) {
      await aoLog("warn", "fill.hotkey_skip", { reason: "未选择档案（先在弹窗选一次）" });
      return;
    }
    // 快捷键路径没有弹窗接住异常：失败必须落日志并清进度，
    // 否则静默无响应且 SW 控制台刷 unhandled rejection
    try {
      await handleAutofill({
        type: "ao:autofill",
        tabId: tab.id,
        url: tab.url,
        profileId: aoProfileId,
        sensitive: false,
      });
    } catch (err) {
      await aoLog("error", "fill.hotkey_failed", {
        url: tab.url,
        error: String((err && err.message) || err),
      });
      await chrome.storage.local
        .set({ aoProgress: { text: `填写失败：${String((err && err.message) || err).slice(0, 60)}`, ts: Date.now() } })
        .catch(() => {});
    }
  });
}
