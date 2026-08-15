# AutoOffer 桌面壳（app）

原生窗口壳，负责启动本地服务并承载前端界面（pywebview）。

## 职责

- 找空闲端口 → 线程内起 Uvicorn（仅监听 127.0.0.1）→ 轮询健康检查 → 打开窗口
- 单实例锁（Windows 命名互斥量 / 其它平台锁文件）
- pywebview 未安装时退化为「起服务 + 打印地址 + 前台等待」（无 GUI 环境可验证启动流程）

## 公共接口

| 符号 | 说明 |
| --- | --- |
| `app.launcher:main` | 启动入口（`pyproject.toml` 注册为 `autooffer-app`） |
| `_find_free_port` | 空闲端口查找（可单元测试） |

## 启动

```bash
# 需先构建前端产物（frontend/dist）
cd frontend && npm run build
cd ..
python -m app.launcher            # 或 autooffer-app
python -m app.launcher --no-window # 仅起服务不弹窗口（调试）
```

## 打包

```bash
python scripts/build_installer.py  # npm build → PyInstaller → 复制 Chromium → Inno Setup
```

## 单独测试

```bash
python -m pytest tests/unit/test_launcher.py -q   # 端口查找等纯逻辑（离线）
```

GUI 窗口与 Windows 命名互斥量依赖真实桌面环境，无法离线覆盖。
