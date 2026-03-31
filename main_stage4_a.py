"""
方案 A：Tool 直接返回 dict（结构化数据），Agent 看到 dict 后自行组织自然语言回答。

特点：
- Tool 返回的是机器可读的 dict
- 模型的最终回答仍是自然语言
- dict 数据同时可被程序直接消费（存库、告警等）
"""
import logging
from datetime import date
from langchain_ollama import ChatOllama
from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferMemory
from langchain import hub
from config import settings
from tools.log_tools_stage4 import (
    get_error_logs_structured,
    get_log_summary_structured,
    get_top_error_services,
    get_log_context_structured,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

llm = ChatOllama(
    model=settings.model_name,
    temperature=settings.temperature,
    timeout=settings.timeout,
)

tools = [
    get_error_logs_structured,
    get_log_summary_structured,
    get_top_error_services,
    get_log_context_structured,
]

memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
prompt = hub.pull("hwchase17/react-chat")
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,
    verbose=True,
    max_iterations=settings.max_iterations,
    handle_parsing_errors=True,
)


def chat(question: str) -> str:
    today = date.today().isoformat()
    logger.info(f"用户提问: {question}")
    result = agent_executor.invoke({"input": f"今天日期是 {today}。{question}"})
    return result["output"]


if __name__ == "__main__":
    print("=== 方案 A：Tool 返回结构化数据 ===")
    print("Agent 拿到 dict 后用自然语言回答，dict 数据也可被程序直接消费\n")
    while True:
        question = input("你：")
        if question.strip().lower() == "quit":
            break
        answer = chat(question)
        print(f"\nAgent：{answer}\n")
