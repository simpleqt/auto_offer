# AutoOffer — 校招/社招网申自动填写智能体（本地桌面软件 + 浏览器插件）

AI 驱动的求职表单自动填写系统 — 上传一次简历，任意招聘网站一键智能填写，告别重复劳动。

**以插件为「手」、本地服务为「脑」**：页面上能规则匹配的字段零 AI 直接写入，冷门问法才由 AI 做语义映射——快、省 token，且**档案值永不出本机**。

## ✨ 核心功能

| 功能 | 说明 |
| --- | --- |
| ⚡ 一键智能填写 | 打开网申页面 → 点插件「开始填写」→ 文本/下拉/日期/级联/附件上传全类型字段自动填 |
| 🧠 两段式匹配引擎 | 第一段本地规则直填（零 LLM、零数据外发）→ 未命中字段送 AI 标签映射（LLM **只见标签不见值**）+ AI 选选项（级联逐层下钻） |
| 🧩 通用控件引擎 | 日历/月份面板/省市区级联/搜索型下拉/组合行/「至今」开关按**行为与内容特征**识别，不为单个网站写适配——华为 AUI、北森 Phoenix、Moka、飞书、智联等自研组件库实测通过 |
| 📄 简历智能解析 | 上传 PDF/Word 简历 → AI 自动提取结构化档案（经历描述逐字保留原文），可编辑确认 |
| 👤 档案中心 | 多档案管理 + 完整度评分提示「还能补什么」；覆盖民族/学制/婚姻/生源地/户口等官网常问字段 |
| 📚 复杂表单 | 多条教育经历自动补块、实习/工作/项目/科研四类经历分库、获奖模块、项目地址自动并入项目描述、多步向导翻页 |
| 📝 填写报告 | 逐字段列出 已填/纠正/跳过/失败 及原因；站点简历解析产生的错误预填自动纠偏；全程动作流水可追溯 |
| 📮 投递台账 | 填写完成自动登记（公司/岗位自动识别、同 URL 去重），状态跟踪：已填写/已提交/面试中/已拒/放弃 |
| 🔒 敏感字段保护 | 身份证号/家庭情况默认剔除，弹窗「包含敏感字段」按次授权后才下发 |
| 🛑 永不自动提交 | 只填不投——`auto_submit` 默认关闭，检查无误后由你手动提交；验证码/扫码登录始终由人工完成 |
| 🌙 暗色模式 | 亮/暗/跟随系统三态，随系统自动切换 |
| 💾 数据全本地 | 档案、配置、日志全部存本机 `%APPDATA%\AutoOffer`，服务只监听 127.0.0.1 |

**真站实测**：华为、海格通信（北森 zhiye）、满帮（Moka）、飞书招聘、大华、游卡、柏楚电子等真实申请页面。

## 🛠 技术栈

- **后端**：Python 3.11 + FastAPI + SQLite（SQLAlchemy）+ WebSocket
- **Agent Core**：LangChain（`langchain-openai`）、Playwright（传统外驱模式）、Pydantic v2
- **界面**：React + TypeScript + Vite + Ant Design（三态主题）
- **插件**：Chrome/Edge Manifest V3
- **桌面壳**：pywebview + PyInstaller + Inno Setup（Windows 安装包）
- **模型**：任意 OpenAI 兼容端点（界面可配多个，按智能体角色路由）
- **工程**：ruff + mypy、pytest（256 项）、GitHub Actions

## 🚀 安装使用

### 方式一：源码运行（开发者）

```bash
pip install -e ".[dev]"
playwright install chromium          # 可选：传统模式需要

# 桌面软件（本地服务 + 原生窗口界面一步启动）
python -m app.launcher               # 加 --port 可改端口，避免冲突

# 前端开发模式（Vite 代理到 8765）
cd frontend && npm install && npm run dev
```

### 方式二：安装包

```bash
python scripts/build_installer.py    # 产出 AutoOffer-Setup.exe（Inno Setup）
```

或从 GitHub Release 下载安装程序，双击安装即用。

### 安装浏览器插件

1. 启动桌面软件（本地服务默认 `http://127.0.0.1:8765`）
2. 打开 `edge://extensions`（Chrome 为 `chrome://extensions`）
3. 开启「开发人员模式」→「加载解压缩的扩展」→ 选择仓库 `extension/` 目录
4. 也可运行 `python scripts/package_extension.py` 生成 zip 从 Release 下载

