"""
═══════════════════════════════════════════════════════════════════════════════
  LangGraph Supervisor —— 多 Agent 调度模式实战
═══════════════════════════════════════════════════════════════════════════════

读者画像：Java 后端开发者，已掌握 LangGraph 基础（单图线性流程）。
本文件目标：从"单 Agent 全搞"升级到"Supervisor 调度 3 个专家 Agent"，
          学会 LangGraph 真正的多 Agent 精髓。

Java 类比（带到你熟悉的语境）：
  Supervisor          ≈ Spring DispatcherServlet（根据请求分发到不同 Controller）
  专家 Agent           ≈ Controller（每个专注一类业务）
  Agent 内部的 Tool     ≈ Service 方法（被 Controller 调用完成具体事）
  SupervisorState      ≈ 请求上下文 + ThreadLocal（所有节点共享的数据）
  条件边 routing       ≈ URL Mapping 规则 + ExclusiveGateway（流程分支）
  RouteDecision schema ≈ @Valid DTO（用 Pydantic 约束 LLM 返回结构）

─── 架构总览 ───────────────────────────────────────────────────────────────

          用户 Query
              ▼
      ┌──────────────────┐
      │ Supervisor Node  │  ← LLM + with_structured_output(RouteDecision)
      └──┬────┬─────┬───┘
          ▼    ▼     ▼
     Parser Analyzer Reporter   ← 每个都是 create_agent（新版 API）子图
         │    │     │
         └────┼─────┘
              ▼
       回到 Supervisor
              ▼
            END

─── 三种典型路由 ─────────────────────────────────────────────────────────────

  "今天有多少 ERROR？"       → Supervisor → Parser → Supervisor → END
  "DBPool 为什么失败？"       → Supervisor → Parser → Supervisor → Analyzer → Supervisor → END
  "生成今天的结构化日志报告"  → Supervisor → Parser → Supervisor → Analyzer → Supervisor → Reporter → Supervisor → END

─── 运行方式 ────────────────────────────────────────────────────────────────

  cd /Users/photonpay/java-to-agent
  python tech_showcase/langgraph_supervisor.py --list
  python tech_showcase/langgraph_supervisor.py --query "今天有多少 ERROR？"
  python tech_showcase/langgraph_supervisor.py --query "DBPool 为什么失败？"
  python tech_showcase/langgraph_supervisor.py --query "生成今天的结构化日志报告"

═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import argparse
import logging
import sys
from operator import add
from pathlib import Path
from typing import Annotated, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

# 把项目根加入 sys.path，以便 import config/tools/rag/schemas
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_llm  # noqa: E402
from schemas.output import LogAnalysisResult  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("supervisor")


# ═══════════════════════════════════════════════════════════════════════════
# §1. State 定义 —— 所有 Node 共享的数据容器
# ═══════════════════════════════════════════════════════════════════════════
# 类比 Spring Batch 的 JobExecutionContext：流程中每个 Step 都能读写它。
#
# 两个关键点：
#   1) Annotated[List[str], add]
#      告诉 LangGraph：当 Node 返回 agent_outputs=[x] 时，用 list 相加合并，
#      而不是覆盖。这样三个 Agent 的产出会按顺序累加。
#   2) next_agent 字段
#      Supervisor 写入，条件边读取，驱动整个图的路由。
# ═══════════════════════════════════════════════════════════════════════════

class SupervisorState(TypedDict):
    user_query: str                               # 本轮用户问题
    agent_outputs: Annotated[List[str], add]      # 本轮各 Agent 产出累加（单轮内合并）
    next_agent: str                               # Supervisor 决策结果
    final_report: Optional[dict]                  # Reporter 产物（LogAnalysisResult 的 dict）
    loop_count: int                               # 防失控计数
    # ↓ 多轮对话相关（由服务端在入口处一次性注入，scalar 类型，LangGraph 不参与跨调用累积）
    conversation_history: str                     # 格式化好的历史 Q&A 字符串，单轮场景留空


class RouteDecision(BaseModel):
    """Supervisor 的结构化输出 Schema。

    用 Pydantic 约束 LLM 必须返回这个形状，避免它回自由文本导致路由崩溃。
    类比 Java 的 @Valid + 自定义约束注解。
    """
    next: Literal["parser", "analyzer", "reporter", "END"] = Field(
        description="下一个要执行的 Agent 名字，或 END 表示结束"
    )
    reason: str = Field(description="为什么选这个 Agent，一句话")


# ═══════════════════════════════════════════════════════════════════════════
# §2. LLM 单例 —— 所有 Agent 和 Supervisor 共享
# ═══════════════════════════════════════════════════════════════════════════
# 注意：这里用的是 langchain.agents.create_agent（LangGraph V1.0 新版 API），
#      旧版 langgraph.prebuilt.create_react_agent 已废弃。
#      create_agent 返回已编译的 subgraph，直接嵌入主图更方便。
#
# LLM 通过 get_llm() 工厂创建，内部根据 settings.llm_provider 切换
# Ollama（本地）/ DashScope（阿里云百炼，OpenAI 兼容）。
# 业务代码无感知，改 .env 即可切换。
# ═══════════════════════════════════════════════════════════════════════════

from langgraph.graph import StateGraph, END  # noqa: E402
from langchain.agents import create_agent  # noqa: E402

llm = get_llm()


# ═══════════════════════════════════════════════════════════════════════════
# §3. Parser Agent —— 数据收集官
# ═══════════════════════════════════════════════════════════════════════════
# 职责：从日志里捞原始数据（ERROR 列表、服务排行、日志统计）
# Tool 集：复用 tools/log_tools_stage4.py（返回 dict，Agent 好消化）
#
# 实现方式：create_react_agent 返回一个已编译的子图，.invoke() 就能跑完
#          Thought → Action → Observation 循环。
# ═══════════════════════════════════════════════════════════════════════════

from tools.log_tools_stage4 import (  # noqa: E402
    get_error_logs_structured,
    get_log_summary_structured,
    get_top_error_services,
    get_log_context_structured,
)

PARSER_SYSTEM_PROMPT = """你是日志数据收集专家。
你的任务是根据用户问题，调用合适的 Tool 收集原始日志数据。
不要做根因分析，那是 analyzer 的活。
拿到数据后，用简洁的一段话总结你收集到了什么。"""

parser_subgraph = create_agent(
    llm,
    tools=[
        get_error_logs_structured,
        get_log_summary_structured,
        get_top_error_services,
        get_log_context_structured,
    ],
    system_prompt=PARSER_SYSTEM_PROMPT,
)


def parser_node(state: SupervisorState) -> dict:
    """Parser Agent 节点：调用 ReAct 子图收集数据。"""
    logger.info("─── [Parser] 开始收集数据 ───")
    context = state["user_query"]
    # 把已有产出也传给 Parser，让它知道已经收集过什么，避免重复
    if state["agent_outputs"]:
        prior = "\n".join(state["agent_outputs"])
        context = f"{state['user_query']}\n\n已有上下文：\n{prior}"

    try:
        result = parser_subgraph.invoke(
            {"messages": [("user", context)]},
            {"recursion_limit": 10},    # 限制子图最多 10 轮，防失控
        )
        output = result["messages"][-1].content
        logger.info(f"[Parser] 产出：{output[:120]}...")
        return {"agent_outputs": [f"[Parser] {output}"]}
    except Exception as e:
        logger.error(f"[Parser] 执行失败：{e}")
        return {"agent_outputs": [f"[Parser] 执行失败：{e}"]}


# ═══════════════════════════════════════════════════════════════════════════
# §4. Analyzer Agent —— 根因分析官
# ═══════════════════════════════════════════════════════════════════════════
# 职责：从 Parser 产出推断根因，用 RAG 检索语义相似的历史日志
# Tool 集：
#   - semantic_search_errors / semantic_search_logs：RAG 语义检索
#   - get_log_context：关键词定位 + ±2 行上下文（非 structured 版本够用）
# ═══════════════════════════════════════════════════════════════════════════

from rag.rag_tools import semantic_search_errors, semantic_search_logs  # noqa: E402
from tools.log_tools_stage2 import get_log_context  # noqa: E402

ANALYZER_SYSTEM_PROMPT = """你是日志根因分析专家。
你会拿到 Parser 收集的原始数据，你的任务是：
  1. 分析最可能的根因（连锁反应、资源耗尽、依赖失败等）
  2. 用 RAG Tool 检索语义相似的历史问题作为佐证
  3. 给出 2-3 句简洁的根因判断

