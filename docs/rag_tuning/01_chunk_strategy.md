# Chunk 策略详解

> RAG 调优系列第 1 篇。Chunk 策略是影响 RAG 效果最大的单一因素。

---

## 什么是 Chunk？

**Chunk（块）** 是向量化和检索的最小单位。你存入向量库的不是整个文档，而是被切分后的一段段文本。

```
原始日志文件（几千行）
         ↓  切分（Chunk）
[chunk1] [chunk2] [chunk3] ... [chunkN]
         ↓  向量化
每个 chunk 变成一个向量坐标
         ↓  存入 Chroma
```

检索时，用户的问题也变成向量，找的是"最相似的 chunk"，**不是最相似的文件**。

---

## 为什么 Chunk 策略影响最大？

一个比喻：

> 你去图书馆找"数据库连接问题"的资料。
> - **Chunk 太小**：每个书签只有一个词，找不到完整上下文
> - **Chunk 太大**：一个书签代表整本书，找到了但信息太杂，LLM 读不完
> - **Chunk 刚好**：每个书签代表一个段落，精准且完整

---

## 5 种 Chunk 策略

### 策略 1：Fixed Size（固定长度切分）

**原理：** 按字符数或 Token 数强制切分，可设置重叠（overlap）。

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=200,      # 每块最多 200 字符
    chunk_overlap=20,    # 相邻块重叠 20 字符（避免切断上下文）
)
chunks = splitter.split_text(text)
```

**适合：** 通用场景，快速上手。

**缺点：** 不理解文本结构，可能把一条完整的错误日志切成两半。

**Java 类比：** 就像 `String.substring(0, 200)`，不管语义强行截断。

---

### 策略 2：Semantic Chunking（语义切分）

**原理：** 不按长度切，而是检测"语义跳变点"，相邻句子如果语义差异大就在这里切分。

```python
from langchain_experimental.text_splitter import SemanticChunker
from langchain_ollama import OllamaEmbeddings

splitter = SemanticChunker(
    OllamaEmbeddings(model="nomic-embed-text"),
    breakpoint_threshold_type="percentile",  # 语义跳变超过 95% 分位点才切
)
chunks = splitter.split_text(text)
```

**适合：** 内容主题变化明显的文档（比如混合了不同服务的日志）。

**缺点：** 慢（每次切分都要向量化），首次建索引耗时长。

---

### 策略 3：Sliding Window（滑动窗口）

**原理：** 固定窗口大小，每次滑动 N 行，相邻 chunk 之间有重叠。

```python
def sliding_window_chunks(lines: list[str], window: int = 5, step: int = 2):
    """
    window=5：每个 chunk 包含 5 行
    step=2：每次滑动 2 行（相邻 chunk 重叠 3 行）
    """
    chunks = []
    for i in range(0, len(lines) - window + 1, step):
        chunk_lines = lines[i:i + window]
        chunks.append("\n".join(chunk_lines))
    return chunks
```

**示意图：**

```
行号:  1  2  3  4  5  6  7  8  9
chunk1: [1  2  3  4  5]
chunk2:       [3  4  5  6  7]
chunk3:             [5  6  7  8  9]
```

**适合：** 日志文件。因为错误通常在前后几行有上下文关联，重叠保证关键信息不被切断。

**当前项目最推荐的改进方向。**

---

### 策略 4：Structure-Aware（结构感知切分）

**原理：** 利用日志本身的结构（时间戳、日志级别、服务名）来切分。

```python
import re

def structure_aware_chunks(lines: list[str]) -> list[str]:
    """
    把同一时间段内同一服务的连续日志合并为一个 chunk
    """
    chunks = []
    current_chunk = []
    current_service = None

    for line in lines:
        # 提取服务名（示例格式：2026-01-01 ERROR ServiceA - message）
        match = re.search(r'(ERROR|WARN|INFO)\s+(\w+)\s+-', line)
        service = match.group(2) if match else "UNKNOWN"

        if service != current_service and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []

        current_chunk.append(line)
        current_service = service

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks
```

**适合：** 格式固定的结构化日志。

---

### 策略 5：Parent-Child（父子结构）

**原理：** 存两层粒度，检索用小 chunk（精准），召回后返回大 chunk（上下文完整）。

```
索引时存入：
  小 chunk（1行，用于精准匹配）
  大 chunk（该行前后5行，用于返回上下文）

检索时：
  用小 chunk 找到匹配 → 返回对应的大 chunk 给 LLM
```

```python
from langchain.retrievers import ParentDocumentRetriever
```

**适合：** 需要精准检索 + 完整上下文的场景（最接近生产级 RAG）。

**缺点：** 实现复杂，需要额外存储父子关系。

---

## 策略对比

| 策略 | 实现难度 | 效果 | 适合场景 |
|---|---|---|---|
| Fixed Size | ⭐ | ★★★ | 快速验证 |
| Sliding Window | ⭐⭐ | ★★★★ | **日志文件（推荐）** |
| Semantic Chunking | ⭐⭐⭐ | ★★★★ | 混合主题文档 |
| Structure-Aware | ⭐⭐⭐ | ★★★★★ | 格式固定的日志 |
| Parent-Child | ⭐⭐⭐⭐ | ★★★★★ | 生产级 RAG |

---

## 当前项目的改进方案

### 现状

```python
# log_indexer.py 当前实现：每行一个 Document
for i, line in enumerate(lines):
    documents.append(Document(page_content=line, ...))
```

### 改进：滑动窗口（推荐第一步）

```python
def sliding_window_chunks(lines: list[str], window: int = 5, step: int = 3) -> list[Document]:
    documents = []
    for i in range(0, len(lines), step):
        chunk_lines = lines[i:i + window]
        if not chunk_lines:
            continue
        content = "\n".join(chunk_lines)
        # 提取这个 chunk 里最高级别的日志级别
        level = "UNKNOWN"
        for lvl in ("ERROR", "WARN", "INFO"):
            if any(lvl in l for l in chunk_lines):
                level = lvl
                break
        documents.append(Document(
            page_content=content,
            metadata={
                "source": "app.log",
                "start_line": i + 1,
                "end_line": i + len(chunk_lines),
                "level": level,
            }
        ))
    return documents
```

**效果对比：**

```
改进前（每行一个 chunk）：
  检索 "connection pool exhausted" → 只返回报错那一行

改进后（滑动窗口）：
  检索 "connection pool exhausted" → 返回报错前后共 5 行
  → Agent 能看到触发原因和后续影响
```

---

## Overlap 的作用

```
lines:   A  B  [C  D  E]  F  G
                   ↑ chunk 边界在这里切断

没有 overlap，B 和 C 之间的关联丢失。

加 overlap：
chunk1: [A  B  C  D  E]
chunk2:       [C  D  E  F  G]  ← C/D/E 重复出现，确保不丢失上下文
```

---

## 实践建议

1. **先改滑动窗口**，window=5，step=3，对比检索结果是否更完整
2. **观察日志格式**，如果日志格式固定，上 Structure-Aware 效果更好
3. **用 RAGAS 评估**，量化改进效果（详见 RAG 评估篇）

---

## 延伸阅读

- [NVIDIA：找到最佳 Chunk 策略](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)
- [Weaviate：RAG Chunk 策略详解](https://weaviate.io/blog/chunking-strategies-for-rag)
- [LangChain TextSplitter 文档](https://python.langchain.com/docs/concepts/text_splitters/)
