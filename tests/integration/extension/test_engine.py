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
            "items": [
                {
                    "学校": "示例大学",
                    "学院": "示例信息学院",
                    "专业": "计算机科学与技术",
                    "学历": "本科",
                }
            ],
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
    assert await page.input_value("#college") == "示例信息学院"  # 别名：学院 → 院系
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
    assert report["counts"]["filled"] == 11


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


async def test_aui_style_components_fill_by_behavior(page: Page) -> None:
    """自研 AUI 风格组件：类名不在引擎名单里，靠行为/内容指纹驱动。

    覆盖：popover 日历(内容指纹识别+prev-year/prev-month 箭头)、
    select-dropdown 弹层选项、国籍别名(证件签发国家/地区→中国大陆)、
    组合行标签继承(联系电话=区号下拉+无标签号码输入框)。
    """
    await page.goto(fixture_url("aui_like.html"))
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {
                "key": "basic",
                "title": "基本信息",
                "kind": "simple",
                "values": {
                    "姓名": "张三",
                    "性别": "男",
                    "国籍": "中国",
                    "出生日期": "2001-03-18",
                    "手机号码": "13800001111",
                },
            }
        ],
    }
    report = await autofill(page, flat)
    assert report["counts"]["failed"] == 0, report["failed"]
    assert await page.input_value(".j-name") == "张三"
    assert await page.input_value(".j-gender") == "男"  # 下拉弹层选项点击
    # 档案值「中国」应匹配选项「中国大陆」（包含匹配）
    assert await page.input_value(".j-country") == "中国大陆"
    # 日历：内容指纹识别 + 年/月箭头导航 + 日格点击
    assert await page.input_value(".j-birth") == "2001-03-18"
    # 组合行：号码写入无标签文本框，区号下拉保持默认
    assert await page.input_value(".j-phone") == "13800001111"
    assert await page.input_value(".j-areacode") == "+86"


async def test_desc_only_entry_merges_link_into_description(page: Page) -> None:
    """站点项目条目没有链接字段时：项目地址追加进描述文本（多行控件保留换行）。"""
    await page.goto(fixture_url("aui_like.html"))
    await page.evaluate("""() => {
      const h = document.createElement('h3');
      h.textContent = '项目经历';
      document.body.appendChild(h);
      const block = document.createElement('div');
      block.className = 'merge-proj-block';
      block.innerHTML = `
        <div class="aui-form-item">
          <div class="aui-form-item__label">项目描述</div>
          <div class="aui-form-item__content"><textarea class="j-merge-desc"></textarea></div>
        </div>`;
      document.body.appendChild(block);
    }""")
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {
                "key": "project",
                "title": "项目经历",
                "kind": "repeat",
                "items": [
                    {
                        "项目名称": "示例平台",
                        "项目描述": "负责接口设计与开发。",
                        "项目链接": "https://github.com/demo/app",
                    }
                ],
            }
        ],
    }
    report = await autofill(page, flat)
    assert report["counts"]["failed"] == 0, report["failed"]
    val = await page.input_value(".j-merge-desc")
    # 站点无链接字段 → 地址并入描述；描述正文保持原样在前
    assert val == "负责接口设计与开发。\n项目地址：https://github.com/demo/app"


async def test_awards_module_fill_and_isolation(page: Page) -> None:
    """获奖情况模块：别名直填（获奖名称/获奖时间/描述）+ 自动补块 + 与项目模块硬隔离。"""
    await page.goto(fixture_url("awards_like.html"))
    flat: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {
                "key": "awards",
                "title": "奖惩情况",
                "kind": "repeat",
                "items": [
                    {
                        "奖惩名称": "校级三等奖学金",
                        "奖惩时间": "2025-12",
                        "奖惩描述": "学业成绩年级前10%",
                    },
                    {
                        "奖惩名称": "省级编程竞赛二等奖",
                        "奖惩时间": "2024-06",
                        "奖惩描述": "团队负责人，负责算法模块",
                    },
                ],
            },
            {
                "key": "project",
                "title": "项目经历",
                "kind": "repeat",
                "items": [{"项目名称": "示例平台", "项目描述": "项目描述正文"}],
            },
        ],
    }
    report = await autofill(page, flat)
    assert report["counts"]["failed"] == 0, report["failed"]
    titles = await page.eval_on_selector_all(
        ".award-title", "els => els.map(e => e.value)"
    )
    assert titles == ["校级三等奖学金", "省级编程竞赛二等奖"]  # 自动点「添加获奖经历」补到 2 块
    dates = await page.eval_on_selector_all(".award-date", "els => els.map(e => e.value)")
    assert dates == ["2025-12", "2024-06"]
    descs = await page.eval_on_selector_all(".award-desc", "els => els.map(e => e.value)")
    assert descs == ["学业成绩年级前10%", "团队负责人，负责算法模块"]
    # 硬隔离：项目模块的裸「描述」拿到项目描述，不得被奖惩条目抢走（反之亦然）
    assert await page.input_value(".proj-title") == "示例平台"
    assert await page.input_value(".proj-desc") == "项目描述正文"


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


