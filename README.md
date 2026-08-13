# AutoOffer — 通用简历自动填写智能体（桌面软件）

AutoOffer 是一款基于多智能体（Multi-Agent）架构的**桌面软件**（Windows 优先），用于自动填写任意招聘网站的简历/求职表单。用户安装软件后，只需上传一次个人信息（简历 PDF/Word 或结构化模板）、在设置页配置好模型端点，即可在任意招聘网页上自动完成简历填写——包括文本输入、下拉选择、日期与日期区间选择、级联选择、文件上传等复杂控件，填写完毕后交由用户审核提交。

> 定位：**泛化优先 + 开箱即用**。不针对单一网站写死脚本，而是通过"感知—规划—执行—校验"的智能体循环适配任意简历表单页面；以安装包形式交付，普通用户无需命令行。

---

## 核心特性

| 特性 | 说明 |
| --- | --- |
| 通用表单泛化 | DOM 结构化感知 + 截图视觉辅助（Set-of-Marks），适配任意招聘网站，无需为单站写脚本 |
| 多智能体协作 | Planner（任务拆分）/ Actor（执行）/ Validator（校验）三角色循环，参考 Skyvern 2.0 验证过的架构 |
| 复杂控件处理 | 原生与自定义下拉、日历式日期选择器、日期区间（实习/项目起止）、级联省市区、单选/复选、富文本 |
| 附件自动上传 | 简历/证件照/成绩单自动上传（隐藏 input、文件选择器、拖拽区三种形态），按站点格式与大小要求自动匹配附件、超限图片自动压缩 |
| 官网场景适配 | 登录墙/隐私弹窗/职位列表入口/多步向导/草稿保存/会话超时/重复投递等场景库；对"上传简历自动解析回填"类官网自动进入核对修正模式 |
| 档案中心 | 上传简历 PDF/Word 自动解析为结构化档案（来源文件自动登记为可上传附件），或手动填写模板；扩展信息体系覆盖性格、爱好、语言等级、获奖、家庭成员等官网常问字段，**按需注入**——表单不问就不提供；开放性问题由 LLM 基于档案生成回答 |
| 投递列表 | 填写完成自动登记投递记录（公司/岗位自动识别、同 URL 去重），支持状态跟踪：已填写 / 已提交 / 面试中 / 已拒 / 放弃 |
| 应用端模型配置 | 界面管理多个 OpenAI 兼容模型端点，自动探测连通性与视觉能力，不同智能体角色可绑定不同模型 |
| 任务管理 | 任务队列、多任务并行、暂停/恢复/人工接管、WebSocket 实时进度与截图流 |
| 安全与审计 | 默认不自动提交、敏感动作人工确认、API Key 加密存储、全程动作留痕可回放 |

## 当前进度

Agent Core 已可用（CLI 形态），服务层与图形界面在建设中。基准表单集（`tests/demo_forms/`）真实模型端到端验收情况：

| 基准页 | 覆盖场景 | 状态 |
| --- | --- | --- |
| demo-1 简单单页 | 基础控件、原生下拉、日期、必填校验 | 通过（13/13 字段） |
| demo-2 复杂控件 | 自定义下拉、三级级联、日历式日期区间、富文本 | 通过 |
| demo-3 多步向导 | 步骤条、步间校验、动态添加经历、预览页 | 通过 |
| demo-4 简历优先 | 文件上传 + 站点解析回填 → 核对修正模式 | 通过 |
| demo-5 中文官网 | 隐私弹窗、政治面貌/入党时间、家庭成员表格、证件照上传 | 通过 |

## 软件形态

以桌面应用交付：原生窗口（pywebview 承载 React 界面）+ 本地服务进程，使用 PyInstaller + Inno Setup 打包为 Windows 安装程序；用户数据（档案、模型配置、任务历史）全部保存在本机 `%APPDATA%\AutoOffer`。

```
┌─────────────────────────────────────────────────────┐
│  桌面客户端（原生窗口，pywebview 承载 React + TS 界面）  │
│  档案管理 / 模型配置 / 任务发起 / 实时监控 / 历史回放     │
├─────────────────────────────────────────────────────┤
│  本地服务（FastAPI，随软件启动，仅监听 127.0.0.1）       │
│  REST API + WebSocket / 任务队列 / 配置与档案存储       │
├─────────────────────────────────────────────────────┤
│  Agent Core（Python 包，可独立使用）                   │
│  Planner–Actor–Validator 循环 / 感知 / 动作 / 控件处理  │
├─────────────────────────────────────────────────────┤
│  执行环境：Playwright（Chromium）                      │
└─────────────────────────────────────────────────────┘
```

