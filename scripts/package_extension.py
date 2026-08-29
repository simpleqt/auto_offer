"""把 extension/ 打包为可直接安装的浏览器扩展 zip（Edge/Chrome 通用）。

用法: python scripts/package_extension.py
产物: dist/AutoOffer-Extension-<版本>.zip
安装: edge://extensions 打开开发人员模式 → 解压 zip → 「加载解压缩的扩展」选中目录。
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
DIST = ROOT / "dist"


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if _stream.encoding and _stream.encoding.lower() not in ("utf-8", "utf8"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]

    files = sorted(
        p for p in EXT.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    # manifest 引用的资源必须齐全
    referenced: list[str] = [
        manifest["action"]["default_popup"],
        manifest["background"]["service_worker"],
    ]
    referenced += list(manifest["action"]["default_icon"].values())
    referenced += list(manifest["icons"].values())
    names = {str(p.relative_to(EXT)).replace("\\", "/") for p in files}
    missing = [r for r in referenced if r not in names]
    if missing:
        print(f"manifest 引用的文件缺失: {missing}")
        return 1

    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / f"AutoOffer-Extension-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(EXT))
    print(f"已打包: {out} ({out.stat().st_size // 1024} KB, {len(files)} 个文件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
