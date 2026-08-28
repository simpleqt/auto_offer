"""扁平档案接口（插件消费）集成测试：敏感门控 + 分区结构。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.integration.server.conftest import sample_profile_payload


def put_sample(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/profiles/demo-profile",
        json={"label": "中文-示例档案", "payload": sample_profile_payload()},
    )
    assert resp.status_code == 200


def collect_labels(body: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for sec in body["sections"]:
        if sec["kind"] == "simple":
            labels.update(sec["values"].keys())
        else:
            for item in sec["items"]:
                labels.update(item.keys())
    return labels


def test_flat_default_excludes_sensitive(client: TestClient) -> None:
    put_sample(client)
    resp = client.get("/api/v1/profiles/demo-profile/flat")
    assert resp.status_code == 200
    body = resp.json()

    labels = collect_labels(body)
    titles = {s["title"] for s in body["sections"]}
    # 敏感契约：默认不含身份证号/家庭区块
    assert "身份证号" not in labels
    assert not any("家庭" in t or "紧急联系人" in t for t in titles)

    basic = next(s for s in body["sections"] if s["key"] == "basic")["values"]
    assert basic["姓名"] == "张三"
    assert basic["手机号码"] == "13800001111"
    assert basic["出生日期"] == "2002-05-12"
    assert basic["国籍"] == "中国"
    assert basic["工作年限"] == "应届毕业生"

    intention = next(s for s in body["sections"] if s["key"] == "intention")["values"]
    assert intention["期望从事行业"] == "人工智能"
    assert intention["现月薪(税前)"] == "3K"
    assert intention["期望月薪(税前)"] == "20-30K"

    edu = next(s for s in body["sections"] if s["key"] == "education")["items"][0]
    assert edu["学校"] == "示例大学"
    assert edu["开始时间"] == "2020-09"
    assert edu["结束时间"] == "2024-06"
    assert edu["学历"] == "本科"
    assert edu["学位"] == "学士"

    # 项目经历 end=None → 至今；实习按 kind 分区
    sections = {s["key"]: s for s in body["sections"]}
    project = sections["project"]["items"][0]
    assert project["结束时间"] == "至今"
    assert sections["internship"]["items"][0]["公司"] == "某科技公司"

    other = sections["other"]["values"]
    assert "Python" in other["专业技能"]
    assert other["自我评价"].startswith("做事踏实")


def test_flat_sensitive_opt_in(client: TestClient) -> None:
    put_sample(client)
    resp = client.get("/api/v1/profiles/demo-profile/flat?sensitive=true")
    assert resp.status_code == 200
    body = resp.json()

    sections = {s["title"]: s for s in body["sections"]}
    assert "家庭情况" in sections
    father = sections["家庭情况"]["items"][0]
    assert father["姓名"] == "张父"
    assert father["关系"] == "父亲"
    # 示例档案家庭成员未填电话（restricted，且无值）——不输出
    assert "电话" not in father


def test_flat_unknown_profile_404(client: TestClient) -> None:
    resp = client.get("/api/v1/profiles/no-such/flat")
    assert resp.status_code == 404
