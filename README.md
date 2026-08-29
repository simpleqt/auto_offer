# AutoOffer — 通用简历自动填写智能体（桌面软件 + 浏览器插件）

AutoOffer 是一款基于多智能体（Multi-Agent）架构的**桌面软件**（Windows 优先），用于自动填写任意招聘网站的简历/求职表单。用户安装软件后，只需上传一次个人信息（简历 PDF/Word 或结构化模板）、在设置页配置好模型端点，即可在任意招聘网页上自动完成简历填写——包括文本输入、下拉选择、日期与日期区间选择、级联选择、文件上传等复杂控件，填写完毕后交由用户审核提交。

> **v0.2.0 架构升级**：填写层迁移为**浏览器插件**（MV3）——以插件为「手」、本地服务为「脑」：页面上能规则匹配的字段零 LLM 直接写入，冷门问法由 AI 仅做「字段语义映射」，档案值永不出本机。原 Playwright 外驱路线保留为传统模式。

---

## 核心特性

| 特性 | 说明 |
| --- | --- |
| **浏览器插件直填（推荐）** | Edge/Chrome 加载 `extension/` 即用：站点适配器（智易/北森 Phoenix、Moka、牛客、智联 + Ant/Element 兜底）+ 本地标签评分直填（含学历下拉、自绘单选、日历/月份选择器、「至今」开关）+ 多条教育经历自动补块 + 附件注入 |
| 规则优先、AI 兜底 | 两段式填写：第一段本地规则直填（零 LLM、零数据外发）；未命中字段送 AI 标签映射（LLM 只见标签不见值），固定选项字段由 AI 选选项（级联逐层下钻） |
| 通用表单泛化 | DOM 结构化感知 + 截图视觉辅助（Set-of-Marks），适配任意招聘网站，无需为单站写脚本（传统模式） |
| 多智能体协作 | Planner（任务拆分）/ Actor（执行）/ Validator（校验）三角色循环（传统模式） |
| 复杂控件处理 | 原生与自定义下拉、日历式日期选择器、日期区间（实习/项目起止）、级联省市区、单选/复选、富文本 |
| 附件自动上传 | 档案附件按用途标签自动匹配（简历/证件照/成绩单），插件内 File + DataTransfer 注入；超限图片自动压缩（传统模式） |
| 官网场景适配 | 登录墙/隐私弹窗/职位列表入口/多步向导/草稿保存/会话超时/重复投递等场景库；对"上传简历自动解析回填"类官网自动进入核对修正模式 |
| 档案中心 | 上传简历 PDF/Word 自动解析为结构化档案（来源文件自动登记为可上传附件），或手动填写模板；覆盖国籍/工作年限/期望行业/月薪等官网常问字段；敏感字段（身份证号/家庭情况）默认剔除、单独授权后才下发 |
| 投递列表 | 填写完成自动登记投递记录（公司/岗位自动识别、同 URL 去重），支持状态跟踪：已填写 / 已提交 / 面试中 / 已拒 / 放弃 |
| 应用端模型配置 | 界面管理多个 OpenAI 兼容模型端点，自动探测连通性与视觉能力，不同智能体角色可绑定不同模型 |
| 安全与审计 | 默认不自动提交、敏感动作人工确认、API Key 加密存储、全程动作留痕可回放；插件不触碰验证码/扫码登录 |

## 当前进度（v0.2.0）

插件化迁移 M1–M4 完成，浏览器插件为推荐填写方式；传统 Playwright 模式完整保留。

| 层 | 状态 |
| --- | --- |
| 浏览器插件（MV3：规则直填引擎 + 两段式 AI 编排） | 已完成，北森（柏楚电子）真实申请表单实测 29 字段填对/0 错填 |
| 本地服务（REST + WebSocket + 任务队列 + 审计 + 映射/选选项通道） | 已完成 |
| 桌面界面（React + TS，模型配置/档案中心/任务监控/回放/投递/设置） | 已实现 |
| 桌面壳与安装包（pywebview 启动器 + PyInstaller/Inno Setup 流水线） | 已实现脚本，待干净 Windows 环境打包验收 |

## 软件形态

以桌面应用交付：原生窗口（pywebview 承载 React 界面）+ 本地服务进程，使用 PyInstaller + Inno Setup 打包为 Windows 安装程序；用户数据（档案、模型配置、任务历史）全部保存在本机 `%APPDATA%\AutoOffer`。

