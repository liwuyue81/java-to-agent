# 技术总览（tech_showcase）

> **一个文件 = 一份速查手册**
> 把 `legacy_learning/` 七个阶段文件用到的所有技术，压进 `all_in_one.py` 一个文件里。

## 为什么这样组织

学习阶段代码散在 7 个 main*.py 里，想看某个技术要在多个文件间跳。归档后：
- **想快速回忆某个技术** → 打开 `all_in_one.py`，Ctrl+F 搜 `§2` / `§4B` 等编号
- **想看完整可运行版本** → 去 `../legacy_learning/` 对应文件
- **想基于这些技术做新东西** → 从本目录新增文件开始

## 目录内容

| 文件 | 覆盖内容 |
|------|----------|
| `all_in_one.py` | legacy 阶段全部技术的单文件总览（§1-§7） |
| `langgraph_supervisor.py` | **P0-2 实战**：Supervisor 多 Agent 调度（Parser/Analyzer/Reporter） |
| `fastapi_service.py` + `static/index.html` | **P1 实战**：FastAPI + SSE 节点级流式推送 |

## Section 索引（all_in_one.py）

| 编号 | 技术点 | 原文件 |
|------|--------|--------|
| §1 | 基础 ReAct Agent | `main.py` |
| §2 | Tool 生态扩展 | `main_stage2.py` |
| §3 | 多轮对话 Memory | `main_stage3.py` |
| §4A | Tool 返回结构化 dict | `main_stage4_a.py` |
| §4B | with_structured_output（Pydantic） | `main_stage4_b.py` |
| §5 | RAG 语义检索（ChromaDB） | `main_rag.py` |
| §6 | 函数式轮询监控 | `monitor_main.py` |
| §7 | LangGraph StateGraph | `monitor_main_langgraph.py` |

## 运行方式

**必须从项目根目录运行**（依赖 `config.py`、`tools/`、`alert/`、`rag/`、`schemas/`）：

```bash
cd /Users/photonpay/java-to-agent

# —— all_in_one.py（legacy 技术总览）——
python tech_showcase/all_in_one.py --list
python tech_showcase/all_in_one.py --section 1
python tech_showcase/all_in_one.py -s 4b
python tech_showcase/all_in_one.py -s 7

# —— langgraph_supervisor.py（多 Agent 调度）——
python tech_showcase/langgraph_supervisor.py --list
python tech_showcase/langgraph_supervisor.py --demo simple     # 今天有多少 ERROR？
python tech_showcase/langgraph_supervisor.py --demo analyze    # DBPool 为什么失败？
python tech_showcase/langgraph_supervisor.py --demo report     # 生成结构化日志报告
python tech_showcase/langgraph_supervisor.py --query "自定义问题"

# —— fastapi_service.py（HTTP + SSE 流式服务）——
python tech_showcase/fastapi_service.py                        # 默认 127.0.0.1:8765
python tech_showcase/fastapi_service.py --port 9000            # 自定义端口
# 另开终端 curl：
curl http://127.0.0.1:8765/health
curl -N -X POST http://127.0.0.1:8765/chat/stream \
     -H "Content-Type: application/json" \
     -d '{"query":"DBPool 为什么失败？"}'
# 浏览器打开 http://127.0.0.1:8765/ 看可视化 demo
```

**学习建议**：
- **CLI 版**：依次跑三个 demo，观察日志里 `[Supervisor] 路由 → xxx（理由）`，体会 Supervisor 怎么派活
- **FastAPI 版**：浏览器打开后输入问题，观察**节点级事件逐条冒出**，对应 ChatGPT 那种流式体验的底层机制（SSE）

## FastAPI 服务端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端 demo 页面（`static/index.html`） |
| `/health` | GET | 健康检查，返回 provider / model |
| `/chat` | POST | 阻塞式，跑完一次性返回完整 SupervisorState JSON |
| `/chat/stream` | POST | **SSE 节点级流式**（主打）。事件：`session` / `node` / `interrupt` / `done` / `error` |
| `/chat/resume` | POST | **HITL 恢复**（Reporter 前中断后调此端点续跑或取消） |
| `/session/{id}` | GET | 查看某 session 的历史轮次（多轮调试用） |
| `/session/{id}` | DELETE | 清除某 session，幂等 |

## HITL（Human-in-the-Loop）

Reporter 节点会额外调一次 LLM 生成 Pydantic 报告（+500~2000 tokens）。
为避免无谓消耗，FastAPI 服务**默认在 Reporter 前中断**，等你确认再继续。

