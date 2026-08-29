"""真实表单终测（M3 全通道）：规则直填 → AI 标签映射 → AI 选选项 → 附件注入。

镜像 extension/src/background.js 的编排逻辑，用持久化登录态驱动真实页面。
"""

import asyncio
import base64
import json
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

URL = (
    "https://fscut.zhiye.com/form?fromPage=job"
    "&jobAdId=945815e0-94d6-40dd-bf93-4ae27e450029&userId=124918838"
)
API = "http://127.0.0.1:8765"
PROFILE_ID = "profile-de2d254d"
CONTENT = Path(__file__).resolve().parents[1] / "extension" / "src" / "content.js"
PROFILE_DIR = str(Path(__file__).resolve().parents[1] / ".browser-profile")


def get_json(url: str, data: dict | None = None, timeout: int = 15) -> dict:
    if data is None:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return json.load(resp)
    req = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(data).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.load(resp)


def fetch_attachment_b64(index: int) -> str | None:
    try:
        with urllib.request.urlopen(  # noqa: S310
            f"{API}/api/v1/profiles/{PROFILE_ID}/attachments/{index}", timeout=20
        ) as resp:
            return base64.b64encode(resp.read()).decode("ascii")
    except Exception as err:  # noqa: BLE001
        print(f"attachment[{index}] fetch failed: {err}")
        return None


def flat_value_map(flat: dict) -> dict:
    out: dict = {}
    for s in flat.get("sections", []):
        if s["kind"] == "simple":
            for k, v in s.get("values", {}).items():
                out.setdefault(k, str(v))
        else:
            for item in s.get("items", [])[:1]:
                for k, v in item.items():
                    out.setdefault(k, str(v))
    return out


async def main() -> None:
    flat = get_json(f"{API}/api/v1/profiles/{PROFILE_ID}/flat")
    attachments = []
    for i, meta in enumerate(flat.get("attachments", [])[:5]):
        b64 = fetch_attachment_b64(i)
        if b64:
            attachments.append({**meta, "b64": b64})

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True, viewport={"width": 1440, "height": 900}
        )
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(5000)
        await pg.add_script_tag(path=str(CONTENT))

        first = await pg.evaluate(
            "(a) => window.__AUTOOFFER_CONTENT__.autofill(a.p, {})", {"p": flat}
        )
        print("PASS1:", first["counts"])

        # 二段-1 AI 标签映射
        mapping_resp = get_json(
            f"{API}/api/v1/mapping",
            {"profile_id": PROFILE_ID, "fields": first["unmatched"]},
            timeout=90,
        )
        matches = mapping_resp.get("matches", [])
        mapping = {m["field_label"]: m["profile_label"] for m in matches}
        print("MAPPING:", [(m["field_label"], m["profile_label"]) for m in matches])

        # 二段-2：映射 + 附件补填
        second_opts = {}
        if mapping:
            second_opts["mapping"] = mapping
        if attachments:
            second_opts["attachments"] = attachments
        failed_rows = first["failed"]
        if second_opts:
            second = await pg.evaluate(
                "(a) => window.__AUTOOFFER_CONTENT__.autofill("
                "a.p, {mapping: a.m, overrides: a.o, attachments: a.f})",
                {"p": flat, "m": mapping, "o": {}, "f": attachments},
            )
            print("PASS2:", second["counts"])
            print("PASS2 FILLED:", [f"{f['label']}={f['value'][:18]}" for f in second["filled"]])
            print("PASS2 FAILED:", [(f["label"], f["reason"][:40]) for f in second["failed"]])
            failed_rows = second["failed"]
            labels1 = {r["label"] for r in first["filled"]}
            new_rows = [r for r in second["filled"] if r["label"] not in labels1]
            total = first["counts"]["filled"] + len(new_rows)
            print(f"TOTAL NEW FILLED THIS RUN: {len(new_rows)} | GRAND TOTAL: {total}")

        # 二段-3 AI 选选项循环（级联逐层下钻，最多 3 轮；用最新失败行的收割选项）
        values = flat_value_map(flat)
        options_by_label = {f["label"]: f["options"] for f in first.get("optionFields", [])}
        labels1 = {r["label"] for r in first["filled"]}
        for round_no in range(3):
            picks = []
            seen = set()
            for row in failed_rows:
                if row.get("options") and len(row["options"]) > 1 and row["label"] not in seen:
                    seen.add(row["label"])
                    picks.append(
                        {"label": row["label"], "options": row["options"], "value": row["value"]}
                    )
            if round_no == 0 and not picks:
                for field_label, profile_label in mapping.items():
                    if field_label in seen:
                        continue
                    options = options_by_label.get(field_label)
                    value = values.get(profile_label)
                    if options and len(options) > 1 and value:
                        seen.add(field_label)
                        picks.append({"label": field_label, "options": options, "value": value})
            if not picks:
                break
            print(
                f"ROUND{round_no} PICKS:",
                [
                    (x["label"], x["value"][:12], f"n={len(x['options'])}", x["options"][:6])
                    for x in picks
                ],
            )
            overrides = {}
            try:
                choice_resp = get_json(f"{API}/api/v1/option-match", {"picks": picks}, timeout=90)
                for c in choice_resp.get("choices", []):
                    overrides[c["label"]] = c["option"]
            except Exception as err:  # noqa: BLE001
                print("option-match error:", err)
                break
            if not overrides:
                print(f"ROUND{round_no}: no choices, stop")
                break
            print(f"ROUND{round_no} PICKS->CHOICES:",
                  [
                      (x["label"], x["value"][:10], "->", overrides.get(x["label"]))
                      for x in picks
                  ])
            r = await pg.evaluate(
                "(a) => window.__AUTOOFFER_CONTENT__.autofill("
                "a.p, {mapping: a.m, overrides: a.o, attachments: a.f})",
                {"p": flat, "m": {}, "o": overrides, "f": []},
            )
            failed_rows = r["failed"]
            new_rows = [x for x in r["filled"] if x["label"] not in labels1]
            labels1.update(x["label"] for x in r["filled"])
            print(
                f"ROUND{round_no} FILLED(new):",
                [f"{f['label']}={f['value'][:18]}" for f in new_rows],
            )
            print(f"ROUND{round_no} FAILED:", [(f["label"], f["reason"][:36]) for f in r["failed"]])

        shot = Path(__file__).parent / ".." / "artifacts"
        shot.mkdir(exist_ok=True)
        await pg.screenshot(path=str(shot / "fscut_m3.png"))
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
