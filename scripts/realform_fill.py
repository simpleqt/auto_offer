"""真实表单终测（通用驱动）：规则直填 → AI 标签映射 → 附件 → AI 选选项。

镜像 extension/src/background.js（v0.2.33）的编排逻辑：
- occurrence 键（label#N）贯穿 picks/overrides（多段经历不串段）
- restricted 值不进 option-match（LLM 通道）
- 附件按 pass1 的 uploadCount 门控下载
- 多步向导翻页在 content.autofill 内部自动处理

用法：python scripts/realform_fill.py <url> [--sensitive] [--no-attach]
要求：本地服务已启动（127.0.0.1:8765），.browser-profile 已完成目标站登录，
且登录陪跑浏览器已关闭（Chromium profile 独占锁）。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

API = "http://127.0.0.1:8765"
PROFILE_ID = "profile-de2d254d"
CONTENT = Path(__file__).resolve().parents[1] / "extension" / "src" / "content.js"
PROFILE_DIR = str(Path(__file__).resolve().parents[1] / ".browser-profile")
ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
IDCARD_RE = re.compile(r"^\d{17}[\dXx]$|^\d{15}$")


def get_json(url: str, data: dict | None = None, timeout: int = 15) -> dict:
    if data is None:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return json.load(resp)
    req = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(data).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.load(resp)


def fetch_attachment_b64(index: int) -> str | None:
    try:
        with urllib.request.urlopen(  # noqa: S310
            f"{API}/api/v1/profiles/{PROFILE_ID}/attachments/{index}", timeout=30
        ) as resp:
            return base64.b64encode(resp.read()).decode("ascii")
    except Exception as err:  # noqa: BLE001
        print(f"  [附件{index}下载失败] {err}")
        return None


def flat_value_map(flat: dict) -> dict:
    out: dict = {}
    for s in flat.get("sections", []):
        if s.get("kind") == "simple":
            for k, v in s.get("values", {}).items():
                out.setdefault(k, str(v))
        else:
            for item in s.get("items", [])[:1]:
                for k, v in item.items():
                    out.setdefault(k, str(v))
    return out


def restricted_value_set(flat: dict, values: dict) -> set[str]:
    return {
        values[label].strip()
        for label in flat.get("restrictedLabels", [])
        if values.get(label)
    }


def build_option_picks(report: dict, mapping: dict, values: dict, restricted: set[str]):
    picks = []
    seen = set()
    seen_plain = set()

    def blocked(value) -> bool:
        v = str(value or "").strip()
        return v in restricted or bool(IDCARD_RE.match(v))

    options_by_label = {f["label"]: f["options"] for f in report.get("optionFields", [])}

    def loose(value, option) -> bool:
        v, o = str(value or ""), str(option or "")
        return v == o or v in o or o in v[:8]

    for row in report.get("failed", []):
        key = f"{row['label']}#{row.get('occurrence') or 0}"
        if (
            row.get("options")
            and len(row["options"]) > 1
            and key not in seen
            and not blocked(row.get("value"))
        ):
            seen.add(key)
            picks.append({"label": row["label"], "occurrence": row.get("occurrence") or 0,
                          "options": row["options"], "value": row.get("value")})
    for field_label, profile_label in mapping.items():
        if field_label in seen_plain:
            continue
        options = options_by_label.get(field_label)
        value = values.get(profile_label)
        if options and len(options) > 1 and value and not any(loose(value, o) for o in options):
            if not blocked(value):
                seen_plain.add(field_label)
                picks.append({"label": field_label, "options": options, "value": value})
    for row in report.get("failed", []):
        key = f"{row['label']}#{row.get('occurrence') or 0}"
        if key in seen or "回读不一致" not in str(row.get("reason", "")):
            continue
        options = options_by_label.get(row["label"])
        value = row.get("value") or values.get(row["label"])
        if options and len(options) > 1 and value and not any(loose(value, o) for o in options):
            if not blocked(value):
                seen.add(key)
                picks.append({"label": row["label"], "occurrence": row.get("occurrence") or 0,
                              "options": options, "value": value})
    return picks


def print_report(tag: str, report: dict) -> None:
    counts = report.get("counts", {})
    print(f"\n===== [{tag}] counts: {counts} =====")
    for r in report.get("filled", []):
        via = f" via={r['via']}" if r.get("via") else ""
        print(f"  ✓ {r.get('occurrence', 0)}#{r['label']} = {str(r.get('value'))[:40]}{via}")
    for r in report.get("failed", []):
        print(f"  ✗ {r.get('occurrence', 0)}#{r['label']} : {str(r.get('reason'))[:60]}")
    skipped = report.get("skipped", [])
    if skipped:
        print(f"  - skipped({len(skipped)}): " +
              "; ".join(f"{s['field']}({s['reason'][:14]})" for s in skipped[:12]))
    errs = report.get("formErrors", [])
    if errs:
        print(f"  ⚠ 页面校验: {errs}")
    if report.get("mappingError"):
        print(f"  ⚠ mappingError: {report['mappingError']}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--sensitive", action="store_true")
    parser.add_argument("--no-attach", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    sensitive = 1 if args.sensitive else 0
    print(f"[1] 拉取扁平档案 sensitive={sensitive}")
    flat = get_json(f"{API}/api/v1/profiles/{PROFILE_ID}/flat?sensitive={sensitive}")
    values = flat_value_map(flat)
    restricted = restricted_value_set(flat, values)
    if restricted:
        print(f"  restricted 值 {len(restricted)} 项已挡在 LLM 通道外")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=args.headless, viewport={"width": 1440, "height": 900},
            args=["--start-maximized"],
        )
        pg = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await pg.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_timeout(4000)
        await pg.add_script_tag(path=str(CONTENT))
        print("[2] 注入 content.js 完成，开始第一段规则直填")

        async def run_pass(opts: dict) -> dict:
            return await pg.evaluate(
                "(a) => window.__AUTOOFFER_CONTENT__.autofill(a.p, a.o)",
                {"p": flat, "o": opts},
            )

        first = await run_pass({})
        print_report("PASS1 规则直填", first)

        report = first
        mapping: dict[str, str] = {}
        attachments: list[dict] = []
        try:
            unmatched = first.get("unmatched", [])
            if unmatched:
                print(f"\n[3] AI 标签映射：{len(unmatched)} 个未命中字段（首20: "
                      f"{[u['label'] for u in unmatched[:20]]}）")
                resp = get_json(f"{API}/api/v1/mapping",
                                {"profile_id": PROFILE_ID, "fields": unmatched}, timeout=200)
                for m in resp.get("matches", []):
                    mapping[m["field_label"]] = m["profile_label"]
                print("  MAPPING:", [(m["field_label"], "→", m["profile_label"],
                                      f"{m['confidence']:.2f}") for m in resp.get("matches", [])])

            upload_count = int(first.get("uploadCount") or 0)
            if upload_count > 0 and not args.no_attach:
                for meta in flat.get("attachments", [])[:5]:
                    idx = meta.get("index", 0)
                    b64 = fetch_attachment_b64(idx)
                    if b64:
                        attachments.append({**meta, "b64": b64})
                print(f"[4] 附件：页面 {upload_count} 个上传框，取到 {len(attachments)} 份")
            else:
                print(f"[4] 附件：页面无上传框（uploadCount={upload_count}），跳过下载")

            second_opts: dict = {}
            if mapping:
                second_opts["mapping"] = mapping
            if attachments:
                second_opts["attachments"] = attachments
            if second_opts:
                second = await run_pass(second_opts)
                mk = set(mapping)
                for row in second.get("filled", []):
                    if not row.get("via") and row.get("field") in mk:
                        row["via"] = "ai"
                print_report("PASS2 映射+附件", second)
                # 合并（与 mergeReports 同口径：按 label#occurrence 去重新增）
                def _key(r: dict) -> str:
                    return f"{r.get('field', r['label'])}#{r.get('occurrence') or 0}"

                filled_keys = {_key(r) for r in report.get("filled", [])}
                new_filled = [r for r in second["filled"] if _key(r) not in filled_keys]
                new_failed = [r for r in second["failed"] if _key(r) not in filled_keys]
                skipped_all = {
                    (s["field"], s["reason"])
                    for s in report.get("skipped", []) + second.get("skipped", [])
                }
                report = {
                    **second,
                    "counts": {
                        "filled": report["counts"]["filled"] + len(new_filled),
                        "failed": report["counts"]["failed"] + len(new_failed),
                        "skipped": len(skipped_all),
                    },
                    "filled": report.get("filled", []) + second.get("filled", []),
                    "failed": report.get("failed", []) + second.get("failed", []),
                }

            print("\n[5] AI 选选项循环（≤3 轮）")
            for round_no in range(3):
                picks = build_option_picks(
                    report, mapping if round_no == 0 else {}, values, restricted
                )
                if not picks:
                    print(f"  ROUND{round_no}: 无待选项，结束")
                    break
                pick_desc = [
                    (x["label"], str(x["value"])[:12], f"n={len(x['options'])}")
                    for x in picks[:8]
                ]
                print(f"  ROUND{round_no} picks({len(picks)}): {pick_desc}")
                overrides: dict[str, str] = {}
                try:
                    resp = get_json(f"{API}/api/v1/option-match",
                                    {"picks": picks, "profile_id": PROFILE_ID}, timeout=140)
                    for c in resp.get("choices", []):
                        occ = c.get("occurrence")
                        key = f"{c['label']}#{occ}" if isinstance(occ, int) else c["label"]
                        overrides[key] = c["option"]
                except urllib.error.HTTPError as err:
                    body = err.read()[:200] if hasattr(err, "read") else err
                    print(f"  option-match HTTP {err.code}: {body}")
                    break
                except Exception as err:  # noqa: BLE001
                    print(f"  option-match error: {err}")
                    break
                if not overrides:
                    print(f"  ROUND{round_no}: 模型未给出选择，结束")
                    break
                print(f"  ROUND{round_no} choices: {overrides}")
                r = await run_pass({"overrides": overrides})
                ov_labels = {k.split("#")[0] for k in overrides}
                for row in r.get("filled", []):
                    if not row.get("via") and row.get("field") in ov_labels:
                        row["via"] = "ai"
                print_report(f"ROUND{round_no} 选选项", r)
                report = {**r, "filled": report.get("filled", []) + r.get("filled", []),
                          "failed": r.get("failed", [])}
        except Exception as err:  # noqa: BLE001
            print(f"  [二段异常] {err}")

        ARTIFACTS.mkdir(exist_ok=True)
        shot = ARTIFACTS / "changhong_fill.png"
        await pg.screenshot(path=str(shot), full_page=False)
        print(f"\n[6] 截图: {shot}")
        total = report.get("counts", {})
        print(f"[完成] 汇总 counts={total}（多轮合并口径见各段明细）")
        await ctx.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
