"""品牌图标栅格化：assets/brand/autooffer.svg → 各端 PNG + Windows ICO。

用仓库已有的 Playwright/Chromium 渲染 SVG（渐变/圆角保真），
输出：
- extension/icons/icon{16,48,128}.png   插件图标（manifest 引用）
- frontend/public/favicon.png (32)       网页标签图标
- frontend/public/logo.png (128)         界面侧边栏/头部
- assets/brand/icon256.png               高清母版
- assets/brand/autooffer.ico             Windows 多尺寸图标（PyInstaller/Inno 用）

用法：python scripts/render_logo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "assets" / "brand" / "autooffer.svg"

PNG_TARGETS: list[tuple[Path, int]] = [
    (ROOT / "extension" / "icons" / "icon16.png", 16),
    (ROOT / "extension" / "icons" / "icon48.png", 48),
    (ROOT / "extension" / "icons" / "icon128.png", 128),
    (ROOT / "frontend" / "public" / "favicon.png", 32),
    (ROOT / "frontend" / "public" / "logo.png", 128),
    (ROOT / "assets" / "brand" / "icon256.png", 256),
]


def render_pngs() -> None:
    from playwright.sync_api import sync_playwright

    svg = SVG_PATH.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 64, "height": 64})
        for path, size in PNG_TARGETS:
            path.parent.mkdir(parents=True, exist_ok=True)
            page.set_viewport_size({"width": size, "height": size})
            sized = svg.replace(
                "<svg ", f'<svg width="{size}" height="{size}" ', 1
            )
            page.set_content(
                f'<body style="margin:0">{sized}</body>'
            )
            page.screenshot(path=str(path), omit_background=True)
            print(f"  {path.relative_to(ROOT)} ({size}x{size})")
        browser.close()


def build_ico() -> None:
    from PIL import Image

    src = Image.open(ROOT / "assets" / "brand" / "icon256.png").convert("RGBA")
    out = ROOT / "assets" / "brand" / "autooffer.ico"
    src.save(
        out,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"  {out.relative_to(ROOT)}")


def main() -> int:
    if not SVG_PATH.exists():
        print(f"SVG 源不存在: {SVG_PATH}", file=sys.stderr)
        return 1
    print("== 渲染 PNG ==")
    render_pngs()
    print("== 合成 ICO ==")
    build_ico()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
