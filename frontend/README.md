# AutoOffer 前端（frontend）

React 18 + TypeScript + Vite + Ant Design 的单页应用，承载档案管理、模型配置、任务监控、回放等界面。

## 页面

| 路由 | 页面 |
| --- | --- |
| 首次引导 | 三步向导：配置模型 → 建立档案 → 发起任务 |
| 档案中心 | 结构化编辑、简历解析、扩展信息问卷、附件、问答库 |
| 模型配置 | 端点 CRUD、能力探测、角色路由矩阵 |
| 任务 | 新建、实时事件流监控、暂停/继续/取消、填写报告 |
| 投递列表 | 状态跟踪与备注 |
| 回放 | 审计事件步进回放 |
| 设置 | 服务信息与关于 |

## 开发

```bash
npm install
npm run dev          # Vite 开发服务，代理 /api 与 /ws 到 127.0.0.1:8765
```

生产模式：`npm run build` 产出 `dist/`，由 FastAPI 服务挂载（同源访问，无需代理）。

## 脚本

| 命令 | 说明 |
| --- | --- |
| `npm run dev` | 开发服务 |
| `npm run build` | tsc 类型检查 + Vite 构建 |
| `npm run typecheck` | tsc 类型检查 |
| `npm run lint` / `lint:fix` | ESLint |
| `npm run format` / `format:check` | Prettier |
| `npm test` / `test:watch` | Vitest 单元与组件测试 |

## 测试

```bash
npm test            # Vitest（jsdom + React Testing Library，mock API，无需后端）
```

关键页面冒烟测试位于 `src/pages/*.test.tsx`；API 客户端与 WebSocket Hook 测试位于 `src/api/*.test.ts`。
