# 99 Future Work（后续优化清单）

> **一行定位** —— 项目当前已完成的 9 项改造之外，所有值得继续投入的方向清单。本文档是「想做但这次没做」的候补菜单，便于下一个迭代周期挑选。

---

## 阅读指南

本文档按照**投入 / 价值 / 难度**分层组织：

- **一、剩余未做的 P2+ 候选**：有明确价值、有清晰实现路径的升级项
- **二、已知 bug 待修**：08 回归测试暴露的具体问题
- **三、回归测试 case 扩展**：08 的数据集还需要扩展
- **四、Prompt 工程方法论**：现有 prompt 是朴素实现，进阶方向
- **五、评估体系进阶**：04 评估的下一层
- **六、成本与性能优化**：生产上线的刚需
- **七、生产级安全加固**：把学习项目拉到可上线的关键项

每条都写明「做 / 不做」的权衡依据。

---

## 一、剩余未做的 P2+ 候选

### 1.1 MCP Server：把 `tools/` 暴露给 Claude Desktop / Cursor  ✅ 已完成（server 侧）

**状态**：2026-04-22 已实现 server 侧。代码在 `mcp_server/`，使用说明见 `mcp_server/README.md`。

**已做的部分（MCP Server 一侧）**：

- 新建 `mcp_server/` 子项目（`__init__.py` / `adapter.py` / `bootstrap.py` / `server.py` / `README.md`）
- 装 `mcp>=1.0.0,<2.0.0` 官方 SDK
- 复用零改动：`tools/log_tools_stage4.py` 的 4 个 Tool + `rag/rag_tools.py` 的 2 个 Tool = 共 6 个 Tool
- LangChain Tool ↔ MCP Tool 适配层（`adapter.py`，新增 Tool 改一行）
- stdio transport 启动 + 启动前 `logs/app.log` + `chroma_db/` 存在性检查
- Claude Desktop 配置示范 + 故障排查

**未做的部分（见 §1.9）**：让本项目自己的 Supervisor Agent 通过 MCP 协议调用这个 Server。

**验证现状**：
- 本地 `.venv/bin/python mcp_server/server.py` 启动正常
- `adapter.py` + `server.py` smoke test 通过（`list_tools` 返回 6 个，`call_tool` 返回格式化 JSON）
- **未在真实 MCP 客户端（Claude Desktop / Cursor）里端到端验证**——用户机器上暂无 Claude Desktop

**下一步可以做（若要真正让 MCP Server 产生价值）**：
- 装 Claude Desktop，按 `mcp_server/README.md` 第 3 步配 `claude_desktop_config.json`
- 或装 Cursor（复制一份配置到 Cursor 的 MCP 配置路径）
- 或先用 MCP Inspector 做协议层调试：
  ```bash
  npx @modelcontextprotocol/inspector .venv/bin/python mcp_server/server.py
  ```

---

### 1.2 CI 集成（GitHub Actions + 回归脚本退出码）

**价值**：★★★★★（工程纪律刚需）

**现状**：08 的 `run_regression.py` 已经返回 `sys.exit(0/1)`，但没接 CI。

**升级**：

```yaml
# .github/workflows/regression.yml
name: Regression
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python tech_showcase/regression/run_regression.py
        env:
          DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: regression-report
          path: tech_showcase/regression/reports/
```

**难度**：⭐⭐（纯工程迁移，Java 开发者有现成经验）

**权衡**：
- **做**：任何 PR 自动跑回归，改坏 Prompt 立即阻塞合并；每次 PR 有 Markdown 报告作为 artifact。
- **不做**：API key 需配 GitHub Secrets，个人学习项目多花一次成本；本地跑也行。

**推荐**：必做。工程化水平一大步。

---

### 1.3 Redis 升级：SESSIONS dict → Redis

**价值**：★★★☆☆（生产必备）

**现状**：06 的 `SESSIONS: OrderedDict` 是单机内存。

**升级**：

