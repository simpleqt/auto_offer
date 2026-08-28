"""真实表单两段式测试：规则直填 → AI 映射（真实 LLM）→ 补填。"""

import asyncio
import json
import tempfile
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

URL = (
    "https://fscut.zhiye.com/form?fromPage=job"
    "&jobAdId=945815e0-94d6-40dd-bf93-4ae27e450029&userId=124918838"
)
API = "http://127.0.0.1:8765"
CONTENT = Path(__file__).resolve().parents[1] / "extension" / "src" / "content.js"
PROFILE_DIR = str(Path(__file__).resolve().parents[1] / ".browser-profile")


def get_json(url: str, data: dict | None = None) -> dict:
    if data is None:
        with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310
            return json.load(resp)
    req = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(data).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
        return json.load(resp)


async def main() -> None:
    flat = get_json(f"{API}/api/v1/profiles/profile-de2d254d/flat")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True, viewport={"width": 1440, "height": 900}
        )
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(5000)
        await pg.add_script_tag(path=str(CONTENT))

        first = await pg.evaluate(
            "(args) => window.__AUTOOFFER_CONTENT__.autofill(args.p, {})",
            {"p": flat},
        )
        print("PASS1:", first["counts"])
        print("UNMATCHED:", [u["label"] for u in first["unmatched"]])

        mapping_resp = get_json(
            f"{API}/api/v1/mapping",
            {"profile_id": "profile-de2d254d", "fields": first["unmatched"]},
        )
        matches = mapping_resp.get("matches", [])
        pairs = [
            (m["field_label"], "->", m["profile_label"], round(m["confidence"], 2))
            for m in matches
        ]
        print("MAPPING:", pairs)
        if not matches:
            print("mapping detail:", mapping_resp)
            await ctx.close()
            return

        mapping = {m["field_label"]: m["profile_label"] for m in matches}
        second = await pg.evaluate(
            "(args) => window.__AUTOOFFER_CONTENT__.autofill(args.p, {mapping: args.m})",
            {"p": flat, "m": mapping},
        )
        print("PASS2:", second["counts"])
        print("AI FILLED:", [f"{f['label']}={f['value'][:20]}" for f in second["filled"]])
        print("AI FAILED:", [(f["label"], f["reason"][:40]) for f in second["failed"]])
        still = [u["label"] for u in second["unmatched"]]
        print("STILL UNMATCHED:", still)
        shot = Path(tempfile.gettempdir()) / "fscut_twopass.png"
        await pg.screenshot(path=str(shot))
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
