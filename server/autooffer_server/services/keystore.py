"""api_key 加密存储（FR-M4，docs/05 §5）。

优先使用系统密钥库（Windows 凭据管理器 / DPAPI，经 keyring）；
不可用时回退到本机文件（权限受限目录）并在日志中明示降级。
明文 key 只在内存与 keyring 中存在，绝不入库、不进日志、不回传界面。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import ModuleType

import structlog

log = structlog.get_logger(__name__)

SERVICE_NAME = "AutoOffer"


def mask_key(key: str) -> str:
    """生成可安全展示的掩码提示：sk-abcdefgh1234 → sk-***1234。"""
    if not key:
        return ""
    tail = key[-4:] if len(key) > 8 else ""
    head = key[:3] if len(key) > 8 else key[:1]
    return f"{head}***{tail}"


class KeyStore:
    """按端点 id 存取 api_key。"""

    def __init__(self, fallback_path: Path | str | None = None) -> None:
        self._fallback = Path(fallback_path) if fallback_path else None
        self._backend_ok = True
        self._keyring: ModuleType | None
        try:
            import keyring

            self._keyring = keyring
        except ImportError:  # pragma: no cover - 依赖缺失属环境问题
            self._keyring = None
            self._backend_ok = False
            log.warning("keystore.keyring_unavailable")

    # ---------- 同步实现 ----------

    def _fallback_load(self) -> dict[str, str]:
        if self._fallback is None or not self._fallback.exists():
            return {}
        try:
            data: dict[str, str] = json.loads(self._fallback.read_text(encoding="utf-8"))
            return data
        except (ValueError, OSError):
            return {}

    def _fallback_save(self, data: dict[str, str]) -> None:
        if self._fallback is None:
            return
        self._fallback.parent.mkdir(parents=True, exist_ok=True)
        self._fallback.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def _store_sync(self, key_id: str, secret: str) -> None:
        if self._keyring is not None and self._backend_ok:
            try:
                self._keyring.set_password(SERVICE_NAME, key_id, secret)
                return
            except Exception as exc:  # keyring 后端异常 → 降级
                self._backend_ok = False
                log.warning("keystore.set_failed_fallback", error=str(exc))
        data = self._fallback_load()
        data[key_id] = secret
        self._fallback_save(data)

    def _retrieve_sync(self, key_id: str) -> str | None:
        if self._keyring is not None and self._backend_ok:
            try:
                got: str | None = self._keyring.get_password(SERVICE_NAME, key_id)
                if got is not None:
                    return got
            except Exception as exc:
                self._backend_ok = False
                log.warning("keystore.get_failed_fallback", error=str(exc))
        return self._fallback_load().get(key_id)

    def _delete_sync(self, key_id: str) -> None:
        if self._keyring is not None and self._backend_ok:
            try:
                self._keyring.delete_password(SERVICE_NAME, key_id)
            except Exception as exc:  # 不存在或后端异常都无需中断删除流程
                log.debug("keystore.delete_skipped", key_id=key_id, error=str(exc))
        data = self._fallback_load()
        if key_id in data:
            del data[key_id]
            self._fallback_save(data)

    # ---------- 异步接口 ----------

    async def store(self, key_id: str, secret: str) -> None:
        await asyncio.to_thread(self._store_sync, key_id, secret)
        log.info("keystore.stored", key_id=key_id)  # 不记录明文

    async def retrieve(self, key_id: str) -> str | None:
        result: str | None = await asyncio.to_thread(self._retrieve_sync, key_id)
        return result

    async def delete(self, key_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, key_id)