## 使用流程（目标体验）

1. 下载安装包 `AutoOffer-Setup.exe`，双击安装并启动。
2. 首次启动进入引导：在「模型配置」页添加你的 OpenAI 兼容模型端点（软件自动测试连通性与视觉能力）。
3. 在「档案中心」上传简历 PDF/Word（自动解析为结构化档案，可编辑确认），或直接手动填写模板。
4. 在「任务」页粘贴目标简历页 URL，点击开始；软件弹出受控浏览器窗口自动填写，界面实时显示进度与截图。
5. 遇到登录/验证码时软件暂停并提醒你手动处理；填写完成后生成填写报告，你检查无误后手动点击提交。

## 现在就能用（CLI）

图形界面完成前，Agent Core 已可通过命令行完整使用：

```bash
pip install -e ".[dev]"
playwright install chromium
cp config.example.yaml config.yaml       # 填入你的模型端点与 api_key

# 1. 检查模型端点（连通性 + 是否支持视觉输入）
python -m cli.main probe

# 2. 建立个人档案：解析简历，或生成模板手填
python -m cli.main parse-resume 我的简历.pdf --out profile.yaml
python -m cli.main profile-template --out profile.yaml

# 3. 自动填写目标表单（省略 --headless 会弹出浏览器窗口实时观看）
python -m cli.main fill "https://example.com/apply" --profile profile.yaml

# 4. 查看投递列表 / 标记已提交
python -m cli.main apps
python -m cli.main apps --mark app-1a2b3c4d --status submitted
```

填写完成后浏览器窗口保留、**不会自动提交**，请自行检查填写报告后手动提交。

## 开发者快速开始

> 服务层与界面处于建设中，以下为目标开发方式。

```bash
# 后端 + Agent Core
pip install -e ".[dev]"
playwright install chromium
python -m autooffer serve --dev          # 以开发模式启动本地服务

# 前端
cd frontend && npm install && npm run dev

# 桌面模式启动（加载前端构建产物）
python -m autooffer app

# 打包 Windows 安装程序
python scripts/build_installer.py

```

## 测试

```bash
python -m pytest tests/unit -q                      # 单元测试（离线，无需模型）
python -m pytest tests/integration -q               # 感知/控件集成测试（需 Chromium）
python scripts/make_test_resume_pdf.py              # 重新生成测试简历 PDF 资产
```

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/01-需求规格说明书.md](docs/01-需求规格说明书.md) | 用户故事、功能需求（FR）、非功能需求（NFR）、验收标准 |
| [docs/02-总体架构设计.md](docs/02-总体架构设计.md) | 分层架构、多智能体设计、任务拆分机制、数据流、技术选型 |
| [docs/03-详细设计.md](docs/03-详细设计.md) | 各模块接口与数据模型、复杂控件处理器、API 设计、提示词策略 |
| [docs/04-开源方案调研.md](docs/04-开源方案调研.md) | browser-use / Skyvern / AIHawk / Qwen-CUA 等方案对比与借鉴点 |
| [docs/05-开发规范.md](docs/05-开发规范.md) | 代码规范、分支与提交规范、测试策略、CI、日志与安全规范 |
| [docs/06-任务拆分与并行开发计划.md](docs/06-任务拆分与并行开发计划.md) | 工作流拆分（Workstream）、接口契约、多子智能体并行开发分工 |

## 技术栈

- **Agent Core**：Python 3.11+、Playwright、LangChain（`langchain-openai`）、Pydantic v2
- **本地服务**：FastAPI、Uvicorn、SQLite（SQLAlchemy）、WebSocket
- **界面**：React 18、TypeScript、Vite、Ant Design
- **桌面壳与打包**：pywebview、PyInstaller、Inno Setup（Windows 安装程序）
- **模型**：任意 OpenAI 兼容端点（默认对接 vLLM 部署的 Qwen 系列多模态模型）
- **工程**：ruff + mypy、pytest、pre-commit、GitHub Actions

## 免责声明

本项目仅用于辅助个人求职者减少重复填表劳动，填写结果需人工审核后自行提交。请遵守目标网站的服务条款，不要用于批量刷投、爬取数据等违反平台规则的行为。
