"""AutoOffer 本地服务（FastAPI）。

随桌面软件启动，仅监听 127.0.0.1（FR-D3）；对外提供 REST + WebSocket，
把 Agent Core 的能力包装为任务队列 + 状态机 + 审计留痕。

模块：
- config.py      数据目录与运行参数
- context.py     依赖装配（存储/密钥库/调度器/模型路由）
- db/            SQLAlchemy 模型与仓储
- services/      密钥库、事件总线、任务调度、Agent 执行体适配
- api/           REST 路由
- ws/            任务事件 WebSocket
- main.py        应用工厂 create_app / run
"""

from autooffer_server.config import ServerConfig
from autooffer_server.context import AppContext
from autooffer_server.main import create_app, run

__all__ = ["AppContext", "ServerConfig", "create_app", "run"]