**工作原理**：
- 启动时 `build_supervisor_graph(checkpointer=InMemorySaver(), interrupt_before=["reporter"])`
- Supervisor 决定调 Reporter 时 LangGraph 自动暂停，state 写入 checkpointer
- 服务端推 `event: interrupt` 给前端（含 `thread_id`）
- 前端弹卡片，用户点 ✅ 继续 或 🛑 取消 → 发 `POST /chat/resume`
- approved=true：`compiled.astream(None, config)` 从 checkpoint 恢复
- approved=false：不执行 Reporter，`final_report` 为 null

**命令行测试**（流程演示）：
```bash
# 发一次带 Reporter 的请求，观察停在 interrupt
curl -sN -X POST http://127.0.0.1:8765/chat/stream \
     -H "Content-Type: application/json" \
     -d '{"query":"生成今天的结构化日志报告"}' | tee /tmp/a.txt

# 抠 thread_id
TID=$(grep -o '"thread_id": "[^"]*"' /tmp/a.txt | head -1 | cut -d'"' -f4)

# 继续
curl -sN -X POST http://127.0.0.1:8765/chat/resume \
     -H "Content-Type: application/json" \
     -d "{\"thread_id\":\"$TID\",\"approved\":true}"

# 或取消
curl -sN -X POST http://127.0.0.1:8765/chat/resume \
     -H "Content-Type: application/json" \
     -d "{\"thread_id\":\"$TID\",\"approved\":false}"
```

**CLI / 回归测试不受影响**：`build_supervisor_graph()` 默认无 checkpointer，保持无状态单轮。
HITL 只在 FastAPI 启动时显式传入，两者并行不冲突。

**Java 类比**：Activiti/Camunda 工作流的**审批节点**。单用户项目里更像"高成本操作前的二次确认"。

## 可观测性（LangSmith）

生产 Agent 必备能力：把每次 `/chat` 内部所有 LLM/Tool 调用记录成**瀑布图**，
可看完整 prompt、response、token、延迟、成本。

**开启步骤**（代码里完全零改动）：
1. 注册 https://smith.langchain.com/（邮箱即可，国内可访问）
2. Settings → API Keys → 创建一个 key
3. 在项目根目录 `.env` 里改两行：
   ```bash
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxx
   ```
4. 重启服务。启动日志会出现：
   ```
   🔍 LangSmith tracing 已启用 | project=java-to-agent | dashboard: https://smith.langchain.com/
   ```
5. 浏览器打开 dashboard，选 `java-to-agent` 项目，发一次 `/chat/stream`，几秒后 trace 出现在列表里。

**能看到什么**：
- Supervisor 每次 LLM 调用的**完整 prompt 文本**（含 `conversation_history` 字段）
- Parser/Analyzer ReAct 子图里每次 Tool 调用的 input/output
- 每个 LLM 调用的 **token 数 + 成本估算**
- 瀑布图一眼定位"哪一步最慢"
- 按 `metadata.session_id` 过滤同一会话的所有 trace（多轮对话调试神器）

**关了怎么办**：`.env` 里 `LANGSMITH_TRACING=false` 或留空 key，服务启动日志会显示
`🔕 LangSmith tracing 未启用`，代码行为和 trace 打开前完全一致。

## Java 类比速查

文件顶部注释里已写，这里摘核心几条方便对照记忆：

| AI Agent | Java 世界 |
|----------|-----------|
| `ChatOllama` | 数据库连接 |
| `@tool` 装饰器 | Spring `@Bean` + 方法反射 |
| `AgentExecutor` | `DispatcherServlet` |
| `ConversationBufferMemory` | `HttpSession` |
| `Pydantic BaseModel` | DTO + `@Valid` |
| `ChromaDB` | Elasticsearch（向量版） |
| `LangGraph StateGraph` | Activiti / Camunda 工作流引擎 |
| `FastAPI` | Spring WebFlux（原生 async） |
| `EventSourceResponse` (SSE) | `SseEmitter` / `Flux<ServerSentEvent>` |
| `compiled.astream()` | Reactor `Flux.fromIterable + onNext` |
| `asyncio.to_thread()` | `@Async` 扔线程池 |

## 后续演进方向

参考根目录 `PROGRESS_SUMMARY.md` 的精进路线，后续在本目录下按主题新增文件，例如：

```
tech_showcase/
├── all_in_one.py              # legacy 技术总览
├── langgraph_supervisor.py    # ✅ 已完成：多 Agent 协作（P0-2）
├── fastapi_service.py         # ✅ 已完成：FastAPI + SSE 流式（P1）
├── static/index.html          # ✅ 已完成：前端 demo
├── claude_native_sdk.py       # P0-1：Claude 原生 SDK + Prompt Caching
├── session_memory.py          # P1：多轮对话 session（内存→Redis）
├── langsmith_observability.py # P1：LangSmith 可观测性
└── mcp_server_demo.py         # P2：自定义 MCP Server
```