```python
import redis.asyncio as redis

_redis = redis.Redis(host="localhost", port=6379)

async def load_history(session_id: str) -> str:
    turns_raw = await _redis.get(f"chat:session:{session_id}")
    if not turns_raw:
        return ""
    turns = json.loads(turns_raw)
    return "\n".join(f"Q{i}: {t['query']}\nA{i}: {t['answer']}" for i, t in enumerate(turns, 1))

async def save_turn(session_id: str, query: str, answer: str):
    key = f"chat:session:{session_id}"
    turns = []
    raw = await _redis.get(key)
    if raw:
        turns = json.loads(raw)
    turns.append({"query": query, "answer": answer, "ts": time.time()})
    turns = turns[-MAX_HISTORY:]
    await _redis.setex(key, 7 * 24 * 3600, json.dumps(turns))   # 7 天 TTL
```

**Key 命名**：遵循全局规范 `{applicationName}:{功能说明}:{动态key值}` → `chat:session:{session_id}`。

**难度**：⭐⭐（改 3-5 个函数，概念直接）

**权衡**：
- **做**：多实例部署、session 跨重启、TTL 自动过期一步到位。
- **不做**：单机教学场景用不到，多一个中间件依赖。

---

### 1.4 持久 Checkpointer：InMemorySaver → SqliteSaver

**价值**：★★★☆☆（HITL 可靠性）

**现状**：09 用 `InMemorySaver`，进程重启丢。

**升级**：

```python
# pip install langgraph-checkpoint-sqlite
from langgraph.checkpoint.sqlite import SqliteSaver

HITL_CHECKPOINTER = SqliteSaver.from_conn_string("data/checkpoint.db")
```

**难度**：⭐（1 行改动）

**权衡**：
- **做**：用户点确认中途服务器重启后仍能恢复。
- **不做**：多一个依赖包、多一个磁盘 IO 点（其实很轻）。

**推荐**：HITL 一旦进入真实业务场景必做。

---

### 1.5 LLM 压缩历史（超过 5 轮摘要化）

**价值**：★★★☆☆（长对话体验）

**现状**：06 滚动窗口 5 轮，超过丢最早的。

**升级**：超过 5 轮时用小模型（qwen-turbo）把前 3 轮压成 1-2 句摘要：

```python
async def compress_history_if_needed(session_id: str):
    turns = SESSIONS.get(session_id, [])
    if len(turns) <= MAX_HISTORY:
        return
    to_compress = turns[:-MAX_HISTORY + 2]     # 留最近两轮完整
    keep = turns[-MAX_HISTORY + 2:]
    summary_prompt = f"""用 2 句话概括以下 {len(to_compress)} 轮对话的核心内容:
{render_turns(to_compress)}"""
    summary = await llm_fast.invoke(summary_prompt)
    SESSIONS[session_id] = [{"query": "[历史摘要]", "answer": summary.content, "ts": ...}] + keep
```

**难度**：⭐⭐（30 行代码）

**权衡**：
- **做**：支持几十轮的长对话，用户体验更连贯。
- **不做**：短对话场景（≤10 轮）当前方案够用；压缩也会丢失细节。

---

### 1.6 Token 级流式（`astream_events("v2")`）

**价值**：★★★☆☆（UX 更像 ChatGPT）

**现状**：05 用节点级流式，每个 Agent 跑完 yield 一次。

**升级**：切到 `astream_events("v2")` + 过滤 `on_chat_model_stream` 事件：

```python
async for event in compiled_graph.astream_events(state, version="v2"):
    if event["event"] == "on_chat_model_stream":
        delta = event["data"]["chunk"].content
        if delta:
            yield {"event": "token", "data": json.dumps({"delta": delta})}
    elif event["event"] == "on_chain_end" and event["name"] == "reporter":
        yield {"event": "node", ...}
```

**难度**：⭐⭐⭐（事件种类多，过滤规则要调）

