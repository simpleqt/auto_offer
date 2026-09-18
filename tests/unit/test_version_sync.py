"""版本号一致性守护：core / extension manifest / frontend package.json 必须一致。

v0.2.34 曾因 SCRIPT_VERSION 与 manifest 漂移导致引擎拒答所有消息
（填写直接失败）；pyproject 曾静态写死 0.1.0 与实际相差 38 个小版本。
pyproject 已改为 dynamic 从 autooffer_core.__version__ 派生，发版改
core 一处后由本测试守护另外两处不漂。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from autooffer_core import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_manifest_and_package_json_match_core_version() -> None:
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text("utf-8"))
    package = json.loads((ROOT / "frontend" / "package.json").read_text("utf-8"))
    assert manifest["version"] == __version__, (
        f"extension/manifest.json {manifest['version']} != core {__version__}"
    )
    assert package["version"] == __version__, (
        f"frontend/package.json {package['version']} != core {__version__}"
    )


def test_pyproject_version_is_dynamic_from_core() -> None:
    """pyproject 不得再写死版本号（曾因此静默漂移）。"""
    text = (ROOT / "pyproject.toml").read_text("utf-8")
    assert re.search(r'^dynamic\s*=\s*\["version"\]', text, re.MULTILINE)
    assert 'version = { attr = "autooffer_core.__version__" }' in text
    assert not re.search(r'^version\s*=\s*"', text, re.MULTILINE)
