# Embedding 模型选型

> RAG 调优系列第 2 篇。Embedding 模型决定了"语义理解的天花板"，再好的 Chunk 策略也需要合适的 Embedding 模型才能发挥作用。

---

## 什么是 Embedding 模型？

Embedding 模型的唯一职责：**把文字变成数字向量**。

```
"Connection pool exhausted"
        ↓  Embedding 模型
[0.12, -0.45, 0.78, ..., 0.33]   （768 维数字）
```

两段意思相近的文字，向量坐标也会相近（距离小）。
两段意思不相关的文字，向量坐标距离大。

```
"Connection pool exhausted"   → 向量 A
"数据库连接池耗尽"             → 向量 B

好的多语言模型：distance(A, B) 很小  ✓
nomic-embed-text：distance(A, B) 很大  ✗（跨语言弱）
```

**Java 类比：** 类似 `Object.hashCode()`，但不是精确匹配，而是"意思越像，hash 越接近"。

---

## 当前项目的问题

```python
# log_indexer.py 当前使用
EMBED_MODEL = "nomic-embed-text"
```

`nomic-embed-text` 的特点：
- 英文效果很好
- **跨语言（中文查英文）效果差**
- 现在靠 LLM 翻译中文问题为英文再检索，属于"绕过问题"而非"解决问题"

---

## 核心指标：MTEB 排行榜

评估 Embedding 模型的权威榜单是 **MTEB（Massive Text Embedding Benchmark）**：

> https://huggingface.co/spaces/mteb/leaderboard

看榜单时重点关注三列：

| 列名 | 含义 |
|---|---|
| Model Size | 模型大小，影响内存和速度 |
| Retrieval | 检索任务得分，RAG 最关心这个 |
| Multilingual | 多语言支持，中文场景必看 |

---

## 主流模型对比

### 本地运行（Ollama）

| 模型 | 大小 | 语言 | 检索效果 | 适用场景 |
|---|---|---|---|---|
| `nomic-embed-text` | 274MB | 英文为主 | ★★★ | 纯英文日志，快速验证 |
| `mxbai-embed-large` | 670MB | 英文 | ★★★★ | 英文场景效果更好 |
| `bge-m3` | 1.2GB | 中英文 | ★★★★★ | **推荐，中英文都强** |
| `multilingual-e5-large` | 560MB | 100+ 语言 | ★★★★ | 多语言场景 |

```bash
# 拉取模型（选其中一个）
ollama pull mxbai-embed-large
ollama pull bge-m3
```

### 云端 API（效果更强，需联网）

| 模型 | 提供方 | 维度 | 特点 |
|---|---|---|---|
| `text-embedding-3-small` | OpenAI | 1536 | 便宜，效果好 |
| `text-embedding-3-large` | OpenAI | 3072 | 最强，贵 |
| `embedding-v3` | 智谱 AI | 2048 | 中文最强之一 |

> 本地 Ollama 场景推荐先用 `bge-m3`，无需联网，中英文都能处理。

---

## 维度（Dimension）是什么？

向量的维度数 = 向量数组的长度。

```
nomic-embed-text：768 维
bge-m3：          1024 维
text-embedding-3-large：3072 维
```

**维度越高 ≠ 效果越好**，但维度高通常能表达更细腻的语义。
代价是：存储空间更大，相似度计算更慢。

---

## 如何在项目中切换模型

### 方式一：直接修改常量（最简单）

```python
# rag/log_indexer.py

# 旧版（英文为主）
# EMBED_MODEL = "nomic-embed-text"

# 新版（中英文，推荐）
EMBED_MODEL = "bge-m3"
```

> **注意：切换模型后必须强制重建索引。**
> 不同模型生成的向量维度和空间不同，混用会导致检索结果错乱。

```bash
# 切换模型后，强制重建
python -c "from rag.log_indexer import index_logs; index_logs(force=True)"
```