**权衡**：
- **做**：用户看着报告逐字生成，ChatGPT 同款体验。
- **不做**：节点级已经够用，token 级代码复杂度高 3 倍。

---

### 1.7 Rerank（BGE-reranker / DashScope gte-rerank-v2）

**价值**：★★★★☆（RAG 质量提升显著）

**现状**：04 的 RAG 是「纯 embedding 相似度 top-5」。

**升级**：先拿 top-20，用 rerank 模型重排 top-5：

```python
from langchain_community.document_compressors import DashScopeRerank

retriever = vectorstore.as_retriever(search_kwargs={"k": 20})
compressor = DashScopeRerank(model="gte-rerank-v2", top_n=5)
compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor,
    base_retriever=retriever,
)
```

**难度**：⭐⭐（集成现有组件）

**权衡**：
- **做**：ragas 综合评分通常涨 5-10 分，4 章的 `faithfulness` 应该能从 0.80 提到 0.88+。
- **不做**：多一次 API 调用延迟（~500ms）+ 成本。

**推荐**：RAG 场景必做的第一步调优。

---

### 1.8 Hybrid Search（向量 + BM25）

**价值**：★★★☆☆（RAG 召回率提升）

**现状**：纯向量检索。

**升级**：BM25（关键词） + 向量（语义）按权重合并：

```python
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever

bm25 = BM25Retriever.from_documents(docs)
bm25.k = 5
vector = vectorstore.as_retriever(search_kwargs={"k": 5})
hybrid = EnsembleRetriever(retrievers=[bm25, vector], weights=[0.3, 0.7])
```

**难度**：⭐⭐（已有现成组件）

**权衡**：
- **做**：对「精确名词查询」（如服务名、错误码）召回率明显提升。
- **不做**：计算量翻倍；小数据集收益不明显。

---

### 1.9 让本项目 Supervisor 作为 MCP 客户端调 Tool（**想做但这次没做**）

**价值**：★★☆☆☆（概念验证 > 实用）

**用户最初的设想（写在这里以免遗忘）**：

> 「我想验证的是——让我自己项目里的 Agent（tech_showcase/langgraph_supervisor.py 里的 Supervisor）**不再直接 import tools/，而是通过 MCP 协议去调用 mcp_server/ 暴露的 Tool**。这样才算真正跑通『我写的 Agent 调 MCP』这件事。」

**为什么 §1.1 只做了一半（只做 Server 侧，没做 Client 侧）**：

§1.1 实现的是「**Server 侧**」——把本项目 Tool 暴露给**外部** AI 应用（Claude Desktop / Cursor / Claude Code 等 MCP 客户端）。

而本节（§1.9）要做的是「**Client 侧**」——让**本项目自己的 Supervisor** 也成为 MCP 客户端。完成后的架构变成：

```
┌─────────────────────┐
│ Supervisor LLM       │
└──────────┬───────────┘
           │ 通过 langchain-mcp-adapters（新增依赖）
           ▼
┌─────────────────────┐
│ MCP Server           │  ← mcp_server/ 已有
│   stdio transport    │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────┐
│ tools/*.py           │
└─────────────────────┘
```

**为什么这次没做（权衡后决定推迟）**：

1. **同进程的项目内不需要 MCP 中间层**：Supervisor 和 Tool 在同一个 Python 进程，直接 import 是零延迟。强行走 MCP 等于在项目内部引入进程间通信（IPC），只增加延迟 + 调试复杂度，没有业务收益。
2. **MCP 的真正价值在跨项目复用**：同一 Tool 被 A 项目 Agent、B 项目 Agent、C 产品（Claude Desktop）共同消费时，MCP 协议才能显出统一协议的好处。本项目当前只有一个消费者（Supervisor），价值权重小。
3. **`langchain-mcp-adapters` 生态还不稳**：这个把 MCP Server 的 Tool 转成 LangChain BaseTool 的适配库，API 变动还比较频繁。投入后未来可能要返工。
4. **调试成本显著升高**：现在 Supervisor 报 Tool 错误一眼看到 Python 堆栈；走 MCP 后错误要穿两层进程（stdio 协议 + 序列化），故障排查难度上一个台阶。
5. **学习目标优先级**：本项目还有更高 ROI 的事（CI 集成 §1.2、Rerank §1.7、修已知 bug §二），先把那些做掉收益更明显。

