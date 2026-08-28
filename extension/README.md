# AutoOffer 浏览器插件（MV3）—— 规则直填 M1

以浏览器插件为「手」、本地服务为「脑」的轻量实现：页面上能规则匹配的字段零 LLM
直接写入，数据不出本机。

## 架构

```
popup(选档案/授权) ──▶ background(SW)
                        │  fetch http://127.0.0.1:8765
                        │   GET /api/v1/profiles/{id}/flat[?sensitive=true]
                        ▼
              content.js（规则直填引擎）
                站点适配器(智易/Moka/北森/牛客/智联 + 框架兜底)
                标签扫描 → 本地评分(textMatchScore) + 硬否决
                         （上传类 / 家庭域 / 值形冲突）
                → setNativeValue 原生注入(React 兼容)
                → 自定义下拉三段降级（点开 → portal 选项匹配 → 搜索框注入重试）
```

- 评分与注入设计参考 OpenJobAutofill（MIT），源码归档于 `reference/OpenJobAutofill/`。
- 敏感字段（身份证号、家庭情况等）默认不输出，弹窗勾选授权后才随 `sensitive=true` 下发。
- 值形/标签语义冲突硬否决来自 Playwright 路线的实战修复（手机号形状的值禁止写入身高/日期类标签）。

## 安装（开发者模式）

1. 启动本地服务：仓库根目录 `.venv/Scripts/python.exe -m app.launcher`
   （健康检查 http://127.0.0.1:8765/api/health）。
2. Chrome 打开 `chrome://extensions` → 开启「开发者模式」→「加载已解压的扩展程序」→ 选择本目录。
3. 打开目标招聘表单页 → 点击插件图标 → 「授权连接」本地服务 → 选择档案 → 「开始填写」。

权限模型：`activeTab + scripting + storage`，站点源与本地服务源均在点击时按需申请
（`optional_host_permissions`），不常驻任何站点访问权。

## M1 已知边界

- repeat 档案区块（教育/实习/工作/项目经历）只匹配**第一条**；多条目「添加再填写」属 M3。
- 附件上传字段一律跳过并提示手动上传（M3 处理）。
- 无 AI 字段映射通道：规则分低于阈值的字段计入「跳过」（M2 在本地服务上加 `/api/v1/mapping`）。
- 不触碰验证码/登录；自动提交不在插件范围内（沿用本地服务 auto_submit 设置语义，M3 接入）。

## 测试

```bash
# 引擎集成测试（真实 Chromium + fixture 基准页注入 content.js）
.venv/Scripts/python.exe -m pytest tests/integration/extension -q
# 扁平档案接口
.venv/Scripts/python.exe -m pytest tests/integration/server/test_profile_flat.py -q
```