async def test_phoenix_radio_pointer_sequence(page: Page) -> None:
    """Phoenix 自绘单选的手势监听在内部 wrapper 上，只认 pointerdown。

    普通 mousedown/mouseup/click 合成序列选不中——引擎必须对内部节点
    补发指针序列并核验选中态，而不是盲报成功；无选中态标记的自绘组
    （无法核验）仍按已执行处理。
    """
    await page.goto(fixture_url("phoenix_radio.html"))
    report = await autofill(page, {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例档案"},
        "sections": [
            {
                "key": "basic",
                "title": "个人信息",
                "kind": "simple",
                "values": {"性别": "男", "出差意愿": "接受出差"},
            }
        ],
    })

    assert report["counts"]["failed"] == 0, report["failed"]
    filled = {r["label"] for r in report["filled"]}
    assert "性别" in filled
    assert "出差意愿" in filled  # 无标记组 → trust 兜底
    checked = await page.evaluate(
        "() => { var el = document.querySelector('.phoenix-radio--checked');"
        " return el ? el.innerText.trim() : '(未选中)'; }"
    )
    assert checked == "男"


async def test_moka_apply_real_structure(page: Page) -> None:
    """真实 Moka apply-field 结构：标签是行首裸文本、placeholder 带语义、
    +86 区号选择器不得成为可填字段（真实站实测暴露的适配缺口）。"""
    await page.goto(fixture_url("moka_apply.html"))
    report = await autofill(page, {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例档案"},
        "sections": [
            {
                "key": "basic",
                "title": "个人信息",
                "kind": "simple",
                "values": {
                    "姓名": "张三",
                    "手机号码": "13800001111",
                    "电子邮箱": "zhangsan@example.com",
                },
            }
        ],
    })

    assert report["counts"]["failed"] == 0, report["failed"]
    # 姓名行：标签在行首裸 DIV，placeholder 同名
    assert await page.input_value('input[placeholder="姓名"]') == "张三"
    # placeholder「请输入手机号」去前缀后命中 手机号 别名
    assert await page.input_value('input[placeholder="请输入手机号"]') == "13800001111"
    assert await page.input_value('input[placeholder="邮箱"]') == "zhangsan@example.com"
    # +86 区号 combobox 未被当作字段写入（保持原文本）
    assert (await page.eval_on_selector(".area-code", "el => el.innerText")) == "+86"
    # 推荐码无对应档案字段 → 跳过而非误填
    assert await page.input_value('input[placeholder="推荐码"]') == ""


