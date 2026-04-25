# MCP Server —— 把日志分析 Tool 接到 Claude Desktop

> 把 `java-to-agent` 项目的 6 个日志分析 Tool 通过 **MCP (Model Context Protocol)** 协议暴露给 Claude Desktop / Cursor 等支持 MCP 的 AI 客户端。
>
> 配好后，在 Claude Desktop 对话框里直接问「今天有多少 ERROR？」，Claude 会自动调到本项目的 Tool，你连 IDE 都不用打开。

---

## 暴露的 6 个 Tool

| Tool | 作用 | 入参 |
|---|---|---|
| `get_error_logs_structured` | 拉 ERROR 级别日志列表 | `date`（可选，如 `2026-04-22`） |
| `get_log_summary_structured` | 统计 INFO/WARN/ERROR 数量 | `date`（可选） |
| `get_top_error_services` | 报错最多的服务排行 | `top_n`（可选，如 `3`） |
| `get_log_context_structured` | 关键词命中 + 前后 2 行上下文 | `keyword`（必填，如 `DBPool`） |
| `semantic_search_logs` | 语义检索全量日志（RAG） | `query`（英文关键词） |
| `semantic_search_errors` | 语义检索 ERROR（RAG） | `query`（英文关键词） |

前 4 个返回结构化 JSON，后 2 个返回自然语言描述的 Top 5 命中结果。

---

## 安装 / 配置步骤（macOS）

### 1. 确认依赖已装

```bash
cd /Users/photonpay/java-to-agent
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` 已包含 `mcp>=1.0.0,<2.0.0`，装过就跳过。

### 2. 本地跑一次确认启动正常

```bash
.venv/bin/python mcp_server/server.py < /dev/null
```

期望看到：

```
✓ 日志文件就绪：/Users/photonpay/java-to-agent/logs/app.log
✓ 向量库就绪：/Users/photonpay/java-to-agent/chroma_db
✓ MCP server listening on stdio
```

立刻就退出是正常的——`< /dev/null` 给了 EOF，真跑时 Claude Desktop 会保持 stdin 长连接。

### 3. 配置 Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "java-to-agent-logs": {
      "command": "/Users/photonpay/java-to-agent/.venv/bin/python",
      "args": ["/Users/photonpay/java-to-agent/mcp_server/server.py"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

**关键点**：

- `command` 必须是 `.venv/bin/python` 绝对路径——不要写 `python` 或 `python3`，否则会落到系统 Python 3.9 上（缺依赖）
- 如果文件里已有其他 `mcpServers`，把这一项合进去即可
- `PYTHONUNBUFFERED=1` 确保日志立即刷出，调试时 stderr 看得到

### 4. 完全重启 Claude Desktop

`⌘Q` 退出，再打开（不是关窗口，是真退出，否则 Claude 不会重读配置）。

### 5. 在 Claude Desktop 对话框测试

新对话框，问：

```
用 get_log_summary_structured 看一下日志各级别数量
```

期望效果：Claude 会在回答里显示「调用了 get_log_summary_structured」，下方展开给出结果 `{INFO: 10, WARN: 4, ERROR: 9}`。

继续问：

```
用 semantic_search_errors 找 connection pool 相关的错误
```

期望：首次调用会慢 3-5 秒（chroma 初始化 + embedding 调用），返回 Top 5 相似 ERROR 日志。

---

## 故障排查

### Claude Desktop 里看不到「java-to-agent-logs」

- **检查 1**：配置文件路径对不对？macOS 一定是 `~/Library/Application Support/Claude/claude_desktop_config.json`。
- **检查 2**：JSON 格式合法吗？用 `cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | .venv/bin/python -m json.tool` 验证。
- **检查 3**：Claude Desktop 真的重启了吗？`⌘Q` 不是关窗口。
- **检查 4**：看 Claude Desktop 自己的日志：`ls -la ~/Library/Logs/Claude/` 会有 `mcp-server-java-to-agent-logs.log`，里面能看到我们 server 的 stderr 输出。

### Tool 调用失败

- **「日志文件不存在」**：`ls logs/app.log` 确认文件在。MCP server 启动时会检查，不存在直接 exit。
- **「chromadb.errors.InvalidDimensionException: dimension XXX does not match YYY」**：之前切换过 LLM provider（ollama ↔ dashscope），embedding 维度变了。修复：
  ```bash
  rm -rf chroma_db/
  # 首次调用 semantic_search_* 会自动重建
  ```
- **调用返回 `[Tool Error] xxx`**：看 `~/Library/Logs/Claude/mcp-server-java-to-agent-logs.log`，里面有完整 Python stacktrace。

### Python 环境问题

- **`ModuleNotFoundError: No module named 'mcp'`**：`.venv/bin/pip install mcp` 没执行，或 `command` 用错了 Python。
- **`ModuleNotFoundError: No module named 'tools'`**：`server.py` 里的 `sys.path.insert` 没生效。确认你是通过完整路径启动的（`args` 是 `["/Users/photonpay/java-to-agent/mcp_server/server.py"]` 不是相对路径）。

---

## 架构说明（给将来改造的人）

```
┌─────────────────┐   stdio   ┌──────────────────┐
│  Claude Desktop │ ────────▶ │ mcp_server/      │
└─────────────────┘           │   server.py      │
                              │   adapter.py     │
                              │   bootstrap.py   │
                              └────────┬─────────┘
                                       │ 复用，零改动
                                       ▼
                              ┌──────────────────┐
                              │ tools/           │
                              │   log_tools_*.py │
                              │ rag/             │
                              │   rag_tools.py   │
                              │ config.py        │
                              └──────────────────┘
```

- **`server.py`**（~130 行）：MCP server 入口 + 注册 Tool + stdio transport。
- **`adapter.py`**（~60 行）：LangChain Tool ↔ MCP Tool 适配。加 Tool 只需在 `server.py` 的 `EXPOSED_TOOLS` 里 append 一行。
- **`bootstrap.py`**（~40 行）：启动前检查日志和向量库。

**关键设计**：不修改 `tools/` 和 `rag/`，证明它们的接口设计是可复用的。如果将来 Tool 签名变了，只改 Tool 本身，MCP server 零感知。

---

## 与本项目其他入口的关系

| 入口 | 定位 | 启动方式 |
|---|---|---|
| `tech_showcase/langgraph_supervisor.py` | CLI，学习 Supervisor 多 Agent 模式 | `python langgraph_supervisor.py --demo simple` |
| `tech_showcase/fastapi_service.py` | HTTP 服务，SSE 流式 + HITL | `uvicorn tech_showcase.fastapi_service:app --port 8765` |
| `mcp_server/server.py`（**本项目**） | 接到 Claude Desktop 日常使用 | 由 Claude Desktop 自动起进程 |

三者复用同一套 `tools/` + `rag/` + `config.py`。

---

## 后续可改（衔接 docs/milestones/99-future-work.md）

- 加 Cursor 客户端配置（代码零差异，只是配置文件路径不同）
- 暴露 MCP Resources（让 Claude 能直接读日志文件内容）
- 暴露 MCP Prompts（把常见查询模板化，一键触发）
- 支持多项目（一个 server 管多个日志源）