---

### 方式二：通过配置文件管理（推荐）

把模型名放入 `config.py`，方便切换和对比：

```python
# config.py
class Settings(BaseSettings):
    model_name: str = "qwen2.5:7b"
    embed_model: str = "bge-m3"          # 新增：embedding 模型
    temperature: float = 0
    timeout: int = 60
    max_iterations: int = 6
    log_file: Path = Path(__file__).parent / "logs" / "app.log"
    model_config = {"env_file": ".env"}
```

```python
# rag/log_indexer.py
from config import settings

EMBED_MODEL = settings.embed_model   # 从配置读取
```

切换模型时只改 `.env` 或 `config.py`，不动业务代码。

---

## 换模型前后效果对比示例

**问题：** "有没有数据库连接方面的问题？"

```
nomic-embed-text（中文查询，未翻译）：
  检索结果：INFO 日志 "Application started successfully"  ✗
  原因：中文向量和英文日志向量距离太大，随机匹配

bge-m3（直接支持中文查询）：
  检索结果：ERROR "DBPool - Connection pool exhausted"    ✓
  原因：中文"数据库连接"和英文"connection pool"在同一向量空间里距离很近
```

---

## 为什么不同模型的向量不能混用？

每个 Embedding 模型都有自己的"坐标系"：

```
nomic-embed-text 的坐标系：
  "connection pool" → [0.12, -0.45, 0.78, ...]

bge-m3 的坐标系：
  "connection pool" → [0.87,  0.23, -0.11, ...]
```

两个模型对同一句话生成完全不同的坐标。用 A 模型索引，用 B 模型查询，就像用中文地图查英文地址，找不到。

**所以：索引和查询必须用同一个 Embedding 模型。**

---

## 选型决策树

```
本地运行（Ollama）？
├── 是
│   ├── 只有英文日志，追求速度 → nomic-embed-text（已有，274MB）
│   ├── 中文查询英文日志       → bge-m3（推荐，1.2GB）
│   └── 内存有限（<4GB）       → multilingual-e5-large（560MB）
└── 否（可以用云端 API）
    ├── 英文为主               → OpenAI text-embedding-3-small
    └── 中文为主               → 智谱 embedding-v3
```

---

## 当前项目的推荐升级路径

```
现在：nomic-embed-text（英文）+ LLM 翻译中文问题
  ↓  第一步
bge-m3（本地，中英文）—— 直接支持中文查询，去掉翻译依赖
  ↓  效果不够时
云端 API（text-embedding-3-small）—— 效果最强，但需要付费
```

**实际操作：**

```bash
# 1. 拉取 bge-m3
ollama pull bge-m3

# 2. 修改 config.py 中的 embed_model = "bge-m3"

# 3. 强制重建索引
python -c "from rag.log_indexer import index_logs; index_logs(force=True)"

# 4. 启动 Agent，直接用中文提问，不再依赖 LLM 翻译
python main_rag.py
```

---

## 小结

| 知识点 | 要点 |
|---|---|
| Embedding 模型的作用 | 把文字变成向量，语义相似 = 向量距离近 |
| 模型选型核心依据 | 语言覆盖（中英文？）+ 检索效果（MTEB 榜单）|
| 切换模型的注意点 | 必须强制重建索引，不同模型向量不兼容 |
| 当前项目推荐 | `bge-m3`，本地运行，中英文都支持 |

---

## 延伸阅读

- [MTEB 排行榜](https://huggingface.co/spaces/mteb/leaderboard) — Embedding 模型权威评测
- [bge-m3 模型介绍](https://huggingface.co/BAAI/bge-m3) — HuggingFace 官方页面
- [Ollama 支持的 Embedding 模型列表](https://ollama.com/search?c=embedding) — 可本地运行的全部模型
- [OpenAI Embeddings 文档](https://platform.openai.com/docs/guides/embeddings) — 云端方案参考
