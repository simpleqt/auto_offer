"""本地服务配置（docs/03 §5，FR-D3：仅监听 127.0.0.1）。"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


def default_data_dir() -> Path:
    """用户数据目录：Windows 用 %APPDATA%/AutoOffer，其它平台用 ~/.autooffer。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "AutoOffer"
    return Path.home() / ".autooffer"


class ServerConfig(BaseModel):
    """服务配置。数据全部落在本机 data_dir（NFR-4 隐私）。"""

    data_dir: Path
    host: str = "127.0.0.1"
    """安全约束：只允许本机访问，不对外暴露。"""

    port: int = 8765
    max_concurrent_tasks: int = 2
    headless: bool = False
    """默认弹出浏览器窗口，便于用户观察与人工接管。"""

    @classmethod
    def create(cls, data_dir: Path | str | None = None, **kwargs: object) -> ServerConfig:
        base = Path(data_dir) if data_dir else default_data_dir()
        return cls(data_dir=base, **kwargs)  # type: ignore[arg-type]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "autooffer.db"

    @property
    def runs_dir(self) -> Path:
        """任务留痕目录（截图、审计事件附件）。"""
        return self.data_dir / "runs"

    @property
    def uploads_dir(self) -> Path:
        """用户上传的简历/附件暂存目录。"""
        return self.data_dir / "uploads"

    @property
    def attachments_dir(self) -> Path:
        """用户上传的附件永久存储目录（证件照/成绩单/证书/作品集等）。"""
        return self.data_dir / "attachments"

    @property
    def browser_profile_dir(self) -> Path:
        """共享持久浏览器 profile 目录（保留登录态，跨任务免登录）。"""
        return self.data_dir / "browser_profile"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.runs_dir, self.uploads_dir, self.attachments_dir):
            p.mkdir(parents=True, exist_ok=True)
