from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_react_agent
from langchain_classic import hub
from tools.log_tools_stage2 import (
    get_error_logs,
    get_log_summary,
    search_logs,
    filter_logs_by_time,
    top_error_services,
    get_log_context,
)

llm = ChatOllama(model="qwen2.5:7b", temperature=0)

tools = [
    get_error_logs,
    get_log_summary,
    search_logs,
    filter_logs_by_time,   # 新增：按时间段过滤
    top_error_services,    # 新增：报错最多的服务 Top N
    get_log_context,       # 新增：根因分析上下文
]

prompt = hub.pull("hwchase17/react")
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    max_iterations=6,
    handle_parsing_errors=True,
)


def chat(question: str) -> str:
    from datetime import date
    today = date.today().isoformat()
    result = agent_executor.invoke({"input": f"今天日期是 {today}。{question}"})
    return result["output"]


if __name__ == "__main__":
    print("日志 Agent 第二阶段已启动，输入 'quit' 退出\n")
    print("新增能力：按时间段过滤 / 报错服务排行 / 根因上下文分析\n")
    while True:
        question = input("你：")
        if question.strip().lower() == "quit":
            break
        answer = chat(question)
        print(f"\nAgent：{answer}\n")
