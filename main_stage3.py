from langchain_ollama import ChatOllama
from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferMemory
from langchain import hub
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
    filter_logs_by_time,
    top_error_services,
    get_log_context,
]

# Memory：把对话历史存在内存里
# memory_key="chat_history" 对应 prompt 模板里的 {chat_history} 占位符
# return_messages=True 表示以消息列表格式存储（适配 ChatOllama）
memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True,
)

# react-chat 是支持多轮对话的 ReAct 模板，比 react 多了 {chat_history} 占位符
prompt = hub.pull("hwchase17/react-chat")

agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    memory=memory,          # 挂载 Memory
    verbose=True,
    max_iterations=6,
    handle_parsing_errors=True,
)


def chat(question: str) -> str:
    from datetime import date
    today = date.today().isoformat()
    # 只在第一轮注入日期，后续轮次模型能从历史记住
    result = agent_executor.invoke({"input": f"今天日期是 {today}。{question}"})
    return result["output"]


if __name__ == "__main__":
    print("日志 Agent 第三阶段已启动（支持多轮对话），输入 'quit' 退出\n")
    print("现在可以追问，例如：")
    print("  你：今天有哪些 ERROR？")
    print("  你：根因是什么？")
    print("  你：那 WARN 呢？\n")
    while True:
        question = input("你：")
        if question.strip().lower() == "quit":
            break
        answer = chat(question)
        print(f"\nAgent：{answer}\n")
