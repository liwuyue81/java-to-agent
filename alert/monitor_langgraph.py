"""
LangGraph 版告警监控。

旧版（monitor.py）：所有逻辑写在一个函数 run_once() 里，顺序执行。
新版（monitor_langgraph.py）：把每个步骤拆成独立 Node，用有向图连接。

对比点：
  - 旧版：流程隐藏在代码里，看代码才知道走哪条路
  - 新版：流程显式建图，add_edge / add_conditional_edges 就是流程文档
"""
import re
import logging
from datetime import datetime
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from config import settings
from alert.monitor import (
    _load_state, _save_state,
    read_new_lines, detect_errors,
    is_in_cooldown, send_alert,
    ERROR_THRESHOLD,
)

logger = logging.getLogger(__name__)


# ── 1. State：所有节点共享的数据容器 ──────────────────────────────
# 类比：Spring Batch 的 JobExecutionContext，各 Step 读写同一份上下文

class AlertState(TypedDict):
    new_lines: list[str]      # 新增日志行
    error_lines: list[str]    # 其中的 ERROR 行
    alert_key: str            # 去重用的 key（服务名）
    analysis: str             # LLM 分析结果
    offset: int               # 新的文件 offset
    alerted: dict             # 历史告警记录（从 state.json 读入）


# ── 2. Nodes：每个节点只做一件事 ──────────────────────────────────

def read_logs_node(state: AlertState) -> dict:
    """节点1：增量读取日志"""
    new_lines, new_offset = read_new_lines()
    logger.info(f"[read_logs] 读取到 {len(new_lines)} 条新日志")
    return {"new_lines": new_lines, "offset": new_offset}


def detect_errors_node(state: AlertState) -> dict:
    """节点2：提取 ERROR 行，找出告警 key"""
    error_lines = detect_errors(state["new_lines"])
    alert_key = "UNKNOWN"
    if error_lines:
        m = re.search(r"ERROR\s+(\w+)", error_lines[0])
        alert_key = m.group(1) if m else "UNKNOWN"
    logger.info(f"[detect_errors] 发现 {len(error_lines)} 条 ERROR，key={alert_key}")
    return {"error_lines": error_lines, "alert_key": alert_key}


def check_cooldown_node(state: AlertState) -> dict:
    """节点3：冷却检测（纯路由节点，不修改 State，供条件边使用）"""
    return {}


def llm_analyze_node(state: AlertState) -> dict:
    """节点4：LLM 分析根因"""
    logger.info("[llm_analyze] 调用 LLM 分析...")
    llm = ChatOllama(model=settings.model_name, temperature=0, timeout=settings.timeout)
    log_text = "\n".join(state["error_lines"])
    prompt = f"""以下是最新检测到的 ERROR 日志：

{log_text}

请用 2-3 句话简要分析：根因是什么？影响了哪些服务？建议排查方向？"""
    response = llm.invoke(prompt)
    return {"analysis": response.content}


def send_alert_node(state: AlertState) -> dict:
    """节点5：推送告警"""
    send_alert(state["error_lines"], state["analysis"])
    return {}


def save_state_node(state: AlertState) -> dict:
    """节点6：持久化 offset 和告警时间"""
    current = _load_state()
    current["offset"] = state["offset"]
    current["alerted"][state["alert_key"]] = datetime.now().isoformat()
    _save_state(current)
    logger.info(f"[save_state] offset={state['offset']} 已保存")
    return {}


def skip_node(state: AlertState) -> dict:
    """节点7：跳过告警，只更新 offset"""
    current = _load_state()
    current["offset"] = state["offset"]
    _save_state(current)
    logger.info("[skip] 无需告警，offset 已更新")
    return {}


# ── 3. 条件边路由函数：根据 State 返回下一个节点名 ────────────────

def route_by_threshold(state: AlertState) -> str:
    """ERROR 数是否超过阈值？决定是继续还是跳过"""
    if len(state["error_lines"]) >= ERROR_THRESHOLD:
        return "check_cooldown"
    logger.info(f"[route] ERROR {len(state['error_lines'])} 条，未达阈值 {ERROR_THRESHOLD}")
    return "skip"


def route_by_cooldown(state: AlertState) -> str:
    """是否在冷却期内？决定是分析还是跳过"""
    if is_in_cooldown(state["alert_key"], state["alerted"]):
        logger.info(f"[route] {state['alert_key']} 在冷却期内，跳过")
        return "skip"
    return "llm_analyze"


# ── 4. 建图：显式声明流程，流程即文档 ────────────────────────────

def build_alert_graph():
    graph = StateGraph(AlertState)

    # 注册节点
    graph.add_node("read_logs",      read_logs_node)
    graph.add_node("detect_errors",  detect_errors_node)
    graph.add_node("check_cooldown", check_cooldown_node)
    graph.add_node("llm_analyze",    llm_analyze_node)
    graph.add_node("send_alert",     send_alert_node)
    graph.add_node("save_state",     save_state_node)
    graph.add_node("skip",           skip_node)

    # 普通边（固定跳转）
    graph.set_entry_point("read_logs")
    graph.add_edge("read_logs",   "detect_errors")
    graph.add_edge("llm_analyze", "send_alert")
    graph.add_edge("send_alert",  "save_state")
    graph.add_edge("save_state",  END)
    graph.add_edge("skip",        END)

    # 条件边（运行时根据 State 决定路径）
    graph.add_conditional_edges(
        "detect_errors",
        route_by_threshold,
        {"check_cooldown": "check_cooldown", "skip": "skip"},
    )
    graph.add_conditional_edges(
        "check_cooldown",
        route_by_cooldown,
        {"llm_analyze": "llm_analyze", "skip": "skip"},
    )

    return graph.compile()


alert_graph = build_alert_graph()


def run_once_langgraph() -> None:
    """LangGraph 版入口，供 monitor_main_langgraph.py 调用。"""
    current = _load_state()
    initial_state: AlertState = {
        "new_lines":   [],
        "error_lines": [],
        "alert_key":   "",
        "analysis":    "",
        "offset":      current["offset"],
        "alerted":     current["alerted"],
    }
    alert_graph.invoke(initial_state)
