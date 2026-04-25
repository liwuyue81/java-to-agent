"""
RAG 评估脚本（官方 ragas 库版）

相比 eval_rag.py：
  - 用 ragas 0.4+ 官方实现，指标算法业界标准，可和他人结果横向对比
  - 通过 LangchainLLMWrapper 指定自定义 judge（此处用 qwen-plus，省钱版）
  - 内部的 answer_relevancy 指标会用 embeddings（复用项目的 DashScope 配置）

评估三项指标（ragas 内置）：
  - context_recall     ：检索结果对 ground truth 的覆盖率
  - faithfulness       ：回答是否忠实于上下文（幻觉检测）
  - answer_relevancy   ：回答与问题的相关性（内部用 embedding 相似度）

用法：
  python rag/eval_rag_ragas.py                                 # 默认 sliding_window / k=5
  python rag/eval_rag_ragas.py --strategy per_line --k 3       # 对照基准
  python rag/eval_rag_ragas.py --compare                       # A/B 对比两种策略
"""
import argparse
import logging
import sys
from pathlib import Path

import yaml
from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_llm, get_embeddings
from rag.log_indexer import index_logs, search_similar_logs

# 抑制 ragas 内部的冗长日志
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "eval_dataset.yaml"


def load_dataset() -> list[dict]:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ═════════════════════════════════════════════════════════════════════
# 准备：生成答案 + 包装 ragas 可用的数据集
# ═════════════════════════════════════════════════════════════════════
def build_eval_samples(dataset: list[dict], k: int, answer_llm) -> dict:
    """
    对每条数据执行：检索 → 生成答案，构造 ragas 需要的 4 列：
      question / answer / contexts / ground_truth / reference
    （ragas 0.4+ 字段名为 user_input / response / retrieved_contexts / reference）
    这里先按老字段名组织，最后统一适配。
    """
    questions, answers, contexts_list, ground_truths = [], [], [], []

    for sample in dataset:
        q = sample["question"]
        gt = sample["ground_truth"]

        docs = search_similar_logs(q, k=k)
        ctx = [d.page_content for d in docs]

        ans_prompt = f"Based on these log entries:\n{chr(10).join(ctx)}\n\nAnswer: {q}"
        ans = answer_llm.invoke([HumanMessage(content=ans_prompt)]).content

        questions.append(q)
        answers.append(ans)
        contexts_list.append(ctx)
        ground_truths.append(gt)

    return {
        "question": questions,
        "answer": answers,
        "contexts": contexts_list,
        "ground_truth": ground_truths,
        # ragas 0.4+ 新字段名
        "user_input": questions,
        "response": answers,
        "retrieved_contexts": contexts_list,
        "reference": ground_truths,
    }


# ═════════════════════════════════════════════════════════════════════
# 主评估函数（调用 ragas.evaluate）
# ═════════════════════════════════════════════════════════════════════
def run_evaluation(strategy: str = "sliding_window", k: int = 5) -> dict:
    # 延迟 import ragas，减轻不用时的启动开销
    from ragas import evaluate
    from ragas.metrics import context_recall, faithfulness, answer_relevancy
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from datasets import Dataset

    # ★ 真正切换：重建向量库
    print(f"\n[setup] 用 strategy={strategy} 重建向量库...")
    index_logs(force=True, strategy=strategy)

    print(f"\n{'='*60}")
    print(f"RAG 评估报告（ragas 官方库）  strategy={strategy}, k={k}")
    print(f"{'='*60}\n")

    # 1) 构造评估样本
    dataset = load_dataset()
    llm = get_llm(temperature=0)
    samples = build_eval_samples(dataset, k=k, answer_llm=llm)
    hf_dataset = Dataset.from_dict(samples)

    # 2) 用 wrapper 把项目的 LLM / Embeddings 注入 ragas
    #    这样 ragas 不会去调默认的 OpenAI API
    ragas_llm = LangchainLLMWrapper(llm)
    ragas_embeddings = LangchainEmbeddingsWrapper(get_embeddings())

    # 3) 跑评估（context_recall + faithfulness 只用 llm；answer_relevancy 需要 embeddings）
    result = evaluate(
        dataset=hf_dataset,
        metrics=[context_recall, faithfulness, answer_relevancy],
        llm=ragas_llm,
        embeddings=ragas_embeddings,
        raise_exceptions=False,   # 单条失败不中断整体评估
    )

    # 4) 提取指标（ragas 0.4 返回的 EvaluationResult 支持 to_pandas()）
    df = result.to_pandas()
    scores = {
        "strategy": strategy,
        "k": k,
        "context_recall":    float(df["context_recall"].mean(skipna=True)),
        "faithfulness":      float(df["faithfulness"].mean(skipna=True)),
        "answer_relevancy":  float(df["answer_relevancy"].mean(skipna=True)),
    }
    scores["overall"] = (scores["context_recall"] + scores["faithfulness"] + scores["answer_relevancy"]) / 3

    # 打印每条详情
    for i, row in df.iterrows():
        print(f"问题 {i+1}: {row.get('user_input', row.get('question', ''))[:50]}")
        print(f"  context_recall   : {row.get('context_recall', float('nan')):.2f}")
        print(f"  faithfulness     : {row.get('faithfulness', float('nan')):.2f}")
        print(f"  answer_relevancy : {row.get('answer_relevancy', float('nan')):.2f}")
        print()

    print(f"{'─'*40}")
    print(f"平均 context_recall   : {scores['context_recall']:.2f}")
    print(f"平均 faithfulness     : {scores['faithfulness']:.2f}")
    print(f"平均 answer_relevancy : {scores['answer_relevancy']:.2f}")
    print(f"综合得分              : {scores['overall']:.2f}")
    print(f"{'='*60}\n")
    return scores


def run_compare(k: int = 5) -> None:
    """一次跑完 per_line vs sliding_window，并列对比。"""
    r1 = run_evaluation(strategy="per_line", k=k)
    r2 = run_evaluation(strategy="sliding_window", k=k)

    print(f"\n{'█'*60}")
    print(f"  A/B 对比（ragas 官方指标）：per_line vs sliding_window (k={k})")
    print(f"{'█'*60}")
    print(f"{'指标':<22} {'per_line':>12} {'sliding_window':>18} {'Δ':>8}")
    print("─" * 60)
    for key, label in [
        ("context_recall",    "context_recall"),
        ("faithfulness",      "faithfulness"),
        ("answer_relevancy",  "answer_relevancy"),
        ("overall",           "综合得分"),
    ]:
        delta = r2[key] - r1[key]
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
        print(f"{label:<20} {r1[key]:>12.2f} {r2[key]:>18.2f} {arrow}{abs(delta):>6.2f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="RAG 评估（ragas 官方库版）")
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
