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
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 20000);
      // meta.index 是档案附件列表下标（服务端扁平化只带默认简历时与循环序号不同）
      const idx = Number.isInteger(meta.index) ? meta.index : i;
      const resp = await fetch(
        `${base}/api/v1/profiles/${encodeURIComponent(profileId)}/attachments/${idx}`,
        { signal: controller.signal }
      );
      clearTimeout(timer);
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

async function runFillPass(tabId, flat, options) {
  const report = await chrome.tabs.sendMessage(tabId, {
    type: "autooffer:fill",
    profile: flat,
    ...options,
  });
  if (!report || report.error) {
    throw new Error((report && report.error) || "内容脚本未返回报告");
  }
  return report;
}

function mergeReports(primary, secondary) {
  // 第二段只统计「新增」的填写：已在第一段填过的标签去重
  const filledLabels = new Set(primary.filled.map((r) => r.label));
  const newFilled = secondary.filled.filter((r) => !filledLabels.has(r.label));
  const newFailed = secondary.failed.filter((r) => !filledLabels.has(r.label));
  return {
    site: primary.site || secondary.site,
    // 页面元信息随第一段报告透传（投递上报要靠 pageTitle 提取公司名）
    pageTitle: primary.pageTitle || secondary.pageTitle,
    url: primary.url || secondary.url,
    counts: {
      filled: primary.counts.filled + newFilled.length,
      failed: primary.counts.failed + newFailed.length,
      skipped: secondary.counts.skipped,
    },
    filled: [...primary.filled, ...newFilled],
    failed: [...primary.failed, ...newFailed],
    skipped: secondary.skipped,
    unmatched: secondary.unmatched || [],
    optionFields: secondary.optionFields || [],
  };
}

/** 组装 AI 选选项请求：选项未匹配的失败字段 + 映射命中但值不贴选项的字段。 */
function buildOptionPicks(first, mapping, values) {
  const picks = [];
  const seen = new Set();
  const optionsByLabel = new Map(
    ((first && first.optionFields) || []).map((f) => [f.label, f.options])
  );
  const looseMatch = (value, option) => {
    const v = String(value || "");
    const o = String(option || "");
    return v === o || v.includes(o) || o.includes(v.slice(0, 8));
  };
  for (const row of (first && first.failed) || []) {
    if (row.options && row.options.length > 1 && !seen.has(row.label)) {
      seen.add(row.label);
      picks.push({ label: row.label, options: row.options, value: row.value });
    }
  }
  for (const [fieldLabel, profileLabel] of Object.entries(mapping || {})) {
    if (seen.has(fieldLabel)) {
      continue;
    }
    const options = optionsByLabel.get(fieldLabel);
    const value = values[profileLabel];
    if (options && options.length > 1 && value && !options.some((o) => looseMatch(value, o))) {
      seen.add(fieldLabel);
      picks.push({ label: fieldLabel, options, value });
    }
  }
  // 回读不一致的固定选项字段（规则直填路径）：值与选项对不上时交给 AI 重挑，
  // 例如档案「前10%」对选项「年级前5%/前10%/前20%」
  for (const row of (first && first.failed) || []) {
    if (seen.has(row.label) || !/回读不一致/.test(row.reason || "")) {
      continue;
    }
    const options = optionsByLabel.get(row.label);
    const value = row.value || values[row.label];
    if (options && options.length > 1 && value && !options.some((o) => looseMatch(value, o))) {
      seen.add(row.label);
      picks.push({ label: row.label, options, value });
    }
  }
  return picks;
}

async function handleAutofill(msg) {
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
    target: { tabId },
    files: ["src/content.js"],
  });

  // 第一段：本地规则直填（零 LLM）
  await setProgress("规则直填…");
  let report = await runFillPass(tabId, flat, {});
  await aoLog("info", "fill.pass1", {
    filled: report.counts ? report.counts.filled : 0,
    failed: report.counts ? report.counts.failed : 0,
    site: report.site ? report.site.name : "",
  });

  const values = flatValueMap(flat);
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

    // 二段-2：附件字节下载（插件侧 DataTransfer 注入）
    let attachments = [];
    if (
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
      const second = await runFillPass(tabId, flat, secondBase);
      for (const row of second.filled) {
        if (!row.via) {
          row.via = "ai";
        }
      }
      report = mergeReports(report, second);
    }

    // 二段-3：AI 选选项循环（级联选择器逐层下钻，最多 3 轮）。
    // 每轮：失败字段收割选项 → AI 挑选项 → override 补填 → 级联展开出新选项再下一轮。
    if (msg.aiMapping !== false) {
      for (let round = 0; round < 3; round += 1) {
        const picks = buildOptionPicks(report, round === 0 ? mapping : {}, values);
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
              body: JSON.stringify({ picks }),
            },
            120000
          );
          for (const c of (choiceResp && choiceResp.choices) || []) {
            overrides[c.label] = c.option;
          }
        } catch (err) {
          report.mappingError = String((err && err.message) || err);
          break;
        }
        if (Object.keys(overrides).length === 0) {
          break;
        }
        const second = await runFillPass(tabId, flat, { overrides });
        for (const row of second.filled) {
          if (!row.via) {
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
    await handleAutofill({
      type: "ao:autofill",
      tabId: tab.id,
      url: tab.url,
      profileId: aoProfileId,
      sensitive: false,
    });
  });
}