```
┌─────────────────────────────────────────────────────┐
│  浏览器插件（Chrome MV3，推荐填写方式）                  │
│  站点适配器 / 标签评分直填 / 自定义控件 / 附件注入        │
├─────────────────────────────────────────────────────┤
│  桌面客户端（原生窗口，pywebview 承载 React + TS 界面）  │
│  档案管理 / 模型配置 / 任务发起 / 实时监控 / 历史回放     │
├─────────────────────────────────────────────────────┤
│  本地服务（FastAPI，随软件启动，仅监听 127.0.0.1）       │
│  REST API + WebSocket / AI 映射与选选项 / 档案存储     │
├─────────────────────────────────────────────────────┤
│  Agent Core（Python 包，可独立使用）                   │
│  Planner–Actor–Validator 循环 / 感知 / 动作 / 控件处理  │
├─────────────────────────────────────────────────────┤
│  传统模式执行环境：Playwright（Chromium，可选）          │
└─────────────────────────────────────────────────────┘
```

## 浏览器插件快速上手（推荐）

1. 启动本地服务：`python -m app.launcher`（健康检查 http://127.0.0.1:8765/api/v1/system/health）。
2. 安装插件（Edge / Chrome 通用，二选一）：
   - **加载仓库目录**（开发推荐）：Edge 打开 `edge://extensions`（Chrome 为 `chrome://extensions`）→ 开「开发人员模式」→「加载解压缩的扩展」→ 选择仓库 `extension/` 目录。
   - **安装打包 zip**：`python scripts/package_extension.py` 生成（或从 GitHub Release 附件下载）`dist/AutoOffer-Extension-<版本>.zip`，解压到固定目录后按上法加载该目录。
3. 打开目标招聘表单页 → 点插件图标 → 「授权连接」→ 选档案 → 「开始填写」。只填不提交，检查无误后手动提交。

权限模型：`activeTab + scripting + storage`，站点源与本地服务源均在点击时按需申请；微信扫码/验证码类登录由用户人工完成。详见 [extension/README.md](extension/README.md)。

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

## 本地服务（供界面/脚本调用）

```bash
python -m cli.main serve --port 8765        # 仅监听 127.0.0.1
# 打开 http://127.0.0.1:8765/docs 查看交互式 API 文档
```

主要接口（前缀 `/api/v1`）：

| 接口 | 说明 |
| --- | --- |
| `GET /system/health` | 健康检查与数据目录 |
| `PUT /models`、`POST /models/{id}/probe` | 模型端点管理与能力探测（响应中 api_key 恒为掩码） |
| `GET/PUT /models/routing` | 智能体角色 → 端点路由 |
| `POST /profiles/parse-resume` | 上传简历文件解析入库 |
| `GET/PUT/DELETE /profiles[/{id}]` | 档案管理 |
| `GET /profiles/{id}/flat[?sensitive=true]` | 扁平档案（插件直填引擎消费；敏感字段默认剔除） |
| `GET /profiles/{id}/attachments/{index}` | 附件字节下载（插件上传通道） |
| `POST /mapping` | AI 字段映射（仅标签，档案值不出服务） |
| `POST /option-match` | AI 选选项（固定选项字段：值 → 选项） |
| `POST /tasks`、`GET /tasks[/{id}]` | 创建与查询填写任务 |
| `POST /tasks/{id}/resume`、`/cancel` | 人工处理完成后继续、取消任务 |
| `GET /tasks/{id}/events` | 审计事件（回放数据源） |
| `WS /ws/tasks/{id}` | 实时事件流（含历史回放） |
| `GET/PUT/DELETE /applications[/{id}]` | 投递列表与状态更新 |

api_key 存入系统凭据管理器（Windows DPAPI），数据库只保存掩码提示；任务浏览器默认可见以便人工接管，遇登录/验证码时任务转入 `WAITING_HUMAN` 等待 `resume`。

## 开发者快速开始

> 服务层与界面处于建设中，以下为目标开发方式。

```bash
# 后端 + Agent Core
pip install -e ".[dev]"
playwright install chromium
python -m cli.main serve --port 8765        # 以开发模式启动本地服务

# 前端（开发模式，Vite 代理到 8765）
cd frontend && npm install && npm run dev

# 桌面模式启动（先 npm run build 产出 frontend/dist，再起本地服务并加载界面）
python -m app.launcher

# 打包 Windows 安装程序
python scripts/build_installer.py

```

## 测试

当前：223 项测试通过（含插件引擎真实 Chromium 集成测试），ruff 与 mypy 零问题。

```bash
python -m pytest tests/unit -q                      # 单元测试（离线，无需模型）
python -m pytest tests/integration -q               # 感知/服务/插件引擎集成测试（需 Chromium）
python -m pytest tests/integration/extension -q     # 插件规则直填引擎专项
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
