/**
 * AutoOffer 后台 Service Worker（MV3）。
 *
 * 职责：
 * 1. 代理本地服务访问（http://127.0.0.1:8765）—— 拿档案列表 / 扁平档案。
 *    在 SW 中 fetch，配合已授权的 host permission 不受页面 CORS 约束，
 *    且内容脚本永远不直接接触本地服务。
 * 2. 按需注入内容脚本并转发档案，回收填写报告。
 * 3. 本地留痕：最近 20 次填写记录存 chrome.storage.local。
 */

const DEFAULT_API = "http://127.0.0.1:8765";

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

async function handleStatus() {
  const base = await apiBase();
  try {
    const health = await fetchJson(`${base}/api/v1/system/health`);
    const profiles = await fetchJson(`${base}/api/v1/profiles`);
    return {
      ok: true,
      base,
      version: health.version,
      profiles: (profiles || []).map((p) => ({ id: p.id, label: p.label, name: p.name })),
    };
  } catch (err) {
    return { ok: false, base, error: String((err && err.message) || err) };
  }
}

async function runFillPass(tabId, flat, mapping) {
  const report = await chrome.tabs.sendMessage(tabId, {
    type: "autooffer:fill",
    profile: flat,
    mapping,
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
    counts: {
      filled: primary.counts.filled + newFilled.length,
      failed: primary.counts.failed + newFailed.length,
      skipped: secondary.counts.skipped,
    },
    filled: [...primary.filled, ...newFilled],
    failed: [...primary.failed, ...newFailed],
    skipped: secondary.skipped,
    unmatched: secondary.unmatched || [],
  };
}

async function handleAutofill(msg) {
  const base = await apiBase();
  const tabId = msg.tabId;
  if (!tabId) {
    throw new Error("缺少目标标签页");
  }
  const sensitive = msg.sensitive ? 1 : 0;
  const flat = await fetchJson(
    `${base}/api/v1/profiles/${encodeURIComponent(msg.profileId)}/flat?sensitive=${sensitive}`
  );
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["src/content.js"],
  });

  // 第一段：本地规则直填（零 LLM）
  let report = await runFillPass(tabId, flat, null);

  // 第二段：规则未命中的字段交 AI 映射（仅标签，不含任何值）
  const unmatched = report.unmatched || [];
  if (unmatched.length > 0 && msg.aiMapping !== false) {
    try {
      const mappingResp = await fetchJson(
        `${base}/api/v1/mapping`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile_id: msg.profileId, fields: unmatched }),
        },
        60000
      );
      const matches = (mappingResp && mappingResp.matches) || [];
      if (matches.length > 0) {
        const mappingUsed = {};
        for (const m of matches) {
          mappingUsed[m.field_label] = m.profile_label;
        }
        const second = await runFillPass(tabId, flat, mappingUsed);
        for (const row of second.filled) {
          row.via = "ai";
        }
        report = mergeReports(report, second);
      }
    } catch (err) {
      report.mappingError = String((err && err.message) || err);
    }
  }

  const { aoHistory = [] } = await chrome.storage.local.get("aoHistory");
  aoHistory.unshift({
    ts: Date.now(),
    url: msg.url || "",
    site: report.site || null,
    counts: report.counts || null,
  });
  await chrome.storage.local.set({ aoHistory: aoHistory.slice(0, 20) });
  return report;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "ao:status") {
        sendResponse(await handleStatus());
      } else if (msg.type === "ao:autofill") {
        sendResponse(await handleAutofill(msg));
      } else {
        sendResponse({ error: `未知消息类型: ${msg.type}` });
      }
    } catch (err) {
      sendResponse({ error: String((err && err.message) || err) });
    }
  })();
  return true; // 异步响应
});
