# Java 转 AI Agent 学习进度总结

> 生成日期：2026-04-18
> 项目目标：基于 Java 后端背景，转型 AI Agent 开发
> 项目定位：五阶段渐进式日志分析 Agent 实战

---

## 一、整体进度概览

> **目录结构说明（2026-04-18 重构）**
> - `legacy_learning/` — 五阶段学习入口脚本 + 配套讲解文档（归档）
> - `tech_showcase/all_in_one.py` — 所有技术点压缩到一个文件，便于回顾
> - `tools/`、`alert/`、`rag/`、`schemas/`、`config.py` — 共享模块，保留在根目录

| 阶段 | 主题 | 状态 | 核心文件 |
|------|------|------|----------|
| Stage 1 | 基础 Agent Loop（ReAct 模式） | ✅ 已完成 | `legacy_learning/main.py` |
| Stage 2 | 工具生态扩展 | ✅ 已完成 | `legacy_learning/main_stage2.py` |
| Stage 3 | 多轮对话记忆 | ✅ 已完成 | `legacy_learning/main_stage3.py` |
| Stage 4 | 工程化实践（结构化输出/测试/配置） | ✅ 已完成 | `legacy_learning/main_stage4_{a,b}.py` |
| Stage 5 | 告警系统 + LangGraph + RAG | 🟡 部分完成 | `legacy_learning/monitor_main*.py`、`main_rag.py` |

**当前能力定位**：入门偏进阶。已具备独立搭建单 Agent 应用的能力，对 Prompt/Tool/Memory/Output 四大核心要素已有体感；LangGraph 与 RAG 开始摸索但深度不足。

---

## 二、已掌握的技术点

### 2.1 核心概念（类比 Java 理解）

| AI Agent 概念 | Java 类比 | 掌握程度 |
|--------------|----------|---------|
| ReAct 循环（Thought→Action→Observation） | 类似责任链 + 状态机 | ✅ 熟练 |
| Tool / Function Calling | 类比 Spring 的 `@Bean` + 方法反射调用 | ✅ 熟练 |
| Prompt Template | 类比 MyBatis XML 模板 + 参数绑定 | ✅ 熟练 |
| Memory（ConversationBufferMemory） | 类比 Session 会话 / ThreadLocal | ✅ 基础 |
| Pydantic Output Schema | 类比 Java DTO + `@Valid` 校验 | ✅ 熟练 |
| Vector DB（ChromaDB） | 类比 Elasticsearch 的向量检索 | 🟡 入门 |
| LangGraph StateGraph | 类比 Activiti / Camunda 工作流引擎 | 🟡 入门 |

### 2.2 技术栈覆盖

- **框架**：LangChain 0.3+、LangGraph 0.2+
- **模型**：Ollama 本地部署（qwen2.5:7b）
- **存储**：ChromaDB（向量库）
- **工程化**：pydantic-settings（配置）、pytest（测试）、ragas（RAG 评估）

### 2.3 工程化实践

- ✅ `.env` + `pydantic-settings` 配置管理（类比 Spring `@ConfigurationProperties`）
- ✅ Tool 内异常吞并返回错误信息给 LLM（而非抛出）
- ✅ Pydantic 结构化输出（避免 LLM 返回自由文本导致下游解析失败）
- ✅ 基础单测（`tests/test_log_tools.py`）

---

## 三、当前短板与薄弱点

### 3.1 技术深度不足

| 方向 | 当前状态 | 差距描述 |
|------|---------|---------|
| **LangGraph** | 仅在告警场景跑通最简 StateGraph | 未接触多 Agent 协作、并行节点、Subgraph、Human-in-the-loop |
| **RAG** | 索引 + 检索跑通，`eval_rag.py` 为骨架 | 未深入 Chunking 策略、Rerank、Hybrid Search、RAGAS 指标分析 |
| **模型调用** | 只用过 Ollama 本地模型 | 未接触 Claude API / OpenAI API 的原生 SDK、Prompt Cache、Tool Use 原生协议 |
| **Prompt 工程** | 使用 LangChain 封装的模板 | 未系统学习 Few-shot、CoT、Self-Consistency、Prompt 调优方法论 |

### 3.2 生产级能力缺失

- ❌ **可观测性**：无 Token 消耗统计、延迟监控、链路追踪（LangSmith 未接入）
- ❌ **评估体系**：无离线测试集、无回归测试、无 A/B 对比框架
- ❌ **容错与降级**：LLM 超时、限流、幻觉的工程处理缺失
- ❌ **多 Agent 架构**：Supervisor / Router / Team 模式未实践
- ❌ **流式输出**：未接触 streaming、SSE 推送
- ❌ **MCP 协议**：Anthropic 主推的 Model Context Protocol 未了解

### 3.3 Java 后端视角可快速迁移但未实践的点

- ❌ Agent 服务 API 化（FastAPI + 异步）—— 类似 Spring Boot Controller
- ❌ 对话状态持久化到 Redis / PostgreSQL —— 类比分布式 Session
- ❌ Celery / RQ 任务队列处理长耗时 Agent 调用 —— 类比 MQ 异步处理
- ❌ Docker 容器化部署 Agent 服务

---

## 四、精进方向建议（优先级排序）