async def test_feishu_ud_formily(page: Page) -> None:
    """飞书 ud-formily：data-form-field-i18n-name 标签、search 型学历选择器、
    区块内裸「添加」补教育块（不得误点相邻模块的添加按钮）。"""
    await page.goto(fixture_url("feishu_like.html"))
    report = await autofill(page, {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {"key": "basic", "title": "基本信息", "kind": "simple",
             "values": {"姓名": "张三", "电子邮箱": "zhangsan@example.com"}},
            {"key": "education", "title": "教育经历", "kind": "repeat", "items": [
                {"学校名称": "示例大学", "学历": "硕士研究生", "专业": "计算机",
                 "开始时间": "2024-09", "结束时间": "2027-06"},
                {"学校名称": "示例理工大学", "学历": "本科", "专业": "软件工程",
                 "开始时间": "2020-09", "结束时间": "2024-06"},
            ]},
        ],
    })

    assert report["counts"]["failed"] == 0, report["failed"]
    assert await page.input_value('[data-form-field-i18n-name="姓名"] input') == "张三"
    assert (
        await page.input_value('[data-form-field-i18n-name="邮箱"] input')
        == "zhangsan@example.com"
    )
    # 教育经历自动补到 2 块并按序配对
    schools = await page.eval_on_selector_all(
        ".school-input", "els => els.map(e => e.value)")
    assert schools == ["示例大学", "示例理工大学"]
    # search 型学历走面板选项路径
    edus = await page.eval_on_selector_all(
        ".edu-select-trigger", "els => els.map(e => e.value)")
    assert edus == ["硕士研究生", "本科"]
    # 相邻模块的「添加」没被误点
    assert await page.locator(".social-added").count() == 0
    # 起止时间区间：第 k 组输入 ↔ 第 k 条档案的 开始/结束时间
    starts = await page.eval_on_selector_all(".range-start", "els => els.map(e => e.value)")
    ends = await page.eval_on_selector_all(".range-end", "els => els.map(e => e.value)")
    assert starts == ["2024-09", "2020-09"]
    assert ends == ["2027-06", "2024-06"]
    # 项目经历：初始零区块，自动点「添加」补块并按序填写
    proj = {
        "key": "projects", "title": "项目经历", "kind": "repeat", "items": [
            {"项目名称": "示例AI助手平台", "项目职务": "核心开发",
             "项目描述": "面向领域知识的智能助手开发",
             "项目链接": "https://example.com/demo-assistant"},
            {"项目名称": "示例预警系统", "项目职务": "负责人", "项目描述": "示例日志数据分析",
             "项目链接": "https://example.com/demo-alert"},
        ],
    }
    report2 = await autofill(page, {
        "schema": 1, "profile": {"id": "demo", "label": "示例"}, "sections": [proj],
    }, {"noAddBlocks": False})
    assert report2["counts"]["failed"] == 0, report2["failed"]
    names = await page.eval_on_selector_all(".proj-name", "els => els.map(e => e.value)")
    roles = await page.eval_on_selector_all(".proj-role", "els => els.map(e => e.value)")
    assert names == ["示例AI助手平台", "示例预警系统"]
    assert roles == ["核心开发", "负责人"]  # 项目职务 → 项目角色 别名
    descs = await page.eval_on_selector_all(".proj-desc", "els => els.map(e => e.value)")
    assert descs == ["面向领域知识的智能助手开发", "示例日志数据分析"]
    # 项目链接：URL 值配对到链接栏（不被长文本守卫误杀）
    links = await page.eval_on_selector_all(".proj-link", "els => els.map(e => e.value)")
    assert links == ["https://example.com/demo-assistant", "https://example.com/demo-alert"]


async def test_research_and_project_module_isolation(page: Page) -> None:
    """科研经历与项目经历分模块：条目同标签也不得互串；
    两个零区块模块各自按自己的「添加」补块。"""
    await page.goto(fixture_url("feishu_like.html"))
    report = await autofill(page, {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {"key": "projects", "title": "项目经历", "kind": "repeat", "items": [
                {"项目名称": "示例工程平台", "项目职务": "负责人"},
                {"项目名称": "示例日志系统", "项目职务": "开发"},
            ]},
            {"key": "research", "title": "科研经历", "kind": "repeat", "items": [
                {"项目名称": "示例科研课题甲", "项目职务": "课题骨干"},
                {"项目名称": "示例科研课题乙", "项目职务": "主持人"},
            ]},
        ],
    })
    assert report["counts"]["failed"] == 0, report["failed"]
    # 项目模块补到 2 块、填工程项目条目；科研模块补到 2 块、填科研条目
    assert await page.eval_on_selector_all(
        ".proj-name", "els => els.map(e => e.value)") == ["示例工程平台", "示例日志系统"]
    assert await page.eval_on_selector_all(
        ".proj-role", "els => els.map(e => e.value)") == ["负责人", "开发"]
    assert await page.eval_on_selector_all(
        ".res-name", "els => els.map(e => e.value)") == ["示例科研课题甲", "示例科研课题乙"]
    assert await page.eval_on_selector_all(
        ".res-role", "els => els.map(e => e.value)") == ["课题骨干", "主持人"]