**什么场景下值得做（未来触发条件）**：

- 要把 `tools/` 或 `rag/` 拆成独立微服务（比如日志 Tool 归运维团队、RAG Tool 归数据团队维护），跨团队复用时
- 想对比「直接 import Tool」vs「走 MCP 协议」两种模式的**延迟 / 复杂度 / 可维护性**差异，写成技术 blog
- 要支持「运行时热加载 Tool」（新部署一个 MCP Server 就能给 Supervisor 增加能力），对插件化架构感兴趣时

**实现路径（留给未来）**：

1. `pip install langchain-mcp-adapters`
2. 新增 `tech_showcase/mcp_adapter.py`，封装「连上 mcp_server/server.py + 把 6 个 Tool 转成 LangChain BaseTool」
3. 改 `tech_showcase/langgraph_supervisor.py`，让 Parser/Analyzer 的 tool 列表从 MCP adapter 拿（而不是直接 import `tools/`）
4. 加一个命令行 flag `--tool-mode={inproc,mcp}` 对比两种模式，跑一次 08 的回归测试看路由准确率和延迟差异
5. 写成一篇 milestone 文档（比如 `docs/milestones/10-mcp-client-integration.md`）记录收益 / 损耗

**难度**：⭐⭐⭐（新增依赖 + 改造入口文件 + 协议层调试）

**预估投入**：1-2 天

---

## 二、已知 bug 待修

这三条 bug 从 08 回归测试真实暴露出来，修复思路具体。

### 2.1 `ambiguous` case 循环：Parser 对模糊 query 无限要求澄清

**现象**：query「帮我分析一下」时，Parser 循环 7 次要求用户澄清具体想问什么，loop_count 达到上限被兜底 END。

**根因**：
- 面对模糊 query，Parser 调 `get_error_logs_structured` 拿了数据后，Supervisor 仍路由到 Parser 让它产出。
- Parser 思考不出新东西，又要求「请提供更多信息」。
- Supervisor 没识破「重复要求澄清」这个信号。

**修复方向**：改 Supervisor prompt 加规则：

```
【模糊 query 处理】
- 如果 Parser 连续 2 次产出中包含「请澄清」「请具体说明」「需要更多信息」，
  立即 next=END 并在最终回答里返回已有数据 + 提示「问题较模糊，已返回日志概览，请具体指定服务/时间/错误类型」
```

**验证**：
```bash
python tech_showcase/regression/run_regression.py --case-id ambiguous
# 改前：fail（循环 7 次 + 没有关键词）
# 改后：pass（loop_count ≤ 2，final_state 包含 ERROR 关键词）
```

---

### 2.2 `follow_up_payment` 路由错：追问类 query 偶尔先调 Analyzer

**现象**：带 history 「Q1: OrderService 的 ERROR?」+ query 「那 Payment 呢？」 Supervisor 第一次决策直接去 Analyzer（错），失败后回退到 Parser。

**根因**：
- Supervisor prompt 没明确区分「追问」和「根因分析」。
- LLM 看到「Payment」名词容易联想到「要查 Payment 问题的根因」，忽略「那 XX 呢」是接着前文收集新数据。

**修复方向**：Supervisor prompt 加规则：

```
【追问类识别】
- 如果 query 以「那 XX 呢」「接着 XX」「XX 怎么样」开头，且 history 存在相关话题，
  必须 next=parser 先收集 XX 的原始数据，不能直接 analyzer
```

**验证**：
```bash
python tech_showcase/regression/run_regression.py --case-id follow_up_payment
# 改前：fail（route_trace=[analyzer, parser]）
# 改后：pass（route_trace=[parser]，关键词 Payment 出现）
```

