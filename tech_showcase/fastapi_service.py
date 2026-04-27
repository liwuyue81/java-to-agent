"""
═══════════════════════════════════════════════════════════════════════════════
  FastAPI + SSE 流式 Agent 服务 —— Supervisor 的 HTTP 化封装
═══════════════════════════════════════════════════════════════════════════════

读者画像：Java 后端开发者，熟悉 Spring Boot，初次接触 Python 异步 Web。
本文件目标：把 CLI 版 Supervisor 包装成 HTTP 服务，用 SSE 流式推送节点级事件，
         学会 LLM 服务对外输出的标准方式（ChatGPT / Claude API 都用 SSE）。

─── Java 类比速查 ────────────────────────────────────────────────────────────

  FastAPI 应用                  ≈ Spring Boot @RestController + @Configuration
  @app.post(...)               ≈ @PostMapping(...)
  async def                    ≈ @Async 方法
  Pydantic BaseModel           ≈ @RequestBody DTO + @Valid
  EventSourceResponse          ≈ Spring SseEmitter / Flux<ServerSentEvent>
  compiled.astream()           ≈ Reactor Flux（每个 Node 完成 onNext 一次）
  asyncio.to_thread(fn)        ≈ 扔到 @Async 线程池跑同步代码
  StaticFiles                  ≈ Spring Resource Handler
  uvicorn                      ≈ 内嵌 Tomcat/Undertow

─── SSE 事件设计（节点级 + session 支持）────────────────────────────────────

  event: session   → 首个事件，data: {"session_id": "...", "prev_turns": N}
  event: node      → 每个 LangGraph Node 完成一次就推一条
  event: done      → Graph 执行结束，携带 final_state + session_id + turn
  event: error     → 执行异常，推错误信息后关流

  data 是 JSON 字符串，浏览器用 event.data 拿到。

─── 多轮对话（session） ─────────────────────────────────────────────────────

  - POST /chat 和 /chat/stream 的 body 可选带 session_id
  - 服务端应用层 dict 维护 {session_id: [最近 5 轮 Q/A]}
  - 每轮入口把历史拼成字符串注入 SupervisorState.conversation_history
  - Supervisor 的 prompt 能看到历史，用户可以自然追问："那 Payment 呢？"
  - GET /session/{id} 查历史，DELETE /session/{id} 清除

─── 为什么 POST 而不是 GET ───────────────────────────────────────────────────

  浏览器原生 EventSource 只支持 GET，但 GET 会：
    1) 把 query 写到 URL 上（中文要转义、长度受限）
    2) query 暴露在服务器访问日志和代理日志里（安全问题）
  所以生产实践都是 POST + fetch + Response.body.getReader()，手动读取 SSE。
  前端 index.html 就是这样实现的。

─── 运行方式 ────────────────────────────────────────────────────────────────

  cd /Users/photonpay/java-to-agent
  .venv/bin/python tech_showcase/fastapi_service.py
  # 监听 http://127.0.0.1:8000

  # 测试：
  curl http://127.0.0.1:8000/health
  curl -N -X POST http://127.0.0.1:8000/chat/stream \
       -H "Content-Type: application/json" \
       -d '{"query":"DBPool 为什么失败？"}'

  # 浏览器：
  open http://127.0.0.1:8000/

═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# ── 路径准备 ──────────────────────────────────────────────────────────
# tech_showcase 目录没有 __init__.py（不是 package），所以用 sys.path
# 把项目根和本目录加进去，就能 import 到 config 和 langgraph_supervisor
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # 项目根，for config/tools/schemas/rag
sys.path.insert(0, str(HERE))          # 本目录，for langgraph_supervisor

from config import settings  # noqa: E402
from langgraph_supervisor import build_supervisor_graph  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("fastapi_service")


# ═══════════════════════════════════════════════════════════════════════════
# §1. 全局：启动时编译一次 Supervisor Graph
# ═══════════════════════════════════════════════════════════════════════════
# build_supervisor_graph() 返回的是已编译的 CompiledStateGraph，
# 内部持有 LLM 单例、Agent 子图等，无状态且线程安全，可被多请求共享。
# 类比 Spring 的 @Bean 单例，容器启动时创建一次。
# ═══════════════════════════════════════════════════════════════════════════

logger.info("编译 Supervisor Graph（启用 HITL：Reporter 前中断）...")
# HITL：InMemorySaver + interrupt_before=["reporter"]
# 参考 plan: 每次请求用独立的 thread_id（uuid4），和业务 session_id 区分开
#   - thread_id  ：LangGraph checkpoint 标识，单次请求生命周期
#   - session_id ：业务多轮对话标识，跨请求共享
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

_checkpointer = InMemorySaver()
compiled_graph = build_supervisor_graph(
    checkpointer=_checkpointer,
    interrupt_before=["reporter"],
)
logger.info(f"编译完成，provider={settings.llm_provider}, model={settings.model_name}"
            f"（HITL 开启，Reporter 前需人工确认）")

# LangSmith tracing 启动提示（config.py 已在 import 时把变量写回 os.environ）
if settings.langsmith_tracing and settings.langsmith_api_key:
    logger.info(
        f"🔍 LangSmith tracing 已启用 | project={settings.langsmith_project}"
        f" | dashboard: https://smith.langchain.com/"
    )
else:
    logger.info("🔕 LangSmith tracing 未启用（.env 里设 LANGSMITH_TRACING=true 可开启）")


# ═══════════════════════════════════════════════════════════════════════════
# §2. Request/Response Schema（Pydantic，类比 Java DTO + @Valid）
# ═══════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="用户问题")
    session_id: Optional[str] = Field(
        None, description="会话 id，不传则服务端新建；带上则启用多轮对话上下文"
    )


class ResumeRequest(BaseModel):
    """HITL 恢复请求：前端收到 event: interrupt 后，用户点继续/取消发送此请求。"""
    thread_id:  str = Field(..., description="interrupt 事件里返回的 thread_id")
    approved:   bool = Field(..., description="true=继续执行被拦截的节点；false=取消")
    session_id: Optional[str] = Field(None, description="业务会话 id，用于写多轮历史")


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str


# ═══════════════════════════════════════════════════════════════════════════
# §2.5. Session 管理（应用层 dict + 线程安全锁，MVP 级别）
# ═══════════════════════════════════════════════════════════════════════════
# 生产级应换 Redis，接口保持一致即可替换。
#
# MAX_HISTORY_TURNS = 5 → 滚动窗口，防止 context 爆炸：
#   第 6 轮时淘汰最早的 1 条，始终只保留最近 5 轮 Q&A
#
# 类比 Java：Map<String, List<Turn>> + synchronized 块
# ═══════════════════════════════════════════════════════════════════════════

class Turn(BaseModel):
    q: str
    a: str
    ts: str


MAX_HISTORY_TURNS = 5
SESSIONS: Dict[str, List[Turn]] = {}
_sess_lock = threading.Lock()


def _get_history(session_id: str) -> List[Turn]:
    """读某 session 的历史轮次（返回拷贝，不持锁在外）。"""
    with _sess_lock:
        return list(SESSIONS.get(session_id, []))


def _append_turn(session_id: str, q: str, a: str) -> None:
    """追加一轮，并维持滚动窗口。"""
    turn = Turn(q=q, a=a, ts=datetime.now().isoformat(timespec="seconds"))
    with _sess_lock:
        turns = SESSIONS.setdefault(session_id, [])
        turns.append(turn)
        if len(turns) > MAX_HISTORY_TURNS:
            # 淘汰最早的
            del turns[: len(turns) - MAX_HISTORY_TURNS]


def _format_history_for_prompt(turns: List[Turn]) -> str:
    """把历史轮次格式化成 prompt 用的字符串。空列表返回空字符串。"""
    if not turns:
        return ""
    lines = []
    for i, t in enumerate(turns, 1):
        lines.append(f"  Q{i}: {t.q}")
        lines.append(f"  A{i}: {t.a}")
    return "\n".join(lines)


def _summarize_answer(final_state: dict) -> str:
    """
    从一轮 Supervisor 执行结果提炼答复摘要（塞进历史的 a 字段）。
    优先级：final_report.summary > agent_outputs[-1] 截断到 200 字。
    """
    report = final_state.get("final_report")
    if report and isinstance(report, dict) and report.get("summary"):
        return str(report["summary"])[:200]
    outputs = final_state.get("agent_outputs") or []
    if outputs:
        return str(outputs[-1])[:200]
    return "（本轮无 Agent 产出）"


def _resolve_session_id(raw: Optional[str]) -> str:
    """若未传 session_id 则生成一个新的。"""
    return raw if (raw and raw.strip()) else str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════════════
# §3. SSE 事件格式化 + 核心流式生成器
# ═══════════════════════════════════════════════════════════════════════════
# sse-starlette 的 EventSourceResponse 接受 async 生成器，yield 的 dict
# 会被自动格式化为标准 SSE 报文：
#
#   yield {"event": "node", "data": "..."}
#   ↓
#   event: node
#   data: ...
#   \n\n
# ═══════════════════════════════════════════════════════════════════════════

def _sse(event: str, payload: dict) -> dict:
    """把 payload 序列化成 SSE event dict。"""
    return {
        "event": event,
        "data": json.dumps(payload, ensure_ascii=False),
    }


def _merge_update(state: dict, update) -> None:
    """
    把单个 Node 的产出合并到累积 state 里。
    规则：agent_outputs 是 list 累加（对应 Annotated[List, operator.add]），
         其他字段直接覆盖。
    直接原地修改 state，返回 None。

    注：LangGraph 有时 yield 的 update 不是 dict（可能是 tuple，如 interrupt 信号），
        非 dict 直接跳过。
    """
    if not isinstance(update, dict):
        return
    for key, value in update.items():
        if key == "agent_outputs" and isinstance(value, list):
            state.setdefault("agent_outputs", []).extend(value)
        else:
            state[key] = value


def _build_run_config(
    session_id: str,
    query: str,
    tag: str,
    thread_id: Optional[str] = None,
    recursion_limit: int = 24,
) -> dict:
    """
    构造 compiled_graph.invoke/astream 的 config 参数。

    作用：
      1) recursion_limit：LangGraph 主图最大步数限制
      2) metadata + tags：上报给 LangSmith，方便在 dashboard 按 session/tag 过滤 trace
      3) configurable.thread_id：LangGraph Checkpointer 定位 state 的 key
                                 HITL 下必填，否则 checkpointer 不知道把 state 存哪

    LangSmith trace 里这些元数据会挂到每条 trace 上：
      - metadata.session_id：同一会话的所有 trace 可一键过滤
      - tags：chat-stream / chat-blocking / resume 等，区分调用入口
    """
    cfg = {
        "recursion_limit": recursion_limit,
        "metadata": {
            "session_id":    session_id,
            "query_preview": query[:80],
        },
        "tags": [tag, f"session:{session_id[:8]}"],
    }
    if thread_id:
        cfg["configurable"] = {"thread_id": thread_id}
        cfg["tags"].append(f"thread:{thread_id[:8]}")
    return cfg


def _interrupt_reason(pending_node: str) -> str:
    """根据被拦截的节点，返回给用户看的确认理由。"""
    reasons = {
        "reporter":
            "即将生成结构化 JSON 报告（多调用 1 次 LLM，预计 +1.5～2s 延迟 / +500～2000 tokens），确认继续？",
    }
    return reasons.get(pending_node, f"即将执行 {pending_node} 节点，确认继续？")


async def stream_graph(query: str, session_id: str) -> AsyncGenerator[dict, None]:
    """
    核心：把 Supervisor Graph 的事件转成 SSE 流（支持多轮 session + HITL）。

    关键点：
      1) 流开头先推 event: session
      2) compiled.astream_events(v2) 升级为 token 级流式：
           - event: token  → LLM 每生成一个 token 推一次（parser/analyzer/reporter/db）
           - event: node   → 每个 Agent 节点完成后推一次（前端侧栏状态更新）
      3) astream_events 结束后检查 get_state：
           - 若 state.next 为空 → 正常结束，推 done
           - 若 state.next 非空 → HITL 中断（Reporter 前），推 interrupt
    """
    # ── 前处理：读历史 + 格式化进 prompt ──
    history_turns = _get_history(session_id)
    conversation_history = _format_history_for_prompt(history_turns)

    yield _sse("session", {
        "session_id": session_id,
        "prev_turns": len(history_turns),
    })

    thread_id = str(uuid.uuid4())

    initial_state = {
        "user_query":           query,
        "agent_outputs":        [],
        "next_agent":           "",
        "final_report":         None,
        "loop_count":           0,
        "conversation_history": conversation_history,
    }
    step = 0

    # 只对这些 Agent 节点做 token 流式推送（Supervisor 的路由决策是内部 JSON，不推）
    STREAMING_NODES = {"parser", "analyzer", "reporter", "db"}
    seen_nodes: set[str] = set()
    current_node: str = ""   # 當前正在執行的外層節點名

    try:
        run_config = _build_run_config(
            session_id, query, tag="chat-stream", thread_id=thread_id,
        )

        async for event in compiled_graph.astream_events(
            initial_state, version="v2", config=run_config
        ):
            kind = event["event"]
            name = event.get("name", "")
            metadata = event.get("metadata", {})
            lg_node = metadata.get("langgraph_node", "")

            # ── 追踪当前外层节点 ────────────────────────────────────────────────
            # Parser/Analyzer 的 LLM 调用，其 lg_node 是内部的 "model"，不是 "parser"
            # 用 on_chain_start/end 追踪哪个外层节点正在运行
            if kind == "on_chain_start" and name in STREAMING_NODES:
                current_node = name

            elif kind == "on_chain_end" and name in STREAMING_NODES:
                if name not in seen_nodes:
                    seen_nodes.add(name)
                    step += 1
                    yield _sse("node", {"step": step, "node": name})
                current_node = ""

            # ── Token 级推送：当前外层节点是 STREAMING_NODES 之一时推 token ────
            elif kind == "on_chat_model_stream" and current_node in STREAMING_NODES:
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse("token", {"delta": chunk.content, "node": current_node})

        # ── 检测是否因 interrupt_before 而中断 ──────────────────────────────────
        state_snap = compiled_graph.get_state(
            {"configurable": {"thread_id": thread_id}}
        )
        final_values = state_snap.values or {}

        if state_snap.next:
            pending_node = state_snap.next[0]
            logger.info(f"⏸  [HITL] 中断在 {pending_node} 前，thread_id={thread_id[:8]}")
            yield _sse("interrupt", {
                "thread_id":    thread_id,
                "session_id":   session_id,
                "pending_node": pending_node,
                "reason":       _interrupt_reason(pending_node),
                "state_preview": {
                    "agent_outputs": final_values.get("agent_outputs", [])[-2:],
                    "loop_count":    final_values.get("loop_count"),
                    "next_agent":    final_values.get("next_agent"),
                },
            })
            return

        # ── 正常结束 ─────────────────────────────────────────────────────────────
        answer = _summarize_answer(final_values)
        _append_turn(session_id, query, answer)
        yield _sse("done", {
            "final_state": final_values,
            "session_id":  session_id,
            "turn":        len(_get_history(session_id)),
        })

    except Exception as e:
        logger.error(f"stream_graph 失败：{e}", exc_info=True)
        yield _sse("error", {
            "message":    f"{type(e).__name__}: {e}",
            "step":       step,
            "session_id": session_id,
        })


# ═══════════════════════════════════════════════════════════════════════════
# §4. FastAPI 应用 + 路由
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Java-to-Agent Supervisor Service",
    description="LangGraph Supervisor 多 Agent 调度的 HTTP 化封装，支持 SSE 节点级流式。",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """健康检查：外部 ping 用。"""
    return HealthResponse(
        status="ok",
        provider=settings.llm_provider,
        model=settings.model_name,
    )


@app.get("/")
async def index():
    """返回前端 demo 页面。"""
    html_path = HERE / "static" / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(html_path, media_type="text/html")


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    阻塞式调用：等 Supervisor 跑完一次性返回完整 state。支持多轮 session。
    用途：自动化脚本 / curl 对比测试 / 不需要流式的场景。
    """
    session_id = _resolve_session_id(req.session_id)
    history_turns = _get_history(session_id)
    conversation_history = _format_history_for_prompt(history_turns)

    initial_state = {
        "user_query":           req.query,
        "agent_outputs":        [],
        "next_agent":           "",
        "final_report":         None,
        "loop_count":           0,
        "conversation_history": conversation_history,
    }
    try:
        run_config = _build_run_config(session_id, req.query, tag="chat-blocking")
        final_state = await asyncio.to_thread(
            compiled_graph.invoke, initial_state, run_config
        )
        # 入库
        answer = _summarize_answer(final_state)
        _append_turn(session_id, req.query, answer)
        # 响应里带上 session 信息
        resp = dict(final_state)
        resp["session_id"] = session_id
        resp["turn"] = len(_get_history(session_id))
        return JSONResponse(content=resp)
    except Exception as e:
        logger.error(f"/chat 失败：{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    ⭐ 主打：SSE 流式推送节点级事件。支持多轮 session + HITL 中断。

    事件类型：
      - event: session   → 首个事件，告知 session_id 和已有历史轮数
      - event: node      → 每个 Node 执行完推一条
      - event: interrupt → HITL：Reporter 等敏感节点前中断，等 /chat/resume
      - event: done      → Graph 执行结束（含 final_state + session_id + turn）
      - event: error     → 异常信息
    """
    session_id = _resolve_session_id(req.session_id)
    return EventSourceResponse(stream_graph(req.query, session_id))


@app.post("/chat/resume")
async def chat_resume(req: ResumeRequest):
    """
    HITL 恢复：前端收到 interrupt 事件，用户选择后调这里。

    - approved=true  → 从 checkpoint 恢复继续执行被拦节点
    - approved=false → 直接 cancel，不执行被拦节点（final_report 为 null）

    响应仍是 SSE 流，事件和 /chat/stream 一样。
    """
    session_id = _resolve_session_id(req.session_id)
    return EventSourceResponse(stream_resume(req, session_id))


async def stream_resume(req: ResumeRequest, session_id: str) -> AsyncGenerator[dict, None]:
    """
    恢复中断的 Supervisor Graph 或取消 Reporter。

    核心 LangGraph API：
      compiled.get_state(config) → 读当前 checkpoint state
      compiled.astream(None, config) → None 作为输入表示从 checkpoint 恢复
    """
    config = {"configurable": {"thread_id": req.thread_id}}
    # 1) 取 checkpoint 快照
    try:
        state_snap = compiled_graph.get_state(config)
    except Exception as e:
        logger.warning(f"get_state 失败：{e}")
        yield _sse("error", {"message": f"checkpoint 读取失败：{e}"})
        return

    # 2) 校验：checkpoint 是否存在、是否还有未执行节点
    if state_snap is None or not state_snap.values:
        yield _sse("error", {"message": "checkpoint 不存在或已过期"})
        return
    if not state_snap.next:
        yield _sse("error", {"message": "该请求已完成，无法恢复"})
        return

    pending_node = state_snap.next[0]

    # 3) 拒绝分支：直接推 cancelled + done
    if not req.approved:
        logger.info(f"🛑 [HITL] 用户取消 {pending_node}，thread_id={req.thread_id[:8]}")
        yield _sse("cancelled", {
            "thread_id":    req.thread_id,
            "pending_node": pending_node,
            "reason":       "用户取消",
        })
        # 把当前 state 作为最终状态返回，并记入 session 历史
        final_state = dict(state_snap.values)
        answer = _summarize_answer(final_state)
        query = final_state.get("user_query", "")
        _append_turn(session_id, query, f"[已取消 {pending_node}] {answer}")
        yield _sse("done", {
            "final_state": final_state,
            "session_id":  session_id,
            "turn":        len(_get_history(session_id)),
            "cancelled":   True,
            "pending_node": pending_node,
        })
        return

    # 4) 接受分支：从 checkpoint resume
    logger.info(f"▶️  [HITL] 用户确认继续 {pending_node}，thread_id={req.thread_id[:8]}")

    # accumulator 从 checkpoint 已有 state 开始（不是空）
    accumulated = dict(state_snap.values)
    step = 0

    try:
        # 给 resume 调用加 tag，LangSmith 里能区分"这是一次续跑"
        resume_config = dict(config)
        resume_config.update({
            "tags":     ["chat-resume", f"thread:{req.thread_id[:8]}"],
            "metadata": {"session_id": session_id, "resume_from": pending_node},
            "recursion_limit": 24,
        })
        async for chunk in compiled_graph.astream(None, resume_config):
            if not isinstance(chunk, dict):
                continue   # 同上，跳过 interrupt 之类的非节点 chunk
            for node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                step += 1
                _merge_update(accumulated, update)
                yield _sse("node", {
                    "step":   step,
                    "node":   node_name,
                    "update": update,
                })

        # resume 后应该是正常结束（没有新的 interrupt_before 再触发）
        answer = _summarize_answer(accumulated)
        query = accumulated.get("user_query", "")
        _append_turn(session_id, query, answer)
        yield _sse("done", {
            "final_state": accumulated,
            "session_id":  session_id,
            "turn":        len(_get_history(session_id)),
            "resumed_from": pending_node,
        })
    except Exception as e:
        logger.error(f"stream_resume 失败：{e}", exc_info=True)
        yield _sse("error", {
            "message":    f"{type(e).__name__}: {e}",
            "thread_id":  req.thread_id,
            "session_id": session_id,
        })


# ═══════════════════════════════════════════════════════════════════════════
# §4.5. Session 管理端点（查看 / 清除）
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """查看某 session 的历史轮次（调试用）。"""
    turns = _get_history(session_id)
    if not turns:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return {
        "session_id": session_id,
        "turns":      [t.model_dump() for t in turns],
        "count":      len(turns),
    }


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """清除某 session。幂等：不存在也返回 200。"""
    with _sess_lock:
        existed = SESSIONS.pop(session_id, None) is not None
    return {"deleted": existed, "session_id": session_id}


# ═══════════════════════════════════════════════════════════════════════════
# §5. 入口：uvicorn 启动
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Supervisor FastAPI 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8765,
                        help="监听端口（默认 8765，避开常用的 8000/8080）")
    args = parser.parse_args()

    uvicorn.run(
        "fastapi_service:app",
        host=args.host,
        port=args.port,
        reload=False,      # 学习场景不开 reload，避免编译 graph 耗时重复
        log_level="info",
    )


if __name__ == "__main__":
    main()
