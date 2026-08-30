"""应用设置存储（单用户本地）：浏览器连接模式、CDP 端点、启动最小化、服务端口。

这些设置由用户在界面「设置」页修改，持久化到数据目录 settings.json。
运行参数在任务启动时读取，因此修改后对下一个任务生效（进行中的任务不受影响）；
service_port 例外：只在软件启动时读取（改端口必须重启服务才能换监听地址）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

BrowserMode = Literal["managed", "cdp"]

DEFAULTS: dict[str, Any] = {
    "browser_mode": "managed",
    "cdp_endpoint": "",
    "minimize_on_startup": False,
    "auto_submit": False,
    "service_port": 8765,
}

_ALLOWED_KEYS = set(DEFAULTS)


class SettingsStore:
    """本机 JSON 设置存取（单用户，无并发写冲突）。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return dict(DEFAULTS)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("settings.load_failed", error=str(exc))
            return dict(DEFAULTS)
        if not isinstance(raw, dict):
            return dict(DEFAULTS)
        data = dict(DEFAULTS)
        for key in _ALLOWED_KEYS:
            if key in raw:
                data[key] = raw[key]
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self) -> dict[str, Any]:
        return self._load()

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        for key in _ALLOWED_KEYS:
            if key in patch:
                data[key] = patch[key]
        self._save(data)
        log.info("settings.updated", keys=sorted(k for k in patch if k in _ALLOWED_KEYS))
        return data
