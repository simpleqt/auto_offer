"""生成测试用文字版简历 PDF（供 demo-4 上传流程与解析测试使用）。

内容为虚构数据。运行：python scripts/make_test_resume_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "tests" / "demo_forms" / "assets"
SOURCE = OUT / "sample_resume.txt"


def main() -> None:
    # 内置 CJK 字体，无需外部字体文件
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    OUT.mkdir(parents=True, exist_ok=True)
    lines = SOURCE.read_text(encoding="utf-8").splitlines()

    target = OUT / "sample_resume.pdf"
    c = canvas.Canvas(str(target), pagesize=A4)
    width, height = A4
    y = height - 50
    for line in lines:
        if y < 50:
            c.showPage()
            y = height - 50
        c.setFont("STSong-Light", 9)
        c.drawString(45, y, line[:90])
        y -= 14
    c.save()
    print(f"已生成: {target} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
