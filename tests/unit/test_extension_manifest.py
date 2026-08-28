"""插件包完整性：manifest 引用的资源必须存在（打包防呆）。"""

from __future__ import annotations

import json
from pathlib import Path

EXT_DIR = Path(__file__).resolve().parents[2] / "extension"


def load_manifest() -> dict:
    return json.loads((EXT_DIR / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_v3_and_permissions() -> None:
    m = load_manifest()
    assert m["manifest_version"] == 3
    # 最小权限模型：无全量 host_permissions，站点源按需 optional 授权
    assert "host_permissions" not in m
    for perm in ("activeTab", "scripting", "storage"):
        assert perm in m["permissions"]
    assert "http://*/*" in m["optional_host_permissions"]
    assert "https://*/*" in m["optional_host_permissions"]


def test_manifest_files_exist() -> None:
    m = load_manifest()
    assert (EXT_DIR / m["background"]["service_worker"]).exists()
    assert (EXT_DIR / m["action"]["default_popup"]).exists()
    for icon in m["icons"].values():
        assert (EXT_DIR / icon).exists()


def test_popup_references_local_resources() -> None:
    popup = (EXT_DIR / "src" / "popup.html").read_text(encoding="utf-8")
    for res in ("popup.css", "popup.js"):
        assert res in popup
    for res in ("popup.html", "popup.css"):
        assert (EXT_DIR / "src" / res).exists()


def test_content_engine_exposes_test_entry() -> None:
    content = (EXT_DIR / "src" / "content.js").read_text(encoding="utf-8")
    # 幂等注入 + 测试入口 + chrome 消息通道
    assert "__AUTOOFFER_CONTENT__" in content
    assert "autooffer:fill" in content
