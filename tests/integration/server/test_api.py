"""REST API 集成测试：档案 / 模型端点 / 任务 / 投递列表全流程（离线）。"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.server.conftest import sample_profile_payload


def wait_state(client: TestClient, task_id: str, target: str, timeout: float = 15.0) -> str:
    """轮询任务状态直到命中目标或超时。"""
    deadline = time.time() + timeout
    state = ""
    while time.time() < deadline:
        state = client.get(f"/api/v1/tasks/{task_id}").json()["state"]
        if state == target:
            return state
        time.sleep(0.05)
    return state


def wait_events(
    client: TestClient, task_id: str, predicate: Any, timeout: float = 10.0
) -> list[dict[str, Any]]:
    """轮询审计事件直到满足条件。

    审计写入是有意的最终一致（单写入者队列，不阻塞智能体循环），
    因此任务已进入终态时事件可能尚未全部落库，测试需轮询而非即时断言。
    """
    deadline = time.time() + timeout
    events: list[dict[str, Any]] = []
    while time.time() < deadline:
        events = client.get(f"/api/v1/tasks/{task_id}/events").json()
        if predicate(events):
            return events
        time.sleep(0.05)
    return events


# ---------- 系统 ----------


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]


# ---------- 模型端点：api_key 脱敏 ----------


def test_endpoint_crud_masks_api_key(client: TestClient) -> None:
    payload = {
        "id": "ep1",
        "name": "本地 Qwen",
        "base_url": "http://127.0.0.1:8011/v1",
        "model": "qwen3.5-35b",
        "api_key": "sk-supersecret-abcd1234",
        "is_default": True,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    r = client.put("/api/v1/models", json=payload)
    assert r.status_code == 200
    body = r.json()
    # 关键安全断言：响应中不含明文 key
    assert "sk-supersecret-abcd1234" not in r.text
    assert body["key_hint"].startswith("sk-") and "***" in body["key_hint"]
    assert body["supports_vision"] is None  # 未探测
    assert body["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False

    listed = client.get("/api/v1/models").json()
    assert len(listed) == 1
    assert "sk-supersecret" not in client.get("/api/v1/models").text


def test_endpoint_update_keeps_key_when_omitted(client: TestClient) -> None:
    base = {
        "id": "ep1", "base_url": "http://x/v1", "model": "m", "api_key": "sk-aaaa1111bbbb",
    }
    client.put("/api/v1/models", json=base)
    hint1 = client.get("/api/v1/models").json()[0]["key_hint"]
    # 不传 api_key 的更新：保留原 key 提示
    client.put("/api/v1/models", json={"id": "ep1", "base_url": "http://x/v1", "model": "m2"})
    row = client.get("/api/v1/models").json()[0]
    assert row["model"] == "m2"
    assert row["key_hint"] == hint1


def test_new_endpoint_requires_api_key(client: TestClient) -> None:
    r = client.put("/api/v1/models", json={"id": "nokey", "base_url": "u", "model": "m"})
    assert r.status_code == 400


def test_endpoint_delete(client: TestClient) -> None:
    client.put(
        "/api/v1/models",
        json={"id": "ep1", "base_url": "u", "model": "m", "api_key": "sk-1234567890"},
    )
    assert client.delete("/api/v1/models/ep1").json()["deleted"] is True
    assert client.get("/api/v1/models").json() == []


def test_routing_roundtrip(client: TestClient) -> None:
    r = client.put("/api/v1/models/routing", json={"mapping": {"validator": "ep-small"}})
    assert r.json() == {"validator": "ep-small"}
    assert client.get("/api/v1/models/routing").json() == {"validator": "ep-small"}


# ---------- 档案 ----------


def test_profile_crud(client: TestClient) -> None:
    payload = sample_profile_payload()
    r = client.put("/api/v1/profiles/p1", json={"payload": payload})
    assert r.status_code == 200
    assert r.json()["basic"]["name"] == "张三"

    summaries = client.get("/api/v1/profiles").json()
    assert len(summaries) == 1
    assert summaries[0]["name"] == "张三"
    assert summaries[0]["attachments"] == 3

    assert client.get("/api/v1/profiles/p1").json()["basic"]["phone"] == "13800001111"
    assert client.get("/api/v1/profiles/missing").status_code == 404
    assert client.delete("/api/v1/profiles/p1").json()["deleted"] is True


def test_profile_validation_error(client: TestClient) -> None:
    r = client.put("/api/v1/profiles/bad", json={"payload": {"basic": {"name": "缺电话"}}})
    assert r.status_code == 422


# ---------- 任务全流程 ----------


def test_task_lifecycle_to_awaiting_review(client: TestClient) -> None:
    client.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
    r = client.post("/api/v1/tasks", json={"url": "https://example.com/apply", "profile_id": "p1"})
    assert r.status_code == 200
    task_id = r.json()["id"]
    assert r.json()["state"] in ("QUEUED", "RUNNING")

    assert wait_state(client, task_id, "AWAITING_REVIEW") == "AWAITING_REVIEW"

    detail = client.get(f"/api/v1/tasks/{task_id}").json()
    assert detail["page_title"] == "示例公司 - 招聘"
    report = detail["report"]
    assert report is not None
    assert any(f["label"] == "姓名" and f["status"] == "filled" for f in report["fields"])

    # 审计事件已入库（最终一致，需轮询）
    events = wait_events(client, task_id, lambda evs: any(e["kind"] == "report" for e in evs))
    assert any(e["agent"] == "planner" for e in events)
    assert any(e["kind"] == "report" for e in events)


def test_task_requires_existing_profile(client: TestClient) -> None:
    r = client.post("/api/v1/tasks", json={"url": "u", "profile_id": "nope"})
    assert r.status_code == 404


def test_task_list_and_404(client: TestClient) -> None:
    client.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
    client.post("/api/v1/tasks", json={"url": "https://a.com", "profile_id": "p1"})
    assert len(client.get("/api/v1/tasks").json()) == 1
    assert client.get("/api/v1/tasks/none").status_code == 404


def test_task_waiting_human_then_resume(ctx_factory: Any) -> None:
    """登录墙类场景：任务挂起 WAITING_HUMAN，resume 后继续到 AWAITING_REVIEW。"""
    from autooffer_server.main import create_app
    from tests.integration.server.conftest import FakeRunner

    runner = FakeRunner(pause_reason="检测到登录页，请手动登录")
    with TestClient(create_app(ctx=ctx_factory(runner))) as c:
        c.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
        task_id = c.post(
            "/api/v1/tasks", json={"url": "https://example.com/login", "profile_id": "p1"}
        ).json()["id"]

        assert wait_state(c, task_id, "WAITING_HUMAN") == "WAITING_HUMAN"
        assert "登录" in c.get(f"/api/v1/tasks/{task_id}").json()["wait_reason"]

        assert c.post(f"/api/v1/tasks/{task_id}/resume").json()["resumed"] is True
        assert wait_state(c, task_id, "AWAITING_REVIEW") == "AWAITING_REVIEW"


def test_task_failure_recorded(ctx_factory: Any) -> None:
    from autooffer_server.main import create_app
    from tests.integration.server.conftest import FakeRunner

    with TestClient(create_app(ctx=ctx_factory(FakeRunner(fail=True)))) as c:
        c.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
        task_id = c.post(
            "/api/v1/tasks", json={"url": "https://x.com", "profile_id": "p1"}
        ).json()["id"]
        assert wait_state(c, task_id, "FAILED") == "FAILED"
        assert "模拟执行失败" in c.get(f"/api/v1/tasks/{task_id}").json()["wait_reason"]


def test_task_cancel(ctx_factory: Any) -> None:
    from autooffer_server.main import create_app
    from tests.integration.server.conftest import FakeRunner

    runner = FakeRunner(pause_reason="等待人工")
    with TestClient(create_app(ctx=ctx_factory(runner))) as c:
        c.put("/api/v1/profiles/p1", json={"payload": sample_profile_payload()})
        task_id = c.post(
            "/api/v1/tasks", json={"url": "https://x.com", "profile_id": "p1"}
        ).json()["id"]
        wait_state(c, task_id, "WAITING_HUMAN")
        assert c.post(f"/api/v1/tasks/{task_id}/cancel").json()["cancelled"] is True
        assert c.get(f"/api/v1/tasks/{task_id}").json()["state"] == "CANCELLED"


# ---------- 投递列表 ----------


def test_applications_auto_recorded_and_status_update(client: TestClient) -> None:
    """填写完成后（真实执行体会登记）——此处直接验证接口的读写能力。"""
    from autooffer_core.applications import ApplicationStore

    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    store = ApplicationStore(ctx.config.data_dir / "applications.json")
    from autooffer_core.report import FieldRecord, FillReport

    record = store.add_from_report(
        FillReport(
            task_id="t1", url="https://example.com/apply", page_title="星辰科技 - 招聘",
            profile_id="p1",
            fields=[FieldRecord(label="应聘岗位", status="filled", value="算法工程师")],
        ),
        page_title="星辰科技 - 招聘",
    )

    rows = client.get("/api/v1/applications").json()
    assert len(rows) == 1
    assert rows[0]["company"] == "星辰科技"
    assert rows[0]["position"] == "算法工程师"
    assert rows[0]["status"] == "filled"

    r = client.put(
        f"/api/v1/applications/{record.id}",
        json={"status": "submitted", "note": "已人工提交"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"

    assert client.get("/api/v1/applications?status=submitted").json()[0]["id"] == record.id
    assert client.delete(f"/api/v1/applications/{record.id}").json()["deleted"] is True


def test_application_report_from_extension(client: TestClient) -> None:
    """插件填写上报：登记投递记录（公司取非通用标题段），同 URL 去重更新。"""
    body = {
        "url": "https://weikezhijia.jobs.feishu.cn/MSXF/resume/1/apply",
        "profile_id": "p1",
        "page_title": "投递简历 - 加入马上消费",
        "fields_filled": 30,
        "fields_failed": 0,
        "fields_pending": 2,
        "note": "插件填写",
    }
    r = client.post("/api/v1/applications", json=body)
    assert r.status_code == 200
    rec = r.json()
    assert rec["company"] == "加入马上消费"
    assert rec["status"] == "filled"
    assert rec["fields_filled"] == 30

    body2 = {**body, "fields_filled": 32, "fields_pending": 0}
    rec2 = client.post("/api/v1/applications", json=body2).json()
    assert rec2["id"] == rec["id"]
    assert rec2["fields_filled"] == 32
    listed = client.get("/api/v1/applications").json()
    assert len(listed) == 1


def test_application_404(client: TestClient) -> None:
    assert client.put("/api/v1/applications/none", json={"status": "submitted"}).status_code == 404


def test_extension_logs_sink_to_stdlib(client: TestClient, caplog: Any) -> None:
    """插件日志上报：条目进入 extension 记录器（生产环境由 launcher 汇入 app.log）。"""
    with caplog.at_level("INFO", logger="extension"):
        r = client.post("/api/v1/logs", json={"entries": [
            {"ts": "2026-08-30 10:00:00", "level": "info", "msg": "fill.done",
             "filled": 30, "url": "https://example.com/apply"},
            {"level": "error", "msg": "fill.fatal", "error": "x"},
            {"msg": ""},
            "not-a-dict",
        ]})
    assert r.status_code == 200
    assert r.json()["written"] == 2  # 空消息与非字典条目跳过
    recs = [r for r in caplog.records if r.name == "extension"]
    assert any("fill.done" in r.message and "filled=30" in r.message for r in recs)
    assert any(r.levelname == "ERROR" and "fill.fatal" in r.message for r in recs)


# ---------- 模型调用统计（FR-M5） ----------

def test_usage_aggregation_by_model_and_task(client: TestClient) -> None:
    """写入若干条用量记录后，/usage 返回按模型与按任务的聚合统计。"""
    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    import asyncio

    async def seed() -> None:
        await ctx.repo.add_llm_usage(
            {"task_id": "t1", "model": "qwen", "prompt_tokens": 100,
             "completion_tokens": 50, "total_tokens": 150, "latency_ms": 200, "success": 1}
        )
        await ctx.repo.add_llm_usage(
            {"task_id": "t1", "model": "qwen", "prompt_tokens": 200,
             "completion_tokens": 100, "total_tokens": 300, "latency_ms": 300, "success": 1}
        )
        await ctx.repo.add_llm_usage(
            {"task_id": "t2", "model": "qwen", "prompt_tokens": 0,
             "completion_tokens": 0, "total_tokens": 0, "latency_ms": 100, "success": 0,
             "error": "超时"}
        )

    asyncio.run(seed())

    r = client.get("/api/v1/usage")
    assert r.status_code == 200
    body = r.json()

    by_model = {m["model"]: m for m in body["by_model"]}
    qwen = by_model["qwen"]
    assert qwen["calls"] == 3
    assert qwen["failed"] == 1
    assert qwen["failure_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert qwen["total_tokens"] == 450
    assert qwen["avg_latency_ms"] == 200  # (200+300+100)/3

    by_task = {t["task_id"]: t for t in body["by_task"]}
    assert by_task["t1"]["calls"] == 2
    assert by_task["t1"]["total_tokens"] == 450
    assert by_task["t2"]["failed"] == 1


def test_usage_empty(client: TestClient) -> None:
    r = client.get("/api/v1/usage")
    assert r.status_code == 200
    assert r.json() == {"by_model": [], "by_task": []}


# ---------- 附件上传（单用户本地存储） ----------

def test_attachment_upload_persists_file_and_meta(client: TestClient) -> None:
    """上传附件应落盘到数据目录 attachments/ 并返回可入库的附件元信息。"""
    files = {"file": ("photo.jpg", b"\xff\xd8\xff\xe0fake-jpeg", "image/jpeg")}
    r = client.post(
        "/api/v1/attachments",
        files=files,
        data={"kind": "photo", "label": "一寸白底照", "language": "zh"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "photo"
    assert body["label"] == "一寸白底照"
    assert body["language"] == "zh"
    assert body["path"].endswith("_photo.jpg")
    assert body["meta"]["size_kb"] >= 1

    # 文件确实落盘到数据目录 attachments/ 下
    from pathlib import Path

    ctx = client.app.state.ctx  # type: ignore[attr-defined]
    saved = Path(body["path"])
    assert saved.exists()
    assert ctx.config.attachments_dir in saved.parents


def test_attachment_upload_invalid_kind(client: TestClient) -> None:
    """非法 kind 应返回 422 且不残留文件。"""
    files = {"file": ("bad.bin", b"data", "application/octet-stream")}
    r = client.post("/api/v1/attachments", files=files, data={"kind": "not-a-kind"})
    assert r.status_code == 422


# ---------- 简历附件管理（多简历 + 默认 + 解析覆盖） ----------


def _make_profile(client: TestClient) -> str:
    client.put("/api/v1/profiles/pr1", json={"payload": sample_profile_payload()})
    return "pr1"


def test_resume_upload_replace_activate_delete(client: TestClient) -> None:
    pid = _make_profile(client)
    files = {"file": ("new_resume.txt", b"name: demo", "text/plain")}
    r = client.post(f"/api/v1/profiles/{pid}/resumes", files=files, data={"mode": "replace"})
    assert r.status_code == 200
    body = r.json()
    # 新简历成为默认；原两份简历 active 被清掉
    atts = body["profile"]["attachments"]
    assert len(atts) == 4
    assert atts[3]["kind"] == "resume" and atts[3]["meta"]["active"] == 1
    assert all("active" not in (a.get("meta") or {}) for a in atts[:3] if a["kind"] == "resume")
    # replace 模式不动档案内容
    assert body["profile"]["basic"]["name"] == "张三"

    # flat 只带默认简历（带档案内下标）
    flat = client.get(f"/api/v1/profiles/{pid}/flat").json()
    resume_atts = [a for a in flat["attachments"] if a["kind"] == "resume"]
    assert len(resume_atts) == 1
    assert resume_atts[0]["index"] == 3
    assert any(a["kind"] == "photo" for a in flat["attachments"])

    # 激活旧简历（index 0），flat 随之切换
    assert client.post(f"/api/v1/profiles/{pid}/attachments/0/activate").status_code == 200
    flat = client.get(f"/api/v1/profiles/{pid}/flat").json()
    resume_atts = [a for a in flat["attachments"] if a["kind"] == "resume"]
    assert resume_atts[0]["index"] == 0

    # 非简历附件不可激活
    assert client.post(f"/api/v1/profiles/{pid}/attachments/2/activate").status_code == 422

    # 删除默认简历 → 自动激活剩下的第一份
    assert client.delete(f"/api/v1/profiles/{pid}/attachments/0").status_code == 200
    atts = client.get(f"/api/v1/profiles/{pid}").json()["attachments"]
    resumes = [a for a in atts if a["kind"] == "resume"]
    assert len(resumes) == 2
    assert (resumes[0].get("meta") or {}).get("active") == 1
    assert client.delete(f"/api/v1/profiles/{pid}/attachments/99").status_code == 404


def test_resume_upload_parse_overwrites_content(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = _make_profile(client)
    from autooffer_core.profile.schema import Profile

    async def fake_parse(path: str, llm: Any) -> tuple[Profile, list[str]]:
        parsed = Profile.model_validate(sample_profile_payload())
        parsed.basic.name = "李四"
        return parsed, ["basic.birth_date"]

    monkeypatch.setattr("autooffer_core.profile.parser.parse_resume", fake_parse)

    async def fake_build_llm(self: Any, role: str = "actor") -> Any:
        return object()

    monkeypatch.setattr("autooffer_server.context.AppContext.build_llm", fake_build_llm)
    files = {"file": ("resume2.txt", b"name: lisi", "text/plain")}
    r = client.post(f"/api/v1/profiles/{pid}/resumes", files=files, data={"mode": "parse"})
    assert r.status_code == 200
    body = r.json()
    assert body["profile"]["basic"]["name"] == "李四"  # 内容被解析结果覆盖
    assert body["low_confidence_paths"] == ["basic.birth_date"]
    # 身份与附件保留：id 不变，新简历入库且为默认
    atts = body["profile"]["attachments"]
    assert (atts[-1]["meta"] or {}).get("active") == 1
    # 覆盖后 flat 正常出数据
    flat = client.get(f"/api/v1/profiles/{pid}/flat").json()
    assert any(v == "李四" for s in flat["sections"] for v in (s.get("values") or {}).values())


def test_resume_upload_bad_mode_and_missing_profile(client: TestClient) -> None:
    files = {"file": ("r.txt", b"x", "text/plain")}
    r = client.post("/api/v1/profiles/none/resumes", files=files, data={"mode": "replace"})
    assert r.status_code == 404
    pid = _make_profile(client)
    r = client.post(f"/api/v1/profiles/{pid}/resumes", files=files, data={"mode": "magic"})
    assert r.status_code == 422


# ---------- 应用设置（浏览器连接模式） ----------

def test_settings_default_and_update(client: TestClient) -> None:
    # 默认值
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    assert r.json() == {
        "browser_mode": "managed",
        "cdp_endpoint": "",
        "minimize_on_startup": False,
        "auto_submit": False,
        "service_port": 8765,
    }

    # 更新为 CDP 模式 + 开启自动提交 + 自定义服务端口
    r = client.put(
        "/api/v1/settings",
        json={
            "browser_mode": "cdp",
            "cdp_endpoint": "http://127.0.0.1:9222",
            "minimize_on_startup": True,
            "auto_submit": True,
            "service_port": 9100,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["browser_mode"] == "cdp"
    assert body["cdp_endpoint"] == "http://127.0.0.1:9222"
    assert body["minimize_on_startup"] is True
    assert body["auto_submit"] is True
    assert body["service_port"] == 9100

    # 已持久化
    assert client.get("/api/v1/settings").json()["browser_mode"] == "cdp"
    assert client.get("/api/v1/settings").json()["auto_submit"] is True
    assert client.get("/api/v1/settings").json()["service_port"] == 9100


def test_settings_rejects_invalid_browser_mode(client: TestClient) -> None:
    r = client.put(
        "/api/v1/settings",
        json={"browser_mode": "invalid", "cdp_endpoint": "", "minimize_on_startup": False},
    )
    assert r.status_code == 422


def test_settings_rejects_invalid_service_port(client: TestClient) -> None:
    """端口范围 1024-65535：特权端口和越界值直接 422，不让用户存进坑里。"""
    for bad in (80, 1023, 65536, "not-a-port"):
        r = client.put(
            "/api/v1/settings",
            json={
                "browser_mode": "managed",
                "cdp_endpoint": "",
                "minimize_on_startup": False,
                "service_port": bad,
            },
        )
        assert r.status_code == 422, bad