### 使用流程

1. **配模型**：软件「模型配置」页添加 OpenAI 兼容端点（自动探测连通性）
2. **建档案**：「档案中心」上传简历 PDF/Word 自动解析，或手动填写；完整度评分提示补充
3. **去填写**：打开网申页面 → 点插件图标 →「授权连接」→ 选档案 →「开始填写」，弹窗实时显示当前阶段
4. **检查提交**：按填写报告核对，确认无误后手动提交

## 🏗 架构

```
┌─────────────────────────────────────────────────────┐
│  浏览器插件（Chrome MV3，推荐填写方式）                  │
│  站点适配器 / 规则直填引擎 / 通用控件 / 附件注入         │
├─────────────────────────────────────────────────────┤
│  桌面客户端（原生窗口，pywebview 承载 React 界面）       │
│  档案管理 / 模型配置 / 任务监控 / 回放 / 投递台账        │
├─────────────────────────────────────────────────────┤
│  本地服务（FastAPI，随软件启动，仅监听 127.0.0.1）      │
│  REST + WebSocket / AI 映射与选选项 / 档案存储 / 审计  │
├─────────────────────────────────────────────────────┤
│  Agent Core（Python 包，可独立使用）                   │
│  Planner–Actor–Validator 循环 / 简历解析 / 传统模式    │
└─────────────────────────────────────────────────────┘
```

### 项目结构

```
core/        Agent Core：简历解析 / LLM 接口 / 多智能体（传统模式）
server/      本地服务：档案 / AI 映射 / 选项匹配 / 任务 / 审计 / 投递
extension/   浏览器插件：规则引擎 / 控件填充 / 弹窗（详见 extension/README.md）
frontend/    React + AntD 界面
app/         桌面壳 launcher（pywebview + 系统托盘图标）
scripts/     打包 / 测试资产脚本
tests/       256 项测试：单元 + 集成 + 插件引擎真实 Chromium 基准页
docs/        需求 / 架构 / 详细设计 / 开发规范等设计文档
```

## 🔒 隐私安全

- ✅ 档案、投递记录、日志全部只存本机（`%APPDATA%\AutoOffer`），不上传任何服务器
- ✅ AI 字段映射只发送页面标签与档案字段目录，**档案值不出本机**
- ✅ API Key 存入 Windows 凭据管理器（DPAPI），数据库只保存掩码
- ✅ 本地服务只监听 127.0.0.1，浏览器扩展权限最小化（activeTab + scripting + storage）
- ✅ 永不自动提交、不触碰验证码与扫码登录，敏感动作人工确认
- ✅ 开源代码，可审计

## 🧪 测试与开发

```bash
python -m pytest tests/unit -q                      # 单元测试（离线，无需模型）
python -m pytest tests/integration -q               # 感知/服务/插件引擎集成测试
python -m pytest tests/integration/extension -q     # 插件规则直填引擎专项（真实 Chromium）
cd frontend && npx vitest run                       # 前端测试（含完整度双语言契约）
```

### CLI 快速使用（Agent Core 独立能力）

```bash
python -m cli.main probe                                   # 检查模型端点
python -m cli.main parse-resume 我的简历.pdf --out p.yaml  # 简历 → 结构化档案
python -m cli.main fill "https://example.com/apply" --profile p.yaml   # 传统模式自动填写
python -m cli.main serve --port 8765                       # 仅起本地服务
```

## 📖 文档索引

| 文档 | 内容 |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | 版本演进 |
| [extension/README.md](extension/README.md) | 插件权限模型与使用细节 |
| [docs/01-需求规格说明书.md](docs/01-需求规格说明书.md) | 用户故事、功能/非功能需求、验收标准 |
| [docs/02-总体架构设计.md](docs/02-总体架构设计.md) | 分层架构、多智能体设计、数据流 |
| [docs/03-详细设计.md](docs/03-详细设计.md) | 模块接口、复杂控件处理器、提示词策略 |
| [docs/05-开发规范.md](docs/05-开发规范.md) | 代码规范、测试策略、CI、日志与安全规范 |

## 免责声明

本项目仅用于辅助个人求职者减少重复填表劳动，填写结果需人工审核后自行提交。请遵守目标网站的服务条款，不要用于批量刷投、爬取数据等违反平台规则的行为。