注意：Tool 输入必须是英文关键词（日志是英文的），请自行翻译。"""

analyzer_subgraph = create_agent(
    llm,
    tools=[semantic_search_errors, semantic_search_logs, get_log_context],
    system_prompt=ANALYZER_SYSTEM_PROMPT,
)


def analyzer_node(state: SupervisorState) -> dict:
    """Analyzer Agent 节点：调用 ReAct 子图做根因分析。"""
    logger.info("─── [Analyzer] 开始根因分析 ───")
    prior = "\n".join(state["agent_outputs"]) or "（暂无前置数据）"
    context = f"""用户问题：{state["user_query"]}

已收集的数据：
{prior}

请基于以上数据进行根因分析。"""

    try:
        result = analyzer_subgraph.invoke(
            {"messages": [("user", context)]},
            {"recursion_limit": 10},
        )
        output = result["messages"][-1].content
        logger.info(f"[Analyzer] 产出：{output[:120]}...")
        return {"agent_outputs": [f"[Analyzer] {output}"]}
    except Exception as e:
        logger.error(f"[Analyzer] 执行失败：{e}")
        return {"agent_outputs": [f"[Analyzer] 执行失败：{e}"]}


# ═══════════════════════════════════════════════════════════════════════════
# §5. Reporter Agent —— 报告生成官
# ═══════════════════════════════════════════════════════════════════════════
# 职责：把 Parser + Analyzer 的产出整合成 LogAnalysisResult（Pydantic）
# 不用 ReAct 子图，因为 Reporter 是"格式化"而非"推理"——
# 直接 LLM + with_structured_output 一次调用就够了。
# ═══════════════════════════════════════════════════════════════════════════

def reporter_node(state: SupervisorState) -> dict:
    """Reporter Agent 节点：生成结构化 JSON 报告。"""
    logger.info("─── [Reporter] 开始生成结构化报告 ───")
    prior = "\n".join(state["agent_outputs"])

    prompt = f"""基于以下分析内容，按 schema 输出一份结构化日志报告。

