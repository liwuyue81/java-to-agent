"""
Prompt 回归测试运行器。

职责：
  1. 加载 seed_cases.yaml 里的测试用例
  2. 逐条跑 Supervisor Graph，记录路由序列、耗时、最终产出
  3. 执行三层评估：硬断言（路由+关键词） + LLM judge（相关性） + 性能
  4. 对比 baseline.json（若存在），输出 Markdown 报告到 reports/
  5. 写 latest.json；首次运行顺便产出 baseline.json
  6. 退出码：0=全过 / 1=有失败，供未来 CI 使用

用法：
  .venv/bin/python tech_showcase/regression/run_regression.py

Java 类比：
  整个框架 ≈ JUnit 的 @Test + @BeforeAll + 自定义 Runner
  baseline.json    ≈ JUnit snapshot（approved 快照）
  LLM judge       ≈ 让另一个 LLM 来评判输出质量（没有 Java 对应物）
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# ── 路径准备：把项目根和 tech_showcase 加进 sys.path ─────────────────────
HERE = Path(__file__).resolve().parent               # .../tech_showcase/regression
TECH_SHOWCASE = HERE.parent                           # .../tech_showcase
PROJECT_ROOT = TECH_SHOWCASE.parent                   # .../java-to-agent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TECH_SHOWCASE))

from config import get_llm, settings  # noqa: E402
from langgraph_supervisor import build_supervisor_graph  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,  # 回归场景不需要 Supervisor 的 INFO 噪声
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
# 但回归脚本自己的 INFO 要打印
logger = logging.getLogger("regression")
logger.setLevel(logging.INFO)


# ═══════════════════════════════════════════════════════════════════════════
# §1. 配置
# ═══════════════════════════════════════════════════════════════════════════

SEED_YAML    = HERE / "seed_cases.yaml"
BASELINE_JSON = HERE / "baseline.json"
LATEST_JSON   = HERE / "latest.json"
REPORTS_DIR   = HERE / "reports"

AGENT_NODES = ("parser", "analyzer", "reporter")

# 可通过 .env 覆盖 judge 模型；默认同被测模型
JUDGE_MODEL_NAME = os.environ.get("REGRESSION_JUDGE_MODEL", "")  # 空则用 settings.model_name


# ═══════════════════════════════════════════════════════════════════════════
# §2. 核心：跑单条 case
# ═══════════════════════════════════════════════════════════════════════════

compiled_graph = build_supervisor_graph()  # 全局复用，一次编译多次跑


def _merge_update(state: dict, update: dict) -> None:
    """和 fastapi_service.py 的逻辑等价：agent_outputs 累加，其余覆盖。"""
    for key, value in update.items():
        if key == "agent_outputs" and isinstance(value, list):
            state.setdefault("agent_outputs", []).extend(value)
        else:
            state[key] = value


def run_case(case: dict, run_id: str) -> dict:
    """
    跑一条 case，返回 result dict（后续会写 json 和 md）。
    """
    name = case["name"]
    query = case["query"]
    conversation_history = case.get("conversation_history", "")

    initial_state = {
        "user_query":           query,
        "agent_outputs":        [],
        "next_agent":           "",
        "final_report":         None,
        "loop_count":           0,
        "conversation_history": conversation_history,
    }

    # LangSmith config：打 tag，方便在 dashboard 里按 run_id / case 过滤
    run_config = {
        "recursion_limit": 24,
        "tags": ["regression", f"run-{run_id}", f"case-{name}"],
        "metadata": {
            "regression_run": run_id,
            "case":           name,
            "query_preview":  query[:80],
        },
    }

    route_trace: list[str] = []
    final_state = dict(initial_state)

    start = time.time()
    try:
        for chunk in compiled_graph.stream(initial_state, run_config):
            for node_name, update in chunk.items():
                _merge_update(final_state, update)
                if node_name in AGENT_NODES:
                    route_trace.append(node_name)
        error_msg = None
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"case {name} 执行异常：{error_msg}")

    duration = round(time.time() - start, 2)

    # ── 硬断言 ──────────────────────────────────────────
    expected_route = case.get("expected_route", [])
    if not expected_route:
        # 越界问题：期望没有任何 Agent 被调到
        route_ok = len(route_trace) == 0
    else:
        # 宽松匹配：expected 里每个 agent 必须在 route_trace 里出现（顺序不严格）
        route_ok = all(a in route_trace for a in expected_route)

    outputs_joined = " ".join(final_state.get("agent_outputs", []))
    kw_ok = all(
        kw.lower() in outputs_joined.lower()
        for kw in case.get("expected_keywords", [])
    )

    expect_report = case.get("expected_final_report", False)
    report_ok = bool(final_state.get("final_report")) == expect_report

    # ── LLM judge ──────────────────────────────────────
    if error_msg or not final_state.get("agent_outputs"):
        judge = 0.0
        judge_reason = "执行失败或无输出"
    else:
        judge, judge_reason = _llm_judge(query, outputs_joined[:800])

    passed = route_ok and kw_ok and report_ok and (error_msg is None)

    return {
        "name":         name,
        "query":        query,
        "pass":         passed,
        "route_ok":     route_ok,
        "kw_ok":        kw_ok,
        "report_ok":    report_ok,
        "judge":        judge,
        "judge_reason": judge_reason,
        "route":        route_trace,
        "expected_route": expected_route,
        "duration_s":   duration,
        "answer":       outputs_joined[:500],
        "error":        error_msg,
    }


# ═══════════════════════════════════════════════════════════════════════════
# §3. LLM judge —— 用同模型打 0/0.5/1 分
# ═══════════════════════════════════════════════════════════════════════════

JUDGE_PROMPT = """你在评估一个日志分析 Agent 的回答质量。

