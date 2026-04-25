"""
RAG 评估脚本（简化版，不依赖 ragas 库）

说明：
  - 用项目统一的 get_llm() 工厂创建 judge，自动适配 Ollama / DashScope
  - 数据集从 rag/eval_dataset.yaml 读取（与代码解耦）
  - 支持通过 CLI 真正切换 chunk 策略和 k 值，而不是仅打印标签

评估的三项指标（和 RAGAS 思路一致，但实现简化）：
  1. Context Recall    —— 检索到的内容是否覆盖了正确答案
  2. Faithfulness      —— 回答是否忠实于检索内容（反向即幻觉）
  3. Answer Relevance  —— 回答是否真正回答了用户问题

⚠️ 已知偏差：judge LLM 即被评估 LLM 自身，存在 self-judgment bias，
   分数会系统性偏高。要更严谨的评估，用 rag/eval_rag_ragas.py。

用法：
  python rag/eval_rag.py                                # 默认 sliding_window / k=5
  python rag/eval_rag.py --strategy per_line --k 3      # 对照基准
  python rag/eval_rag.py --compare                      # 一次跑完两种策略对比
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import yaml
from langchain_core.messages import HumanMessage

# 支持从项目根或 rag/ 子目录运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_llm
from rag.log_indexer import index_logs, search_similar_logs

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "eval_dataset.yaml"


def load_dataset() -> list[dict]:
    """从 YAML 加载评估数据集。"""
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# 评估用的 LLM（judge），用项目工厂创建
judge_llm = get_llm(temperature=0)


# =====================================================================
# 指标 1：Context Recall
# =====================================================================
def evaluate_context_recall(contexts: list[str], ground_truth: str) -> float:
    context_text = "\n---\n".join(contexts)
    prompt = f"""You are evaluating a RAG system.

Ground truth answer: {ground_truth}

Retrieved contexts:
{context_text}

Task: Check if the key information in the ground truth can be found in the retrieved contexts.
Return a JSON with:
- "covered_points": list of key facts from ground truth that ARE present in contexts
- "missing_points": list of key facts from ground truth that are NOT in contexts
- "score": float from 0.0 to 1.0 (covered / total key points)

Return only valid JSON, no other text."""

    response = judge_llm.invoke([HumanMessage(content=prompt)])
    try:
        result = json.loads(_strip_code_fence(response.content))
        return float(result.get("score", 0.0))
    except Exception:
        # 解析失败时回退到关键词匹配
        keywords = ground_truth.lower().split()
        matched = sum(1 for kw in keywords if any(kw in ctx.lower() for ctx in contexts))
        return matched / len(keywords) if keywords else 0.0


# =====================================================================
# 指标 2：Faithfulness
# =====================================================================
def evaluate_faithfulness(answer: str, contexts: list[str]) -> float:
    context_text = "\n---\n".join(contexts)
    prompt = f"""You are evaluating a RAG system for hallucination.

Answer to evaluate: {answer}

Source contexts (the only ground truth):
{context_text}

Task: For each factual claim in the answer, check if it is supported by the contexts.
Return a JSON with:
- "supported_claims": list of claims that ARE supported by contexts
- "unsupported_claims": list of claims that are NOT supported (hallucinations)
- "score": float from 0.0 to 1.0 (supported / total claims)

Return only valid JSON, no other text."""

    response = judge_llm.invoke([HumanMessage(content=prompt)])
    try:
        result = json.loads(_strip_code_fence(response.content))
        return float(result.get("score", 0.0))
    except Exception:
        return 1.0


# =====================================================================
# 指标 3：Answer Relevance
# =====================================================================
def evaluate_answer_relevance(question: str, answer: str) -> float:
    prompt = f"""You are evaluating a RAG system.

Original question: {question}
Answer given: {answer}

Task: Rate how well the answer addresses the original question.
Consider:
- Does the answer directly respond to what was asked?
- Is the answer focused, or does it include irrelevant information?

Return a JSON with:
- "reasoning": one sentence explanation
- "score": float from 0.0 to 1.0

Return only valid JSON, no other text."""

    response = judge_llm.invoke([HumanMessage(content=prompt)])
    try:
        result = json.loads(_strip_code_fence(response.content))
        return float(result.get("score", 0.0))
    except Exception:
        return 0.5


def _strip_code_fence(text: str) -> str:
    """去掉 LLM 偶尔加的 ```json...``` 围栏，让 json.loads 能吃。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


