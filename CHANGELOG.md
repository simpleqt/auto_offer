# Changelog

本项目遵循 [Conventional Commits](https://www.conventionalcommits.org/)，版本策略为 SemVer。
由 `git-cliff` 从提交历史生成（配置见 `cliff.toml`；本文件在无 git-cliff 环境下按同格式手动维护）。

## [v0.2.2] - 2026-08-28

**跨站泛化修复版**：非北森平台（Moka）真实站点实测暴露的适配缺口全修复。

### Bug Fixes

- (**extension**) Moka 自研 sd-* 组件适配：`apply-field` 行容器进适配器选择器；候选 label 属于含其他控件的行时拒绝（爬公共祖先抓到别人的 label）；纯数字标签（如手机区号 +86）剔除；行首裸文本与「请输入 X」型 placeholder 作为标签兜底；区号前缀选择器（空触发器且同行另有正文输入框）不再成为可填字段
- 真实站点验证：知乎（推荐算法工程师 27 届）与乐元素（AI 算法工程师）两个 Moka 租户，规则直填 3（姓名/手机/邮箱）+ PDF 附件注入 1，0 失败 0 错填
- 新增 moka_apply 基准页回归用例；牛客实测为选简历直投模式（无表单）
- (**release**) Release 附件新增浏览器扩展 zip（`AutoOffer-Extension-<版本>.zip`，Edge/Chrome 解压加载即用，Edge 实测安装通过）

## [v0.2.1] - 2026-08-28

**真实站点复验修复版**：针对柏楚电子（北森 Phoenix 表单）实测暴露的两个问题修复。

### Bug Fixes

- (**extension**) 自绘单选组误报成功：Phoenix 单选的手势监听挂在内部 wrapper 上，普通 mousedown/mouseup/click 合成序列选不中（页面实际未选中，报告却计为已填）。现对内部节点补发完整指针序列（pointerdown/up + 坐标）并核验选中态 class，选中态与期望不符时报失败；无选中态标记的组件保持「已执行」兜底。附 Phoenix 单选基准页回归测试
- (**extension**) custom-group 不再走「信任跳过核验」通道，回读不一致会在报告中如实呈现
- (**scripts**) 新增 `md_resume_to_pdf.py`：档案 .md 简历转 PDF 附件（招聘站普遍拒收 .md），转换后自动更新档案附件清单

## [v0.2.0] - 2026-08-29

**插件化架构正式版**：填写层从 Playwright 外驱迁移为浏览器插件 + 本地服务混合架构——插件为「手」（本地规则直填优先），本地服务为「脑」（LLM 降级为只做字段语义映射，档案值不出本机）。

### Features

- (**extension**) M1 插件骨架与规则直填引擎：MV3 最小权限（activeTab/scripting/storage + 按需站点授权）、站点适配器（智易/北森 Phoenix、Moka、牛客、智联 + Ant/Element 兜底）、textMatchScore 标签评分 + 硬否决（上传类/家庭域/值形冲突）、原生 setter 注入（React 兼容）
- (**extension**) M2 两段式 AI 编排：规则未命中字段走标签映射（LLM 只见标签不见值），报告标注「AI映射」
- (**extension**) M3 复杂控件与多区块：学历类裸 div 下拉（弹层叶子兜底 + 虚拟列表逐屏滚动收割）、Phoenix 自绘单选组、日历/月份选择器（年月箭头导航）、「至今」伴随开关（幂等）、多条教育经历自动补块（occurrence/itemIndex 配对）、附件 File+DataTransfer 注入、AI 选选项级联最多 3 轮下钻
- (**server**) 插件服务接口：`GET /profiles/{id}/flat`（扁平档案，敏感字段默认剔除）、`GET /profiles/{id}/attachments/{index}`（附件字节下载）、`POST /mapping`（AI 字段映射：幻觉过滤 + 置信度门槛）、`POST /option-match`（AI 选选项：逐字校验 + 大类提示重试）
- (**profile**) 档案补齐官网常问字段：国籍、工作年限、期望从事行业、现/期望月薪（schema + 编辑器 + 扁平化 + 引擎别名全链路）
- (**frontend**) W6 React 界面 + W8 桌面壳与打包：首次引导、模型配置、档案中心、任务监控、投递、回放、设置七页；pywebview 启动器与 PyInstaller/Inno Setup 打包脚本
- (**server**) W5 本地服务层：REST + WebSocket + 任务队列 + 审计留痕
- 简历解析 / 档案模板 CLI + 附件格式匹配 + 控件层测试补齐
- demo-4 简历优先流程基准页 + 上传链路实测通过（verify_and_fix 核对模式）
- demo-5 中文官网风格基准页全通过；核心切片补附件与常问扩展字段
- 投递列表管理 + 复杂控件场景优化
- Agent Core MVP：多智能体简历自动填写引擎与端到端验收

### Bug Fixes

- (**extension**) 北森 Phoenix 实测攻坚：弹层与触发器区分（高度门槛）、React 重渲染元素重定位、回读竞态二次重读、回读上限 60→400 字符（长文本校验恒假根因）、选项收割元素/文本类型混用
- (**perception/runner**) 月份格子 label 串位修复；多步表单翻页只认可见按钮 + 兜底重定位
- (**widgets**) 日历面板支持年-月形态（纯年份标题 + 月份格子精确匹配），修复起始月份点击偏差

### Documentation

- 根 README 改为插件优先双模式架构；extension/README（安装/权限/边界）；CHANGELOG

### Testing

- 插件规则直填引擎真实 Chromium 集成测试（Ant/Element 基准页 + 多区块补块 + 附件注入 + AI 选项覆盖 + 硬否决）
- 映射/选选项/扁平档案/附件下载接口测试（脱敏契约、幻觉过滤、503/404/410）
- (**frontend**) Vitest + React Testing Library 组件与单测，补 TaskDetail/ProfilesPage 冒烟
- 前端静态挂载 + 桌面壳启动器测试；SPA 挂载支持注入目录

### Build & CI

- GitHub Actions CI（后端 + 前端，Windows + Ubuntu 双矩阵）+ pre-commit 钩子
- e2e 工作流骨架（手动触发，可选注入真实模型端点）
- release 工作流（tag 触发打包 Windows 安装程序 → GitHub Release 草稿）

### 真实站点验收

北森（柏楚电子 fscut.zhiye.com）校园招聘申请表单：29 个字段填对 / 0 错填（规则 24 + AI 映射 4 + 附件 1）。当前共 223 项后端 + 30 项前端测试全绿。
