# Changelog

本项目遵循 [Conventional Commits](https://www.conventionalcommits.org/)，版本策略为 SemVer。
由 `git-cliff` 从提交历史生成（配置见 `cliff.toml`；本文件在无 git-cliff 环境下按同格式手动维护）。

## [Unreleased]

### Features

- (**frontend**) W6 React 界面 + W8 桌面壳与打包：首次引导、模型配置、档案中心、任务监控、投递、回放、设置七页；pywebview 启动器与 PyInstaller/Inno Setup 打包脚本
- (**server**) W5 本地服务层：REST + WebSocket + 任务队列 + 审计留痕
- 简历解析 / 档案模板 CLI + 附件格式匹配 + 控件层测试补齐
- demo-5 中文官网风格基准页全通过；核心切片补附件与常问扩展字段
- demo-4 简历优先流程基准页 + 上传链路实测通过（verify_and_fix 核对模式）
- 投递列表管理 + 复杂控件场景优化
- Agent Core MVP：多智能体简历自动填写引擎与端到端验收

### Bug Fixes

- (**perception/runner**) 月份格子 label 串位修复；多步表单翻页只认可见按钮 + 兜底重定位
- (**widgets**) 日历面板支持年-月形态（纯年份标题 + 月份格子精确匹配），修复起始月份点击偏差

### Refactoring

- (**frontend**) 引入 ESLint/Prettier，拆分超标组件（ProfileEditor/TasksPage ≤ 300 行）

### Testing

- (**frontend**) Vitest + React Testing Library 组件与单测（26 项），补 TaskDetail/ProfilesPage 冒烟
- 前端静态挂载 + 桌面壳启动器测试；SPA 挂载支持注入目录

### Build & CI

- GitHub Actions CI（后端 + 前端，Windows + Ubuntu 双矩阵）+ pre-commit 钩子
- e2e 工作流骨架（手动触发，可选注入真实模型端点）
- release 工作流骨架（tag 触发打包安装程序）
- 各顶层包 README 与 git-cliff 配置
