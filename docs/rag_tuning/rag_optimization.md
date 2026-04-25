# RAG 调优方向 & 学习路线

## 当前 Demo 的局限

| 问题 | 现状 | 影响 |
|---|---|---|
| 每行日志作为一个 chunk | 单行日志上下文太短 | 语义不完整 |
| nomic-embed-text 跨语言弱 | 中文问题靠 LLM 翻译兜底 | 不稳定 |
| 全量重建索引 | 日志追加时需手动 `force=True` | 不实用 |
| 没有评估体系 | 不知道检索准不准 | 无法量化改进 |

---

## 调优方向（按优先级）

### 1. Chunk 策略（最影响效果）

现在是一行一个 Document，实际应该：
- 把连续的 ERROR + 上下文几行合并成一个 chunk
- 或按时间窗口（同一秒的日志）合并
- 滑动窗口：N 行为一个 chunk，相邻 chunk 有重叠

```
当前：  [ERROR line42]  [INFO line43]  [ERROR line44]
改进：  [line40~44 context]  [line42~46 context]  ← 带上下文
```

### 2. 增量索引

日志文件一直在追加，需要记录已索引到哪一行（类似告警系统的 `offset`），只索引新增部分。

```python
# 参考告警系统的 state.json 思路
# 记录 last_indexed_line，每次只索引新行
```

### 3. 换多语言 Embedding 模型

| 模型 | 特点 | 适用场景 |
|---|---|---|
| `nomic-embed-text` | 英文最佳，274MB | 纯英文日志 |
| `multilingual-e5-large` | 中英文都行 | 中文查询英文日志 |
| `bge-m3` | 多语言，效果强 | 生产级推荐 |

### 4. Reranker（检索后重排）

```
向量检索召回 20 条
      ↓
用小模型重新打分排序
      ↓
取 top 5 返回给 Agent
```

解决向量检索"召回准但排序乱"的问题。

### 5. 评估体系（RAGAS）

用 RAGAS 框架评估三个核心指标：

| 指标 | 含义 |
|---|---|
| Context Recall | 检索到的内容是否覆盖了正确答案 |
| Faithfulness | 回答是否忠实于检索到的内容 |
| Answer Relevance | 回答是否真正回答了问题 |

> **不做评估，调优就是玄学。**

---

## 你需要学到什么地步

```
必须掌握
├── Chunk 策略（怎么切文档影响效果最大）
├── Embedding 模型选型（英文 / 中文 / 多语言）
├── 向量数据库基本操作（已掌握 ✓）
└── RAG 评估（RAGAS，至少跑一次知道怎么看指标）

了解原理即可
├── 向量距离算法（cosine / L2，知道有区别就行）
├── Reranker（知道有这个优化手段，需要时再深入）
└── HyDE / RAG-Fusion 等高级检索技巧

不需要深入
├── 自己训练 Embedding 模型
└── 向量数据库底层实现（HNSW 索引等）
```

---

## 建议的下一步实践

> 最有价值的一步：把 Chunk 策略从"每行"改成"N 行滑动窗口"，对比检索质量是否提升。
> 改动小，但能直接感受到 chunk 策略对效果的影响。

---

## 学习资料

### 入门必看

| 资源 | 链接 | 说明 |
|---|---|---|
| RAG from Scratch（LangChain 官方）| [GitHub](https://github.com/langchain-ai/rag-from-scratch) | LangChain 工程师写的从零实现，有配套视频 |
| LangChain RAG 官方文档 | [文档](https://www.langchain.com/retrieval) | 官方检索文档 |
| freeCodeCamp RAG 教程 | [教程](https://www.freecodecamp.org/news/mastering-rag-from-scratch/) | 从零掌握 RAG，适合入门 |

### Chunk 策略

| 资源 | 链接 | 说明 |
|---|---|---|
| NVIDIA：最佳 Chunk 策略 | [博客](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/) | 不同策略对比实验 |
| Weaviate：RAG Chunk 策略 | [博客](https://weaviate.io/blog/chunking-strategies-for-rag) | 有图解，易理解 |
| Unstructured：Chunk 最佳实践 | [博客](https://unstructured.io/blog/chunking-for-rag-best-practices) | 生产实践总结 |

### Embedding 模型选型

| 资源 | 链接 | 说明 |
|---|---|---|
| MTEB 排行榜 | [HuggingFace](https://huggingface.co/spaces/mteb/leaderboard) | Embedding 模型权威评测榜单 |
| Hugging Face 高级 RAG | [Cookbook](https://huggingface.co/learn/cookbook/en/advanced_rag) | 含 Embedding 模型选型指南 |

### Reranker

| 资源 | 链接 | 说明 |
|---|---|---|
| Pinecone：Reranker 详解 | [文章](https://www.pinecone.io/learn/series/rag/rerankers/) | Reranker 原理最清晰的一篇 |
| NVIDIA：RAG + Reranking | [博客](https://developer.nvidia.com/blog/enhancing-rag-pipelines-with-re-ranking/) | 工程实践视角 |

### RAG 评估（RAGAS）

| 资源 | 链接 | 说明 |
|---|---|---|
| RAGAS 官方文档 | [文档](https://docs.ragas.io/) | 必看，含快速上手指南 |
| RAGAS GitHub | [GitHub](https://github.com/explodinggradients/ragas) | 源码 + 示例 |
| RAGAS 快速评估教程 | [文档](https://docs.ragas.io/en/stable/getstarted/rag_eval/) | 10 分钟跑完第一个评估 |

### 中文资源

| 资源 | 链接 | 说明 |
|---|---|---|
| Datawhale All-in-RAG | [GitHub](https://github.com/datawhalechina/all-in-rag) | 中文 RAG 全栈教程，最推荐 |
| 知乎：大模型 RAG 高级方法 | [知乎](https://zhuanlan.zhihu.com/p/675509396) | 中文原理讲解 |
| LangChain 中文文档 | [文档](https://www.langchain.com.cn/docs/tutorials/rag/) | 官方文档中文版 |
| Prompt Engineering Guide（中文）| [文档](https://www.promptingguide.ai/zh/techniques/rag) | RAG 技术中文介绍 |

### 视频课程

| 资源 | 链接 | 说明 |
|---|---|---|
| Krish Naik：RAG 完整课程（2小时）| [Class Central](https://www.classcentral.com/course/youtube-complete-rag-crash-course-with-langchain-in-2-hours-488732) | 实战向，用 LangChain |
| RAG Patterns and Best Practices | [Class Central](https://www.classcentral.com/course/youtube-retrieval-augmented-generation-rag-patterns-and-best-practices-411059) | InfoQ 出品，偏工程实践 |
| 12 Best RAG Courses 2026 | [Class Central](https://www.classcentral.com/report/best-rag-courses/) | 课程汇总，可按需选择 |

---

## 一句话总结学习路线

```
入门    → RAG from Scratch（LangChain 官方 GitHub）
实践    → 改 Chunk 策略，对比效果
评估    → 跑一次 RAGAS，知道怎么量化
中文    → Datawhale All-in-RAG
进阶    → Reranker + 多语言 Embedding 模型
```
