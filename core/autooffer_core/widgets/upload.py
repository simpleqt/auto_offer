"""附件上传处理器（docs/03 §3.4，FR-A13/A16、FR-P10）。

链路：解析 AttachmentSpec（accept + 周边提示文本）→ 图片超限时 Pillow 等比压缩
→ Driver.upload_file（三种入口形态在驱动层闭合：input / file_chooser / dropzone）
→ 等待成功信号（文件名回显 / "上传成功"提示，默认 30s 超时）。

本包只接收文件路径与目标 spec，档案数据由上层注入。
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

import structlog
from PIL import Image
from pydantic import BaseModel

from autooffer_core.errors import ActionError
from autooffer_core.perception.models import UIElement
from autooffer_core.profile.schema import AttachmentSpec
from autooffer_core.widgets.base import ExecContext, FillResult

log = structlog.get_logger(__name__)

_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
_SUCCESS_HINTS = ("上传成功", "已上传", "success", "uploaded", "完成")

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kb|mb|k|m)\b", re.IGNORECASE)
_PIXEL_RE = re.compile(r"(\d{2,5})\s*[x×*]\s*(\d{2,5})")
_FORMAT_RE = re.compile(
    r"\b(pdf|docx?|xlsx?|pptx?|jpe?g|png|gif|webp|bmp|zip|rar|txt)\b",
    re.IGNORECASE,
)


class UploadTask(BaseModel):
    """上传任务：本机文件路径 + 站点规格要求（档案匹配在上层完成）。"""

    path: str
    spec: AttachmentSpec = AttachmentSpec()


def parse_attachment_spec(accept: str | None, hint_text: str = "") -> AttachmentSpec:
    """从 accept 属性与周边提示文本解析站点附件要求。"""
    formats: list[str] = []
    if accept:
        for part in accept.split(","):
            part = part.strip().lower().lstrip(".")
            if part and "/" not in part:
                formats.append(part)
            elif "/" in part:  # image/* 之类
                main, _, sub = part.partition("/")
                if sub != "*":
                    formats.append(sub)
    for m in _FORMAT_RE.finditer(hint_text):
        fmt = m.group(1).lower()
        if fmt == "jpeg":
            fmt = "jpg"
        if fmt not in formats:
            formats.append(fmt)

    max_size_kb: int | None = None
    size_m = _SIZE_RE.search(hint_text)
    if size_m is not None:
        value = float(size_m.group(1))
        unit = size_m.group(2).lower()
        max_size_kb = int(value * 1024) if unit in ("mb", "m") else int(value)

    pixel_size: str | None = None
    p = _PIXEL_RE.search(hint_text)
    if p is not None:
        pixel_size = f"{p.group(1)}x{p.group(2)}"

    return AttachmentSpec(formats=formats, max_size_kb=max_size_kb, pixel_size=pixel_size)


def _parse_pixel(pixel_size: str) -> tuple[int, int]:
    m = _PIXEL_RE.search(pixel_size)
    if m is None:
        raise ActionError(f"像素规格无法解析: {pixel_size}")
    return int(m.group(1)), int(m.group(2))


def compress_image_to_spec(path: str, spec: AttachmentSpec, out_dir: str | None = None) -> str:
    """图片按 spec 等比压缩（FR-A16）：先收像素尺寸，再压文件大小。

    返回（可能新生成的）文件路径；非图片或已达标时原样返回。
    无法达标（非图片超限等）抛 ActionError，由上层转 ask_user。
    """
    p = Path(path)
    if not p.is_file():
        raise ActionError(f"附件不存在: {path}")
    ext = p.suffix.lower().lstrip(".")
    if ext not in _IMAGE_EXTS:
        if spec.max_size_kb is not None and p.stat().st_size > spec.max_size_kb * 1024:
            raise ActionError(f"非图片附件超过大小限制且无法自动压缩: {path}")
        return path

    need_pixel = spec.pixel_size is not None
    need_size = spec.max_size_kb is not None and p.stat().st_size > spec.max_size_kb * 1024
    if not need_pixel and not need_size:
        return path

    out = Path(out_dir) if out_dir else p.parent
    out.mkdir(parents=True, exist_ok=True)
    target_path = str(out / f"{p.stem}_compressed.jpg")

    def _work() -> None:
        with Image.open(p) as src:
            rgb = src.convert("RGB")
        if need_pixel:
            max_w, max_h = _parse_pixel(spec.pixel_size or "")
            rgb.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        quality = 90
        while True:
            rgb.save(target_path, "JPEG", quality=quality)
            if spec.max_size_kb is None:
                break
            if Path(target_path).stat().st_size <= spec.max_size_kb * 1024:
                break
            if quality > 50:
                quality -= 10
            elif rgb.width > 200 and rgb.height > 200:
                new_size = (rgb.width * 3 // 4, rgb.height * 3 // 4)
                rgb = rgb.resize(new_size, Image.Resampling.LANCZOS)
            else:
                raise ActionError(
                    f"图片压缩后仍超过 {spec.max_size_kb}KB: {path}"
                )

    _work()
    return target_path


class UploadHandler:
    """附件上传（三种入口由驱动层闭合，本处理器负责规格与结果校验）。"""

    def __init__(self, *, timeout_s: float = 30.0, poll_s: float = 0.5) -> None:
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def match(self, el: UIElement) -> bool:
        return el.role == "file"

    async def fill(self, el: UIElement, target: Any, ctx: ExecContext) -> FillResult:
        if isinstance(target, str):
            task = UploadTask(path=target, spec=parse_attachment_spec(el.accept, el.label))
        elif isinstance(target, UploadTask):
            task = target
        else:
            raise ActionError(f"上传目标必须为路径或 UploadTask: {target!r}")

        has_spec = task.spec.formats or task.spec.max_size_kb or task.spec.pixel_size
        spec = task.spec if has_spec else parse_attachment_spec(el.accept, el.label)
        path = await asyncio.to_thread(compress_image_to_spec, task.path, spec)
        file_name = Path(path).name

        await ctx.driver.upload_file(el, path)
        log.info("upload.sent", label=el.label, file=file_name)

        if await self._await_success(ctx, file_name):
            return FillResult(ok=True, strategy="upload", detail=file_name)
        return FillResult(
            ok=False,
            strategy="confirm_timeout",
            detail=f"上传后 {self.timeout_s}s 内未出现成功信号: {file_name}",
        )

    async def _await_success(self, ctx: ExecContext, file_name: str) -> bool:
        """轮询感知，等待文件名回显或"上传成功"类提示。"""
        stem = Path(file_name).stem.lower()
        deadline = time.monotonic() + self.timeout_s
        while True:
            obs = await ctx.driver.observe(with_screenshot=False)
            for e in obs.elements:
                text = f"{e.label} {e.value}".lower()
                if stem and stem in text:
                    return True
                if any(h in text for h in _SUCCESS_HINTS):
                    return True
            if time.monotonic() >= deadline:
                return False
            await ctx.driver.wait(self.poll_s)