async def test_correct_mismatched_prefill(page: Page) -> None:
    """纠偏：站点解析简历产生的乱配预填（标题带编号/角色串位/链接空）
    与档案不一致时按普通阈值覆盖；值一致的预填不动；可关。"""
    await page.goto(fixture_url("feishu_like.html"))
    for _ in range(2):
        await page.click("#proj-add")
    # 模拟站点解析预填：块1 乱值（编号标题+串位角色），块2 名称恰好已正确
    await page.evaluate(r"""() => {
      const native = (el, val) => {
        const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                                : window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
        el.dispatchEvent(new Event('input', {bubbles: true}));
      };
      const names = document.querySelectorAll('.proj-name');
      const roles = document.querySelectorAll('.proj-role');
      native(names[0], '1. 示例ai助手平台');
      native(roles[0], '大数据开发负责人');
      native(names[1], '示例预警系统');
    }""")
    profile: dict[str, Any] = {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [{"key": "projects", "title": "项目经历", "kind": "repeat", "items": [
            {"项目名称": "示例AI助手平台", "项目职务": "核心开发", "项目链接": "https://example.com/a"},
            {"项目名称": "示例预警系统", "项目职务": "负责人"},
        ]}],
    }
    report = await autofill(page, profile, {"noAddBlocks": True})
    assert report["counts"]["failed"] == 0, report["failed"]
    # 块1 乱值被纠正（含链接补上）
    assert await page.eval_on_selector_all(
        ".proj-name", "els => els.map(e => e.value)") == ["示例AI助手平台", "示例预警系统"]
    assert await page.eval_on_selector_all(
        ".proj-role", "els => els.map(e => e.value)") == ["核心开发", "负责人"]
    assert await page.eval_on_selector_all(
        ".proj-link", "els => els.map(e => e.value)") == ["https://example.com/a", ""]
    corrected = [r for r in report["filled"] if r.get("corrected")]
    assert {r["label"] for r in corrected} == {"项目名称", "项目角色"}  # 块2 正确值未重写

    # 关闭纠偏：乱值保留
    await page.goto(fixture_url("feishu_like.html"))
    for _ in range(2):
        await page.click("#proj-add")
    await page.evaluate(r"""() => {
      const native = (el, val) => {
        const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                                : window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
        el.dispatchEvent(new Event('input', {bubbles: true}));
      };
      const names = document.querySelectorAll('.proj-name');
      native(names[0], '1. 示例ai助手平台');
    }""")
    report2 = await autofill(page, profile, {"noAddBlocks": True, "correctPrefilled": False})
    assert report2["counts"]["failed"] == 0
    names2 = await page.eval_on_selector_all(
        ".proj-name", "els => els.map(e => e.value)")
    assert names2[0] == "1. 示例ai助手平台"  # 关闭纠偏：乱值原样保留


async def test_long_text_readback_over_400_chars(page: Page) -> None:
    """超长描述（>400 字）回读被截断：按同口径比对，不得误报「回读不一致」。"""
    await page.goto(fixture_url("feishu_like.html"))
    await page.click("#proj-add")
    long_desc = "面向核电子学领域的智能体平台描述。" * 26  # 17×26=442 字
    assert len(long_desc) > 400
    report = await autofill(page, {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [{"key": "projects", "title": "项目经历", "kind": "repeat", "items": [
            {"项目名称": "示例AI助手平台", "项目描述": long_desc},
        ]}],
    })
    assert report["counts"]["failed"] == 0, report["failed"]
    assert report["counts"]["filled"] >= 1
    assert len(await page.input_value(".proj-desc")) == len(long_desc)


async def test_link_field_rejects_long_text(page: Page) -> None:
    """链接栏守卫：档案里链接字段的值若是一段长文本（无 URL），不得灌进链接输入框。"""
    await page.goto(fixture_url("feishu_like.html"))
    await page.click("#proj-add")  # 手动建 1 块，绕开补块逻辑单独考察守卫
    report = await autofill(page, {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [{"key": "projects", "title": "项目经历", "kind": "repeat", "items": [
            {"项目名称": "示例AI助手平台",
             "项目链接": "这是一个误把项目介绍当成链接填进档案字段的长文本，没有可用的网址"},
        ]}],
    })
    assert await page.eval_on_selector_all(
        ".proj-link", "els => els.map(e => e.value)") == [""]
    assert all(r["label"] != "项目链接" for r in report["filled"])
    # 同块其他字段不受影响
    assert await page.eval_on_selector_all(
        ".proj-name", "els => els.map(e => e.value)") == ["示例AI助手平台"]


async def test_phoenix_month_picker_and_area_cascade(page: Page) -> None:
    """北森 Phoenix 风格：月选择面板（12 月格 + 两套翻年箭头，首套无效）与
    籍贯省市级联（首层选项只是值前缀，需逐层下钻）。真站 haige.zhiye.com 驱动。"""
    await page.goto(fixture_url("phoenix_form.html"))
    report = await autofill(page, {
        "schema": 1,
        "profile": {"id": "demo", "label": "示例"},
        "sections": [
            {"key": "basic", "title": "基本信息", "kind": "simple", "values": {
                "姓名": "张三", "籍贯": "四川省德阳市",
            }},
            {"key": "education", "title": "教育经历", "kind": "repeat", "items": [
                {"开始时间": "2024-09"},
            ]},
        ],
    })
    assert report["counts"]["failed"] == 0, report["failed"]
    assert await page.input_value("#name") == "张三"
    # 月面板：翻年箭头应跳过无效装饰箭头，2026 → 2024 后点 9 月格
    assert await page.input_value("#start-input") == "2024-09"
    # 级联：首层选项「四川省」只是值前缀 → 点开下层 → 「德阳市」补全
    assert await page.input_value("#jiguan-input") == "四川省德阳市"
