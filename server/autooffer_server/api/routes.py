"""REST 路由实现（docs/03 §5.1）。

依赖通过 app.state.ctx 注入（create_app 装配），便于测试替换执行体与密钥库。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from autooffer_core import __version__
from autooffer_core.applications import ApplicationStore
from autooffer_server.api.schemas import (
    ApplicationStatusIn,
    EndpointIn,
    EndpointOut,
    ProfileIn,
    ProfileSummary,
    RoutingIn,
    TaskIn,
    TaskOut,
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
    }


@router.get("/system/version")
async def version() -> dict[str, str]:
    return {"version": __version__}


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
    return [
        {
            "id": r["id"],
            "label": r["label"],
            "updated_at": r["updated_at"],
            "name": r["payload"].get("basic", {}).get("name", ""),
            "attachments": len(r["payload"].get("attachments", [])),
        }
        for r in rows
    ]


@router.get("/profiles/{profile_id}")
async def get_profile(request: Request, profile_id: str) -> dict[str, Any]:
    row: dict[str, Any] | None = await _ctx(request).repo.get_profile(profile_id)
    if row is None:
        raise HTTPException(404, f"档案不存在: {profile_id}")
    return row


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
