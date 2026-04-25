"""
RAG 版日志 Agent 入口。

升级点：在原有 6 个 Tool 基础上，新增 2 个 RAG Tool（语义检索）。
首次运行会自动索引日志文件到向量数据库。

传统 Tool vs RAG Tool 对比：
  search_logs("DBPool")        → 关键词精确匹配，只找包含 "DBPool" 的行
  semantic_search_logs("数据库连接问题") → 语义匹配，能找到意思相近的日志
"""
import logging
from datetime import date
from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_react_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_classic import hub
from config import settings
from rag.log_indexer import index_logs
from rag.rag_tools import semantic_search_logs, semantic_search_errors
from tools.log_tools_stage2 import (
    get_error_logs,
    get_log_summary,
    search_logs,
    filter_logs_by_time,
    top_error_services,
    get_log_context,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def init():
    """首次运行自动索引日志"""
    logger.info("检查向量数据库...")
    count = index_logs()
    if count > 0:
        logger.info(f"首次索引完成，共 {count} 条日志已写入向量库")
    else:
        logger.info("向量库已就绪")


llm = ChatOllama(
    model=settings.model_name,
    temperature=settings.temperature,
    timeout=settings.timeout,
)

# 全部 Tool：原有 6 个 + 新增 2 个 RAG Tool
tools = [
    # 原有 Tool（精确匹配）
    get_error_logs,
    get_log_summary,
    search_logs,
    filter_logs_by_time,
    top_error_services,
    get_log_context,
    # RAG Tool（语义匹配）
    semantic_search_logs,
    semantic_search_errors,
]

memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
prompt = hub.pull("hwchase17/react-chat")
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    verbose=True,
    max_iterations=6,
    handle_parsing_errors=True,
)


def chat(question: str) -> str:
    today = date.today().isoformat()
    result = agent_executor.invoke({"input": f"今天日期是 {today}。{question}"})
    return result["output"]


if __name__ == "__main__":
    init()
    print("\n=== RAG 版日志 Agent（支持语义检索 + 多轮对话）===")
    print("新增能力：用自然语言描述问题，Agent 能找到语义相似的日志\n")
    print("示例问题：")
    print("  - 有没有数据库连接方面的问题？")
    print("  - 缓存相关的异常有哪些？")
    print("  - 有没有超时类的错误？\n")
    while True:
        question = input("你：")
        if question.strip().lower() == "quit":
            break
        answer = chat(question)
        print(f"\nAgent：{answer}\n")
