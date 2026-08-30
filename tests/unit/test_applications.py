"""投递列表单元测试。"""

from __future__ import annotations

from pathlib import Path

from autooffer_core.applications import ApplicationStore, guess_company_position
from autooffer_core.report import FieldRecord, FillReport


def make_report(url: str = "https://example.com/apply") -> FillReport:
    return FillReport(
        task_id="t1",
        url=url,
        page_title="星辰科技 - 校园招聘简历登记",
        profile_id="p1",
        fields=[
            FieldRecord(label="姓名", status="filled", value="张三"),
            FieldRecord(label="应聘岗位", status="filled", value="算法工程师"),
            FieldRecord(label="期望薪资", status="pending_confirm"),
        ],
    )


def test_guess_company_position() -> None:
    report = make_report()
    company, position = guess_company_position(report.page_title, report)
    assert company == "星辰科技"
    assert position == "算法工程师"


def test_guess_company_skips_generic_parts() -> None:
    """飞书式标题「投递简历 - 加入马上消费」：公司应取非通用段。"""
    from autooffer_core.applications import guess_company

    assert guess_company("投递简历 - 加入马上消费") == "加入马上消费"
    assert guess_company("职位申请-乐元素校园招聘") == "乐元素校园招聘"
    assert guess_company("星辰科技 - 校园招聘") == "星辰科技"
    assert guess_company("") == ""


def test_add_or_update_from_extension(tmp_path: Path) -> None:
    """插件上报入口：无 FillReport 也能登记；同 URL 去重更新。"""
    store = ApplicationStore(tmp_path / "apps.json")
    r1 = store.add_or_update(
        url="https://weikezhijia.jobs.feishu.cn/apply",
        profile_id="p1",
        page_title="投递简历 - 加入马上消费",
        filled=30,
        failed=0,
        pending=2,
        note="插件填写",
    )
    assert r1.company == "加入马上消费"
    assert r1.fields_filled == 30
    r2 = store.add_or_update(
        url="https://weikezhijia.jobs.feishu.cn/apply",
        page_title="投递简历 - 加入马上消费",
        filled=32,
        failed=0,
        pending=0,
    )
    assert r2.id == r1.id  # 同 URL 更新而非新增
    assert r2.fields_filled == 32
    assert len(store.list()) == 1


def test_add_list_update(tmp_path: Path) -> None:
    store = ApplicationStore(tmp_path / "apps.json")
    record = store.add_from_report(make_report(), page_title="星辰科技 - 校园招聘简历登记")
    assert record.company == "星辰科技"
    assert record.position == "算法工程师"
    assert record.status == "filled"
    assert record.fields_filled == 2
    assert record.fields_pending == 1

    records = store.list()
    assert len(records) == 1

    updated = store.update_status(record.id, "submitted", note="已人工提交")
    assert updated is not None
    assert updated.status == "submitted"
    assert store.list(status="submitted")[0].id == record.id


def test_same_url_dedup(tmp_path: Path) -> None:
    store = ApplicationStore(tmp_path / "apps.json")
    r1 = store.add_from_report(make_report())
    r2 = store.add_from_report(make_report())  # 同 URL 未提交 → 更新而非新增
    assert r1.id == r2.id
    assert len(store.list()) == 1

    # 已提交后再次填写同 URL → 新增记录
    store.update_status(r1.id, "submitted")
    r3 = store.add_from_report(make_report())
    assert r3.id != r1.id
    assert len(store.list()) == 2


def test_remove(tmp_path: Path) -> None:
    store = ApplicationStore(tmp_path / "apps.json")
    r = store.add_from_report(make_report())
    assert store.remove(r.id) is True
    assert store.remove(r.id) is False
    assert store.list() == []
