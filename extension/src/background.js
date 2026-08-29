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
      const resp = await fetch(
        `${base}/api/v1/profiles/${encodeURIComponent(profileId)}/attachments/${i}`,
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
      profiles: (profiles || []).map((p) => ({ id: p.id, label: p.label, name: p.name })),
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
  return picks;
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
  let report = await runFillPass(tabId, flat, {});

  const values = flatValueMap(flat);
  try {
    // 二段-1：AI 标签映射（仅标签，不含任何值）
    const unmatched = report.unmatched || [];
    const mapping = {};
    if (unmatched.length > 0 && msg.aiMapping !== false) {
      const mappingResp = await fetchJson(
        `${base}/api/v1/mapping`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile_id: msg.profileId, fields: unmatched }),
        },
        60000
      );
      for (const m of (mappingResp && mappingResp.matches) || []) {
        mapping[m.field_label] = m.profile_label;
      }
    }

    // 二段-2：附件字节下载（插件侧 DataTransfer 注入）
    let attachments = [];
    if (
      Array.isArray(flat.attachments) &&
      flat.attachments.length > 0 &&
      msg.uploadAttachments !== false
    ) {
      attachments = await fetchAttachments(base, msg.profileId, flat.attachments);
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
        let overrides = {};
        try {
          const choiceResp = await fetchJson(
            `${base}/api/v1/option-match`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ picks }),
            },
            60000
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
