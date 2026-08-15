# AutoOffer CLI（cli）

面向开发者 / 高级用户的命令行入口；普通用户走桌面软件界面。

## 命令

| 命令 | 说明 |
| --- | --- |
| `autooffer version` | 版本信息 |
| `autooffer probe` | 探测模型端点连通性与视觉能力 |
| `autooffer parse-resume <file>` | 简历 PDF/Word → 结构化档案 YAML |
| `autooffer profile-template --out <yaml>` | 生成可手填的档案模板 |
| `autooffer fill <url>` | 自动填写目标表单（默认弹出浏览器窗口） |
| `autooffer apps` | 投递列表查看 / 更新状态 |
| `autooffer serve` | 启动本地服务（REST + WebSocket） |

入口：`cli/main.py:app`（`pyproject.toml` 中注册为 `autooffer`）。

## 单独测试

CLI 主要作为其它模块的组合入口，行为由 core / server 的测试间接覆盖；手动验证：

```bash
pip install -e ".[dev]"
autooffer version
autooffer profile-template --out /tmp/profile.yaml
```
