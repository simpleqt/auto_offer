"""知乎 Moka 真实表单两段式实测（非北森站点回归）。

流程：直开申请页 → 规则直填 → AI 映射 → 注入 PDF 简历（触发站点解析）
→ 对解析后展开的问卷区块再跑引擎 → 汇总报告。全程不点「预览并提交」。
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

APPLY_URL = (
    "https://app.mokahr.com/campus_apply/zhihu/68321"
    "#/job/259dda17-5279-4ad0-b7b1-e20efc783619/apply"
)
if len(sys.argv) > 1:
    APPLY_URL = sys.argv[1]
API = "http://127.0.0.1:8765"
PROFILE_ID = "profile-de2d254d"
CONTENT = Path(__file__).resolve().parents[1] / "extension" / "src" / "content.js"
PROFILE_DIR = str(Path(__file__).resolve().parents[1] / ".browser-profile")


def get_json(url: str, data: dict | None = None, timeout: int = 90) -> dict:
    if data is None:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310, ASYNC210
            return json.load(resp)
    req = urllib.request.Request(  # noqa: S310
        url, data=json.dumps(data).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310, ASYNC210
        return json.load(resp)


async def scroll_sweep(pg) -> None:
    height = await pg.evaluate("() => document.body.scrollHeight")
    for y in range(0, height, 800):
        await pg.evaluate(f"() => window.scrollTo(0, {y})")
        await pg.wait_for_timeout(220)
    await pg.evaluate("() => window.scrollTo(0, 0)")
    await pg.wait_for_timeout(500)


async def run_pass(pg, flat: dict, opts: dict) -> dict:
    return await pg.evaluate(
        "(a) => window.__AUTOOFFER_CONTENT__.autofill(a.p, a.o)", {"p": flat, "o": opts}
    )


def report(tag: str, r: dict, known: set[str] | None = None) -> set[str]:
    filled = {f["label"] for f in r["filled"]}
    new = filled - (known or set()) if known is not None else filled
    print(f"[{tag}] filled={r['counts']['filled']} failed={r['counts']['failed']} "
          f"skipped={r['counts']['skipped']} | 本次新增: {sorted(new)}")
    for row in r["failed"]:
        print(f"  ✗ {row['label']} | {str(row['reason'])[:50]}")
    return filled


async def main() -> None:
    flat = get_json(f"{API}/api/v1/profiles/{PROFILE_ID}/flat", timeout=15)
    attachments = []
    for i, meta in enumerate(flat.get("attachments", [])[:5]):
        try:
            import base64
            with urllib.request.urlopen(  # noqa: S310, ASYNC210
                f"{API}/api/v1/profiles/{PROFILE_ID}/attachments/{i}", timeout=20
            ) as resp:
                attachments.append({**meta, "b64": base64.b64encode(resp.read()).decode()})
        except Exception:  # noqa: BLE001, S110
            pass

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True, viewport={"width": 1440, "height": 1000})
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await pg.goto(APPLY_URL, wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(6000)
        await scroll_sweep(pg)
        await pg.add_script_tag(path=str(CONTENT))

        scan0 = await pg.evaluate(
            "() => { const A = window.__AUTOOFFER_CONTENT__;"
            " const { fields, uploads } = A.scanFields(A.detectSiteAdapter());"
            " return { n: fields.length, uploads,"
            " list: fields.map(f => (f.label || '(?)') + ':' + f.kind).slice(0, 40) }; }")
        print("初始扫描:", json.dumps(scan0, ensure_ascii=False))

        # 清空草稿里站点预填的值（上轮上传解析留存），让引擎直填真实生效
        await pg.evaluate(r"""() => {
          for (const el of document.querySelectorAll(
              '[class*="apply-field"] input[type="text"],[class*="apply-field"] textarea')) {
            if (!el.offsetParent || el.readOnly || el.disabled) continue;
            const set = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype, 'value').set;
            (el.tagName === 'TEXTAREA'
              ? Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
              : set).call(el, '');
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
          }
        }""")
        await pg.wait_for_timeout(600)

        first = await run_pass(pg, flat, {})
        known = report("PASS1 规则直填", first)

        mapping = {}
        if first["unmatched"]:
            resp = get_json(f"{API}/api/v1/mapping",
                            {"profile_id": PROFILE_ID, "fields": first["unmatched"]})
            mapping = {m["field_label"]: m["profile_label"] for m in resp.get("matches", [])}
            print("AI 映射:", mapping)

        second = await run_pass(pg, flat, {
            "mapping": mapping, "attachments": attachments})
        known |= report("PASS2 映射+附件", second, known)

        # 简历上传后 Moka 自行解析，可能展开更多问卷区块
        print("等待站点解析简历...")
        await pg.wait_for_timeout(9000)
        await scroll_sweep(pg)
        scan1 = await pg.evaluate(
            "() => { const A = window.__AUTOOFFER_CONTENT__;"
            " const { fields, uploads } = A.scanFields(A.detectSiteAdapter());"
            " return { n: fields.length, uploads,"
            " list: fields.map(f => (f.label || '(?)') + ':' + f.kind + ':'"
            " + String(f.currentValue || '').slice(0, 8)).slice(0, 60) }; }")
        print("解析后扫描:", json.dumps(scan1, ensure_ascii=False))

        third = await run_pass(pg, flat, {"mapping": mapping})
        known |= report("PASS3 解析后区块", third, known)

        for row in third["failed"]:
            if row.get("options") and len(row["options"]) > 1:
                try:
                    pick = {"label": row["label"], "options": row["options"],
                            "value": row["value"]}
                    resp = get_json(f"{API}/api/v1/option-match", {"picks": [pick]})
                    ch = resp.get("choices", [])
                    if ch:
                        r4 = await run_pass(pg, flat, {"overrides": {ch[0]["label"]: ch[0]["option"]}})  # noqa: E501
                        known |= report("PASS4 选选项", r4, known)
                except Exception as err:  # noqa: BLE001
                    print("option-match error:", err)

        spot = await pg.evaluate(r"""() => {
          const out = {};
          for (const el of document.querySelectorAll('input,textarea')) {
            if (!el.offsetParent || el.value.length === 0 || el.type === 'file') continue;
            const row = el.closest('[class*="item"],[class*="field"],[class*="row"]');
            const lb = row ? (row.innerText || '').split('\n')[0].slice(0, 10) : '?';
            if (!out[lb]) out[lb] = el.value.slice(0, 30);
          }
          return out;
        }""")
        print("页面实值:", json.dumps(spot, ensure_ascii=False))
        shot = Path(__file__).resolve().parents[1] / "artifacts" / "moka_after.png"  # noqa: ASYNC240
        await pg.screenshot(path=str(shot), full_page=True)
        print("截图:", shot)
        print(f"合计填对(去重): {len(known)}")
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
