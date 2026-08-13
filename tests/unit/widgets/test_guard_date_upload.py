"""敏感门禁、日期格式、附件规格与图片压缩单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from autooffer_core.actions.guard import SensitiveActionGuard
from autooffer_core.actions.models import Action
from autooffer_core.errors import ActionError
from autooffer_core.perception.models import UIElement
from autooffer_core.profile.schema import AttachmentSpec, DateYM
from autooffer_core.widgets.datepicker import format_date, parse_placeholder_format
from autooffer_core.widgets.upload import compress_image_to_spec, parse_attachment_spec


def make_el(label: str = "", *, index: int = 1, value: str = "") -> UIElement:
    return UIElement(
        index=index, tag="button", role="button", label=label, value=value, selector="#b"
    )


# ---------- 敏感动作门禁（FR-A11） ----------


@pytest.mark.parametrize(
    "label",
    ["提交申请", "确认投递", "立即投递", "Submit Application", "删除这段经历", "确认提交"],
)
def test_guard_blocks_sensitive_click(label: str) -> None:
    guard = SensitiveActionGuard()
    action = Action(type="click", element_index=1, reason="点击")
    assert guard.check(action, make_el(label)) is not None


@pytest.mark.parametrize(
    "label", ["下一步", "上一步", "保存草稿", "添加一段实习经历", "同意并继续"]
)
def test_guard_allows_normal_click(label: str) -> None:
    guard = SensitiveActionGuard()
    action = Action(type="click", element_index=1, reason="点击")
    assert guard.check(action, make_el(label)) is None


def test_guard_only_intercepts_click() -> None:
    """填写类动作即便元素文本敏感也不拦截（只拦截点击）。"""
    guard = SensitiveActionGuard()
    action = Action(type="input_text", element_index=1, value="x", reason="填写")
    assert guard.check(action, make_el("提交说明")) is None


def test_guard_ignores_whitespace_and_case() -> None:
    guard = SensitiveActionGuard()
    action = Action(type="click", element_index=1, reason="点击")
    assert guard.check(action, make_el(" S U B M I T ")) == "submit"


def test_guard_custom_word_list() -> None:
    guard = SensitiveActionGuard(["解约"])
    action = Action(type="click", element_index=1, reason="点击")
    assert guard.check(action, make_el("解约确认")) == "解约"
    assert guard.check(action, make_el("提交")) is None  # 自定义词表替换默认


def test_guard_no_element_passes() -> None:
    guard = SensitiveActionGuard()
    assert guard.check(Action(type="click", reason="无元素"), None) is None


# ---------- 日期格式 ----------


@pytest.mark.parametrize(
    ("placeholder", "expected"),
    [
        ("yyyy-MM-dd", "yyyy-mm-dd"),
        ("YYYY/MM/DD", "yyyy/mm/dd"),
        ("yyyy-MM", "yyyy-mm"),
        ("yyyy", "yyyy"),
        ("请选择日期", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_placeholder_format(placeholder: str | None, expected: str | None) -> None:
    assert parse_placeholder_format(placeholder) == expected


def test_format_date_full_and_partial() -> None:
    assert format_date(DateYM(year=2024, month=7, day=5), "yyyy-mm-dd") == "2024-07-05"
    assert format_date(DateYM(year=2024, month=7), "yyyy-mm-dd") == "2024-07"
    assert format_date(DateYM(year=2024), "yyyy-mm-dd") == "2024"
    assert format_date(DateYM(year=2024, month=7), "yyyy/mm") == "2024/07"


def test_format_date_pads_single_digit_month() -> None:
    """站点普遍要求两位月份：7 → 07（避免 2023-7 被拒）。"""
    assert format_date(DateYM(year=2023, month=7), "yyyy-mm") == "2023-07"


# ---------- 附件规格解析（FR-A13） ----------


def test_parse_spec_from_accept() -> None:
    spec = parse_attachment_spec(".pdf,.docx", "")
    assert set(spec.formats) >= {"pdf", "docx"}


def test_parse_spec_from_mime_accept() -> None:
    spec = parse_attachment_spec("image/jpeg,image/png", "")
    assert "jpeg" in spec.formats or "jpg" in spec.formats
    assert "png" in spec.formats


def test_parse_spec_size_kb_and_mb() -> None:
    assert parse_attachment_spec(None, "大小不超过 200KB").max_size_kb == 200
    assert parse_attachment_spec(None, "文件不超过 5MB").max_size_kb == 5 * 1024


def test_parse_spec_pixel_size() -> None:
    spec = parse_attachment_spec(None, "要求 295x413 像素以内")
    assert spec.pixel_size == "295x413"
    assert parse_attachment_spec(None, "295×413").pixel_size == "295x413"


def test_parse_spec_from_hint_text_formats() -> None:
    spec = parse_attachment_spec(None, "支持 PDF/DOCX 格式，≤5MB")
    assert "pdf" in spec.formats
    assert "docx" in spec.formats


# ---------- 图片压缩（FR-A16） ----------


def make_image(path: Path, size: tuple[int, int]) -> str:
    Image.new("RGB", size, (200, 210, 255)).save(path, "JPEG", quality=95)
    return str(path)


def test_compress_shrinks_to_pixel_spec(tmp_path: Path) -> None:
    src = make_image(tmp_path / "photo.jpg", (900, 1260))
    out = compress_image_to_spec(src, AttachmentSpec(pixel_size="295x413"), str(tmp_path))
    with Image.open(out) as im:
        assert im.width <= 295
        assert im.height <= 413


def test_compress_respects_size_limit(tmp_path: Path) -> None:
    src = make_image(tmp_path / "big.jpg", (2000, 2000))
    out = compress_image_to_spec(src, AttachmentSpec(max_size_kb=60), str(tmp_path))
    assert Path(out).stat().st_size <= 60 * 1024


def test_compress_skips_when_within_spec(tmp_path: Path) -> None:
    """已达标图片原样返回，不重新编码。"""
    src = make_image(tmp_path / "ok.jpg", (200, 300))
    out = compress_image_to_spec(src, AttachmentSpec(max_size_kb=5000), str(tmp_path))
    assert out == src


def test_compress_non_image_within_limit_passthrough(tmp_path: Path) -> None:
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    assert compress_image_to_spec(str(pdf), AttachmentSpec(max_size_kb=100)) == str(pdf)


def test_compress_non_image_oversize_raises(tmp_path: Path) -> None:
    """非图片超限无法压缩：抛错由上层转人工（不静默上传超限文件）。"""
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * 2048)
    with pytest.raises(ActionError):
        compress_image_to_spec(str(pdf), AttachmentSpec(max_size_kb=1))


def test_compress_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ActionError):
        compress_image_to_spec(str(tmp_path / "nope.jpg"), AttachmentSpec())
