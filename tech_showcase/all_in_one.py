"""
═══════════════════════════════════════════════════════════════════════════════
  AI Agent 技术总览 — 一个文件看懂 legacy_learning 里所有技术点
═══════════════════════════════════════════════════════════════════════════════

读者画像：Java 后端开发者，5 年经验，转 AI Agent 方向。
阅读策略：每个 Section 独立可运行（都有 `if __name__` 判断），
         通过命令行参数选择跑哪一段，方便对比记忆。

技术点清单（与 legacy_learning/ 下的文件对应）：
  §1  基础 ReAct Agent         ← main.py
  §2  Tool 生态扩展            ← main_stage2.py
  §3  多轮对话 Memory          ← main_stage3.py
  §4A Tool 返回结构化 dict     ← main_stage4_a.py
  §4B with_structured_output   ← main_stage4_b.py
  §5  RAG 语义检索             ← main_rag.py
  §6  函数式轮询监控           ← monitor_main.py / alert/monitor.py
  §7  LangGraph StateGraph     ← monitor_main_langgraph.py / alert/monitor_langgraph.py

Java 类比速查：
  ChatOllama           ≈ 数据库连接（LLM 客户端单例）
  @tool                ≈ Spring @Bean + 方法反射（暴露给 Agent 调用）
  AgentExecutor        ≈ DispatcherServlet（调度 Thought→Action→Observation）
  ConversationBufferMemory ≈ HttpSession（会话状态）
  Pydantic BaseModel   ≈ DTO + @Valid 校验
  ChromaDB             ≈ Elasticsearch（向量检索版）
  LangGraph StateGraph ≈ Activiti/Camunda 工作流引擎

运行方式：
  cd /Users/photonpay/java-to-agent
  python tech_showcase/all_in_one.py --section 1     # 跑 §1
  python tech_showcase/all_in_one.py --section 4b    # 跑 §4B
  python tech_showcase/all_in_one.py --list          # 列出所有 Section
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import List, Literal, TypedDict

from pydantic import BaseModel

# ── 外部依赖（按需 import，避免启动就加载重量级模块）─────────────────
# 每个 Section 在自己的函数内部 import，方便单独运行和定位依赖

# 共享配置：本项目 config.py 已提供
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("tech_showcase")


# ═══════════════════════════════════════════════════════════════════════════
# §1. 基础 ReAct Agent —— 最小可运行 Agent（对应 main.py）
# ═══════════════════════════════════════════════════════════════════════════
# 核心概念：
#   ReAct = Reasoning + Acting。模型在一次回答中循环执行：
#     Thought  → 思考下一步做什么
#     Action   → 选择一个 Tool 调用
#     Observation → 拿到 Tool 返回值
#     Thought → ... 直到得出 Final Answer
#
#   可以类比成 Spring 的责任链 + 状态机：Agent 根据观察结果决定下一步。
# ═══════════════════════════════════════════════════════════════════════════

def section_1_basic_react():
    from langchain_ollama import ChatOllama
    from langchain_classic.agents import AgentExecutor, create_react_agent
    from langchain_classic import hub
    from tools.log_tools import get_error_logs, get_log_summary, search_logs

    # 1) LLM 客户端（单例，类比数据库连接池中的连接）
    llm = ChatOllama(model=settings.model_name, temperature=0)

    # 2) 注册 Tool —— Tool 本质是带描述的 Python 函数，描述给 LLM 读
    tools = [get_error_logs, get_log_summary, search_logs]

    # 3) 拉取社区维护的 ReAct Prompt 模板
    #    模板里定义了 Agent 的思考格式，hub.pull 相当于从 Maven Central 拉包
    prompt = hub.pull("hwchase17/react")

    # 4) 创建 Agent（把 LLM + Tool + Prompt 绑在一起，还不会自己运行）
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

    # 5) AgentExecutor 才是真正的"运行时"，相当于 DispatcherServlet
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,                 # 打印 Thought/Action 过程，调试必开
        max_iterations=5,             # 最大迭代次数，防止死循环
        handle_parsing_errors=True,   # LLM 输出格式错误时自动修正
    )

    # 6) 注入"今天日期"，解决 LLM 不知道当前时间的问题
    today = date.today().isoformat()
    question = "今天有哪些 ERROR 日志？"
    result = executor.invoke({"input": f"今天日期是 {today}。{question}"})
    print(f"\n[§1 Result]\n{result['output']}")


# ═══════════════════════════════════════════════════════════════════════════
# §2. Tool 生态扩展（对应 main_stage2.py）
# ═══════════════════════════════════════════════════════════════════════════
# 核心思想：
#   数据处理留在 Tool 里（确定性 + 高效），推理判断留给 LLM（灵活）
#   不要把 LLM 当 SQL 引擎用 —— 过滤/排序/聚合这些都是 Tool 的活
#
# Java 类比：
#   Tool 就像 Service 层的多个方法。Agent 是 Controller，
#   根据用户问题选择调哪个 Service 方法、怎么组合结果。
# ═══════════════════════════════════════════════════════════════════════════

def section_2_tool_ecosystem():
    from langchain_ollama import ChatOllama
    from langchain_classic.agents import AgentExecutor, create_react_agent
    from langchain_classic import hub
    from tools.log_tools_stage2 import (
        get_error_logs, get_log_summary, search_logs,
        filter_logs_by_time,   # ← 时间段过滤
        top_error_services,    # ← 报错服务 TopN
        get_log_context,       # ← 根因上下文（类比 grep -A -B）
    )

    llm = ChatOllama(model=settings.model_name, temperature=0)
    tools = [get_error_logs, get_log_summary, search_logs,
             filter_logs_by_time, top_error_services, get_log_context]

    prompt = hub.pull("hwchase17/react")
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    executor = AgentExecutor(
        agent=agent, tools=tools,
        verbose=True, max_iterations=6, handle_parsing_errors=True,
    )

    today = date.today().isoformat()
    question = "今天 08:00 到 09:00 之间，哪个服务报错最多？"
    result = executor.invoke({"input": f"今天日期是 {today}。{question}"})
    print(f"\n[§2 Result]\n{result['output']}")


# ═══════════════════════════════════════════════════════════════════════════
# §3. 多轮对话 Memory（对应 main_stage3.py）
# ═══════════════════════════════════════════════════════════════════════════
# 核心：
#   ConversationBufferMemory 把对话历史原样塞进 Prompt 的 {chat_history} 占位。
#   类比 Spring Session：会话状态持久化（这里存在内存里，生产应换 Redis）。
#
# 坑：
#   - react-chat 模板 ≠ react 模板（前者多了 chat_history 占位符）
#   - BufferMemory 会不断膨胀，长对话要换 BufferWindowMemory（只留最近 N 轮）
#     或 ConversationSummaryMemory（用 LLM 压缩历史）
# ═══════════════════════════════════════════════════════════════════════════

def section_3_memory():
    from langchain_ollama import ChatOllama
    from langchain_classic.agents import AgentExecutor, create_react_agent
    from langchain_classic.memory import ConversationBufferMemory
    from langchain_classic import hub
    from tools.log_tools_stage2 import (
        get_error_logs, get_log_summary, search_logs,
        filter_logs_by_time, top_error_services, get_log_context,
    )

    llm = ChatOllama(model=settings.model_name, temperature=0)
    tools = [get_error_logs, get_log_summary, search_logs,
             filter_logs_by_time, top_error_services, get_log_context]

    # 关键点：memory_key 必须和 prompt 里的占位符名称一致
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        return_messages=True,   # 用 Message 对象而不是纯字符串，适配 ChatOllama
    )

    prompt = hub.pull("hwchase17/react-chat")   # 注意是 react-chat
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    executor = AgentExecutor(
        agent=agent, tools=tools, memory=memory,
        verbose=True, max_iterations=6, handle_parsing_errors=True,
    )

    today = date.today().isoformat()
    # 第一轮：需要主动注入日期
    r1 = executor.invoke({"input": f"今天日期是 {today}。今天有哪些 ERROR？"})
    print(f"\n[§3 Round1]\n{r1['output']}")
    # 第二轮：可以用代词追问，Agent 从 chat_history 里还原上下文
    r2 = executor.invoke({"input": "根因大概是什么？"})
    print(f"\n[§3 Round2]\n{r2['output']}")


# ═══════════════════════════════════════════════════════════════════════════
# §4A. Tool 返回结构化 dict（对应 main_stage4_a.py）
# ═══════════════════════════════════════════════════════════════════════════
# 思路：
#   Tool 不再返回拼好的字符串，而是返回 dict（类似 Java 方法返回 DTO）
#   好处：dict 能被 Agent 理解，也能被程序直接消费（存库、告警）
#   代价：dict 的键名描述必须写清楚，否则 LLM 读不懂字段含义
#
# Java 类比：
#   相当于 Controller 统一用 ResultVO 返回，既给前端看又给下游服务消费
# ═══════════════════════════════════════════════════════════════════════════

def section_4a_structured_dict():
    from langchain_ollama import ChatOllama
    from langchain_classic.agents import AgentExecutor, create_react_agent
    from langchain_classic.memory import ConversationBufferMemory
    from langchain_classic import hub
    from tools.log_tools_stage4 import (
        get_error_logs_structured,
        get_log_summary_structured,
        get_top_error_services,
        get_log_context_structured,
    )

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
    executor = AgentExecutor(
        agent=agent, tools=tools, memory=memory,
        verbose=True, max_iterations=settings.max_iterations,
        handle_parsing_errors=True,
    )

    today = date.today().isoformat()
    q = "今天 ERROR 最多的 3 个服务是？"
    r = executor.invoke({"input": f"今天日期是 {today}。{q}"})
    print(f"\n[§4A Result]\n{r['output']}")


# ═══════════════════════════════════════════════════════════════════════════
# §4B. with_structured_output —— 强制 JSON 输出（对应 main_stage4_b.py）
# ═══════════════════════════════════════════════════════════════════════════
# 与 §4A 的区别：
#   §4A：Tool 返回 dict，Agent 最终回答仍是自然语言
#   §4B：Agent 最终输出一个 Pydantic 对象，字段类型强约束
#
# 适用场景：
#   下游是程序消费（不需要自然语言），比如：
#   - 生成 JSON 报告入库
#   - 触发下一步自动化流程
#   - 返回给前端渲染表格
#
# 坑：小模型（7B）对复杂 schema 有时会生成失败，schema 越简单越稳
# ═══════════════════════════════════════════════════════════════════════════

class ErrorLogItem_Demo(BaseModel):
    """一条 ERROR 日志的结构化表示。"""
    time: str
    service: str
    message: str


class LogAnalysisResult_Demo(BaseModel):
    """Agent 分析结果的 schema（与 schemas/output.py 等价，这里内联以便对照）。"""
    error_count: int
    top_service: str
    errors: List[ErrorLogItem_Demo]
    summary: str
    severity: Literal["low", "medium", "high"]


def section_4b_structured_output():
    from langchain_ollama import ChatOllama
    from langchain_classic.agents import AgentExecutor, create_react_agent
    from langchain_classic import hub
    from tools.log_tools_stage2 import (
        get_error_logs, get_log_summary, top_error_services, get_log_context,
    )

    llm = ChatOllama(
        model=settings.model_name,
        temperature=settings.temperature,
        timeout=settings.timeout,
    )

    # 关键一行：把 LLM 包装成"只输出符合 schema 的 JSON"的版本
    # 底层是 function calling / JSON mode，不同模型实现不同
    structured_llm = llm.with_structured_output(LogAnalysisResult_Demo)

    tools = [get_error_logs, get_log_summary, top_error_services, get_log_context]
    prompt = hub.pull("hwchase17/react")
    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
    executor = AgentExecutor(
        agent=agent, tools=tools,
        verbose=True, max_iterations=settings.max_iterations,
        handle_parsing_errors=True,
    )

    # 两段式：先用普通 Agent 收集数据，再用 structured_llm 格式化输出
    # 这种分离比直接让 Agent 输出 JSON 更稳定
    today = date.today().isoformat()
    raw = executor.invoke({"input": f"今天日期是 {today}。今天的 ERROR 情况？"})

    format_prompt = f"""根据以下日志分析，按 schema 输出：