用户问题：{state["user_query"]}

各 Agent 产出：
{prior}

要求：
  - error_count：从上述内容提取 ERROR 总数（找不到就填 0）
  - top_service：报错最多的服务名
  - errors：具体 ERROR 列表，每条含 time/service/message
  - summary：一句话总结
  - severity：0-2 条 low / 3-5 条 medium / 6+ 条 high"""

    structured_llm = llm.with_structured_output(LogAnalysisResult)
    try:
        report: LogAnalysisResult = structured_llm.invoke(prompt)
        logger.info(f"[Reporter] 报告生成成功：{report.summary}")
        return {
            "final_report": report.model_dump(),
            "agent_outputs": [f"[Reporter] 报告已生成：{report.summary}"],
        }
    except Exception as e:
        logger.warning(f"[Reporter] 结构化输出失败（7B 模型对复杂 schema 有时会崩）：{e}")
        return {"agent_outputs": [f"[Reporter] 结构化失败：{e}"]}


# ═══════════════════════════════════════════════════════════════════════════
# §6. Supervisor 节点 —— 调度官
# ═══════════════════════════════════════════════════════════════════════════
# 核心思路：
#   让 LLM 看用户问题 + 已有产出，用 RouteDecision schema 强制输出下一步。
#   Supervisor 不调 Tool，它的"Tool"就是"派活给哪个 Agent"。
#
# 三层兜底（防止失控）：
#   1) loop_count >= MAX_LOOPS 强制 END
#   2) structured_output 异常 → END
#   3) Agent 内部 recursion_limit 限制子图迭代
# ═══════════════════════════════════════════════════════════════════════════

MAX_LOOPS = 8


SUPERVISOR_PROMPT_TEMPLATE = """你是一个多 Agent 调度官，根据用户问题和已有产出，决定下一步调哪个专家 Agent，或结束流程。
{history_section}
本轮用户问题：{user_query}

