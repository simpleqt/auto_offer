"""真实表单填写验证：两段式全通道 + 页面实值抽查 + 截图存证。"""

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
PROFILE_ID = "profile-de2d254d"
CONTENT = Path(__file__).resolve().parents[1] / "extension" / "src" / "content.js"
PROFILE_DIR = str(Path(__file__).resolve().parents[1] / ".browser-profile")

SPOT_JS = r"""() => {
  const rows = [...document.querySelectorAll('.form-item')];
  const rowOf = (kw) => rows.find(r => (r.innerText || '').trim().startsWith(kw));
  const textVal = (kw) => {
    const r = rowOf(kw);
    if (!r) return '(无此字段)';
    const inp = r.querySelector('input');
    const t = inp && inp.value ? inp.value : r.innerText.split('\n').slice(1, 3).join(' ');
    return String(t).slice(0, 44);
  };
  const genderChecked = () => {
    const r = rowOf('性别');
    if (!r) return '(无此字段)';
    const on = [...r.querySelectorAll('.phoenix-radio')]
      .find(el => /checked|selected|active/i.test(el.className));
    return on ? (on.innerText || '').trim() : '未选中';
  };
  const uploadInfo = () => {
    const r = rowOf('简历附件');
    if (!r) return { file: '(无字段)', error: '' };
    const err = r.querySelector('[class*="error" i]');
    const file = (r.innerText.match(/[\w\-.]+\.(pdf|docx?|md|jpe?g|png)/i) || [''])[0];
    return { file, error: err ? err.innerText.trim().slice(0, 30) : '' };
  };
  const up = uploadInfo();
  return {
    姓名: textVal('姓名'), 性别选中: genderChecked(), 出生日期: textVal('出生日期'),
    学历: textVal('学历'), 国籍: textVal('国籍'), 工作年限: textVal('工作年限'),
    学校名称: textVal('学校名称'), 专业名称: textVal('专业名称'),
    附件文件: up.file, 附件报错: up.error,
  };
}"""


def post_json(url: str, data: dict, timeout: int = 90) -> dict:
    req = urllib.request.Request(  # noqa: S310
        url, data=json.dumps(data).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.load(resp)


async def main() -> None:
    flat = json.load(urllib.request.urlopen(  # noqa: S310, ASYNC210
        f"{API}/api/v1/profiles/{PROFILE_ID}/flat", timeout=15))
    # 附件字节
    attachments = []
    for i, meta in enumerate(flat.get("attachments", [])[:5]):
        try:
            with urllib.request.urlopen(  # noqa: S310, ASYNC210
                f"{API}/api/v1/profiles/{PROFILE_ID}/attachments/{i}", timeout=20
            ) as resp:
                import base64
                attachments.append({**meta, "b64": base64.b64encode(resp.read()).decode()})
        except Exception:  # noqa: BLE001, S110
            pass

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True, viewport={"width": 1440, "height": 900})
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(5000)
        await pg.add_script_tag(path=str(CONTENT))

        first = await pg.evaluate(
            "(a) => window.__AUTOOFFER_CONTENT__.autofill(a.p, {})", {"p": flat})
        mapping_resp = post_json(
            f"{API}/api/v1/mapping",
            {"profile_id": PROFILE_ID, "fields": first["unmatched"]})
        mapping = {m["field_label"]: m["profile_label"] for m in mapping_resp.get("matches", [])}
        second = await pg.evaluate(
            "(a) => window.__AUTOOFFER_CONTENT__.autofill("
            "a.p, {mapping: a.m, attachments: a.f})",
            {"p": flat, "m": mapping, "f": attachments})

        labels1 = {r["label"] for r in first["filled"]}
        new_rows = [r for r in second["filled"] if r["label"] not in labels1]
        total = first["counts"]["filled"] + len(new_rows)
        failed = [r for r in second["failed"] if r["label"] not in labels1]
        print(f"规则直填: {first['counts']['filled']} | AI/附件补填: {len(new_rows)} "
              f"| 合计填对: {total} | 失败: {len(failed)}")
        for r in new_rows:
            tag = '附件' if r.get('via') == '附件' else 'AI'
            print(f"  + [{tag}] {r['label']} = {r['value'][:30]}")
        for r in failed:
            print(f"  ✗ {r['label']} | {r['reason'][:40]}")

        print("页面抽查:", json.dumps(await pg.evaluate(SPOT_JS), ensure_ascii=False))
        blocks = await pg.evaluate(
            "() => [...document.querySelectorAll('.form-item')]"
            ".filter(e => (e.innerText || '').trim().startsWith('学校名称')).length")
        print("教育区块数(期望2):", blocks)
        shot = Path(tempfile.gettempdir()) / "fscut_verify.png"
        await pg.screenshot(path=str(shot))
        print("截图:", shot)
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