{raw['output']}

要求：error_count 为 ERROR 总数；severity 根据数量判定（0-2: low / 3-5: medium / 6+: high）。"""
    result: LogAnalysisResult_Demo = structured_llm.invoke(format_prompt)

    # 下游可以直接用字段，不用再解析字符串
    print(f"\n[§4B] error_count={result.error_count}, top={result.top_service}, sev={result.severity}")
    print(result.model_dump_json(indent=2))


# ═══════════════════════════════════════════════════════════════════════════
# §5. RAG 语义检索（对应 main_rag.py）
# ═══════════════════════════════════════════════════════════════════════════
# 核心三步：
#   1. Embedding：把文本变成向量（nomic-embed-text 模型，274MB 专做向量化）
#   2. 入库：Document(content, metadata) 存进 ChromaDB
#   3. 检索：similarity_search 找语义最近的 Top K
#
# Chunk 策略（决定检索质量的关键）：
#   v1 每行一个 Document：上下文缺失，不推荐
#   v2 滑动窗口（window=5, step=3）：带 overlap，保证上下文完整性
#
# Java 类比：
#   Embedding ≈ Elasticsearch 的分词+索引
#   similarity_search ≈ ES 查询 + _score 排序
#   区别：ES 按词命中打分，向量库按"语义距离"打分
# ═══════════════════════════════════════════════════════════════════════════

def section_5_rag():
    from rag.log_indexer import index_logs, search_similar_logs

    # 首次运行会索引，后续直接加载（会打印 "向量库已有 N 条数据，跳过索引"）
    count = index_logs()
    logger.info(f"索引状态：新增 {count} 条（0 表示已有库）")

    # 纯向量检索（不经过 Agent）
    for q in ["数据库连接问题", "缓存超时", "认证失败"]:
        docs = search_similar_logs(q, k=3)
        print(f"\n[§5 query='{q}'] 返回 {len(docs)} 条：")
        for d in docs:
            print(f"  [{d.metadata.get('level')}] {d.page_content[:80]}")

    # 包装成 Agent 可调用的 Tool（见 rag/rag_tools.py）
    # 对比：search_logs(关键字匹配) vs semantic_search_logs(语义匹配)
    # 用户问"缓存有没有问题" → semantic_search 能找到 Redis/Cache 相关日志
    #                      → search_logs 必须用户精确输入 "Redis" 才能命中


# ═══════════════════════════════════════════════════════════════════════════
# §6. 函数式轮询监控（对应 monitor_main.py + alert/monitor.py）
# ═══════════════════════════════════════════════════════════════════════════
# 架构：定时器 → run_once() → [读日志 → 规则过滤 → 冷却判断 → LLM 分析 → 告警]
#
# 核心细节（都是生产级工程点）：
#   1) 增量读取：持久化 offset（state.json），类比 Kafka consumer offset
#   2) 硬规则前置：ERROR 数 < 阈值 不调 LLM（省 Token，LLM 不是万能）
#   3) 冷却去重：同类告警 5 分钟内不重复（类比 Sentry 的 rate limiting）
#   4) 状态持久化：state.json 存 offset 和 alerted，重启不丢
#
# 痛点：所有流程写在 run_once() 一个函数里，条件分支多了会乱 → §7 解决
# ═══════════════════════════════════════════════════════════════════════════

def section_6_polling_monitor():
    from alert.monitor import run_once
    logger.info("跑一次函数式监控（不会循环，只跑一轮用于演示）")
    run_once()


# ═══════════════════════════════════════════════════════════════════════════
# §7. LangGraph StateGraph（对应 monitor_main_langgraph.py）
# ═══════════════════════════════════════════════════════════════════════════
# 为什么需要 LangGraph：
#   当 Agent 逻辑包含分支、循环、多步协作时，写在一个函数里会变成面条代码。
#   LangGraph 把每个步骤抽成 Node，用 Edge 显式声明跳转 —— 流程即文档。
#
# 核心三件套：
#   State     —— 所有 Node 共享的数据容器（TypedDict，类比 Spring Batch JobContext）
#   Node      —— 接 State 返 dict（部分字段更新），纯函数，易测
#   Edge      —— 固定边 add_edge / 条件边 add_conditional_edges（对应 if-else 路由）
#
# Java 类比：
#   LangGraph ≈ Activiti/Camunda 工作流引擎：
#   - State    ≈ ProcessInstance 的 variables
#   - Node     ≈ ServiceTask
#   - Edge     ≈ SequenceFlow
#   - 条件边   ≈ ExclusiveGateway + Condition Expression
#
# 下面这段是精简版（把原告警监控流程压到一个文件里）
# ═══════════════════════════════════════════════════════════════════════════

class AlertState(TypedDict):
    """所有 Node 共享的状态容器。"""
    new_lines: List[str]
    error_lines: List[str]
    alert_key: str
    should_alert: bool


def section_7_langgraph_demo():
    from langgraph.graph import StateGraph, END

    # ─ Node 1：读日志（模拟）─
    def node_read_logs(state: AlertState) -> dict:
        mock = [
            "2026-04-18 09:00 ERROR DBPool Connection timeout",
            "2026-04-18 09:01 ERROR DBPool Pool exhausted",
            "2026-04-18 09:02 INFO  App Started successfully",
        ]
        logger.info(f"[node_read_logs] 读取 {len(mock)} 行")
        return {"new_lines": mock}

    # ─ Node 2：提取 ERROR + 告警 key ─
    def node_detect(state: AlertState) -> dict:
        errors = [l for l in state["new_lines"] if "ERROR" in l]
        key = errors[0].split()[3] if errors else "UNKNOWN"  # DBPool
        logger.info(f"[node_detect] ERROR={len(errors)}, key={key}")
        return {"error_lines": errors, "alert_key": key}

    # ─ Node 3：LLM 分析根因（此处 mock 为字符串，避免真实调用）─
    def node_analyze(state: AlertState) -> dict:
        logger.info("[node_analyze] 调 LLM 分析（演示省略）")
        return {"should_alert": True}

    # ─ Node 4：推送告警（演示打印）─
    def node_send(state: AlertState) -> dict:
        print(f"\n[§7 ALERT] key={state['alert_key']}, "
              f"errors={len(state['error_lines'])}")
        return {}

    # ─ Node 5：跳过分支 ─
    def node_skip(state: AlertState) -> dict:
        logger.info("[node_skip] 未达阈值，跳过告警")
        return {}

    # ─ 路由函数：条件边根据它的返回值决定下一个 Node ─
    def route_by_threshold(state: AlertState) -> str:
        return "analyze" if len(state["error_lines"]) >= 2 else "skip"

    # ─ 建图：这部分就是流程文档 ─
    graph = StateGraph(AlertState)
    graph.add_node("read",    node_read_logs)
    graph.add_node("detect",  node_detect)
    graph.add_node("analyze", node_analyze)
    graph.add_node("send",    node_send)
    graph.add_node("skip",    node_skip)

    graph.set_entry_point("read")
    graph.add_edge("read",    "detect")
    graph.add_edge("analyze", "send")
    graph.add_edge("send",    END)
    graph.add_edge("skip",    END)

    # 条件边：detect 完了根据 route_by_threshold 返回值决定去 analyze 还是 skip
    graph.add_conditional_edges("detect", route_by_threshold, {
        "analyze": "analyze",
        "skip":    "skip",
    })

    app = graph.compile()

    # 运行：传初始 State，LangGraph 会按图执行到 END
    initial: AlertState = {
        "new_lines": [], "error_lines": [], "alert_key": "", "should_alert": False,
    }
    app.invoke(initial)


# ═══════════════════════════════════════════════════════════════════════════
# 入口：命令行选择 Section
# ═══════════════════════════════════════════════════════════════════════════

SECTIONS = {
    "1":  ("基础 ReAct Agent",           section_1_basic_react),
    "2":  ("Tool 生态扩展",              section_2_tool_ecosystem),
    "3":  ("多轮对话 Memory",            section_3_memory),
    "4a": ("Tool 返回结构化 dict",       section_4a_structured_dict),
    "4b": ("with_structured_output",    section_4b_structured_output),
    "5":  ("RAG 语义检索",               section_5_rag),
    "6":  ("函数式轮询监控",             section_6_polling_monitor),
    "7":  ("LangGraph StateGraph",      section_7_langgraph_demo),
}


def main():
    parser = argparse.ArgumentParser(description="AI Agent 技术总览")
    parser.add_argument("--section", "-s", help="要运行的 section 编号，如 1 / 4b / 7")
    parser.add_argument("--list", action="store_true", help="列出所有 section")
    args = parser.parse_args()

    if args.list or not args.section:
        print("可用 sections：")
        for k, (title, _) in SECTIONS.items():
            print(f"  §{k:<3} {title}")
        print("\n用法：python tech_showcase/all_in_one.py --section 1")
        return

    key = args.section.lower()
    if key not in SECTIONS:
        print(f"未知 section: {key}，用 --list 查看可用项")
        sys.exit(1)

    title, func = SECTIONS[key]
    print(f"\n{'═' * 70}\n  §{key}  {title}\n{'═' * 70}")
    func()


if __name__ == "__main__":
    main()
