"""
方案 B：with_structured_output 强制模型输出 JSON。

流程分两步：
  第一步：普通 Agent 调 Tool 收集原始日志数据（字符串）
  第二步：把收集到的数据交给结构化 LLM，强制输出符合 schema 的 JSON

特点：
- 最终输出是严格的 Pydantic 对象，字段类型有保证
- 下游程序可以直接用 result.error_count、result.severity 等
- 对小模型（7B）有一定挑战，schema 越简单成功率越高
"""
from __future__ import annotations

import logging
from datetime import date
from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_react_agent
from langchain_classic import hub
from config import settings
from schemas.output import LogAnalysisResult
from tools.log_tools_stage2 import (
    get_error_logs,
    get_log_summary,
    top_error_services,
    get_log_context,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 第一步用的普通 LLM：负责调 Tool 收集数据
llm = ChatOllama(
    model=settings.model_name,
    temperature=settings.temperature,
    timeout=settings.timeout,
)

# 第二步用的结构化 LLM：负责把数据格式化成 JSON
structured_llm = llm.with_structured_output(LogAnalysisResult)

tools = [get_error_logs, get_log_summary, top_error_services, get_log_context]
prompt = hub.pull("hwchase17/react")
agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    max_iterations=settings.max_iterations,
    handle_parsing_errors=True,
)


def analyze(question: str) -> LogAnalysisResult | None:
    today = date.today().isoformat()

    # ── 第一步：Agent 调 Tool，收集原始数据 ──────────────────────────
    logger.info("第一步：Agent 调 Tool 收集数据...")
    raw = agent_executor.invoke({"input": f"今天日期是 {today}。{question}"})
    raw_answer = raw["output"]
    logger.info(f"Agent 原始回答: {raw_answer}")

    # ── 第二步：把原始回答交给结构化 LLM，输出 JSON ──────────────────
    logger.info("第二步：结构化 LLM 格式化输出...")
    format_prompt = f"""
根据以下日志分析结果，提取关键信息并按 schema 输出：

{raw_answer}

要求：
- error_count: ERROR 总数（整数）
- top_service: 报错最多的服务名
- errors: ERROR 列表，每条包含 time/service/message
- summary: 一句话总结
- severity: low（0-2条）/ medium（3-5条）/ high（6条以上）
"""
    try:
        result: LogAnalysisResult = structured_llm.invoke(format_prompt)
        return result
    except Exception as e:
        logger.error(f"结构化输出失败: {e}")
        return None


if __name__ == "__main__":
    print("=== 方案 B：with_structured_output 强制 JSON 输出 ===")
    print("最终输出是 Pydantic 对象，字段类型有保证，可直接被程序消费\n")

    while True:
        question = input("你：")
        if question.strip().lower() == "quit":
            break

        result = analyze(question)

        if result:
            print("\n─── 结构化输出结果 ───")
            print(f"ERROR 总数   : {result.error_count}")
            print(f"最严重服务   : {result.top_service}")
            print(f"严重程度     : {result.severity}")
            print(f"总结         : {result.summary}")
            print(f"\nERROR 列表：")
            for e in result.errors:
                print(f"  [{e.time}] {e.service} - {e.message}")
            print("\n─── 原始 JSON ───")
            print(result.model_dump_json(indent=2))
        else:
            print("结构化输出失败，请查看日志")
        print()
