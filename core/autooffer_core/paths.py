"""用户数据目录约定（唯一事实源）。

Windows: %APPDATA%/AutoOffer；其它平台: ~/.autooffer。
服务层（ServerConfig）与 CLI/核心（ApplicationStore 默认路径）都必须
消费本函数——此前 ApplicationStore 自带另一套默认（~/AutoOffer，无点号），
非 Windows 平台上 CLI 登记的投递与桌面台账分裂成两份文件。
"""

from __future__ import annotations

import os
from pathlib import Path


def default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "AutoOffer"
    return Path.home() / ".autooffer"