### P0：近期 1-2 周重点（补齐核心盲点）

#### 1. 直接接入 Claude / OpenAI 原生 API
**原因**：生产环境本地模型能力不足，必须掌握云端大模型调用。
- 学习 Anthropic Python SDK 原生使用方式
- 掌握 **Prompt Caching**（同类 Redis 缓存，但是 Token 层面节省成本）
- 掌握 **Tool Use** 原生协议（不依赖 LangChain 抽象层）
- **产出**：在 `tech_showcase/claude_native_sdk.py` 中用原生 SDK 重写 Stage 4B 的功能

#### 2. LangGraph 深度实践
**原因**：已是主流方向，现有实现过于简单。
- 学习 `StateGraph` 的 `conditional_edges`、并行节点、Subgraph
- 实践 Supervisor 模式（多 Agent 协作）
- 加入 Human-in-the-loop 检查点（类比 Activiti 审批节点）
- **产出**：在 `tech_showcase/langgraph_supervisor.py` 中实现 Supervisor 调度 3 个专家 Agent（Parser/Analyzer/Reporter）

### P1：2-4 周进阶（建立完整工程体系）

#### 3. RAG 进阶与评估
- Chunking 策略对比（固定长度 / 语义切分 / 层级切分）
- Rerank 模型接入（BGE-reranker）
- Hybrid Search（向量 + BM25 关键字）
- 用 RAGAS 跑指标（Faithfulness / Answer Relevancy / Context Precision）
- **产出**：为现有日志 RAG 生成评估报告，找出 bad cases 并优化

#### 4. Agent 服务化（发挥 Java 后端优势）
- FastAPI 封装 Agent 为 HTTP 服务，支持 SSE 流式输出
- 接入 Redis 存储对话历史（替换 `ConversationBufferMemory`）
- 接入 LangSmith / LangFuse 做可观测性
- **产出**：`/agent/chat` 接口 + Grafana 监控看板

### P2：4-8 周深入（建立差异化竞争力）

#### 5. MCP 协议与 Claude Code SDK
- 了解 Model Context Protocol 规范
- 用 Claude Agent SDK 构建自定义 Agent
- 开发自定义 MCP Server（暴露 Java 后端服务给 AI）
- **产出**：把公司一个 Java 内部系统封装成 MCP Server

#### 6. Prompt 工程系统化
- 学习 Anthropic/OpenAI 官方 Prompt 指南
- 实践 Meta-Prompting、Prompt 自动优化
- 建立项目 Prompt 版本管理（类比 Git 管理 SQL 脚本）

#### 7. 评估与 CI/CD
- 建立 Prompt 回归测试集（类比 JUnit 测试）
- GitHub Actions 中跑 Prompt 评估
- 版本化 Prompt + 模型 + 评估结果三者绑定

---

## 五、Java 后端经验如何"反哺"Agent 开发

你已有的 Java 经验在以下方向是**直接优势**，应该强化而不是丢弃：

| Java 经验 | 在 Agent 开发中的价值 |
|----------|---------------------|
| 事务 / 幂等 / 状态机 | 多步 Agent 工作流的可靠性设计 |
| 分布式锁 / 限流 | LLM API 调用并发控制 |
| 连接池 / 超时 / 重试 | LLM 客户端的稳定性工程 |
| Spring Bean 作用域 | LangChain Runnable / Chain 的生命周期管理 |
| MQ 最终一致性 | Async Agent + 回调通知架构 |
| MyBatis-Plus 参数化查询 | RAG 检索 + 结构化查询的组合 |
| 日志规范 / 链路追踪 | LangSmith 接入 + Prompt 可观测性 |

**定位建议**：走"Agent 基础设施工程师 / Agent 中间件方向"，而非纯算法/调 Prompt 的方向。**后端经验决定了你在工程化、稳定性、可观测性方面的天花板比纯 AI 出身的同学高。**

---

## 六、近期行动清单（Checklist）

### 本周
- [ ] 注册 Anthropic API Key，跑通第一个不依赖 LangChain 的 Claude 调用
- [ ] 学习 Prompt Caching 机制，在现有项目中应用
- [ ] 把 `monitor_main_langgraph.py` 扩展为 3 节点 + 条件边的 Graph

### 本月
- [ ] 完成"日志分析 Agent Supervisor 版"重构（LangGraph 多 Agent）
- [ ] 用 FastAPI 把 Agent 服务化，加 SSE 流式接口
- [ ] 接入 LangSmith，建立第一个可观测性看板

### 季度目标
- [ ] 产出一个生产级 Agent 项目（服务化 + 观测 + 评估 + CI）
- [ ] 在公司内部把一个 Java 系统包装为 MCP Server
- [ ] 能独立评审团队其他人的 Agent 方案

---

## 七、参考资源

- **Anthropic 官方文档**：https://docs.anthropic.com/
- **LangGraph 官方教程**：https://langchain-ai.github.io/langgraph/
- **LangSmith 可观测性**：https://smith.langchain.com/
- **MCP 协议规范**：https://modelcontextprotocol.io/
- **RAGAS 评估框架**：https://docs.ragas.io/

---

*文档基于 2026-04-18 项目现状生成，建议每 2 周更新一次进度状态。*
