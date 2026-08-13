"""AutoOffer CLI（开发/高级用户用；普通用户走桌面软件界面）。

命令：
- autooffer version                     版本信息
- autooffer probe --config config.yaml  探测配置中的模型端点（连通性 + 视觉能力）
- autooffer fill <url> ...              自动填写（I1 集成阶段接入 Runner 后可用）
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


async def _probe(ep_cfg: dict[str, Any]) -> int:
    # 延迟导入：探测实现由 W4 提供（llm.probe）。尚未合入时给出提示。
    try:
        from autooffer_core.llm.interfaces import ModelEndpoint
        from autooffer_core.llm.probe import probe_endpoint  # type: ignore[import-not-found]
    except ImportError:
        print("探测实现尚未集成（W4 llm.probe），请先完成集成阶段 I1。", file=sys.stderr)
        return 1

    ep = ModelEndpoint(
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
    result = await probe_endpoint(ep)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    return 0 if result.reachable else 1


def app(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autooffer", description="AutoOffer 简历自动填写")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("version", help="显示版本")

    p_probe = sub.add_parser("probe", help="探测模型端点连通性与视觉能力")
    p_probe.add_argument("--config", default="config.yaml", help="配置文件路径")
    p_probe.add_argument("--endpoint", default=None, help="端点 id（默认取 default_endpoint）")

    p_fill = sub.add_parser("fill", help="自动填写简历表单")
    p_fill.add_argument("url", help="目标简历表单 URL")
    p_fill.add_argument("--config", default="config.yaml")
    p_fill.add_argument("--profile", required=False, help="档案 YAML 路径（缺省用示例档案）")
    p_fill.add_argument("--headless", action="store_true", help="无头模式（默认弹出浏览器窗口）")

    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"AutoOffer {__version__}")
        return 0
    if args.command == "probe":
        cfg = _load_config(args.config)
        ep = _endpoint_from_config(cfg, args.endpoint)
        return asyncio.run(_probe(ep))
    if args.command == "fill":
        cfg = _load_config(args.config)
        ep_cfg = _endpoint_from_config(cfg, None)
        return asyncio.run(_fill(args.url, ep_cfg, args.profile, headless=args.headless))

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
        task_instruction="自动填写这份简历/求职表单；填完等待用户审核，不要提交。",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(app())
