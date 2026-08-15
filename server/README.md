# AutoOffer 本地服务（autooffer_server）

随桌面软件启动的本地 FastAPI 服务，把 Agent Core 的能力包装为 REST + WebSocket 任务队列。仅监听 `127.0.0.1`（FR-D3）。

## 职责

- REST API（前缀 `/api/v1`）与任务事件 WebSocket（`/ws/tasks/{id}`）
- 任务队列与状态机（`QUEUED → RUNNING ⇄ WAITING_HUMAN → AWAITING_REVIEW → DONE/FAILED/CANCELLED`）
- SQLite 存储（档案 / 模型端点 / 角色路由 / 任务 / 审计事件）
- api_key 系统级加密存储（Windows DPAPI，经 `keyring`）
- 挂载前端构建产物（SPA 回退），无产物时纯 API 模式

## 公共接口

| 符号 | 说明 |
| --- | --- |
| `create_app(config=None, *, ctx=None, frontend_dir=None)` | 应用工厂；`ctx` 可注入测试替身，`frontend_dir` 显式指定前端产物目录 |
| `run(**kwargs)` | 启动 Uvicorn（供 CLI `serve` 与桌面启动器调用） |
| `ServerConfig` | 数据目录 / 主机 / 端口 / 并发 / headless 配置 |
| `AppContext` | 依赖装配（仓储 / 事件总线 / 密钥库 / 调度器） |

API 契约详见 `server/autooffer_server/api/schemas.py` 与 `docs/03-详细设计.md §5`。

## 单独测试

```bash
pip install -e ".[dev]"
python -m pytest tests/integration/server -q    # 服务集成测试（用假执行体，无需模型/浏览器）
```

启动：

```bash
python -m cli.main serve --port 8765            # 打开 http://127.0.0.1:8765/docs
```
