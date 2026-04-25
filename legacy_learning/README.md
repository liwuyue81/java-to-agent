# 学习阶段归档代码

本目录存放五阶段学习过程中的入口脚本和配套文档，**已不再维护**，仅作学习回顾。

## 目录结构

```
legacy_learning/
├── main.py                     # Stage 1: 基础 ReAct Agent（3 个 Tool）
├── main_stage2.py              # Stage 2: Tool 生态扩展（6 个 Tool）
├── main_stage3.py              # Stage 3: 多轮对话 Memory
├── main_stage4_a.py            # Stage 4A: 配置管理 + 字典输出
├── main_stage4_b.py            # Stage 4B: Pydantic 结构化 JSON 输出
├── main_rag.py                 # RAG 版 Agent（ChromaDB 语义检索）
├── monitor_main.py             # 告警监控（函数化轮询）
├── monitor_main_langgraph.py   # 告警监控（LangGraph 版）
└── docs/                       # 五阶段详细讲解文档
    ├── stage1_explanation.md
    ├── stage2_explanation.md
    ├── stage3_explanation.md
    ├── stage4_plan.md
    ├── stage5_plan.md
    ├── stage5_alert_explanation.md
    ├── stage5_langgraph_*.md
    ├── tool_ecosystem.md
    ├── rag_explanation.md
    └── 向量数据简介.md
```

## 如何运行

**必须从项目根目录运行**，因为这些脚本的 import 路径基于根目录（`from tools.log_tools import ...`）：

```bash
# 正确 ✓
cd /Users/photonpay/java-to-agent
python legacy_learning/main_stage3.py

# 错误 ✗（会报 ModuleNotFoundError）
cd legacy_learning && python main_stage3.py
```

依赖的共享模块仍在根目录：`tools/`、`alert/`、`rag/`、`schemas/`、`config.py`

## 想学习综合用法？

不要从这些单独的阶段文件入手，直接看 `../tech_showcase/all_in_one.py`，一个文件覆盖全部技术点。
