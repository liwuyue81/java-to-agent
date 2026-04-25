"""
LangChain Tool ↔ MCP Tool 适配层。

核心设计：不重写 Tool。把每个 LangChain @tool 装饰的函数当作输入，
产出 MCP Tool 元信息 + 调用 wrapper，保证 tools/ 目录 0 改动。

Java 类比：
  Adapter Pattern —— 一侧是 LangChain BaseTool，另一侧是 MCP Tool，
  中间这层让双方互不感知。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from mcp.types import TextContent, Tool as McpTool

logger = logging.getLogger(__name__)


def langchain_to_mcp(tool: BaseTool) -> McpTool:
    """
    把 LangChain Tool 的元信息转成 MCP Tool 声明。

    字段映射：
      tool.name                                   → McpTool.name
      tool.description                            → McpTool.description
      tool.args_schema.model_json_schema()        → McpTool.inputSchema
    """
    if tool.args_schema is not None:
        schema = tool.args_schema.model_json_schema()
    else:
        # 极少情况：Tool 无参数，给 MCP 一个空 object schema
        schema = {"type": "object", "properties": {}}

    # MCP inputSchema 要求顶层是 "object" 且至少有 properties 字段
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})

    return McpTool(
        name=tool.name,
        description=tool.description or f"Tool: {tool.name}",
        inputSchema=schema,
    )


async def invoke_langchain_tool(tool: BaseTool, arguments: dict[str, Any] | None) -> list[TextContent]:
    """
    把 MCP 传来的参数喂给 LangChain Tool，再把返回值包装成 MCP 的 TextContent。

    关键点：
      1. LangChain Tool.invoke() 是同步的，用 asyncio.to_thread 避免阻塞 MCP 事件循环
      2. 返回值可能是 dict / list / str，统一序列化为文本
      3. 异常捕获后返回错误消息（不 raise），让 Claude Desktop 能看到错误
    """
    arguments = arguments or {}
    try:
        result = await asyncio.to_thread(tool.invoke, arguments)
    except Exception as e:
        logger.exception(f"Tool {tool.name} 调用失败")
        return [TextContent(type="text", text=f"[Tool Error] {tool.name}: {type(e).__name__}: {e}")]

    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            # 兜底：无法 JSON 序列化（比如带 Pydantic 对象），转 str
            text = str(result)

    return [TextContent(type="text", text=text)]
