"""Windows 安装包打包脚本（W8，docs/03 §7）。

流程：
1. `npm run build` 产出前端 dist。
2. PyInstaller（onedir）打包桌面壳入口 `app/launcher.py`。
3. 复制 Playwright Chromium 与前端 dist 到产物目录。
4. 调用 Inno Setup 编译安装程序（若安装）。

依赖：pip install pyinstaller；Inno Setup 为可选（无则跳过编译步骤并提示）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP = ROOT / "app"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=cwd)  # noqa: S603 - 命令由本脚本静态构造，非外部输入


def build_frontend() -> None:
    print("== 1/4 构建前端 ==")
    # Windows 下 npm 是 npm.cmd，subprocess 不带 shell 解析不了裸 "npm"
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    _run([npm, "run", "build"], cwd=FRONTEND)


def build_pyinstaller() -> None:
    print("== 2/4 PyInstaller 打包桌面壳 ==")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "AutoOffer",
        "--add-data",
        f"{FRONTEND / 'dist'}{';' if sys.platform == 'win32' else ':'}frontend/dist",
        str(APP / "launcher.py"),
    ]
    _run(cmd, cwd=ROOT)


def copy_chromium() -> None:
    """把 Playwright 的浏览器缓存复制进产物，供打包后离线使用。"""
    print("== 3/4 复制 Chromium ==")
    browsers = _playwright_browsers_dir()
    if browsers is None or not browsers.exists():
        print(f"  未找到 Playwright 浏览器缓存目录（{browsers}），跳过")
        return
    dest = DIST / "AutoOffer" / "ms-playwright"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(browsers, dest)
    print(f"  Chromium 已复制到 {dest}")


def _playwright_browsers_dir() -> Path | None:
    """定位 Playwright 浏览器缓存目录（优先环境变量，其次按平台默认路径）。"""
    import os

    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return Path(env)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def sync_iss_version() -> None:
    """把 autooffer_core.__version__ 注入 Inno Setup 脚本，避免手抄版本号漂移。"""
    import re

    from autooffer_core import __version__

    iss = ROOT / "scripts" / "AutoOffer.iss"
    text = iss.read_text(encoding="utf-8")
    new = f'#define MyAppVersion "{__version__}"'
    updated, count = re.subn(r'#define MyAppVersion "[^"]*"', new, text)
    if count and updated != text:
        iss.write_text(updated, encoding="utf-8")
        print(f"  AutoOffer.iss 版本已同步为 {__version__}")


def build_installer() -> None:
    print("== 4/4 编译 Inno Setup 安装程序 ==")
    iss = ROOT / "scripts" / "AutoOffer.iss"
    if not iss.exists():
        print(f"  未找到 {iss}，跳过（Inno Setup 编译可选）")
        return
    iscc = shutil.which("iscc") or _default_iscc_path()
    if not iscc or not Path(iscc).exists():
        print("  未找到 Inno Setup（iscc.exe），跳过编译。请安装后重试。")
        return
    sync_iss_version()
    _run([iscc, str(iss)])


def _default_iscc_path() -> str | None:
    if sys.platform != "win32":
        return None
    candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoOffer Windows 安装包构建")
    parser.add_argument("--skip-frontend", action="store_true", help="跳过前端构建（已构建过）")
    args = parser.parse_args()

    if not args.skip_frontend:
        build_frontend()
    build_pyinstaller()
    copy_chromium()
    build_installer()
    print("\n构建完成：dist/AutoOffer/ 下为可执行目录。")
    print("安装包（若已编译）：dist/AutoOffer-Setup.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
