"""插件规则直填引擎集成测试（M1）。

真实 Chromium 加载本地 fixture 基准页，用 add_script_tag 注入
extension/src/content.js，直接调用 window.__AUTOOFFER_CONTENT__.autofill(flat)。
与内容脚本在真实扩展中的执行路径一致，但不依赖 chrome.runtime。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest_asyncio
from playwright.async_api import Page, async_playwright

HERE = Path(__file__).resolve().parent
CONTENT_JS = HERE.parents[2] / "extension" / "src" / "content.js"
FIXTURES = HERE.parent / "fixtures" / "extension"


def fixture_url(name: str) -> str:
    return (FIXTURES / name).as_uri()


@pytest_asyncio.fixture
async def page() -> AsyncIterator[Page]:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        pg = await context.new_page()
        yield pg
        await browser.close()


async def autofill(
    page: Page, flat: dict[str, Any], options: dict[str, Any] | None = None
) -> dict[str, Any]:
    await page.add_script_tag(path=str(CONTENT_JS))
    return await page.evaluate(
        "(args) => window.__AUTOOFFER_CONTENT__.autofill(args.p, args.o)",
        {"p": flat, "o": options or {}},
    )


ZHIYE_PROFILE: dict[str, Any] = {
    "schema": 1,
    "profile": {"id": "demo", "label": "示例档案"},
    "sections": [
        {
            "key": "basic",
            "title": "基本信息",
            "kind": "simple",
            "values": {
                "姓名": "张三",
                "性别": "男",
                "出生日期": "2002-05-12",
                "手机号码": "13800001111",
                "电子邮箱": "zhangsan@example.com",
                "政治面貌": "共青团员",
                "现居住城市": "成都市",
            },
        },
        {
            "key": "education",
            "title": "教育经历",
            "kind": "repeat",
            "items": [{"学校": "示例大学", "专业": "计算机科学与技术", "学历": "本科"}],
        },
        {
            "key": "other",
            "title": "其他信息",
            "kind": "simple",
            "values": {"自我评价": "做事踏实。"},
        },
    ],
}


async def test_zhiye_like_basic_fill(page: Page) -> None:
    """Ant 风格表单：文本/单选/原生下拉/自定义下拉(含搜索)/别名匹配/跳过规则。"""
    await page.goto(fixture_url("zhiye_like.html"))
    report = await autofill(page, ZHIYE_PROFILE)

    assert report["counts"]["failed"] == 0, report["failed"]
    assert report["site"]["id"] == "ant-design"
    # 文本与原生控件
    assert await page.input_value("#name") == "张三"
    assert await page.is_checked('input[name="gender"][value="1"]')  # 男
    assert await page.input_value("#birth") == "2002-05-12"
    assert await page.input_value("#phone") == "13800001111"
    assert await page.input_value("#email") == "zhangsan@example.com"
    sel = await page.eval_on_selector("#political", "el => el.value")
    text = await page.eval_on_selector(
        f"#political option[value='{sel}']", "el => el.textContent.trim()"
    )
    assert text == "共青团员"
    assert await page.input_value("#school") == "示例大学"  # 别名：学校 → 毕业院校
    assert await page.input_value("#self-eval") == "做事踏实。"
    # 自定义下拉（portal 面板选项）
    edu = await page.eval_on_selector(
        "#edu-select .ant-select-selection-item", "el => el.textContent.trim()"
    )
    assert edu == "本科"
    city = await page.eval_on_selector(
        "#city-select .ant-select-selection-item", "el => el.textContent.trim()"
    )
    assert city == "成都市"
    # 未匹配字段不得误填；附件必须跳过
    assert await page.input_value("#weight") == ""
    skipped = {s["field"]: s["reason"] for s in report["skipped"]}
    assert any("附件需手动上传" in r for r in skipped.values())
    assert report["counts"]["filled"] == 10


async def test_moka_like_element_fill(page: Page) -> None:
    """Element 风格表单：label-for 结构 + el-select 下拉 + 复选框。"""
    await page.goto(fixture_url("moka_like.html"))
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例档案"},
        "sections": [
            {
                "key": "basic",
                "title": "基本信息",
                "kind": "simple",
                "values": {
                    "姓名": "李四",
                    "手机号码": "13900002222",  # 页面标签是「电话」，靠别名匹配
                    "电子邮箱": "lisi@example.com",
                },
            },
            {
                "key": "education",
                "title": "教育经历",
                "kind": "repeat",
                "items": [{"学历": "硕士"}],
            },
            {
                "key": "intention",
                "title": "求职意向",
                "kind": "simple",
                "values": {"接受工作地调剂": "是"},  # 页面标签「接受调剂」
            },
        ],
    }
    report = await autofill(page, flat)

    assert report["counts"]["failed"] == 0, report["failed"]
    assert report["site"]["id"] == "element-ui"
    assert await page.input_value("#m-name") == "李四"
    assert await page.input_value("#m-phone") == "13900002222"
    assert await page.input_value("#m-email") == "lisi@example.com"
    assert await page.is_checked("#m-agree")
    edu_value = await page.eval_on_selector("#m-edu input", "el => el.value")
    assert edu_value == "硕士"


async def test_ai_mapping_pass_fills_leftover(page: Page) -> None:
    """AI 映射通道：别名表没有的问法（应聘方向）经 mapping 直通补填。"""
    await page.goto(fixture_url("moka_like.html"))
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例档案"},
        "sections": [
            {
                "key": "intention",
                "title": "求职意向",
                "kind": "simple",
                "values": {"意向岗位": "LLM 应用开发工程师"},
            }
        ],
    }
    # 第一段：规则分不足（「应聘方向」与「意向岗位」无词元重合）→ 跳过并上报
    first = await autofill(page, flat)
    assert await page.input_value("#m-direction") == ""
    assert any(u["label"] == "应聘方向" for u in first["unmatched"])

    # 第二段：带 AI 映射补填
    second = await autofill(page, flat, {"mapping": {"应聘方向": "意向岗位"}})
    assert await page.input_value("#m-direction") == "LLM 应用开发工程师"
    assert any(f["label"] == "应聘方向" for f in second["filled"])


async def test_repeat_blocks_add_and_fill(page: Page) -> None:
    """教育经历多条目：自动点「添加教育经历」补块，第 N 块配第 N 条档案。"""
    await page.goto(fixture_url("repeat_upload.html"))
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {
                "key": "education",
                "title": "教育经历",
                "kind": "repeat",
                "items": [
                    {"学校": "示例大学", "专业": "大数据技术与工程"},
                    {"学校": "示例理工大学", "专业": "计算机科学与技术"},
                ],
            }
        ],
    }
    report = await autofill(page, flat)
    assert report["counts"]["failed"] == 0, report["failed"]
    schools = await page.eval_on_selector_all(
        ".edu-school", "els => els.map(e => e.value)"
    )
    assert schools == ["示例大学", "示例理工大学"]
    majors = await page.eval_on_selector_all(".edu-major", "els => els.map(e => e.value)")
    assert majors == ["大数据技术与工程", "计算机科学与技术"]


async def test_attachment_upload(page: Page) -> None:
    """附件通道：File 构造 + DataTransfer 注入触发 change。"""
    await page.goto(fixture_url("repeat_upload.html"))
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [],
    }
    import base64

    b64 = base64.b64encode("name: 张三\nmajor: 大数据\n".encode()).decode("ascii")
    report = await autofill(
        page,
        flat,
        {
            "attachments": [
                {
                    "kind": "resume",
                    "label": "中文简历",
                    "filename": "resume_cn.md",
                    "language": "zh",
                    "b64": b64,
                }
            ]
        },
    )
    status = await page.text_content("#upload-status")
    assert "resume_cn.md" in (status or "")
    rows = [r for r in report["filled"] if r.get("via") == "附件"]
    assert rows and rows[0]["value"] == "resume_cn.md"


async def test_option_override_fills_custom_select(page: Page) -> None:
    """AI 选选项覆盖：选项值不匹配时用 override 替换后点中。"""
    await page.goto(fixture_url("zhiye_like.html"))
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {
                "key": "education",
                "title": "教育经历",
                "kind": "repeat",
                "items": [{"学历": "LLM 应用开发相关"}],  # 选项里没有该文本
            }
        ],
    }
    first = await autofill(page, flat)
    assert first["counts"]["failed"] >= 1  # 选项未匹配
    row = next(r for r in first["failed"] if r["label"] == "最高学历")
    assert "硕士" in row.get("options", [])  # 失败时收割到选项

    await autofill(page, flat, {"overrides": {"最高学历": "博士"}})
    edu = await page.eval_on_selector(
        "#edu-select .ant-select-selection-item", "el => el.textContent.trim()"
    )
    assert edu == "博士"


async def test_hard_vetoes(page: Page) -> None:
    """硬否决：家庭域条目禁入普通字段；邮箱形状的值禁入电话类标签。"""
    await page.goto(fixture_url("moka_like.html"))

    # 1) 家庭域约束：家庭情况条目的电话不得写入「电话」字段
    family: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例档案"},
        "sections": [
            {
                "key": "family",
                "title": "家庭情况",
                "kind": "simple",
                "values": {"电话": "13700003333"},
            }
        ],
    }
    report = await autofill(page, family)
    assert await page.input_value("#m-phone") == ""
    assert report["counts"]["filled"] == 0

    # 2) 值形冲突：邮箱形状的值遇到电话类标签直接否决
    shape: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例档案"},
        "sections": [
            {
                "key": "other",
                "title": "其他信息",
                "kind": "simple",
                "values": {"电子邮箱": "someone@example.com"},
            }
        ],
    }
    report = await autofill(page, shape)
    assert await page.input_value("#m-phone") == ""  # 值形冲突否决
    # 邮箱形状的值写入邮箱字段是正确行为
    assert await page.input_value("#m-email") == "someone@example.com"
    assert all(r["label"] != "电话" for r in report["filled"])
