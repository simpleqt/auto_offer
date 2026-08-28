"""登录陪跑浏览器：常驻有头 Chromium（登录态保存在 .browser-profile），等用户扫码。

用法：python scripts/browser_login.py <url>
按 Ctrl+C 或关闭浏览器窗口退出。
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path(__file__).resolve().parents[1] / ".browser-profile"


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://fscut.zhiye.com/"
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        print(f"已打开: {url}")
        print("浏览器保持常驻，供登录/人工介入；关闭窗口即退出。")
        try:
            while True:
                page.wait_for_timeout(5000)
                if not context.pages:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            context.close()


if __name__ == "__main__":
    main()
