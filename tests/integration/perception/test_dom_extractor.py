"""DomExtractor 端到端集成测试：真实 Chromium + 本地夹具。"""


from playwright.async_api import Page
from tests.integration.perception.conftest import fixture_url

from autooffer_core.perception import DomExtractor, PageObservation


async def load(page: Page, name: str) -> PageObservation:
    await page.goto(fixture_url(name))
    return await DomExtractor().extract(page)


def by_label(obs: PageObservation, label: str):
    for el in obs.elements:
        if label in el.label:
            return el
    raise AssertionError(f"未找到 label 含 {label!r} 的元素: {[e.label for e in obs.elements]}")


async def test_native_select_options_and_truncation(page):
    obs = await load(page, "native_select.html")
    degree = by_label(obs, "最高学历")
    assert degree.role == "select"
    assert degree.required is True
    assert degree.options == ["请选择", "大专", "本科", "硕士", "博士"]
    assert degree.options_truncated is False
    assert degree.value == "本科"  # 已选中项作为当前值

    city = by_label(obs, "意向城市")
    assert city.options is not None
    assert len(city.options) == 30
    assert city.options_truncated is True


async def test_custom_controls_classified(page):
    obs = await load(page, "custom_select.html")
    years = by_label(obs, "工作年限")
    assert years.role == "combobox"
    assert years.value == "3-5年"
    salary = by_label(obs, "期望薪资")
    assert salary.role == "combobox"  # 级联/选择类只读输入框归为 combobox
    arrival = by_label(obs, "到岗时间")
    assert arrival.role == "date"


async def test_date_and_file_inputs(page):
    obs = await load(page, "date_file.html")
    birth = by_label(obs, "出生日期")
    assert birth.role == "date"
    # file 控件不进入默认填写流（从源头消除「上传简历」子任务），应被过滤
    file_labels = [e.label for e in obs.elements if e.role == "file"]
    assert file_labels == []
    assert not any("简历" in e.label or "证件照" in e.label for e in obs.elements)


async def test_radio_checkbox(page):
    obs = await load(page, "radio_checkbox.html")
    radios = [e for e in obs.elements if e.role == "radio"]
    checks = [e for e in obs.elements if e.role == "checkbox"]
    assert len(radios) == 2
    assert len(checks) >= 3  # 2 原生 + 1 role=checkbox
    male = next(e for e in radios if "男" in e.label)
    assert male.value == "true"  # JS 侧约定: 勾选为 "true", 未勾选为 ""
    custom = next(e for e in checks if "订阅" in e.label)
    assert custom.value == ""


async def test_element_states(page):
    """控件状态内联提取（纯 DOM 无视觉模式的状态来源）。"""
    obs = await load(page, "element_states.html")

    locked = by_label(obs, "禁用输入")
    assert locked.disabled is True
    ro = by_label(obs, "只读输入")
    assert ro.readonly is True

    combos = [e for e in obs.elements if e.role == "combobox"]
    expanded = [c for c in combos if c.expanded is True]
    collapsed = [c for c in combos if c.expanded is False]
    assert len(expanded) == 1 and len(collapsed) == 1

    # 类名选中态（antd 风格 custom radio）：checked 类 → value "true"
    radios = [e for e in obs.elements if e.role == "radio"]
    male = next(e for e in radios if "男" in e.label)
    female = next(e for e in radios if "女" in e.label)
    assert male.value == "true"
    assert female.value == ""

    # listbox 选项 aria-selected
    options = [e for e in obs.elements if e.role == "option"]
    picked = [o for o in options if "已选项" in o.label]
    assert picked and picked[0].value == "true"
    unpicked = [o for o in options if "未选项" in o.label]
    assert unpicked and unpicked[0].value == ""


async def test_multi_section_and_pagination(page):
    obs = await load(page, "multi_section.html")
    titles = [s.title for s in obs.sections]
    assert any("基本信息" in t for t in titles)
    assert any("教育经历" in t for t in titles)
    # 区块元素区间合法
    for sec in obs.sections:
        assert 0 <= sec.element_start <= sec.element_end < len(obs.elements)
    # 归属区块的元素确实落在区间内
    basic = next(s for s in obs.sections if "基本信息" in s.title)
    name = by_label(obs, "姓名")
    assert name.section_id == basic.id
    assert basic.element_start <= name.index <= basic.element_end
    # 分页：步骤条 + 下一步按钮
    assert obs.pagination.kind == "multi_step"
    assert obs.pagination.total_steps == 3
    assert obs.pagination.current_step == 2
    assert obs.pagination.next_button_index is not None
    next_el = obs.elements[obs.pagination.next_button_index]
    assert "下一步" in next_el.label
    # 预填占比：姓名/邮箱有值
    assert 0.0 < obs.scenario.prefilled_ratio < 1.0


async def test_long_page_scroll_merge(page):
    obs = await load(page, "long_page.html")
    labels = [e.label for e in obs.elements]
    assert "字段01" in labels and "字段40" in labels
    # 去重：selector 不重复
    keys = [(e.frame_path, e.selector) for e in obs.elements]
    assert len(keys) == len(set(keys))
    assert obs.scroll_height > obs.viewport_height


async def test_same_origin_iframe(page):
    obs = await load(page, "iframe_host.html")
    inner = [e for e in obs.elements if e.frame_path]
    assert inner, "应提取到同源 iframe 内元素"
    assert any("iframe内姓名" in e.label for e in inner)