---

### 2.3 `time_filter` seed YAML 错误

**现象**：期望关键词「DBPool」在 08:00-09:00 时段不存在。

**根因**：YAML 写错了——该时段真没 DBPool 错误。

**修复**：改 `seed_cases.yaml`：

```yaml
- id: time_filter
  query: "08:00-09:00 的 ERROR？"
  expected_route: [parser]
  expected_keywords: ["OrderService"]   # 改为该时段真实存在的服务
  expect_report: false
```

**验证**：
```bash
python tech_showcase/regression/run_regression.py --case-id time_filter
# 改 YAML 后：pass
```

---

## 三、回归测试 case 扩展

**现状**：8 条 seed case。

**目标**：扩到 20-30 条。

**方法**：

### 3.1 遇 bug 加 case

每发现一次生产/线上 bug，立即加一条复现 case。经典做法是「先用 case 证明 bug 存在（red），修复后 case 自动变 green」。

### 3.2 从 LangSmith trace 捞有趣 case

每月从 LangSmith 的 dashboard 里挑 5 条：
- 路由错的（如 2.2）
- 耗时异常的
- token 消耗极大的
- 用户重跑多次的

加到 seed YAML。

### 3.3 按路由组合系统性覆盖

目前 8 条已覆盖主要组合，还可补：

| 场景 | 预期路由 | 测试意图 |
|---|---|---|
| query 含数字 | parser | 数字识别 |
| query 是 SQL 风格 | parser | 结构化查询 |
| query 要导出 | parser + reporter | 非交互式 output |
| 多轮同一主题 | parser* 或 END | 识别重复 |
| 混合中英文 | parser | 语言鲁棒 |
| 极长 query（500+ 字） | parser | 上下文处理 |

**目标数量**：30 条左右，覆盖率足够。

---

## 四、Prompt 工程方法论

本项目 prompt 都是「直观写的」（写 system_prompt 的自然语言规则）。进阶方向：

### 4.1 Few-shot（最易上手）

在 prompt 里放 2-3 条 Q&A 示例：

```python
SUPERVISOR_SYSTEM = """你是日志分析 Supervisor，下面是几个路由示例：

示例 1:
query: 「今天有多少 ERROR？」
next: parser
reason: 需要先拉日志数据

示例 2:
query: 「那 Payment 呢？」（有 history）
next: parser
reason: 追问类必须先收集新数据

...
"""
```

**效果**：LLM 路由准确率通常涨 10-20%。几乎零成本。

### 4.2 Chain-of-Thought

让模型显式「先思考再回答」：

```
Before outputting the route decision, write out your reasoning in <thinking> tags.
Then output the JSON.
```

**效果**：复杂决策场景准确率提升，代价是 token 多。

### 4.3 Self-Consistency

同一 query 跑 N=3 次，取多数票作为最终路由决策。

**效果**：鲁棒性提升，成本翻 3 倍。适合关键决策。

### 4.4 Prompt Chaining

把复杂任务拆成多个 prompt 串联（「先让模型列出子任务」→「再让模型解决每个子任务」）。本项目的 Supervisor → 专家 Agent 某种程度已经是 Prompt Chaining 的范式。

每个方向都应该用 08 的回归测试跑「改前 / 改后」对比验证。

---

## 五、评估体系进阶

### 5.1 LangSmith Experiment

把 08 的本地回归结果上报成 LangSmith Experiment：
- UI 里直接看历次实验对比曲线
- 支持「同一数据集跑多个 Prompt 版本」的 A/B 对比
- 可多人协作查看

**难度**：⭐⭐（改 `run_regression.py` 几十行）

### 5.2 OpenAI Evals 或自建 eval harness

ragas 和 LangSmith 之外，OpenAI Evals 是另一套独立体系。多个框架对照更严谨。

### 5.3 自动化指标

- **BLEU / ROUGE**：文本相似度（和 ground_truth 比对）
- **factual consistency 专用模型**：专门检测幻觉
- **latency / token budget 监控**：每次跑都记录，趋势图

