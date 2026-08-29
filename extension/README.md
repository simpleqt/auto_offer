# AutoOffer 浏览器插件（MV3）

以浏览器插件为「手」、本地服务为「脑」：页面上能规则匹配的字段零 LLM 直接写入，
规则未命中的字段走本地服务的 AI 标签映射/选选项通道，档案值不出本机。

## 架构

```
popup(选档案/授权敏感字段) ──▶ background(SW) 两段式编排
                               │  fetch http://127.0.0.1:8765
                               │   GET /api/v1/profiles/{id}/flat[?sensitive=true]
                               │   GET /api/v1/profiles/{id}/attachments/{idx}
                               │   POST /api/v1/mapping        （只见标签不见值）
                               │   POST /api/v1/option-match   （AI 选选项，≤3轮级联）
                               ▼
                     content.js（规则直填引擎）
                       站点适配器(智易/北森 Phoenix/Moka/牛客/智联 + Ant/Element 兜底)
                       标签扫描 → 本地评分(textMatchScore) + 硬否决
                                 （上传类 / 家庭域 / 值形冲突）
                       → setNativeValue 原生注入(React 兼容)
                       → 自定义下拉（弹层叶子兜底 + 搜索框重试 + 选项收割）
                       → Phoenix 自绘单选（内部节点指针序列 + 选中态核验）
                       → 日历/月份选择器、「至今」开关（幂等）
                       → 多条教育经历自动补块（occurrence/itemIndex 配对）
                       → 附件 File+DataTransfer 注入
```

- 评分与注入设计参考 OpenJobAutofill（MIT），源码归档于 `reference/OpenJobAutofill/`。
- 敏感字段（身份证号、家庭情况等）默认不输出，弹窗勾选授权后才随 `sensitive=true` 下发。
- 值形/标签语义冲突硬否决来自 Playwright 路线的实战修复（手机号形状的值禁止写入身高/日期类标签）。
- AI 映射只送字段标签与档案键名，不送档案值；选选项通道送单个值到你自己配置的 LLM（与简历解析同一信任域）。

## 安装到 Edge / Chrome

前提：本地服务已启动（`.venv/Scripts/python.exe -m app.launcher`，
健康检查 http://127.0.0.1:8765/api/health）。

**方式一：加载解压缩目录（开发推荐，改动即生效）**

1. Edge 打开 `edge://extensions`（Chrome 为 `chrome://extensions`）。
2. 打开左侧「开发人员模式」/「开发者模式」开关。
3. 点「加载解压缩的扩展」/「加载已解压的扩展程序」，选择本仓库的 `extension/` 目录。

**方式二：安装打包 zip（`dist/AutoOffer-Extension-<版本>.zip`）**

1. `python scripts/package_extension.py` 生成 zip（或从 GitHub Release 下载附件）。
2. 解压 zip 到任意固定目录（加载后目录不能删/移动）。
3. 同方式一，加载解压缩的扩展时选中**解压出的目录**。

**使用**：打开目标招聘表单页 → 点插件图标 → 首次「授权连接」本地服务（一并申请站点源与
API 源）→ 选择档案 → 按需勾选「包含敏感字段」→「开始填写」→ 查看填写报告（AI 映射/附件
补填的字段带标注）。

权限模型：`activeTab + scripting + storage`，站点源与本地服务源均在点击时按需申请
（`optional_host_permissions`），不常驻任何站点访问权。

## 已知边界

- 两 pane 虚拟级联的职业大类（如北森「期望从事职业」46 类目）在自动化下仅部分可见，
  AI 会拒选而不是乱选，该类字段留人工。
- 不触碰验证码/登录（微信扫码等由人工完成）；不自动提交（沿用本地服务 auto_submit 设置）。
- 招聘站普遍拒收 .md 附件，档案简历附件请用 PDF/Word
  （`python scripts/md_resume_to_pdf.py` 可把 .md 转 PDF 并更新档案）。

## 测试

```bash
.venv/Scripts/python.exe -m pytest tests/integration/extension -q
.venv/Scripts/python.exe -m pytest tests/integration/server/test_profile_flat.py -q
```

真实 Chromium 注入 `src/content.js` 跑本地基准页（Ant/Element/北森 Phoenix 单选/多块/附件上传）。
