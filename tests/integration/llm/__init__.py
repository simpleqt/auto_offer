"""需真实模型端点的 e2e 冒烟（pytest -m llm 才会运行）。

环境变量（与 .github/workflows/e2e.yml 对齐）：
- AO_BASE_URL / AO_API_KEY / AO_MODEL：OpenAI 兼容端点
- AO_RUN_LLM=1：显式开关（防误跑烧 token）
"""
