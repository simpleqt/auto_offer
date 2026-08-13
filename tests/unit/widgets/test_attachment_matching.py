"""附件格式匹配单元测试（FR-A13：按站点 accept 选择合适附件）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from autooffer_core.actions.executor import ActionExecutor, _ext_allowed
from autooffer_core.actions.models import Action
from autooffer_core.errors import ActionError
from autooffer_core.perception.models import PageObservation, UIElement
from autooffer_core.profile.schema import AttachmentSpec
from autooffer_core.testing import FakeDriver
from autooffer_core.widgets.upload import UploadHandler

# FakeDriver 不会产生"上传成功"信号，用短超时避免测试等待真实的 30s
FAST_UPLOAD = UploadHandler(timeout_s=0.2, poll_s=0.05)


def file_el(accept: str | None, *, index: int = 1) -> UIElement:
    return UIElement(
        index=index, tag="input", role="file", label="上传简历",
        selector="#f", accept=accept,
    )


def make_observation(el: UIElement) -> PageObservation:
    return PageObservation(url="u", title="t", elements=[el])


# ---------- 扩展名判定 ----------


def test_ext_allowed_basic() -> None:
    assert _ext_allowed("a/b/resume.pdf", ["pdf", "docx"]) is True
    assert _ext_allowed("a/b/resume.txt", ["pdf", "docx"]) is False


def test_ext_allowed_no_restriction() -> None:
    assert _ext_allowed("resume.txt", []) is True


def test_ext_allowed_jpg_jpeg_equivalence() -> None:
    assert _ext_allowed("photo.jpg", ["jpeg"]) is True
    assert _ext_allowed("photo.jpeg", ["jpg"]) is True


def test_ext_allowed_case_and_dot_insensitive() -> None:
    assert _ext_allowed("Resume.PDF", [".pdf"]) is True


# ---------- 执行器选附件 ----------


@pytest.mark.asyncio
async def test_upload_picks_matching_format_when_label_mismatches(tmp_path: Path) -> None:
    """标签命中的是 txt、站点只要 pdf → 自动改选档案里的 pdf 附件。"""
    txt = tmp_path / "resume.txt"
    txt.write_text("简历", encoding="utf-8")
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")

    driver = FakeDriver()
    ex = ActionExecutor(
        driver,
        attachments={"中文简历": str(txt), "PDF简历": str(pdf)},
        humanize=False,
        upload=FAST_UPLOAD,
    )
    el = file_el(".pdf,.docx")
    action = Action(
        type="upload_file", element_index=1, attachment_label="中文简历", reason="上传简历"
    )
    # FakeDriver 无成功信号，确认阶段会失败；关键是验证选中的文件格式正确
    with pytest.raises(ActionError):
        await ex.execute(action, make_observation(el))
    uploaded = [c for c in driver.calls if c[0] == "upload_file"]
    assert uploaded
    assert str(pdf) == uploaded[0][1][1]  # 实际上传的是格式匹配的 pdf


@pytest.mark.asyncio
async def test_upload_raises_actionable_error_when_no_format_matches(tmp_path: Path) -> None:
    txt = tmp_path / "resume.txt"
    txt.write_text("简历", encoding="utf-8")
    driver = FakeDriver()
    ex = ActionExecutor(
        driver, attachments={"中文简历": str(txt)}, humanize=False, upload=FAST_UPLOAD
    )
    action = Action(
        type="upload_file", element_index=1, attachment_label="中文简历", reason="上传"
    )
    with pytest.raises(ActionError) as exc:
        await ex.execute(action, make_observation(file_el(".pdf,.docx")))
    msg = str(exc.value)
    assert "pdf" in msg
    assert "补充" in msg  # 提示可操作


@pytest.mark.asyncio
async def test_upload_unknown_label_lists_available(tmp_path: Path) -> None:
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF")
    ex = ActionExecutor(
        FakeDriver(), attachments={"中文简历": str(pdf)}, humanize=False, upload=FAST_UPLOAD
    )
    action = Action(
        type="upload_file", element_index=1, attachment_label="英文简历", reason="上传"
    )
    with pytest.raises(ActionError) as exc:
        await ex.execute(action, make_observation(file_el(None)))
    assert "中文简历" in str(exc.value)  # 错误信息列出可用标签


def test_spec_parsed_from_accept_used_for_matching() -> None:
    """站点 accept 解析出的格式列表参与匹配判定。"""
    from autooffer_core.widgets.upload import parse_attachment_spec

    spec: AttachmentSpec = parse_attachment_spec(".pdf,.docx", "")
    assert _ext_allowed("x.docx", spec.formats) is True
    assert _ext_allowed("x.png", spec.formats) is False