# =====================================================================
# 主流程
# =====================================================================
def run_evaluation(strategy: str = "sliding_window", k: int = 5) -> dict:
    """
    对评估数据集运行完整评估。

    参数：
      strategy：chunk 策略，"per_line" 或 "sliding_window"（会真正重建向量库）
      k       ：检索 top-k
    返回：
      dict，含 avg_recall / avg_faithfulness / avg_relevance / overall
    """
    dataset = load_dataset()

    # ★ 真正切换：重建向量库为指定策略
    print(f"\n[setup] 用 strategy={strategy} 重建向量库...")
    index_logs(force=True, strategy=strategy)

    print(f"\n{'='*60}")
    print(f"RAG 评估报告（简化版）  strategy={strategy}, k={k}")
    print(f"{'='*60}\n")

    total_recall = total_faithfulness = total_relevance = 0.0

    for i, sample in enumerate(dataset, 1):
        question = sample["question"]
        ground_truth = sample["ground_truth"]

        # 1) 检索
        docs = search_similar_logs(question, k=k)
        contexts = [doc.page_content for doc in docs]

        # 2) 用检索结果生成回答（模拟 Agent 行为）
        context_text = "\n".join(contexts)
        answer_prompt = f"Based on these log entries:\n{context_text}\n\nAnswer: {question}"
        answer = judge_llm.invoke([HumanMessage(content=answer_prompt)]).content

        # 3) 三项指标
        recall = evaluate_context_recall(contexts, ground_truth)
        faithfulness = evaluate_faithfulness(answer, contexts)
        relevance = evaluate_answer_relevance(question, answer)

        total_recall += recall
        total_faithfulness += faithfulness
        total_relevance += relevance

        print(f"问题 {i}: {question}")
        print(f"  Context Recall  : {recall:.2f}")
        print(f"  Faithfulness    : {faithfulness:.2f}")
        print(f"  Answer Relevance: {relevance:.2f}")
        print()

    n = len(dataset)
    result = {
        "strategy": strategy,
        "k": k,
        "avg_recall": total_recall / n,
        "avg_faithfulness": total_faithfulness / n,
        "avg_relevance": total_relevance / n,
    }
    result["overall"] = (result["avg_recall"] + result["avg_faithfulness"] + result["avg_relevance"]) / 3

    print(f"{'─'*40}")
    print(f"平均 Context Recall  : {result['avg_recall']:.2f}")
    print(f"平均 Faithfulness    : {result['avg_faithfulness']:.2f}")
    print(f"平均 Answer Relevance: {result['avg_relevance']:.2f}")
    print(f"综合得分             : {result['overall']:.2f}")
    print(f"{'='*60}\n")
    return result


def run_compare(k: int = 5) -> None:
    """一次跑完 per_line vs sliding_window，对比打印。"""
    r1 = run_evaluation(strategy="per_line", k=k)
    r2 = run_evaluation(strategy="sliding_window", k=k)

    print(f"\n{'█'*60}")
    print(f"  A/B 对比：per_line vs sliding_window (k={k})")
    print(f"{'█'*60}")
    print(f"{'指标':<22} {'per_line':>12} {'sliding_window':>18} {'Δ':>8}")
    print("─" * 60)
    for key, label in [
        ("avg_recall", "Context Recall"),
        ("avg_faithfulness", "Faithfulness"),
        ("avg_relevance", "Answer Relevance"),
        ("overall", "综合得分"),
    ]:
        delta = r2[key] - r1[key]
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
        print(f"{label:<20} {r1[key]:>12.2f} {r2[key]:>18.2f} {arrow}{abs(delta):>6.2f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="RAG 评估（简化版）")
    parser.add_argument("--strategy", "-s", default="sliding_window",
                        choices=["per_line", "sliding_window"],
                        help="chunk 策略")
    parser.add_argument("--k", type=int, default=5, help="检索 top-k")
    parser.add_argument("--compare", action="store_true",
                        help="一次跑完 per_line vs sliding_window 对比")
    args = parser.parse_args()

    if args.compare:
        run_compare(k=args.k)
    else:
        run_evaluation(strategy=args.strategy, k=args.k)


if __name__ == "__main__":
    main()
