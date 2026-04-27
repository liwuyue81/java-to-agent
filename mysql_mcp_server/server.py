"""
MySQL MCP Server —— 把 MySQL 查询能力通过 MCP stdio 协议暴露给外部 AI 客户端。

支持的 Tool：
  - list_tables()                    列出所有表名
  - describe_table(table_name)       查看表结构（字段名/类型/注释）
  - query_database(sql)              执行 SELECT 查询（只读，拒绝写操作）

连接配置（环境变量）：
  MYSQL_URL   mysql+pymysql://root:password@localhost:3307/testdb

运行方式（本地调试）：
  MYSQL_URL="mysql+pymysql://root:dev123456@localhost:3307/testdb" \
  .venv/bin/python mysql_mcp_server/server.py

Claude Code 会通过 .mcp.json 自动启动本进程。

安全约束：
  - 只允许 SELECT 语句，其他操作一律拒绝
  - 日志写 stderr（stdout 是 MCP 协议通道，绝不能污染）
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# 日志写 stderr
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mysql-mcp-server")

# 项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool as McpTool  # noqa: E402

# ── MySQL 连接 ─────────────────────────────────────────────────────────────────

MYSQL_URL = os.environ.get("MYSQL_URL", "")


def get_engine():
    """SQLAlchemy engine 懒加载单例。"""
    if not MYSQL_URL:
        raise RuntimeError(
            "MYSQL_URL 环境变量未配置。\n"
            "格式：mysql+pymysql://user:password@host:port/database"
        )
    from sqlalchemy import create_engine
    return create_engine(MYSQL_URL, pool_pre_ping=True)


# ── Tool 定义 ──────────────────────────────────────────────────────────────────

TOOLS: list[McpTool] = [
    McpTool(
        name="list_tables",
        description="列出 MySQL 数据库中所有表名。无需参数。",
        inputSchema={"type": "object", "properties": {}},
    ),
    McpTool(
        name="describe_table",
        description="查看指定表的字段结构（字段名、类型、注释、是否可空）。",
        inputSchema={
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": "要查看的表名，如 'users' 或 'orders'",
                }
            },
            "required": ["table_name"],
        },
    ),
    McpTool(
        name="query_database",
        description=(
            "执行 SELECT 查询并返回结果（JSON 格式）。"
            "只允许 SELECT 语句，禁止 INSERT/UPDATE/DELETE/DROP 等写操作。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "要执行的 SELECT SQL 语句，例如 'SELECT * FROM users'",
                }
            },
            "required": ["sql"],
        },
    ),
]


def _list_tables() -> str:
    from sqlalchemy import text
    with get_engine().connect() as conn:
        rows = conn.execute(text("SHOW TABLES")).fetchall()
    tables = [row[0] for row in rows]
    return json.dumps({"tables": tables}, ensure_ascii=False)


def _describe_table(table_name: str) -> str:
    from sqlalchemy import text
    # 防止 SQL 注入：只允许字母、数字、下划线
    if not table_name.replace("_", "").isalnum():
        return json.dumps({"error": f"非法表名：{table_name}"})
    with get_engine().connect() as conn:
        rows = conn.execute(text(f"DESCRIBE `{table_name}`")).fetchall()
    columns = [
        {"field": r[0], "type": r[1], "null": r[2], "key": r[3], "default": r[4]}
        for r in rows
    ]
    return json.dumps({"table": table_name, "columns": columns}, ensure_ascii=False)


def _query_database(sql: str) -> str:
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return json.dumps({"error": "只允许 SELECT 查询，拒绝执行写操作。"})

    from sqlalchemy import text
    with get_engine().connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]

    return json.dumps(
        {"columns": columns, "rows": rows, "count": len(rows)},
        ensure_ascii=False,
        default=str,   # Decimal / datetime 自动转 str
    )


# ── MCP Server ─────────────────────────────────────────────────────────────────

server = Server("mysql-mcp-server")


@server.list_tools()
async def handle_list_tools() -> list[McpTool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    arguments = arguments or {}
    logger.info(f"[Tool Call] {name} args={arguments}")

    try:
        if name == "list_tables":
            text_result = await asyncio.to_thread(_list_tables)
        elif name == "describe_table":
            text_result = await asyncio.to_thread(_describe_table, arguments["table_name"])
        elif name == "query_database":
            text_result = await asyncio.to_thread(_query_database, arguments["sql"])
        else:
            text_result = json.dumps({"error": f"未知 Tool: {name}"})
    except Exception as e:
        logger.exception(f"Tool {name} 执行失败")
        text_result = json.dumps({"error": f"{type(e).__name__}: {e}"})

    return [TextContent(type="text", text=text_result)]


# ── 入口 ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("=" * 55)
    logger.info("MySQL MCP Server 启动")
    logger.info(f"MYSQL_URL: {MYSQL_URL.split('@')[-1] if '@' in MYSQL_URL else '(未配置)'}")
    logger.info(f"暴露 Tool 数: {len(TOOLS)}")
    for t in TOOLS:
        logger.info(f"  - {t.name}")
    logger.info("=" * 55)

    # 提前验证数据库连接
    try:
        _list_tables()
        logger.info("✓ 数据库连接正常")
    except Exception as e:
        logger.error(f"✗ 数据库连接失败：{e}")
        sys.exit(1)

    async with stdio_server() as (read_stream, write_stream):
        logger.info("✓ MySQL MCP Server listening on stdio")
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，退出")
