/**
 * AutoOffer 弹窗：档案选择 + 授权 + 触发填写 + 展示报告。
 *
 * 权限模型：MV3 最小授权。点「开始填写」时才申请两类源：
 * - 当前标签页站点源（注入内容脚本）
 * - 本地服务源（SW fetch 档案）
 * 均在用户手势内调用 chrome.permissions.request。
 */

const $ = (id) => document.getElementById(id);
let activeTab = null;
let status = { ok: false };

const DEFAULT_API = "http://127.0.0.1:8765";

async function getApiBase() {
  const { aoApiBase } = await chrome.storage.local.get("aoApiBase");
  return aoApiBase || DEFAULT_API;
}

async function loadTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTab = tab || null;
  const fillable = Boolean(
    activeTab && activeTab.url && /^https?:/i.test(activeTab.url)
  );
  $("hint").textContent = fillable
    ? "点击「开始填写」将申请页面授权并自动填写。"
    : "当前页面不可注入（仅支持 http/https 页面）。";
  return fillable;
}

async function refreshStatus() {
  $("server-state").textContent = "检查本地服务…";
  status = await chrome.runtime.sendMessage({ type: "ao:status" });
  $("api-base").value = status.base || DEFAULT_API;
  const dot = $("status-dot");
  if (status.ok) {
    dot.classList.replace("off", "on");
    $("server-state").textContent = `已连接 v${status.version}`;
    $("btn-grant").classList.add("hidden");
    const sel = $("profile-select");
    sel.innerHTML = "";
    for (const p of status.profiles || []) {
      const opt = document.createElement("option");
      opt.value = p.id;
      const base = p.name ? `${p.label}（${p.name}）` : p.label;
      // 完整度随档案名展示：选档案时即可判断这份档案够不够填
      opt.textContent =
        p.completeness != null ? `${base} · ${p.completeness}%` : base;
      sel.appendChild(opt);
    }
    sel.disabled = sel.options.length === 0;
    if (sel.options.length === 0) {
      $("server-state").textContent = "已连接，但尚无档案";
    }
    await restoreSelection();
  } else {
    dot.classList.replace("on", "off");
    $("server-state").textContent = "未连接本地服务";
    $("btn-grant").classList.remove("hidden");
    $("profile-select").disabled = true;
  }
  updateFillButton();
}

async function restoreSelection() {
  const { aoProfileId } = await chrome.storage.local.get("aoProfileId");
  const sel = $("profile-select");
  if (aoProfileId) {
    for (const opt of sel.options) {
      if (opt.value === aoProfileId) {
        sel.value = aoProfileId;
        break;
      }
    }
  }
}

function updateFillButton() {
  const fillable =
    status.ok &&
    (status.profiles || []).length > 0 &&
    Boolean(activeTab && activeTab.url && /^https?:/i.test(activeTab.url));
  $("btn-fill").disabled = !fillable;
}

async function grantApiPermission() {
  const base = await getApiBase();
  let origin = base;
  try {
    origin = new URL(base).origin + "/*";
  } catch {
    /* 保留原文 */
  }
  const granted = await chrome.permissions.request({ origins: [origin] });
  if (granted) {
    await refreshStatus();
  } else {
    $("server-state").textContent = "未授权，无法连接本地服务";
  }
}

async function startFill() {
  const sel = $("profile-select");
  const profileId = sel.value;
  if (!profileId || !activeTab || !activeTab.id) {
    return;
  }
  await chrome.storage.local.set({ aoProfileId: profileId });

  const origins = [];
  try {
    origins.push(new URL(activeTab.url).origin + "/*");
  } catch {
    /* 忽略非法地址 */
  }
  try {
    origins.push(new URL(await getApiBase()).origin + "/*");
  } catch {
    /* 忽略非法地址 */
  }
  const granted = await chrome.permissions.request({ origins });
  if (!granted) {
    $("hint").textContent = "未获得页面授权，已取消。";
    return;
  }

  $("btn-fill").disabled = true;
  $("btn-fill").textContent = "填写中…";
  $("report").classList.add("hidden");
  try {
    const report = await chrome.runtime.sendMessage({
      type: "ao:autofill",
      tabId: activeTab.id,
      url: activeTab.url,
      profileId,
      sensitive: $("opt-sensitive").checked,
    });
    if (report && report.error) {
      throw new Error(report.error);
    }
    renderReport(report);
  } catch (err) {
    renderError(String((err && err.message) || err));
  } finally {
    $("btn-fill").disabled = false;
    $("btn-fill").textContent = "开始填写";
  }
}

