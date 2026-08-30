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
# 页面标题里的通用段（页面名/招聘词），不是公司名（「加入」除外——"加入马上消费"类公司名常见）
_GENERIC_TITLE_PART_RE = re.compile(
    r"^(投递|申请|简历|招聘|校招|社招|内推|官网|官方|职位|岗位|campus|career|job|join|apply)",
    re.IGNORECASE,
)


def guess_company(page_title: str) -> str:
    """从页面标题猜公司名：按常见分隔符切分，跳过「投递/招聘/加入」类通用段。"""
    if not page_title:
        return ""
    parts = [p.strip() for p in _TITLE_SPLIT_RE.split(page_title) if p.strip()]
    for p in parts:
        if not _GENERIC_TITLE_PART_RE.match(p):
            return p[:40]
    return parts[0][:40] if parts else ""


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

    - 公司：标题切分后跳过通用段（「投递简历 - 加入马上消费」→ 马上消费）。
    - 岗位：填写报告中"应聘岗位/期望职位/岗位"类字段的实际值优先。
    """
    company = guess_company(page_title)
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

    def add_or_update(
        self,
        *,
        url: str,
        profile_id: str = "",
        page_title: str = "",
        company: str = "",
        position: str = "",
        filled: int = 0,
        failed: int = 0,
        pending: int = 0,
        note: str | None = None,
    ) -> ApplicationRecord:
        """登记/更新一条投递记录：同 URL 的既有 filled 记录更新而非重复添加。

        插件填写上报与任务流报告共用此入口。
        """
        if not company:
            company = guess_company(page_title)
        records = self._load()
        existing = next(
            (r for r in records if r.url == url and r.status == "filled"), None
        )
        if existing is not None:
            existing.fields_filled = filled
            existing.fields_failed = failed
            existing.fields_pending = pending
            existing.company = existing.company or company
            existing.position = existing.position or position
            existing.profile_id = existing.profile_id or profile_id
            existing.updated_at = _now()
            if note:
                existing.note = note
            self._save(records)
            log.info("applications.updated", id=existing.id, url=url)
            return existing

        record = ApplicationRecord(
            id=f"app-{uuid.uuid4().hex[:8]}",
            url=url,
            company=company,
            position=position,
            profile_id=profile_id,
            status="filled",
            filled_at=_now(),
            updated_at=_now(),
            fields_filled=filled,
            fields_failed=failed,
            fields_pending=pending,
            note=note,
        )
        records.append(record)
        self._save(records)
        log.info("applications.added", id=record.id, company=company, position=position)
        return record

    def add_from_report(
        self, report: FillReport, *, page_title: str = "", note: str | None = None
    ) -> ApplicationRecord:
        """由填写报告登记一条投递记录（岗位名取报告里 岗位/职位 类字段的值）。"""
        counts = report.counts()
        _, position = guess_company_position(page_title, report)
        return self.add_or_update(
            url=report.url,
            profile_id=report.profile_id,
            page_title=page_title,
            position=position,
            filled=counts["filled"],
            failed=counts["failed"],
            pending=counts["pending_confirm"],
            note=note,
        )

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
