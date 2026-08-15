"""AutoOffer CLI（开发/高级用户用；普通用户走桌面软件界面）。

命令：
- autooffer version                     版本信息
- autooffer probe                       探测模型端点（连通性 + 视觉能力）
- autooffer parse-resume <file>          简历 PDF/Word → 结构化档案 YAML（FR-P1）
- autooffer profile-template <out>       生成可手填的档案模板（FR-P2）
- autooffer fill <url>                   自动填写目标表单
- autooffer apps                         投递列表：查看 / 更新状态
- autooffer serve                        启动本地服务（REST + WebSocket，仅监听 127.0.0.1）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from autooffer_core import __version__


def _load_config(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        print(f"配置文件不存在: {path}（可从 config.example.yaml 复制）", file=sys.stderr)
        raise SystemExit(2)
    data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data


def _endpoint_from_config(cfg: dict[str, Any], endpoint_id: str | None) -> dict[str, Any]:
    endpoints: list[dict[str, Any]] = cfg.get("endpoints", [])
    if not endpoints:
        print("配置中没有任何模型端点", file=sys.stderr)
        raise SystemExit(2)
    target = endpoint_id or cfg.get("default_endpoint")
    for ep in endpoints:
        if ep.get("id") == target:
            return ep
    print(f"未找到端点 {target!r}", file=sys.stderr)
    raise SystemExit(2)


def _build_endpoint(ep_cfg: dict[str, Any]) -> Any:
    """配置字典 → ModelEndpoint。"""
    from autooffer_core.llm.interfaces import ModelEndpoint

    return ModelEndpoint(
        id=str(ep_cfg.get("id", "cli")),
        name=str(ep_cfg.get("name", ep_cfg.get("id", "cli"))),
        base_url=str(ep_cfg["base_url"]),
        api_key=ep_cfg.get("api_key", ""),
        model=str(ep_cfg["model"]),
        temperature=float(ep_cfg.get("temperature", 0.1)),
        max_tokens=int(ep_cfg.get("max_tokens", 4096)),
        timeout_s=int(ep_cfg.get("timeout_s", 600)),
        max_concurrency=int(ep_cfg.get("max_concurrency", 4)),
        extra_body=dict(ep_cfg.get("extra_body", {})),
    )


async def _probe(ep_cfg: dict[str, Any]) -> int:
    from autooffer_core.llm.probe import probe_endpoint

    result = await probe_endpoint(_build_endpoint(ep_cfg))
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.reachable else 1


async def _parse_resume(ep_cfg: dict[str, Any], file_path: str, out_path: str) -> int:
    """简历文件 → 结构化档案 YAML（FR-P1）。"""
    from autooffer_core.errors import AutoOfferError
    from autooffer_core.llm.client import ChatOpenAIClient
    from autooffer_core.profile.parser import parse_resume
    from autooffer_core.profile.store import save_profile

    llm = ChatOpenAIClient(_build_endpoint(ep_cfg))
    print(f"正在解析简历: {file_path}")
    try:
        profile, low_conf = await parse_resume(file_path, llm)
    except AutoOfferError as exc:
        print(f"解析失败: {exc}", file=sys.stderr)
        return 1

    save_profile(profile, out_path)
    print(f"\n已生成档案: {out_path}")
    print(
        f"姓名={profile.basic.name} 教育={len(profile.education)}条 "
        f"经历={len(profile.experiences)}条 技能={len(profile.skills)}项"
    )
    if low_conf:
        print("\n以下字段置信度较低，请打开档案文件确认后再使用：")
        for path in low_conf:
            print(f"  - {path}")
    print("\n下一步: autooffer fill <表单URL> --profile " + out_path)
    return 0


def _profile_template(out_path: str) -> int:
    """生成可手填的档案模板（FR-P2）：以示例档案为骨架，清空个人数据。"""
    from autooffer_core.profile.store import profile_to_yaml
    from autooffer_core.testing import build_sample_profile

    sample = build_sample_profile()
    text = profile_to_yaml(sample)
    header = (
        "# AutoOffer 档案模板：按注释替换为你自己的信息后保存。\n"
        "# 用法: autooffer fill <表单URL> --profile 本文件路径\n"
        "# 说明: 扩展信息(extended)按需填写——表单问到才会用到，没填的字段会记入待确认清单。\n"
        "# 敏感字段(身份证号/家庭成员电话)使用时会单独请求授权。\n\n"
    )
    Path(out_path).write_text(header + text, encoding="utf-8")
    print(f"已生成档案模板: {out_path}（内含示例数据，请替换为你自己的信息）")
    return 0


def app(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autooffer", description="AutoOffer 简历自动填写")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("version", help="显示版本")

    p_probe = sub.add_parser("probe", help="探测模型端点连通性与视觉能力")
    p_probe.add_argument("--config", default="config.yaml", help="配置文件路径")
    p_probe.add_argument("--endpoint", default=None, help="端点 id（默认取 default_endpoint）")

    p_parse = sub.add_parser("parse-resume", help="简历 PDF/Word → 结构化档案 YAML")
    p_parse.add_argument("file", help="简历文件路径（pdf/docx/txt）")
    p_parse.add_argument("--config", default="config.yaml")
    p_parse.add_argument("--out", default="profile.yaml", help="输出档案路径")

    p_tpl = sub.add_parser("profile-template", help="生成可手填的档案模板")
    p_tpl.add_argument("--out", default="profile.yaml", help="输出档案路径")

    p_fill = sub.add_parser("fill", help="自动填写简历表单")
    p_fill.add_argument("url", help="目标简历表单 URL")
    p_fill.add_argument("--config", default="config.yaml")
    p_fill.add_argument("--profile", required=False, help="档案 YAML 路径（缺省用示例档案）")
    p_fill.add_argument("--headless", action="store_true", help="无头模式（默认弹出浏览器窗口）")

    p_serve = sub.add_parser("serve", help="启动本地服务（供桌面界面调用）")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--data-dir", default=None, help="数据目录（默认 %%APPDATA%%/AutoOffer）")
    p_serve.add_argument("--headless", action="store_true", help="任务浏览器无头运行")

    p_apps = sub.add_parser("apps", help="投递列表：查看/更新状态")
    p_apps.add_argument("--mark", help="要更新状态的记录 id")
    p_apps.add_argument("--status", default="submitted",
                        choices=["filled", "submitted", "interview", "rejected", "abandoned"],
                        help="目标状态（配合 --mark）或过滤状态（配合 --filter-status）")
    p_apps.add_argument("--filter-status", action="store_true", help="按 --status 过滤列表")
    p_apps.add_argument("--note", help="备注")
    p_apps.add_argument("--store", help="自定义存储文件路径（默认 %%APPDATA%%/AutoOffer）")

    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"AutoOffer {__version__}")
        return 0
    if args.command == "probe":
        cfg = _load_config(args.config)
        ep = _endpoint_from_config(cfg, args.endpoint)
        return asyncio.run(_probe(ep))
    if args.command == "parse-resume":
        cfg = _load_config(args.config)
        ep_cfg = _endpoint_from_config(cfg, None)
        return asyncio.run(_parse_resume(ep_cfg, args.file, args.out))
    if args.command == "profile-template":
        return _profile_template(args.out)
    if args.command == "fill":
        cfg = _load_config(args.config)
        ep_cfg = _endpoint_from_config(cfg, None)
        return asyncio.run(_fill(args.url, ep_cfg, args.profile, headless=args.headless))
    if args.command == "serve":
        from autooffer_server.main import run as run_server

        print(f"本地服务启动中: http://127.0.0.1:{args.port}  (API 文档 /docs)")
        run_server(data_dir=args.data_dir, port=args.port, headless=args.headless)
        return 0
    if args.command == "apps":
        return _apps(args)

    parser.print_help()
    return 0


async def _fill(
    url: str, ep_cfg: dict[str, Any], profile_path: str | None, *, headless: bool
) -> int:
    from autooffer_core.actions.executor import ActionExecutor
    from autooffer_core.drivers.playwright_driver import PlaywrightDriver
    from autooffer_core.llm.interfaces import ModelEndpoint
    from autooffer_core.llm.probe import probe_endpoint
    from autooffer_core.llm.router import ModelRouterImpl
    from autooffer_core.profile.store import load_profile
    from autooffer_core.runner import AgentRunner
    from autooffer_core.testing import build_sample_profile

    ep = ModelEndpoint(
        id=str(ep_cfg.get("id", "cli")),
        name=str(ep_cfg.get("name", "cli")),
        base_url=str(ep_cfg["base_url"]),
        api_key=ep_cfg.get("api_key", ""),
        model=str(ep_cfg["model"]),
        temperature=float(ep_cfg.get("temperature", 0.1)),
        max_tokens=int(ep_cfg.get("max_tokens", 4096)),
        timeout_s=int(ep_cfg.get("timeout_s", 600)),
        max_concurrency=int(ep_cfg.get("max_concurrency", 4)),
        extra_body=dict(ep_cfg.get("extra_body", {})),
    )
    probe = await probe_endpoint(ep)
    if not probe.reachable:
        print(f"模型端点不可用: {probe.error}", file=sys.stderr)
        return 2
    ep = ep.model_copy(update={"supports_vision": bool(probe.supports_vision)})
    print(f"端点就绪: {ep.model} 视觉={probe.supports_vision} 时延={probe.latency_ms}ms")

    profile = load_profile(profile_path) if profile_path else build_sample_profile()
    # 示例档案的附件路径指向仓库内测试资产（存在才替换），保证上传链路可用
    assets = Path("tests/demo_forms/assets")
    for att in profile.attachments:
        cand = assets / Path(att.path).name
        if cand.exists():
            att.path = str(cand.resolve())
    print(f"档案: {profile.label}（{profile.basic.name}）")

    async def gate(reason: str) -> None:
        from autooffer_core.errors import AutoOfferError

        print(f"\n[需要人工处理] {reason}")
        try:
            await asyncio.to_thread(input, "请在浏览器中处理完成后回车继续...")
        except EOFError as exc:  # 无人值守（stdin 不可用）时安全终止而不是崩溃
            raise AutoOfferError(f"无人值守模式无法人工介入: {reason}") from exc

    driver = PlaywrightDriver(headless=headless)
    attachments = {a.label: a.path for a in profile.attachments}
    runner = AgentRunner(
        task_id=f"cli-{abs(hash(url)) % 10_000}",
        task_instruction="自动填写这份简历/求职表单：直接用档案内容填写页面上的所有表单字段，"
        "不要上传简历文件或任何附件；遇到文件上传控件请跳过并继续填写其余字段。"
        "填完等待用户审核，不要提交。",
        driver=driver,
        router=ModelRouterImpl(ep),
        executor=ActionExecutor(driver, attachments=attachments),
        profile=profile,
        on_event=lambda e: print(f"  [{e.seq:03d}] {e.kind}/{e.agent}: {e.summary}"),
        human_gate=gate,
    )
    try:
        report = await runner.run(url)
    finally:
        if headless:
            await driver.close()
        else:
            print("\n浏览器窗口保留，请人工审核后自行提交/关闭。")
    counts = report.counts()
    print(
        f"\n=== 填写报告 ===\n成功 {counts['filled']} | 失败 {counts['failed']} | "
        f"跳过 {counts['skipped']} | 待确认 {counts['pending_confirm']} | "
        f"tokens {report.total_tokens}"
    )
    for f in report.fields:
        print(f"  - {f.label}: {f.status}" + (f"（{f.note}）" if f.note else ""))

    # 自动登记投递列表（FR：填写过的岗位加入投递管理）
    from autooffer_core.applications import ApplicationStore

    record = ApplicationStore().add_from_report(report, page_title=report.page_title)
    print(
        f"\n已登记投递列表: [{record.id}] {record.company or '(公司待补)'} / "
        f"{record.position or '(岗位待补)'} 状态={record.status}"
    )
    print("提交后可执行: autooffer apps --mark " + record.id + " submitted")
    return 0


def _apps(args: argparse.Namespace) -> int:
    from autooffer_core.applications import ApplicationStore

    store = ApplicationStore(args.store) if args.store else ApplicationStore()
    if args.mark:
        record = store.update_status(args.mark, args.status, note=args.note)
        if record is None:
            print(f"未找到记录: {args.mark}", file=sys.stderr)
            return 1
        print(f"已更新 [{record.id}] -> {record.status}")
        return 0
    records = store.list(status=args.status if args.filter_status else None)
    if not records:
        print("投递列表为空。完成一次 fill 后会自动登记。")
        return 0
    print(f"{'ID':<14} {'状态':<10} {'公司':<16} {'岗位':<14} {'填写':<4} {'时间'}")
    for r in records:
        print(
            f"{r.id:<14} {r.status:<10} {(r.company or '-'):<16} "
            f"{(r.position or '-'):<14} {r.fields_filled:<4} {r.filled_at}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(app())