function renderError(message) {
  $("report").classList.remove("hidden");
  $("report-title").textContent = "填写失败";
  $("report-list").innerHTML = "";
  const li = document.createElement("li");
  li.className = "failed";
  li.textContent = message;
  $("report-list").appendChild(li);
}

function renderReport(report) {
  $("report").classList.remove("hidden");
  const counts = report.counts || {};
  const site = report.site ? report.site.name : "";
  $("report-title").innerHTML =
    `<span class="badge ok">已填 ${counts.filled || 0}</span>` +
    `<span class="badge bad">失败 ${counts.failed || 0}</span>` +
    `<span class="badge skip">跳过 ${counts.skipped || 0}</span>` +
    (site ? `<span class="badge site">${site}</span>` : "");
  const list = $("report-list");
  list.innerHTML = "";
  const rows = [
    ...(report.filled || []).map((r) => [
      "filled",
      r.label,
      ` = ${r.value}`,
      r.via === "ai" ? "AI映射" : r.via === "附件" ? "附件" : "",
    ]),
    ...(report.failed || []).map((r) => ["failed", r.label, `：${r.reason}`, ""]),
    ...(report.skipped || []).map((r) => ["skipped", r.field, `：${r.reason}`, ""]),
  ];
  for (const [cls, label, detail, via] of rows.slice(0, 60)) {
    const li = document.createElement("li");
    li.className = cls;
    const name = document.createElement("span");
    name.className = "fld";
    name.textContent = label;
    li.appendChild(name);
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = detail;
    li.appendChild(val);
    if (via) {
      const tag = document.createElement("span");
      tag.className = "via";
      tag.textContent = via;
      li.appendChild(tag);
    }
    list.appendChild(li);
  }
}

async function saveApiBase() {
  const value = $("api-base").value.trim().replace(/\/+$/, "");
  await chrome.storage.local.set({
    aoApiBase: /^https?:\/\/.+/.test(value) ? value : "",
  });
  await refreshStatus();
}

function formatLogEntries(entries) {
  return (entries || [])
    .map((e) => {
      const extra = Object.entries(e)
        .filter(([k]) => !["ts", "level", "msg"].includes(k))
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(" ");
      return `${e.ts} [${e.level}] ${e.msg}${extra ? " " + extra : ""}`;
    })
    .join("\n");
}

async function toggleLogView() {
  const view = $("log-view");
  if (!view.classList.contains("hidden")) {
    view.classList.add("hidden");
    return;
  }
  const { aoLog = [] } = await chrome.storage.local.get("aoLog");
  view.textContent = aoLog.length
    ? formatLogEntries(aoLog.slice(0, 60))
    : "（暂无日志——触发一次填写后这里会有记录）";
  view.classList.remove("hidden");
}

async function copyLog() {
  const { aoLog = [] } = await chrome.storage.local.get("aoLog");
  const text = aoLog.length ? formatLogEntries(aoLog) : "（暂无日志）";
  try {
    await navigator.clipboard.writeText(text);
    $("btn-log-copy").textContent = "已复制";
    setTimeout(() => {
      $("btn-log-copy").textContent = "复制";
    }, 1200);
  } catch {
    $("log-view").textContent = text;
    $("log-view").classList.remove("hidden");
  }
}

async function clearLog() {
  await chrome.runtime.sendMessage({ type: "ao:log.clear" });
  $("log-view").classList.add("hidden");
}

document.addEventListener("DOMContentLoaded", async () => {
  $("api-base").value = await getApiBase();
  await loadTab();
  await refreshStatus();
  $("btn-grant").addEventListener("click", grantApiPermission);
  $("btn-fill").addEventListener("click", startFill);
  $("btn-save-api").addEventListener("click", saveApiBase);
  $("btn-log").addEventListener("click", toggleLogView);
  $("btn-log-copy").addEventListener("click", copyLog);
  $("btn-log-clear").addEventListener("click", clearLog);
});
