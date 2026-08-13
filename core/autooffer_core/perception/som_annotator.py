"""SoM（Set-of-Mark）截图标注（docs/03 §2.2）。

在整页截图上为每个可见元素绘制编号角标，颜色按 role 区分；
输出图片长边压缩到 1288px 以内，控制视觉模型 token 消耗。
"""

from __future__ import annotations

import io

import structlog
from PIL import Image, ImageDraw, ImageFont

from autooffer_core.perception.models import UIElement

logger = structlog.get_logger(__name__)

MAX_LONG_EDGE = 1288
_BADGE_MIN = 16

_ROLE_COLORS: dict[str, tuple[int, int, int]] = {
    "input": (0, 102, 204),
    "textarea": (0, 102, 204),
    "richtext": (0, 102, 204),
    "select": (0, 153, 102),
    "combobox": (0, 153, 102),
    "custom": (0, 153, 102),
    "date": (153, 102, 0),
    "file": (153, 51, 153),
    "radio": (204, 102, 0),
    "checkbox": (204, 102, 0),
    "button": (204, 0, 0),
    "link": (102, 102, 102),
}
_DEFAULT_COLOR = (51, 51, 51)


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


class SomAnnotator:
    """把 UIElement 列表标注到截图上。"""

    def __init__(self, *, max_long_edge: int = MAX_LONG_EDGE) -> None:
        self._max_long_edge = max_long_edge

    def annotate(self, screenshot: bytes, elements: list[UIElement]) -> bytes:
        """返回标注后的 PNG 字节。元素 bbox 须与截图像素坐标同系（整页截图）。"""
        image = Image.open(io.BytesIO(screenshot)).convert("RGB")
        draw = ImageDraw.Draw(image)
        marked = 0
        for el in elements:
            if not el.visible:
                continue
            x, y, w, h = el.bbox
            if w <= 0 or h <= 0:
                continue
            if not self._in_bounds(image, x, y):
                continue
            color = _ROLE_COLORS.get(el.role, _DEFAULT_COLOR)
            draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
            self._draw_badge(draw, x, y, el.index, color)
            marked += 1
        image = self._shrink(image)
        out = io.BytesIO()
        image.save(out, format="PNG")
        logger.info(
            "som_annotated",
            marked=marked,
            total=len(elements),
            size=f"{image.width}x{image.height}",
        )
        return out.getvalue()

    def _in_bounds(self, image: Image.Image, x: int, y: int) -> bool:
        return 0 <= x < image.width and 0 <= y < image.height

    def _draw_badge(
        self, draw: ImageDraw.ImageDraw, x: int, y: int, index: int, color: tuple[int, int, int]
    ) -> None:
        text = str(index)
        font = _load_font(max(_BADGE_MIN - 4, 10))
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        pad = 2
        bw = max(tw + pad * 2, _BADGE_MIN)
        bh = max(th + pad * 2, _BADGE_MIN)
        bx, by = x, max(y - bh, 0)  # 角标贴元素左上角，避免遮挡控件本体
        draw.rectangle([bx, by, bx + bw, by + bh], fill=color)
        pos = (bx + (bw - tw) / 2 - tb[0], by + (bh - th) / 2 - tb[1])
        draw.text(pos, text, fill=(255, 255, 255), font=font)

    def _shrink(self, image: Image.Image) -> Image.Image:
        long_edge = max(image.width, image.height)
        if long_edge <= self._max_long_edge:
            return image
        scale = self._max_long_edge / long_edge
        new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        return image.resize(new_size, Image.Resampling.LANCZOS)
