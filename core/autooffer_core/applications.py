"""投递记录列表：每次自动填写完成后登记，支持状态跟踪（软件端"投递管理"数据源）。

存储为本机 JSON 文件（默认 %APPDATA%/AutoOffer/applications.json）；
W5 服务层落地后由 SQLite 仓储替换，本模块接口保持不变。
"""

from __future__ import annotations

import datetime
import json
import re
import uuid
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel

from autooffer_core.report import FillReport

log = structlog.get_logger(__name__)

ApplicationStatus = Literal[
    "filled",       # 已自动填写，等待用户审核提交
    "submitted",    # 用户已确认提交
    "interview",    # 已约面试
    "rejected",     # 已拒/流程终止
    "abandoned",    # 放弃投递
]

_TITLE_SPLIT_RE = re.compile(r"[-—|_·]|\s{2,}")


class ApplicationRecord(BaseModel):
    id: str
    url: str
    company: str = ""
    position: str = ""
    profile_id: str = ""
    status: ApplicationStatus = "filled"
    filled_at: str = ""
    updated_at: str = ""
    fields_filled: int = 0
    fields_failed: int = 0
    fields_pending: int = 0
    note: str | None = None


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def guess_company_position(page_title: str, report: FillReport) -> tuple[str, str]:
    """从页面标题与填写报告猜测公司名与岗位（可被用户在列表中修改）。

    - 公司：标题按常见分隔符切分取首段（"星辰科技 - 校园招聘" → "星辰科技"）。
    - 岗位：填写报告中"应聘岗位/期望职位/岗位"类字段的实际值优先。
    """
    company = ""
    if page_title:
        parts = [p.strip() for p in _TITLE_SPLIT_RE.split(page_title) if p.strip()]
        if parts:
            company = parts[0][:40]
    position = ""
    for f in report.fields:
        if any(k in f.label for k in ("应聘岗位", "期望职位", "应聘职位", "岗位", "职位")):
            if f.value:
                position = f.value[:40]
                break
    return company, position


class ApplicationStore:
    """投递记录的本机 JSON 存取。"""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            import os

            base = Path(os.environ.get("APPDATA", str(Path.home()))) / "AutoOffer"
            path = base / "applications.json"
        self._path = Path(path)

    # ---------- 读写 ----------

    def _load(self) -> list[ApplicationRecord]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [ApplicationRecord.model_validate(r) for r in raw]
        except (ValueError, OSError) as exc:
            log.warning("applications.load_failed", error=str(exc))
            return []

    def _save(self, records: list[ApplicationRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [r.model_dump() for r in records]
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- 操作 ----------

    def add_from_report(
        self, report: FillReport, *, page_title: str = "", note: str | None = None
    ) -> ApplicationRecord:
        """由填写报告登记一条投递记录；同 URL 的既有 filled 记录会被更新而不是重复添加。"""
        counts = report.counts()
        company, position = guess_company_position(page_title, report)
        records = self._load()
        existing = next(
            (r for r in records if r.url == report.url and r.status == "filled"), None
        )
        if existing is not None:
            existing.fields_filled = counts["filled"]
            existing.fields_failed = counts["failed"]
            existing.fields_pending = counts["pending_confirm"]
            existing.company = existing.company or company
            existing.position = existing.position or position
            existing.updated_at = _now()
            if note:
                existing.note = note
            self._save(records)
            log.info("applications.updated", id=existing.id, url=report.url)
            return existing

        record = ApplicationRecord(
            id=f"app-{uuid.uuid4().hex[:8]}",
            url=report.url,
            company=company,
            position=position,
            profile_id=report.profile_id,
            status="filled",
            filled_at=_now(),
            updated_at=_now(),
            fields_filled=counts["filled"],
            fields_failed=counts["failed"],
            fields_pending=counts["pending_confirm"],
            note=note,
        )
        records.append(record)
        self._save(records)
        log.info("applications.added", id=record.id, company=company, position=position)
        return record

    def list(self, *, status: ApplicationStatus | None = None) -> list[ApplicationRecord]:
        records = self._load()
        if status is not None:
            records = [r for r in records if r.status == status]
        return sorted(records, key=lambda r: r.filled_at, reverse=True)

    def update_status(
        self, record_id: str, status: ApplicationStatus, *, note: str | None = None
    ) -> ApplicationRecord | None:
        records = self._load()
        for r in records:
            if r.id == record_id:
                r.status = status
                r.updated_at = _now()
                if note:
                    r.note = note
                self._save(records)
                log.info("applications.status_changed", id=record_id, status=status)
                return r
        return None

    def remove(self, record_id: str) -> bool:
        records = self._load()
        remained = [r for r in records if r.id != record_id]
        if len(remained) == len(records):
            return False
        self._save(remained)
        return True