用户问题：{query}

Agent 回答：
{answer}

请按以下维度评分：
  - 是否正面回答了用户问题（不是答非所问）
  - 是否基于真实日志（而非编造）
  - 回答是否简洁、无明显冗余

输出严格的 JSON，字段：
  score: 1.0（完全合格）/ 0.5（部分合格）/ 0.0（不合格）
  reason: 一句话说明

只返回 JSON，不要别的。"""


_judge_llm = None


def _get_judge_llm():
    """延迟初始化 judge LLM。"""
    global _judge_llm
    if _judge_llm is None:
        if JUDGE_MODEL_NAME:
            # 用户通过 env 指定了不同模型（如 qwen-max 做 judge）
            from langchain_openai import ChatOpenAI
            _judge_llm = ChatOpenAI(
                model=JUDGE_MODEL_NAME,
                api_key=settings.api_key,
                base_url=settings.api_base_url or None,
                temperature=0,
                timeout=settings.timeout,
            )
        else:
            _judge_llm = get_llm(temperature=0)
    return _judge_llm


def _llm_judge(query: str, answer: str) -> tuple[float, str]:
    """让 LLM 打分，返回 (score, reason)。"""
    prompt = JUDGE_PROMPT.format(query=query, answer=answer)
    try:
        raw = _get_judge_llm().invoke(prompt).content.strip()
        # 去掉可能的 ```json 围栏
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        score = float(data.get("score", 0.0))
        reason = str(data.get("reason", ""))[:120]
        return score, reason
    except Exception as e:
        logger.warning(f"judge 解析失败，回退 0.5：{e}")
        return 0.5, f"judge error: {e}"


# ═══════════════════════════════════════════════════════════════════════════
# §4. 报告生成
# ═══════════════════════════════════════════════════════════════════════════

def _aggregate(results: list[dict]) -> dict:
    """聚合指标用于总览和对比。"""
    n = len(results)
    if n == 0:
        return {"pass_rate": 0.0, "judge_avg": 0.0, "total_duration_s": 0.0}
    return {
        "pass_count":       sum(1 for r in results if r["pass"]),
        "total":            n,
        "pass_rate":        round(sum(1 for r in results if r["pass"]) / n, 3),
        "judge_avg":        round(sum(r["judge"] for r in results) / n, 3),
        "total_duration_s": round(sum(r["duration_s"] for r in results), 1),
    }


def _cmp(label: str, curr: float, base: Optional[float], is_percent: bool = False) -> str:
    """格式化 before → after 的单行对比。"""
    fmt = "{:.1%}" if is_percent else "{:.2f}"
    if base is None:
        return f"- {label}：{fmt.format(curr)}"
    delta = curr - base
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
    return f"- {label}：{fmt.format(base)} → {fmt.format(curr)} （{arrow}{fmt.format(abs(delta))}）"


def build_report(results: list[dict], baseline: Optional[dict], run_id: str) -> str:
    """生成 Markdown 报告。"""
    agg = _aggregate(results)
    baseline_agg = _aggregate(baseline["results"]) if baseline else None

    lines = []
    lines.append(f"# Prompt 回归报告 — {run_id}")
    lines.append("")
    lines.append(f"**模型**：{settings.llm_provider} / {settings.model_name}")
    if JUDGE_MODEL_NAME:
        lines.append(f"**Judge 模型**：{JUDGE_MODEL_NAME}")
    lines.append("")

    lines.append("## 总览")
    lines.append(f"- 通过：{agg['pass_count']}/{agg['total']}（{agg['pass_rate']:.1%}）")
    lines.append(f"- LLM judge 平均：{agg['judge_avg']:.2f}")
    lines.append(f"- 总耗时：{agg['total_duration_s']:.1f} 秒")
    lines.append("")

    if baseline_agg:
        lines.append(f"## vs baseline（run_id={baseline.get('run_id', '?')}）")
        lines.append(_cmp("通过率", agg["pass_rate"], baseline_agg["pass_rate"], is_percent=True))
        lines.append(_cmp("LLM judge 平均", agg["judge_avg"], baseline_agg["judge_avg"]))
        lines.append(_cmp("总耗时（秒）", agg["total_duration_s"], baseline_agg["total_duration_s"]))
        lines.append("")

    lines.append("## 单 case 详情")
    lines.append("")
    for r in results:
        icon = "✅" if r["pass"] else "❌"
        lines.append(f"### {icon} {r['name']}")
        lines.append(f"- query: `{r['query']}`")
        lines.append(f"- route: {r['route']} | expected: {r['expected_route']} → **{'✓' if r['route_ok'] else '✗'}**")
        lines.append(f"- kw: {'✓' if r['kw_ok'] else '✗'}｜report: {'✓' if r['report_ok'] else '✗'}｜judge: {r['judge']:.1f}（{r['judge_reason']}）")
        lines.append(f"- duration: {r['duration_s']}s")
        if r["error"]:
            lines.append(f"- **error**: `{r['error']}`")
        if r["answer"]:
            lines.append(f"- answer: {r['answer'][:200].replace(chr(10), ' ')}")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# §5. 入口
# ═══════════════════════════════════════════════════════════════════════════

def main():
    if not SEED_YAML.exists():
        logger.error(f"找不到 seed 文件：{SEED_YAML}")
        sys.exit(2)

    with open(SEED_YAML, "r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger.info(f"开始回归，共 {len(cases)} 条 case，run_id={run_id}")
    logger.info(f"模型：{settings.llm_provider}/{settings.model_name}，"
                f"LangSmith={'on' if settings.langsmith_tracing else 'off'}")

    results = []
    for i, case in enumerate(cases, 1):
        logger.info(f"[{i}/{len(cases)}] 跑 case: {case['name']}")
        r = run_case(case, run_id)
        status = "✅ pass" if r["pass"] else "❌ fail"
        logger.info(f"  → {status} | route={r['route']} | judge={r['judge']} | {r['duration_s']}s")
        results.append(r)

    payload = {"run_id": run_id, "model": settings.model_name, "results": results}

    # 写 latest.json
    LATEST_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # 对比 baseline（若无则不对比）
    baseline = None
    if BASELINE_JSON.exists():
        try:
            baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"读 baseline 失败：{e}")

    # 报告
    md = build_report(results, baseline, run_id)
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"{run_id}.md"
    report_path.write_text(md, encoding="utf-8")
    print()
    print(md)
    print()
    logger.info(f"报告已写入：{report_path.relative_to(PROJECT_ROOT)}")

    # 首次运行自动建立 baseline
    if baseline is None:
        BASELINE_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info(f"🎯 首次运行，baseline.json 已建立：{BASELINE_JSON.relative_to(PROJECT_ROOT)}")
        logger.info("   下次改完 prompt 再跑就会自动对比。想更新基线：mv latest.json baseline.json && git commit")

    # 退出码
    fail_count = sum(1 for r in results if not r["pass"])
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
