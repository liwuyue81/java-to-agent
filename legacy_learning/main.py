from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_react_agent
from langchain_classic import hub
from tools.log_tools import get_error_logs, get_log_summary, search_logs

# 1. 初始化本地模型（类比：创建数据库连接）
llm = ChatOllama(model="qwen2.5:7b", temperature=0)

# 2. 注册 Tools（类比：注册 API endpoint）
tools = [get_error_logs, get_log_summary, search_logs]

# 3. 加载 ReAct 提示模板（ReAct = Reasoning + Acting，Agent 的思考-行动循环）
prompt = hub.pull("hwchase17/react")

# 4. 创建 Agent
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

# 5. AgentExecutor 负责运行循环（类比：DispatcherServlet）
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,       # 打印 Agent 的思考过程
    max_iterations=5,
    handle_parsing_errors=True,
)


def chat(question: str) -> str:
    from datetime import date
    today = date.today().isoformat()  # 2026-03-30
    result = agent_executor.invoke({"input": f"今天日期是 {today}。{question}"})
    return result["output"]


if __name__ == "__main__":
    print("日志 Agent 已启动，输入 'quit' 退出\n")
    while True:
        question = input("你：")
        if question.strip().lower() == "quit":
            break
        answer = chat(question)
        print(f"\nAgent：{answer}\n")