---

## 六、成本与性能优化

### 6.1 Token 使用分析

LangSmith trace 已经记录每次调用的 token 数。聚合脚本：

```python
# 从 LangSmith API 拉最近 7 天的 runs，按 tag 分组统计
traces = client.list_runs(project_name="java-to-agent", start_time=yesterday)
by_tag = defaultdict(int)
for t in traces:
    for tag in t.tags:
        by_tag[tag] += t.total_tokens
print(by_tag)
```

### 6.2 缓存策略

- **Anthropic Prompt Caching / OpenAI Predicted Outputs**：系统 prompt 不变的情况下缓存前缀，省钱。
- **Redis LLM-output cache**：相同 query 直接返回上次结果（如 Supervisor 已学会的重复识别，可以更激进地用缓存）。

### 6.3 模型路由分级

简单问题走 qwen-turbo（1/10 成本），复杂才 qwen-plus：

```python
def choose_model(query: str) -> str:
    if len(query) < 30 and not any(kw in query for kw in ["为什么", "根因", "分析"]):
        return "qwen-turbo"
    return "qwen-plus"
```

---

## 七、生产级安全加固

学习项目当前是「裸奔」，上生产前必做：

### 7.1 接口鉴权

- OAuth2 / API Key
- FastAPI 用 `Depends(HTTPBearer())`：

```python
security = HTTPBearer()

@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if not verify_token(credentials.credentials):
        raise HTTPException(401)
    # ...
```

### 7.2 速率限制

- `slowapi`（基于 starlette）
- nginx rate limit
- Redis 计数器

```python
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address)

@app.post("/chat/stream")
@limiter.limit("10/minute")
async def chat_stream(request: Request, req: ChatRequest):
    ...
```

### 7.3 输入净化（Prompt Injection 防护）

- 禁止 query 里有「ignore previous instructions」之类的越狱模式。
- 用 LLM judge 做输入分类（`is_malicious_prompt` 打分）。
- OpenAI 的 `moderation` endpoint 类似用。

### 7.4 输出过滤

- 敏感信息脱敏（身份证、银行卡号、手机号 regex 替换）
- 遵循全局规范 `sercurity-dev-rule.md` 的 C2/C3 类信息处理

### 7.5 审计日志

- 所有 `/chat` 请求记录 audit log（user_id + query + session_id + result_summary）
- 便于事后合规审计

---

## 八、优先级建议（如果只挑 5 件事做）

按 ROI 排序：

1. **CI 集成（1.2）** — 工程纪律立马提一档
2. **Rerank（1.7）** — RAG 质量立马提一档
3. **修复已知 bug（2.1 + 2.2）** — 暴露出来的问题不该放着
4. **持久 Checkpointer（1.4）** — 生产级 HITL 必备
5. **LangSmith Experiment（5.1）** — 评估工作流进化

其他根据具体业务需求挑选。

---

## 九、结语

本项目到 09 milestone 的版本，已经具备完整的 AI Agent 工程化闭环：

- 技术栈完整（LangChain + LangGraph + FastAPI + RAG + 评估 + HITL）
- 工程纪律到位(工厂模式、回归测试、LangSmith 追踪、session 管理)
- 3 个踩过的大坑（CRLF / RustBindings / astream chunk tuple）有明确教训

2026-04-22 **额外完成** MCP Server 子项目（§1.1）——Server 侧已就绪，见 `mcp_server/README.md`。Client 侧（让 Supervisor 自己走 MCP 调 Tool）在 §1.9 详述为什么推迟。

如果要把这个项目继续推到「生产上线」水平，本 99 号文档列的是接下来最值得做的事。

整个 milestone 系列建议按顺序读 [00-summary.md](00-summary.md) → [01-legacy-archive.md](01-legacy-archive.md) → ... → [09-hitl-checkpointer.md](09-hitl-checkpointer.md) → 本文档。
