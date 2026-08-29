"""把档案里的 .md 简历转换为 PDF 附件并更新档案（.md 被招聘站拒收）。

用法: python scripts/md_resume_to_pdf.py [profile_id]
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
from pathlib import Path
from uuid import uuid4

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

API = "http://127.0.0.1:8765/api/v1"
PROFILE_ID = sys.argv[1] if len(sys.argv) > 1 else "profile-de2d254d"


def md_to_pdf(md_text: str, out: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    c = canvas.Canvas(str(out), pagesize=A4)
    width, height = A4
    y = height - 50
    for line in md_text.splitlines():
        if y < 50:
            c.showPage()
            y = height - 50
        stripped = line.strip()
        size = 12 if stripped.startswith("#") else 9
        c.setFont("STSong-Light", size)
        c.drawString(45, y, stripped.lstrip("# ")[:92] or " ")
        y -= 15 if size > 10 else 13
    c.save()


def main() -> None:
    with urllib.request.urlopen(f"{API}/profiles/{PROFILE_ID}", timeout=15) as resp:  # noqa: S310
        row = json.load(resp)
    payload = row.get("payload", row)
    attachments = payload.get("attachments", [])
    md_att = next(
        (a for a in attachments if str(a.get("path", "")).lower().endswith((".md", ".markdown"))),
        None,
    )
    if not md_att:
        print("档案中没有 .md 附件，无需转换")
        return

    src = Path(str(md_att["path"]))
    out = Path(tempfile.gettempdir()) / f"{uuid4().hex[:8]}_个人信息.pdf"
    md_to_pdf(src.read_text(encoding="utf-8"), out)
    print(f"PDF 已生成: {out} ({out.stat().st_size // 1024} KB)")

    # multipart 上传到服务端附件目录
    boundary = "----autoofferboundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="个人信息.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + out.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(  # noqa: S310
        f"{API}/attachments", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        att = json.load(resp)
    print("服务端返回:", json.dumps(att, ensure_ascii=False))

    # 用 PDF 替换档案中的 .md 条目（原 .md 文件保留在磁盘）
    new_att = {
        "kind": md_att.get("kind", "resume"),
        "label": md_att.get("label", "中文简历"),
        "path": att["path"],
        "language": md_att.get("language", "zh"),
        "meta": md_att.get("meta", {}),
    }
    payload["attachments"] = [new_att]
    req = urllib.request.Request(  # noqa: S310
        f"{API}/profiles/{PROFILE_ID}",
        data=json.dumps({"payload": payload}, ensure_ascii=False).encode(),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        print("档案已更新:", resp.status)
    out.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
