"""REST 路由实现（docs/03 §5.1）。

依赖通过 app.state.ctx 注入（create_app 装配），便于测试替换执行体与密钥库。
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from autooffer_core import __version__
from autooffer_core.applications import ApplicationStore
from autooffer_core.profile.completeness import profile_completeness
from autooffer_core.profile.schema import Profile
from autooffer_server.api.schemas import (
    ApplicationReportIn,
    ApplicationStatusIn,
    AppSettings,
    EndpointIn,
    EndpointOut,
    LogsIn,
    MappingIn,
    MappingOut,
    OptionMatchIn,
    OptionMatchOut,
    ProfileIn,
    ProfileSummary,
    RoutingIn,
    TaskIn,
    TaskOut,
    UsageReport,
)
from autooffer_server.services.keystore import mask_key

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1")


def _ctx(request: Request) -> Any:
    return request.app.state.ctx


def _vision_int(row: dict[str, Any]) -> int:
    v = row.get("supports_vision")
    return -1 if v is None else int(bool(v))


# ---------- 系统 ----------


@router.get("/system/health")
async def health(request: Request) -> dict[str, Any]:
    ctx = _ctx(request)
    return {
        "status": "ok",
        "version": __version__,
        "data_dir": str(ctx.config.data_dir),
        "headless": ctx.config.headless,
        "port": ctx.config.port,
    }


@router.get("/system/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/usage", response_model=UsageReport)
async def usage_report(request: Request) -> dict[str, Any]:
    """模型调用统计（FR-M5）：按模型与按任务聚合 token 用量/时延/失败率。"""
    return await _ctx(request).repo.aggregate_llm_usage()


@router.get("/settings", response_model=AppSettings)
async def get_settings(request: Request) -> dict[str, Any]:
    """读取应用设置（浏览器连接模式 / CDP 端点 / 启动最小化）。"""
    result: dict[str, Any] = _ctx(request).settings.get()
    return result


@router.put("/settings", response_model=AppSettings)
async def put_settings(request: Request, body: AppSettings) -> dict[str, Any]:
    """更新应用设置。运行参数在任务启动时读取，对下一个任务生效。"""
    result: dict[str, Any] = _ctx(request).settings.update(body.model_dump())
    return result


# ---------- 模型端点 ----------


@router.get("/models", response_model=list[EndpointOut])
async def list_models(request: Request) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = await _ctx(request).repo.list_endpoints()
    return result


@router.put("/models", response_model=EndpointOut)
async def upsert_model(request: Request, body: EndpointIn) -> dict[str, Any]:
    ctx = _ctx(request)
    existing = await ctx.repo.get_endpoint(body.id)
    data = body.model_dump(exclude={"api_key"})
    if body.api_key:
        await ctx.keystore.store(body.id, body.api_key)
        data["key_hint"] = mask_key(body.api_key)
    elif existing is not None:
        data["key_hint"] = existing["key_hint"]
    else:
        raise HTTPException(400, "新增端点必须提供 api_key")
    data["supports_vision"] = -1 if existing is None else _vision_int(existing)
    await ctx.repo.save_endpoint(data)
    saved: dict[str, Any] | None = await ctx.repo.get_endpoint(body.id)
    assert saved is not None
    return saved


@router.delete("/models/{endpoint_id}")
async def delete_model(request: Request, endpoint_id: str) -> dict[str, bool]:
    ctx = _ctx(request)
    ok: bool = await ctx.repo.delete_endpoint(endpoint_id)
    if ok:
        await ctx.keystore.delete(endpoint_id)
    return {"deleted": ok}


@router.post("/models/{endpoint_id}/probe")
async def probe_model(request: Request, endpoint_id: str) -> dict[str, Any]:
    """连通性与视觉能力探测（FR-M2）。"""
    from autooffer_core.llm.probe import probe_endpoint

    ctx = _ctx(request)
    ep = await ctx.build_endpoint(endpoint_id)
    result = await probe_endpoint(ep)
    await ctx.repo.set_vision(endpoint_id, result.supports_vision)
    payload: dict[str, Any] = result.model_dump()
    return payload


@router.get("/models/routing")
async def get_routing(request: Request) -> dict[str, str]:
    result: dict[str, str] = await _ctx(request).repo.get_routing()
    return result


@router.put("/models/routing")
async def put_routing(request: Request, body: RoutingIn) -> dict[str, str]:
    ctx = _ctx(request)
    await ctx.repo.set_routing(body.mapping)
    result: dict[str, str] = await ctx.repo.get_routing()
    return result


# ---------- 档案 ----------


@router.get("/profiles", response_model=list[ProfileSummary])
async def list_profiles(request: Request) -> list[dict[str, Any]]:
    rows = await _ctx(request).repo.list_profiles()
    out: list[dict[str, Any]] = []
    for r in rows:
        score, _missing = profile_completeness(Profile.model_validate(r["payload"]))
        out.append(
            {
                "id": r["id"],
                "label": r["label"],
                "updated_at": r["updated_at"],
                "name": r["payload"].get("basic", {}).get("name", ""),
                "attachments": len(r["payload"].get("attachments", [])),
                "completeness": score,
            }
        )
    return out


@router.get("/profiles/{profile_id}")
async def get_profile(request: Request, profile_id: str) -> dict[str, Any]:
    row: dict[str, Any] | None = await _ctx(request).repo.get_profile(profile_id)
    if row is None:
        raise HTTPException(404, f"档案不存在: {profile_id}")
    return row


@router.get("/profiles/{profile_id}/flat")
async def get_profile_flat(
    request: Request, profile_id: str, sensitive: bool = False
) -> dict[str, Any]:
    """扁平档案（浏览器插件规则直填引擎消费）。

    sensitive=true 时输出 schema 标注的敏感/受限字段（身份证号、家庭情况等），
    由插件弹窗单独授权后携带；默认剔除。
    """
    from autooffer_server.services.flat_profile import flatten_profile

    payload: dict[str, Any] | None = await _ctx(request).repo.get_profile(profile_id)
    if payload is None:
        raise HTTPException(404, f"档案不存在: {profile_id}")
    return flatten_profile(payload, include_sensitive=sensitive)


@router.post("/mapping", response_model=MappingOut)
async def map_fields_api(request: Request, body: MappingIn) -> dict[str, Any]:
    """AI 字段映射（M2）：页面字段标签 → 档案字段标签。

    隐私契约：请求只含标签/选项文本；LLM 提示词只含标签目录，档案值不出服务。
    """
    from autooffer_server.services.flat_profile import flatten_profile
    from autooffer_server.services.mapping import PageField, map_fields

    ctx = _ctx(request)
    payload: dict[str, Any] | None = await ctx.repo.get_profile(body.profile_id)
    if payload is None:
        raise HTTPException(404, f"档案不存在: {body.profile_id}")
    if not body.fields:
        return {"matches": []}
    flat = flatten_profile(payload, include_sensitive=False)
    try:
        llm = await ctx.build_llm("profile_parser")
    except LookupError as exc:
        raise HTTPException(503, f"映射需要可用的模型端点: {exc}") from exc
    page_fields = [
        PageField(
            label=f.label,
            section=f.section,
            kind=f.kind,
            placeholder=f.placeholder,
            options=f.options,
        )
        for f in body.fields
    ]
    matches = await map_fields(page_fields, flat, llm)
    return {"matches": [m.model_dump() for m in matches]}


@router.post("/option-match", response_model=OptionMatchOut)
async def option_match_api(request: Request, body: OptionMatchIn) -> dict[str, Any]:
    """AI 选选项（M3）：固定选项字段中为档案值挑最接近的选项。

    隐私说明：字段值会进入 LLM 提示词——与简历解析同一信任域
    （该值本就要写入目标页面），且仅逐字段发送。
    """
    from autooffer_server.services.mapping import OptionPick, match_options

    ctx = _ctx(request)
    if not body.picks:
        return {"choices": []}
    try:
        llm = await ctx.build_llm("profile_parser")
    except LookupError as exc:
        raise HTTPException(503, f"选选项需要可用的模型端点: {exc}") from exc
    picks = [OptionPick(label=p.label, options=p.options, value=p.value) for p in body.picks]
    choices = await match_options(picks, llm)
    return {"choices": [c.model_dump() for c in choices]}


@router.get("/profiles/{profile_id}/attachments/{index}")
async def download_attachment(request: Request, profile_id: str, index: int) -> Any:
    """下载档案附件字节（插件上传通道用；仅限档案登记过的路径）。"""
    import anyio
    from fastapi.responses import FileResponse

    payload: dict[str, Any] | None = await _ctx(request).repo.get_profile(profile_id)
    if payload is None:
        raise HTTPException(404, f"档案不存在: {profile_id}")
    attachments = payload.get("attachments", [])
    if index < 0 or index >= len(attachments):
        raise HTTPException(404, f"附件不存在: index={index}")
    path = Path(str(attachments[index].get("path", "")))
    if not await anyio.to_thread.run_sync(path.is_file):
        raise HTTPException(410, f"附件文件已丢失: {path.name}")
    return FileResponse(path, filename=path.name)


@router.put("/profiles/{profile_id}")
async def put_profile(request: Request, profile_id: str, body: ProfileIn) -> dict[str, Any]:
    from autooffer_core.profile.schema import Profile

    try:
        profile = Profile.model_validate({**body.payload, "id": profile_id})
    except ValueError as exc:
        raise HTTPException(422, f"档案校验失败: {exc}") from exc
    ctx = _ctx(request)
    payload: dict[str, Any] = profile.model_dump(mode="json")
    await ctx.repo.save_profile(profile_id, profile.label, payload)
    return payload


def _deactivate_resumes(attachments: list[dict[str, Any]]) -> None:
    for a in attachments:
        if a.get("kind") == "resume":
            meta = dict(a.get("meta") or {})
            meta.pop("active", None)
            a["meta"] = meta


@router.post("/profiles/{profile_id}/resumes")
async def upload_resume(
    request: Request,
    profile_id: str,
    file: Annotated[UploadFile, File()],
    mode: Annotated[str, Form()] = "replace",
    label: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """上传简历附件并设为默认（填表注入用这份）。

    mode=replace 仅替换附件；mode=parse 重新解析简历并**覆盖档案内容**
    （保留 id/label/附件列表；基本/教育/经历/技能等全部以解析结果为准）。
    """
    from autooffer_core.errors import AutoOfferError
    from autooffer_core.profile.parser import parse_resume
    from autooffer_core.profile.schema import Attachment

    if mode not in ("replace", "parse"):
        raise HTTPException(422, f"mode 必须是 replace 或 parse: {mode}")
    ctx = _ctx(request)
    payload: dict[str, Any] | None = await ctx.repo.get_profile(profile_id)
    if payload is None:
        raise HTTPException(404, f"档案不存在: {profile_id}")
    ctx.config.ensure_dirs()
    name = Path(file.filename or "resume").name
    dest = ctx.config.attachments_dir / f"{uuid.uuid4().hex[:8]}_{name}"
    dest.write_bytes(await file.read())
    try:
        attachment = Attachment.model_validate(
            {
                "kind": "resume",
                "label": label or Path(name).stem,
                "path": str(dest.resolve()),
                "meta": {
                    "size_kb": max(1, dest.stat().st_size // 1024),
                    "filename": name,
                    "active": 1,
                },
            }
        )
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"附件参数非法: {exc}") from exc

    low_conf: list[str] = []
    if mode == "parse":
        llm = await ctx.build_llm("profile_parser")
        try:
            parsed, low_conf = await parse_resume(str(dest), llm)
        except AutoOfferError as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(422, f"简历解析失败: {exc}") from exc
        new_payload: dict[str, Any] = parsed.model_dump(mode="json")
        # 覆盖内容字段；身份与附件列表保留原档案
        new_payload["id"] = profile_id
        new_payload["label"] = payload.get("label") or "解析-待确认"
        new_payload["attachments"] = payload.get("attachments", [])
        payload = new_payload

    attachments = list(payload.get("attachments", []))
    _deactivate_resumes(attachments)
    attachments.append(attachment.model_dump(mode="json"))
    payload["attachments"] = attachments
    await ctx.repo.save_profile(profile_id, str(payload.get("label") or ""), payload)
    return {
        "profile": payload,
        "low_confidence_paths": low_conf,
        "active_resume_index": len(attachments) - 1,
    }


@router.post("/profiles/{profile_id}/attachments/{index}/activate")
async def activate_attachment(
    request: Request, profile_id: str, index: int
) -> dict[str, Any]:
    """把指定简历附件设为默认（填表注入用）。"""
    ctx = _ctx(request)
    payload: dict[str, Any] | None = await ctx.repo.get_profile(profile_id)
    if payload is None:
        raise HTTPException(404, f"档案不存在: {profile_id}")
    attachments = list(payload.get("attachments", []))
    if index < 0 or index >= len(attachments):
        raise HTTPException(404, f"附件不存在: index={index}")
    if attachments[index].get("kind") != "resume":
        raise HTTPException(422, "只有简历附件可以设为默认")
    _deactivate_resumes(attachments)
    meta = dict(attachments[index].get("meta") or {})
    meta["active"] = 1
    attachments[index]["meta"] = meta
    payload["attachments"] = attachments
    await ctx.repo.save_profile(profile_id, str(payload.get("label") or ""), payload)
    return {"active_resume_index": index}


@router.delete("/profiles/{profile_id}/attachments/{index}")
async def delete_attachment(
    request: Request, profile_id: str, index: int
) -> dict[str, Any]:
    """从档案移除附件（文件保留在数据目录，不删盘）。"""
    ctx = _ctx(request)
    payload: dict[str, Any] | None = await ctx.repo.get_profile(profile_id)
    if payload is None:
        raise HTTPException(404, f"档案不存在: {profile_id}")
    attachments = list(payload.get("attachments", []))
    if index < 0 or index >= len(attachments):
        raise HTTPException(404, f"附件不存在: index={index}")
    was_active = (
        attachments[index].get("kind") == "resume"
        and (attachments[index].get("meta") or {}).get("active")
    )
    del attachments[index]
    if was_active:
        # 删的是默认简历：显式激活剩下的第一份简历（若有），保持标记落盘
        for a in attachments:
            if a.get("kind") == "resume":
                meta = dict(a.get("meta") or {})
                meta["active"] = 1
                a["meta"] = meta
                break
    payload["attachments"] = attachments
    await ctx.repo.save_profile(profile_id, str(payload.get("label") or ""), payload)
    return {"attachments": attachments}


@router.delete("/profiles/{profile_id}")
async def delete_profile(request: Request, profile_id: str) -> dict[str, bool]:
    deleted: bool = await _ctx(request).repo.delete_profile(profile_id)
    return {"deleted": deleted}


@router.post("/profiles/parse-resume")
async def parse_resume_api(
    request: Request, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """上传简历文件 → 解析为档案并入库（FR-P1）。"""
    from autooffer_core.errors import AutoOfferError
    from autooffer_core.profile.parser import parse_resume

    ctx = _ctx(request)
    llm = await ctx.build_llm("profile_parser")
    ctx.config.ensure_dirs()
    name = Path(file.filename or "resume").name
    dest = ctx.config.uploads_dir / f"{uuid.uuid4().hex[:8]}_{name}"
    dest.write_bytes(await file.read())
    try:
        profile, low_conf = await parse_resume(str(dest), llm)
    except AutoOfferError as exc:
        raise HTTPException(422, f"简历解析失败: {exc}") from exc
    payload: dict[str, Any] = profile.model_dump(mode="json")
    await ctx.repo.save_profile(profile.id, profile.label, payload)
    return {"profile": payload, "low_confidence_paths": low_conf}


@router.post("/attachments")
async def upload_attachment(
    request: Request,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()] = "other",
    label: Annotated[str, Form()] = "",
    language: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """上传附件（证件照/成绩单/证书/作品集等）并落盘，返回附件元信息。

    落盘到数据目录 attachments/，路径随档案一起存 SQLite（FR-P10：多附件管理）。
    前端拿到返回的附件信息后写入档案的 attachments 列表再保存。
    """
    from autooffer_core.profile.schema import Attachment

    ctx = _ctx(request)
    ctx.config.ensure_dirs()
    name = Path(file.filename or "attachment").name
    dest = ctx.config.attachments_dir / f"{uuid.uuid4().hex[:8]}_{name}"
    dest.write_bytes(await file.read())
    try:
        attachment = Attachment.model_validate(
            {
                "kind": kind,
                "label": label or name,
                "path": str(dest.resolve()),
                "language": language,
                "meta": {"size_kb": max(1, dest.stat().st_size // 1024), "filename": name},
            }
        )
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"附件参数非法: {exc}") from exc
    return attachment.model_dump()


# ---------- 任务 ----------


@router.post("/tasks", response_model=TaskOut)
async def create_task(request: Request, body: TaskIn) -> dict[str, Any]:
    ctx = _ctx(request)
    if await ctx.repo.get_profile(body.profile_id) is None:
        raise HTTPException(404, f"档案不存在: {body.profile_id}")
    task_id = f"task-{uuid.uuid4().hex[:10]}"
    await ctx.scheduler.submit(task_id, body.url, body.profile_id)
    row: dict[str, Any] | None = await ctx.repo.get_task(task_id)
    assert row is not None
    return row


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = await _ctx(request).repo.list_tasks(limit)
    return result


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(request: Request, task_id: str) -> dict[str, Any]:
    row: dict[str, Any] | None = await _ctx(request).repo.get_task(task_id)
    if row is None:
        raise HTTPException(404, f"任务不存在: {task_id}")
    return row


@router.post("/tasks/{task_id}/resume")
async def resume_task(request: Request, task_id: str) -> dict[str, bool]:
    """人工处理完成（登录/验证码/授权）后继续执行。"""
    resumed: bool = await _ctx(request).scheduler.resume(task_id)
    return {"resumed": resumed}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> dict[str, bool]:
    cancelled: bool = await _ctx(request).scheduler.cancel(task_id)
    return {"cancelled": cancelled}


@router.get("/tasks/{task_id}/events")
async def task_events(request: Request, task_id: str, limit: int = 500) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = await _ctx(request).repo.list_events(task_id, limit)
    return result


# ---------- 投递列表 ----------


def _app_store(ctx: Any) -> ApplicationStore:
    return ApplicationStore(ctx.config.data_dir / "applications.json")


@router.get("/applications")
async def list_applications(request: Request, status: str | None = None) -> list[dict[str, Any]]:
    store = _app_store(_ctx(request))
    records = store.list(status=status)  # type: ignore[arg-type]
    return [r.model_dump() for r in records]


@router.post("/applications")
async def report_application(
    request: Request, body: ApplicationReportIn
) -> dict[str, Any]:
    """插件填写完成后上报投递记录；同 URL 的 filled 记录更新而非重复添加。"""
    store = _app_store(_ctx(request))
    record = store.add_or_update(
        url=body.url,
        profile_id=body.profile_id,
        page_title=body.page_title,
        company=body.company,
        position=body.position,
        filled=body.fields_filled,
        failed=body.fields_failed,
        pending=body.fields_pending,
        note=body.note,
    )
    return record.model_dump()


@router.put("/applications/{record_id}")
async def update_application(
    request: Request, record_id: str, body: ApplicationStatusIn
) -> dict[str, Any]:
    store = _app_store(_ctx(request))
    record = store.update_status(record_id, body.status, note=body.note)  # type: ignore[arg-type]
    if record is None:
        raise HTTPException(404, f"投递记录不存在: {record_id}")
    payload: dict[str, Any] = record.model_dump()
    return payload


@router.delete("/applications/{record_id}")
async def delete_application(request: Request, record_id: str) -> dict[str, bool]:
    store = _app_store(_ctx(request))
    return {"deleted": store.remove(record_id)}


# ---------- 插件日志汇聚（与 exe 日志同写一个 app.log） ----------

_LOG_LEVELS = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}


@router.post("/logs")
async def receive_extension_logs(request: Request, body: LogsIn) -> dict[str, int]:
    """接收插件运行日志条目，写入本地 app.log（logger=extension）。

    插件与 exe 的时间线在同一文件里按时间排序，一次填写可端到端追溯。
    """
    logger = logging.getLogger("extension")
    written = 0
    for e in body.entries[:100]:
        if not isinstance(e, dict):
            continue
        msg = str(e.get("msg", ""))[:200]
        if not msg:
            continue
        extra = " ".join(
            f"{k}={str(v)[:120]}"
            for k, v in e.items()
            if k not in ("ts", "level", "msg") and v is not None
        )
        logger.log(
            _LOG_LEVELS.get(str(e.get("level", "info")).lower(), 20),
            "%s%s",
            msg,
            f" {extra}" if extra else "",
        )
        written += 1
    return {"written": written}
