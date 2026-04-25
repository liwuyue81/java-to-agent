"""
RAG Tool：把向量检索能力包装成 LangChain Tool，供 Agent 调用。

与之前 Tool 的区别：
  之前的 Tool：用代码过滤日志（精确匹配）
  RAG Tool：用语义检索日志（模糊匹配，能找到"意思相近"的日志）

跨语言处理：日志是英文，用户问题可能是中文。
Agent（LLM）在调用 Tool 时会自行把问题翻译成英文关键词传入，
所以 Tool 本身只需要处理英文输入。
"""
import logging
from langchain.tools import tool
from rag.log_indexer import search_similar_logs

logger = logging.getLogger(__name__)


@tool
def semantic_search_logs(query: str) -> str:
    """
    Semantic search in logs using natural language. Input must be in English.
    Use this when keyword search is insufficient, e.g. 'database connection issue',
    'cache failure', 'timeout related errors'.
    Returns the most semantically similar log entries.
    """
    results = search_similar_logs(query, k=5)
    if not results:
        return f"No logs found related to: {query}"

    lines = [f"  [{doc.metadata.get('level', '?')}] {doc.page_content}" for doc in results]
    return f"Top {len(results)} logs related to '{query}':\n" + "\n".join(lines)


@tool
def semantic_search_errors(query: str) -> str:
    """
    Semantic search only in ERROR level logs. Input must be in English.
    Use this to find errors similar to a described problem,
    e.g. 'connection pool exhausted', 'redis connection failed'.
    """
    results = search_similar_logs(query, k=5, level="ERROR")
    if not results:
        return f"No ERROR logs found related to: {query}"

    lines = [f"  {doc.page_content}" for doc in results]
    return f"Top {len(results)} ERROR logs related to '{query}':\n" + "\n".join(lines)
