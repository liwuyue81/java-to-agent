# RAG 评估（RAGAS 核心思想）

> RAG 调优系列第 3 篇。不做评估，调优就是玄学。本篇介绍如何量化 RAG 的检索质量。

---

## 为什么需要评估？

调优 Chunk 策略或 Embedding 模型之后，你怎么知道效果变好了还是变差了？

```
改了 chunk 策略 → 主观感觉"好像好一点"
                          ↑
                    这不够，需要数字
```

评估的目标：**用可量化的指标，对比不同配置的检索质量。**

---

## RAGAS 是什么？

[RAGAS](https://docs.ragas.io/)（Retrieval Augmented Generation Assessment）是专门为 RAG 系统设计的评估框架，定义了一套衡量 RAG 质量的标准指标。

**RAGAS 的核心思想：**

```
RAG 系统 = 检索 + 生成
                ↓
评估 = 分别衡量"检索得对不对" + "生成有没有乱说"
```

---

## 三项核心指标

### 指标 1：Context Recall（上下文召回率）

**问的是：** 检索到的内容，有没有覆盖正确答案所需的信息？

```
ground_truth（标准答案）：
  "Connection pool exhausted, failed to acquire connection"

检索到的 chunks：
  chunk1: "ERROR DBPool - Connection pool exhausted..."  ← 覆盖 ✓
  chunk2: "INFO UserService - User login success..."     ← 无关 ✗
  chunk3: "ERROR DBPool - failed to acquire connection"  ← 覆盖 ✓

Context Recall = 2 / 2 关键点覆盖 = 1.0  （满分）
```

**低分说明：** 向量库里有答案，但没检索到。根因通常是 Chunk 切得太小或 Embedding 模型跨语言弱。

---

### 指标 2：Faithfulness（忠实度）

**问的是：** Agent 的回答，每一句话都有检索内容作为依据吗？

```
检索内容：
  "Connection pool exhausted at 08:15:22"

Agent 回答：
  "连接池在 08:15 耗尽"             ← 有依据 ✓
  "这是因为并发请求超过了 500 个"   ← 日志里没提，是幻觉 ✗

Faithfulness = 1 / 2 陈述有依据 = 0.5
```

**低分说明：** LLM 在"编故事"，回答里有检索内容之外的内容。这是大模型的常见问题（幻觉）。

---

### 指标 3：Answer Relevance（回答相关性）

**问的是：** 回答有没有真正回答用户的问题？

```
问题：   "有没有数据库连接方面的问题？"

好的回答（高分）：
  "是的，08:15 DBPool 连接池耗尽，导致订单和支付服务失败"

差的回答（低分）：
  "日志里有 UserService、OrderService、DBPool 等多个服务..."
  ↑ 答非所问，没有聚焦在"是否有问题"上
```

**低分说明：** LLM 答非所问，或者把检索内容原文堆砌，没有提炼。

---

## 三者的关系

```
Context Recall    → 衡量"检索"部分的质量
Faithfulness      → 衡量"生成"部分是否诚实
Answer Relevance  → 衡量"最终回答"是否有用

都高 = RAG 系统整体健康
只有 Recall 低 = 检索有问题（Chunk/Embedding 需要调）
只有 Faithfulness 低 = LLM 幻觉严重（换更强模型或加 Prompt 约束）
只有 Relevance 低 = Prompt 设计有问题
```

---

## Ground Truth 是什么？

RAGAS 需要"标准答案"（ground truth）作为评估基准。

```python
# rag/eval_rag.py 中的评估数据集示例
EVAL_DATASET = [
    {
        "question": "database connection pool exhausted",
        "ground_truth": "Connection pool exhausted, failed to acquire connection. DBPool max=50 reached.",
    },
    {
        "question": "redis cache connection failure",
        "ground_truth": "Redis connection failed: host=redis-01, port=6379.",
    },
    ...
]
```

**谁来写 ground truth？**

| 场景 | 来源 |
|---|---|
| 开发阶段（当前）| 开发者根据已知日志手工标注 |
| 测试阶段 | QA 团队标注 |
| 生产阶段 | 用 GPT-4 / Claude 自动生成后人工复核 |

---

## 关于 RAGAS 库的兼容性

项目已升级到 Python 3.11 + ragas 0.4.3，**可直接使用官方 RAGAS**。

```bash
# 已包含在 requirements.txt，直接安装即可
pip install -r requirements.txt
```

---

## 本项目的评估脚本

项目提供了 `rag/eval_rag.py`，用项目自带的 Ollama LLM 作为"评委"实现三项指标，
**无需 OpenAI Key，完全本地运行**。

### 运行方式

> **注意：** 必须在项目根目录下用 `-m` 方式运行，否则 `rag` 模块找不到。

```bash
# 进入项目根目录
cd /Users/photonpay/java-to-agent

# 第一次运行前先建索引（已建过可跳过）
.venv/bin/python -c "from rag.log_indexer import index_logs; index_logs()"

# 运行评估（用 -m 方式）
.venv/bin/python -m rag.eval_rag
```

### 实际输出（sliding_window 策略，2026-04-10）

```
============================================================
RAG 评估报告  [chunk 策略: sliding_window]
============================================================

问题 1: database connection pool exhausted
  Context Recall  : 0.80
  Faithfulness    : 1.00
  Answer Relevance: 0.95

问题 2: redis cache connection failure
  Context Recall  : 0.71
  Faithfulness    : 1.00
  Answer Relevance: 1.00

问题 3: payment service error
  Context Recall  : 0.83
  Faithfulness    : 1.00
  Answer Relevance: 0.85

问题 4: slow scheduled job
  Context Recall  : 0.83
  Faithfulness    : 1.00
  Answer Relevance: 1.00

问题 5: order creation failure
  Context Recall  : 0.86
  Faithfulness    : 1.00
  Answer Relevance: 1.00

────────────────────────────────────────
平均 Context Recall  : 0.81
平均 Faithfulness    : 1.00
平均 Answer Relevance: 0.96
综合得分             : 0.92
============================================================
```

**结果解读：**
- Faithfulness 1.00：qwen2.5:7b 没有产生幻觉，回答完全基于检索内容 ✓
- Answer Relevance 0.96：回答几乎都直接回答了问题 ✓
- Context Recall 0.81：检索覆盖率有提升空间，是后续调优的主要方向

---

## 用评估指导调优

### 对比 Chunk 策略

```bash
# 第一步：用 per_line 建索引，评估
.venv/bin/python -c "from rag.log_indexer import index_logs; index_logs(force=True, strategy='per_line')"
.venv/bin/python -m rag.eval_rag   # 记录分数 A

# 第二步：用 sliding_window 建索引，评估
.venv/bin/python -c "from rag.log_indexer import index_logs; index_logs(force=True)"
.venv/bin/python -m rag.eval_rag   # 记录分数 B

# 对比 A vs B，Context Recall 有没有提升？
```

### 对比 Embedding 模型

```bash
# 修改 config.py: embed_model = "nomic-embed-text"，强制重建索引，运行评估
.venv/bin/python -c "from rag.log_indexer import index_logs; index_logs(force=True)"
.venv/bin/python -m rag.eval_rag   # 记录分数

# 修改 config.py: embed_model = "bge-m3"，强制重建索引，运行评估
.venv/bin/python -c "from rag.log_indexer import index_logs; index_logs(force=True)"
.venv/bin/python -m rag.eval_rag   # 对比 Context Recall 变化
```

### 分数参考

| 分数 | 含义 |
|---|---|
| 0.9+ | 优秀，可用于生产 |
| 0.7~0.9 | 良好，有优化空间 |
| 0.5~0.7 | 一般，需要明确找出短板 |
| <0.5 | 较差，检索策略需要重新设计 |

---

## 使用官方 RAGAS 库

项目已升级到 Python 3.11，可直接使用官方 RAGAS 替换 `eval_rag.py` 的自定义实现。
官方 RAGAS 的优势是指标更精准、支持批量评估、有更详细的报告。

```bash
# 已在 requirements.txt 中，直接可用
pip install -r requirements.txt
```

```python
from ragas import evaluate
from ragas.metrics.collections import faithfulness, answer_relevancy, context_recall
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_ollama import ChatOllama, OllamaEmbeddings
from datasets import Dataset

# 配置使用本地 Ollama（不需要 OpenAI）
llm = LangchainLLMWrapper(ChatOllama(model="qwen2.5:7b", temperature=0))
embeddings = LangchainEmbeddingsWrapper(OllamaEmbeddings(model="bge-m3"))

data = {
    "question": ["database connection pool exhausted"],
    "answer": ["08:15 DBPool connection pool exhausted, max=50 reached"],
    "contexts": [["ERROR DBPool - Connection pool exhausted..."]],
    "ground_truth": ["Connection pool exhausted, failed to acquire connection"],
}

dataset = Dataset.from_dict(data)
result = evaluate(
    dataset,
    metrics=[faithfulness, answer_relevancy, context_recall],
    llm=llm,
    embeddings=embeddings,
)
print(result)
```

---

## 小结

| 指标 | 衡量什么 | 低分根因 |
|---|---|---|
| Context Recall | 检索有没有找到正确内容 | Chunk 太小 / Embedding 跨语言弱 |
| Faithfulness | 回答有没有幻觉 | LLM 能力不足 / Prompt 约束不够 |
| Answer Relevance | 回答有没有答非所问 | Prompt 设计 / LLM 理解能力 |

**调优闭环：**

```
改 Chunk / Embedding
      ↓
运行 eval_rag.py
      ↓
对比三项指标的分数变化
      ↓
继续改 → 继续评估
```

---

## 延伸阅读

- [RAGAS 官方文档](https://docs.ragas.io/) — 完整指标说明和快速上手
- [RAGAS GitHub](https://github.com/explodinggradients/ragas) — 源码 + 示例
- [RAGAS 快速评估教程](https://docs.ragas.io/en/stable/getstarted/rag_eval/) — 10 分钟跑完第一个评估
