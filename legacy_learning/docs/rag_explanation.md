# RAG 版日志 Agent 代码解析

## 新增内容概览

| 文件 | 用途 |
|---|---|
| `rag/log_indexer.py` | 把日志文件向量化，存入 Chroma 向量数据库 |
| `rag/rag_tools.py` | 把向量检索能力包装成 LangChain Tool |
| `main_rag.py` | RAG 版 Agent 入口，整合原有 6 个 Tool + 新增 2 个 RAG Tool |
| `chroma_db/` | 自动生成，向量数据库的持久化文件 |

---

## 先回答核心问题：RAG 和之前的版本有什么本质区别？

**之前的 Tool（精确匹配）：**
```
你问：搜索 DBPool
Tool：逐行扫描日志，找包含 "DBPool" 字符串的行 → 找不到就没有
```

**RAG Tool（语义匹配）：**
```
你问：有没有数据库连接方面的问题？
Agent：把问题翻译成英文 → "database connection issue"
Tool：把 "database connection issue" 变成向量坐标
      → 在向量库里找距离最近的日志
      → 返回语义最相似的结果
```

**一句话总结：** 精确匹配找的是"字"，语义匹配找的是"意思"。

---

## 完整流程图

### 索引阶段（首次运行自动触发）

```
main_rag.py 启动
      ↓
init() 检查向量库是否已有数据
      ↓ 没有
读取 logs/app.log 的每一行
      ↓
每行日志 → OllamaEmbeddings(nomic-embed-text) → 变成向量坐标
例：
"ERROR DBPool - Connection pool exhausted"
      ↓ 向量化
[0.12, -0.45, 0.78, ..., 0.33]  （768 维数字）
      ↓
存入 Chroma（写到 chroma_db/ 目录，持久化）
      ↓
索引完成，共 23 条
```

### 查询阶段（每次对话）

```
你：有没有数据库连接方面的问题？
      ↓
Agent（qwen2.5:7b）决策：
  这个问题适合用 semantic_search_errors
  参数翻译成英文：'database connection issue'
      ↓
semantic_search_errors.invoke('database connection issue')
      ↓
'database connection issue' → OllamaEmbeddings → 向量坐标
      ↓
Chroma 计算该向量与库里所有日志向量的距离
      ↓
返回距离最近（语义最相似）的 5 条日志
      ↓
Agent 拿到结果，组织成自然语言回答你
```

---

## 核心文件逐段解析

### 1. log_indexer.py：向量化 + 存储

**Embedding 模型：**

```python
EMBED_MODEL = "nomic-embed-text"

embeddings = OllamaEmbeddings(model=EMBED_MODEL)
```

`nomic-embed-text` 是专门做文本向量化的模型，只有 274MB，比对话模型小很多。
它的唯一职责是：把文字变成数字向量。

**Java 类比：** 就像把一个对象序列化成字节数组，只不过序列化后的数组能反映语义相似度。

---

**Document 结构：**

```python
documents.append(Document(
    page_content=line,           # 日志原文
    metadata={
        "source": "app.log",
        "line_number": i + 1,
        "level": "ERROR",        # 日志级别，用于过滤
    }
))
```

每条日志包装成一个 `Document` 对象，`metadata` 类似数据库的额外字段，可以在检索时用来过滤（比如只检索 ERROR 级别）。

**Java 类比：** 类似 Elasticsearch 的 Document，有正文内容也有字段索引。

---

**向量库初始化：**

```python
vectorstore = Chroma(
    persist_directory=str(CHROMA_DIR),   # 持久化路径
    embedding_function=embeddings,        # 用什么模型做向量化
    collection_name="logs",              # 相当于数据库的表名
)
```

`persist_directory` 指定数据存在磁盘的哪里，程序重启后数据不丢失。

**Java 类比：** 类似 `DataSource` 指定数据库文件路径，配合 `collection_name` 相当于表名。

---

**增量索引检查：**

```python
if not force and vectorstore._collection.count() > 0:
    logger.info(f"向量库已有数据，跳过索引")
    return 0
```

首次运行建索引，之后重启直接复用，不会重复向量化。
传 `force=True` 可以强制重建（比如日志文件内容变了）。

---

### 2. rag_tools.py：检索 Tool

```python
@tool
def semantic_search_errors(query: str) -> str:
    """
    Semantic search only in ERROR level logs. Input must be in English.
    Use this to find errors similar to a described problem,
    e.g. 'connection pool exhausted', 'redis connection failed'.
    """
    results = search_similar_logs(query, k=5, level="ERROR")
```

**docstring 为什么用英文：**

模型读 docstring 决定怎么用这个 Tool。写 `Input must be in English`，模型在传参时会自动把中文问题翻译成英文再传入，解决了日志是英文而用户是中文提问的跨语言问题。

**level 过滤：**

```python
filter_dict = {"level": level} if level else None
vectorstore.similarity_search(query, k=k, filter=filter_dict)
```

Chroma 支持在向量检索的同时按 metadata 过滤。`semantic_search_errors` 只检索 `level=ERROR` 的日志，不会混入 INFO/WARN 结果。

---

### 3. main_rag.py：整合新旧 Tool

```python
tools = [
    # 原有 Tool（精确匹配）
    get_error_logs,
    get_log_summary,
    search_logs,
    filter_logs_by_time,
    top_error_services,
    get_log_context,
    # RAG Tool（语义匹配）
    semantic_search_logs,
    semantic_search_errors,
]
```

Agent 现在有 8 个 Tool，根据问题性质自动选择用哪个：

| 问题类型 | Agent 会选 |
|---|---|
| 今天有几条 ERROR？ | `get_error_logs`（精确） |
| DBPool 相关日志 | `search_logs`（关键词） |
| 有没有数据库连接方面的问题？ | `semantic_search_errors`（语义） |
| 有没有类似超时的异常？ | `semantic_search_logs`（语义） |

---

## 向量数据库 vs 传统数据库

| 维度 | MySQL / 传统数据库 | Chroma / 向量数据库 |
|---|---|---|
| 查询方式 | 精确匹配（`WHERE content = 'DBPool'`）| 语义相似（找"意思最近"的内容）|
| 适合场景 | 结构化数据、精确查询 | 非结构化文本、模糊语义查询 |
| 存储内容 | 原始数据 | 原始数据 + 向量坐标 |
| 核心操作 | INSERT / SELECT | add_documents / similarity_search |

---

## 关于跨语言问题

`nomic-embed-text` 对英文支持最好，跨语言（中文查英文日志）效果有限。

**当前解决方案：** Tool 的 docstring 用英文写，并注明 `Input must be in English`，Agent 在调用时会自动翻译。

**更好的方案（后续可以升级）：**
- 换多语言 Embedding 模型（如 `multilingual-e5`）
- 或者在索引时给每条日志加中文摘要字段

---

## 一句话总结

```
nomic-embed-text  = 把日志文字变成数字坐标（向量化）
Chroma            = 存储向量坐标，支持"找最相似"的查询
RAG Tool          = 把向量检索包装成 Agent 可调用的能力
Agent             = 根据问题决定用精确匹配还是语义检索
```