本轮已有 Agent 产出：
{history}

可选动作：
  - parser：收集原始日志数据（ERROR 列表、服务排行、日志统计）
  - analyzer：根因分析 + RAG 检索历史相似问题
  - reporter：生成结构化 JSON 报告（仅在用户明确要"报告/结构化/JSON"时用）
  - END：已经充分回答用户问题，结束流程

决策规则：
  - agent_outputs 为空 → 通常先 parser 收集数据
  - 简单查询（数量、列表、统计）→ parser 之后直接 END
  - 含"为什么/根因/原因/怎么回事"的问题 → parser 后接 analyzer
  - 用户明确要"报告/JSON/结构化"时，最后一步调 reporter
  - 每个 Agent 一般只调一次，避免重复
  - 追问类问题（"那 XX 呢？"、"XX 呢？"、"接下来 XX"）：必须先调 parser 收集该主题的新数据，不可直接调 analyzer
  - 如果 agent_outputs 里已有 parser 输出的澄清请求（如"请具体说明""请提供更多信息"），说明问题过于模糊，直接 END 并告知用户可以问什么

请只返回一个 Agent 名字和简短理由。"""


def _build_history_section(conversation_history: str) -> str:
    """把历史对话字符串包装成可选的 Prompt 片段，空时返回空字符串。"""
    if not conversation_history or not conversation_history.strip():
        return ""
    return f"\n历史对话（仅参考，不必重复已答过的内容）：\n{conversation_history}\n"


def supervisor_node(state: SupervisorState) -> dict:
    """Supervisor 节点：LLM 决定下一个 Agent。"""
    # 兜底一：循环过多强制结束
    if state["loop_count"] >= MAX_LOOPS:
        logger.warning(f"[Supervisor] loop_count={state['loop_count']} 达到上限，强制 END")
        return {"next_agent": "END", "loop_count": state["loop_count"] + 1}

    history = "\n".join(state["agent_outputs"]) or "（尚无 Agent 产出）"
    history_section = _build_history_section(state.get("conversation_history", ""))
    prompt = SUPERVISOR_PROMPT_TEMPLATE.format(
        user_query=state["user_query"],
        history=history,
        history_section=history_section,
    )

    structured_llm = llm.with_structured_output(RouteDecision)
    try:
        decision: RouteDecision = structured_llm.invoke(prompt)
        logger.info(f"🎯 [Supervisor] 路由 → {decision.next}（{decision.reason}）")
        return {
            "next_agent": decision.next,
            "loop_count": state["loop_count"] + 1,
        }
    except Exception as e:
        # 兜底二：LLM 结构化输出失败 → END 避免死循环
        logger.warning(f"[Supervisor] 结构化输出异常，兜底 END：{e}")
        return {"next_agent": "END", "loop_count": state["loop_count"] + 1}


# ═══════════════════════════════════════════════════════════════════════════
# §7. 建图 —— 流程即文档
# ═══════════════════════════════════════════════════════════════════════════
# 图结构一目了然：
#   所有专家 Agent 执行完都回到 Supervisor
#   Supervisor 通过条件边决定下一跳，包括 END
# ═══════════════════════════════════════════════════════════════════════════

def build_supervisor_graph(
    checkpointer=None,
    interrupt_before: list[str] | None = None,
):
    """
    构建 Supervisor Graph。默认无状态（向下兼容 CLI/回归测试）。

    参数：
      checkpointer     —— LangGraph Checkpointer 实例（如 InMemorySaver）。
                          传入则启用 HITL：state 会按 thread_id 持久化，支持中断/恢复。
      interrupt_before —— 节点名列表，执行到这些节点前自动中断。需配合 checkpointer 使用。
                          例如 ["reporter"]：Supervisor 决定调 Reporter 时先停，由应用层
                          决定是否恢复（用户确认场景）。
    """
    graph = StateGraph(SupervisorState)

    # 注册节点
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("parser",     parser_node)
    graph.add_node("analyzer",   analyzer_node)
    graph.add_node("reporter",   reporter_node)

    # 入口
    graph.set_entry_point("supervisor")

    # 专家 Agent 执行完都回到 Supervisor
    graph.add_edge("parser",   "supervisor")
    graph.add_edge("analyzer", "supervisor")
    graph.add_edge("reporter", "supervisor")

    # Supervisor 的条件边：从 state["next_agent"] 取路由
    graph.add_conditional_edges(
        "supervisor",
        lambda s: s["next_agent"],
        {
            "parser":   "parser",
            "analyzer": "analyzer",
            "reporter": "reporter",
            "END":      END,
        },
    )

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before or [],
    )


# ═══════════════════════════════════════════════════════════════════════════
# §8. CLI 入口 —— 支持三种 demo 查询
# ═══════════════════════════════════════════════════════════════════════════

DEMO_QUERIES = {
    "simple":   "今天有多少 ERROR？",
    "analyze":  "DBPool 为什么失败？",
    "report":   "生成今天的结构化日志报告",
}


def run(query: str) -> SupervisorState:
    """跑一次完整的 Supervisor 流程，返回最终 State。"""
    compiled = build_supervisor_graph()

    initial: SupervisorState = {
        "user_query":           query,
        "agent_outputs":        [],
        "next_agent":           "",
        "final_report":         None,
        "loop_count":           0,
        "conversation_history": "",   # CLI 场景无历史
    }

    print(f"\n{'═' * 70}")
    print(f"  用户 Query：{query}")
    print(f"{'═' * 70}\n")

    # recursion_limit：主图最大步数，超过会抛异常
    # MAX_LOOPS * 2 是经验值：每次循环 Supervisor + 一个 Agent
    final_state = compiled.invoke(initial, {"recursion_limit": MAX_LOOPS * 3})

    print(f"\n{'─' * 70}")
    print(f"  流程结束，共调度 {final_state['loop_count']} 次 Supervisor")
    print(f"{'─' * 70}")

    # 打印各 Agent 产出
    for i, out in enumerate(final_state["agent_outputs"], 1):
        print(f"\n  第 {i} 步：{out}")

    # 如果有结构化报告，额外打印
    if final_state.get("final_report"):
        import json
        print(f"\n{'─' * 70}")
        print("  最终结构化报告（LogAnalysisResult）")
        print(f"{'─' * 70}")
        print(json.dumps(final_state["final_report"], indent=2, ensure_ascii=False))

    return final_state


def main():
    parser = argparse.ArgumentParser(description="LangGraph Supervisor 多 Agent 演示")
    parser.add_argument("--query", "-q", help="自定义查询问题")
    parser.add_argument("--demo", "-d", choices=list(DEMO_QUERIES.keys()),
                        help=f"预置 demo：{'/'.join(DEMO_QUERIES.keys())}")
    parser.add_argument("--list", action="store_true", help="列出预置 demo")
    args = parser.parse_args()

    if args.list:
        print("预置 demo 查询：")
        for k, v in DEMO_QUERIES.items():
            print(f"  --demo {k:<8}  →  {v}")
        return

    if args.query:
        run(args.query)
    elif args.demo:
        run(DEMO_QUERIES[args.demo])
    else:
        # 默认跑第一个 demo，方便新手直接上手
        print("未指定 --query 或 --demo，跑默认 demo（--list 查看全部）\n")
        run(DEMO_QUERIES["simple"])


if __name__ == "__main__":
    main()
