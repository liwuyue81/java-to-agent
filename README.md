# 日志 Agent 学习项目

## 背景

Java 后端开发（5年经验），目标转型 AI Agent 开发。
从零开始，以日志 Agent 为实战项目，边做边学。

本地环境：macOS M5 16GB · Ollama + qwen2.5:7b · Python 3.9 · LangChain

---

## 知识地图

### 必学核心概念

| AI Agent 概念 | 对应后端概念 | 说明 |
|---|---|---|
| LLM | 智能处理器 | 理解自然语言、推理、生成回答 |
| Tool | API endpoint | Agent 能调用的能力，自己用 Python 写 |
| Agent Loop | 事件循环 / 状态机 | 思考 → 行动 → 观察 → 再思考，循环直到完成 |
| Prompt | 业务规则描述 | 告诉模型它是谁、能做什么、怎么做 |
| Memory | 数据库 / 缓存 | 保存对话历史，支持多轮追问 |
| RAG | 带检索的查询 | 从外部文档中找到相关内容再回答 |

### 技术栈

```
LangChain      — Agent 框架，负责 Tool 注册、Loop 调度、Memory 管理
Ollama         — 本地模型运行时，当前使用 qwen2.5:7b
Python         — 开发语言
```

---

## 项目：日志 Agent

### 目标

用自然语言查询和分析本地日志文件，替代手工 grep。

**示例对话：**
```
你：今天有哪些 ERROR 日志？
Agent：共 6 条 ERROR，主要集中在 08:15 的数据库连接池耗尽事件...

你：根因是什么？
Agent：根因是 DBPool 连接池耗尽，导致 OrderService 和 PaymentService 级联失败...

你：WARN 日志呢？
Agent：共 3 条 WARN，包括连接池使用率超阈值、定时任务耗时过长、缓存命中率下降...
```

### 项目结构

```
log-agent/
├── main.py              # 入口，Agent 主循环
├── requirements.txt     # 依赖
├── tools/
│   ├── __init__.py
│   └── log_tools.py     # Tool 实现
└── logs/
    └── app.log          # 日志文件
```

---

## 分阶段路线

### 第一阶段：最小可用 Agent ✅ 已完成

- [x] LangChain + Ollama 本地跑通
- [x] 实现 `get_error_logs` Tool：按日期查 ERROR
- [x] 实现 `get_log_summary` Tool：统计各级别数量
- [x] 实现 `search_logs` Tool：关键词搜索
- [x] Agent 能正确调用 Tool 并回答问题

**收获：** 理解了 Agent = LLM + Tools + Loop 的基本运作方式

---

### 第二阶段：完善 Tools

- [ ] 按时间范围过滤（如 08:00~09:00 之间的日志）
- [ ] 统计高频错误 Top N（哪个服务报错最多）
- [ ] 根因分析 Tool：找到某条 ERROR 前后 N 行上下文
- [ ] 支持多个日志文件

**学习重点：** Tool 的设计原则——Tool 做数据，LLM 做推理，职责分离

---

### 第三阶段：加 Memory（多轮对话）

- [ ] 保存对话历史，支持追问（「那 WARN 呢？」）
- [ ] 使用 `ConversationBufferMemory` 或 `ConversationSummaryMemory`
- [ ] 理解 Memory 对 Token 消耗的影响

**学习重点：** Memory 的几种类型及取舍（全量 vs 摘要 vs 滑动窗口）

---

### 第四阶段：工程化

- [ ] 配置文件管理（日志路径、模型名称等）
- [ ] 结构化输出（返回 JSON 而不是自然语言）
- [ ] 错误处理与重试机制
- [ ] 单元测试 Tool 函数

**学习重点：** 如何让 Agent 输出可被程序消费的结构化数据

---

### 第五阶段：进阶（可选）

- [ ] 对接真实日志系统（读文件目录 / ELK / 数据库）
- [ ] 异常自动告警（检测到 ERROR 聚集时主动推送）
- [ ] 换用更强模型（GPT-4o / Claude）对比效果差异
- [ ] 了解 LangGraph：更复杂的多步骤 Agent 流程

---

## 推荐学习资源

| 资源 | 用途 |
|---|---|
| [LangChain 官方文档](https://python.langchain.com) | Tool、Agent、Memory 用法 |
| [Ollama 官网](https://ollama.com) | 模型管理、本地部署 |
| ReAct 论文（搜索 "ReAct Synergizing Reasoning"） | 理解 Agent Loop 的设计原理 |

---

## 关键认知

1. **Tool 做数据，LLM 做推理** — Tool 返回原始数据，不要在 Tool 里加判断逻辑，让模型去分析
2. **Prompt 是代码** — Prompt 写得好不好直接决定 Agent 的行为质量
3. **本地模型有上限** — qwen2.5:7b 适合学习，复杂推理任务可换更大模型
4. **Agent 不是万能的** — 确定性逻辑（统计、过滤）用代码写，模糊判断交给 LLM
