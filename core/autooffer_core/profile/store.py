"""档案的 YAML 序列化与本机读写（FR-P6）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from autooffer_core.errors import ProfileError
from autooffer_core.profile.schema import Profile


def profile_to_yaml(profile: Profile) -> str:
    data = profile.model_dump(mode="json", exclude_none=True)
    text: str = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return text


def profile_from_yaml(text: str) -> Profile:
    try:
        data = yaml.safe_load(text)
        return Profile.model_validate(data)
    except Exception as exc:  # yaml 或校验错误统一为 ProfileError
        raise ProfileError(f"档案 YAML 解析失败: {exc}") from exc


def save_profile(profile: Profile, path: str | Path) -> None:
    Path(path).write_text(profile_to_yaml(profile), encoding="utf-8")


def load_profile(path: str | Path) -> Profile:
    p = Path(path)
    if not p.exists():
        raise ProfileError(f"档案文件不存在: {p}")
    return profile_from_yaml(p.read_text(encoding="utf-8"))
