"""
══════════════════════════════════════════════════════════════════════════════
  MCP Server —— 把 java-to-agent 的日志分析 Tool 暴露给 Claude Desktop / Cursor
══════════════════════════════════════════════════════════════════════════════

架构：
  Claude Desktop ←(stdio)→ 本 server ← 复用 → tools/log_tools_stage4
                                    └── 复用 → rag/rag_tools

6 个暴露的 Tool：
  - get_error_logs_structured       （stage4 结构化 ERROR 列表）
  - get_log_summary_structured       （stage4 INFO/WARN/ERROR 计数）
  - get_top_error_services           （stage4 报错服务排行）
  - get_log_context_structured       （stage4 关键词 + ±2 行上下文）
  - semantic_search_logs             （RAG 语义检索全量日志）
  - semantic_search_errors           （RAG 语义检索 ERROR）

运行方式（Claude Desktop 会帮你代劳，这里是本地调试用）：
  .venv/bin/python mcp_server/server.py

重要约束：
  - 所有日志写 stderr（stdout 被 MCP 协议占用）
  - 同步的 LangChain Tool 通过 asyncio.to_thread 包起来，别阻塞事件循环
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# 项目根加入 sys.path（和 tech_showcase/langgraph_supervisor.py 一样的套路，
# 确保直接 python mcp_server/server.py 也能 import 到 tools/rag/config）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 日志输出到 stderr —— stdout 是 MCP 协议通道，绝不能污染
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-server")

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool as McpTool  # noqa: E402

from mcp_server.adapter import invoke_langchain_tool, langchain_to_mcp  # noqa: E402
from mcp_server.bootstrap import check_environment  # noqa: E402

# 复用现有 Tool（0 改动）
from tools.log_tools_stage4 import (  # noqa: E402
    get_error_logs_structured,
    get_log_summary_structured,
    get_log_context_structured,
    get_top_error_services,
)
from rag.rag_tools import (  # noqa: E402
    semantic_search_errors,
    semantic_search_logs,
)

# ── 暴露的 Tool 注册表 ──────────────────────────────────────────────────────
# 放模块级，查表复杂度 O(1)，也方便日后新增 Tool 一行搞定
EXPOSED_TOOLS = [
    get_error_logs_structured,
    get_log_summary_structured,
    get_top_error_services,
    get_log_context_structured,
    semantic_search_logs,
    semantic_search_errors,
]
TOOL_INDEX = {t.name: t for t in EXPOSED_TOOLS}


# ── MCP Server 定义 ─────────────────────────────────────────────────────────
server = Server("java-to-agent-logs")


@server.list_tools()
async def handle_list_tools() -> list[McpTool]:
    """Claude Desktop 拉 Tool 列表时调。"""
    return [langchain_to_mcp(t) for t in EXPOSED_TOOLS]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
    """Claude Desktop 真正调用 Tool 时走这里。"""
    logger.info(f"[Tool Call] name={name} args={arguments}")

    tool = TOOL_INDEX.get(name)
    if tool is None:
        available = ", ".join(TOOL_INDEX.keys())
        return [TextContent(
            type="text",
            text=f"[Error] 未知 Tool: {name}。可用: {available}",
        )]

    return await invoke_langchain_tool(tool, arguments)


# ── 入口 ────────────────────────────────────────────────────────────────────
async def main() -> None:
    logger.info("=" * 60)
    logger.info(f"java-to-agent MCP Server 启动")
    logger.info(f"项目根: {PROJECT_ROOT}")
    logger.info(f"暴露 Tool 数: {len(EXPOSED_TOOLS)}")
    for t in EXPOSED_TOOLS:
        logger.info(f"  - {t.name}")
    logger.info("=" * 60)

    # 启动前检查（日志文件 / 向量库状态）
    check_environment(PROJECT_ROOT)

    # stdio transport：标准输入输出作 MCP 通道
    async with stdio_server() as (read_stream, write_stream):
        logger.info("✓ MCP server listening on stdio (Ctrl+C 退出)")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，退出")
