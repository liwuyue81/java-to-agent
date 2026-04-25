"""
把 seed_cases.yaml 同步成 LangSmith Dataset。

目的：让团队在 LangSmith UI 里可视化 case 列表，未来还可以直接在 UI 上跑
      Experiment 对比不同 prompt/model。

幂等：dataset 已存在则清空 examples 重推（upsert 语义）。

用法：
  .venv/bin/python tech_showcase/regression/sync_to_langsmith.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("sync_to_langsmith")

SEED_YAML = HERE / "seed_cases.yaml"
DATASET_NAME = "java-to-agent-regression"
DATASET_DESC = "Supervisor Agent 回归测试用例（从 seed_cases.yaml 同步）"


def main():
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        logger.error(
            "LangSmith 未启用。请在 .env 设置 LANGSMITH_TRACING=true 和 LANGSMITH_API_KEY"
        )
        sys.exit(2)

    from langsmith import Client
    client = Client()

    with open(SEED_YAML, "r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)
    logger.info(f"从 {SEED_YAML.relative_to(PROJECT_ROOT)} 读到 {len(cases)} 条 case")

    # 1) 建/取 dataset
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
        logger.info(f"dataset 已存在：{DATASET_NAME}，准备清空 examples 后重推")
        # 删旧 examples（幂等 upsert）
        old_examples = list(client.list_examples(dataset_name=DATASET_NAME))
        if old_examples:
            ids = [ex.id for ex in old_examples]
            client.delete_examples(example_ids=ids)
            logger.info(f"已删除 {len(ids)} 条旧 examples")
    else:
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME, description=DATASET_DESC
        )
        logger.info(f"新建 dataset：{DATASET_NAME}")

    # 2) 推新 examples
    inputs = [
        {
            "query":                c["query"],
            "conversation_history": c.get("conversation_history", ""),
        }
        for c in cases
    ]
    outputs = [
        {
            "expected_route":        c.get("expected_route", []),
            "expected_keywords":     c.get("expected_keywords", []),
            "expected_final_report": c.get("expected_final_report", False),
        }
        for c in cases
    ]
    metadata = [{"case_name": c["name"], "notes": c.get("notes", "")} for c in cases]

    client.create_examples(
        inputs=inputs,
        outputs=outputs,
        metadata=metadata,
        dataset_id=dataset.id,
    )
    logger.info(f"已 upsert {len(cases)} 条 examples 到 dataset {DATASET_NAME}")
    logger.info(
        f"浏览器查看：https://smith.langchain.com/ → 左侧 Datasets & Experiments"
        f" → 点 {DATASET_NAME}"
    )


if __name__ == "__main__":
    main()
