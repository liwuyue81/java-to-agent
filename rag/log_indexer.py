"""
日志索引器：把 app.log 的每一行向量化，存入 Chroma 向量数据库。

类比：
  传统数据库：INSERT INTO logs (content) VALUES (...)
  向量数据库：把日志内容变成数字坐标，存入 Chroma，之后可按语义检索

Chunk 策略演进：
  v1（当前默认）：每行日志作为一个独立 Document —— 简单，但上下文缺失
  v2（滑动窗口） ：N 行合并为一个 Document，相邻 chunk 有重叠 —— 上下文更完整
"""
import logging
import threading
from pathlib import Path
from langchain_chroma import Chroma
from langchain_core.documents import Document
from config import settings, get_embeddings

logger = logging.getLogger(__name__)

# 向量数据库持久化目录
CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"

# 模块级单例：避免多次 new Chroma 在异步/并发场景下触发 Rust bindings 竞争
# 症状：'RustBindingsAPI' object has no attribute 'bindings'
_vectorstore: Chroma | None = None
_vs_lock = threading.Lock()


def get_vectorstore() -> Chroma:
    """获取向量数据库实例（全局单例，线程安全的 double-checked locking）。

    embedding 通过 config.get_embeddings() 工厂获得，
    根据 settings.llm_provider 自动切 Ollama / DashScope。
    """
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore
    with _vs_lock:
        if _vectorstore is None:
            embeddings = get_embeddings()
            _vectorstore = Chroma(
                persist_directory=str(CHROMA_DIR),
                embedding_function=embeddings,
                collection_name="logs",
            )
    return _vectorstore


# =============================================================================
# 【旧版本 v1】每行日志作为一个独立 Document
#
# 实现方式：
#   遍历日志文件的每一行，每行单独包装成一个 Document 存入向量库。
#
# 优点：
#   - 实现最简单，代码直观
#   - 检索结果粒度细，精确到某一行
#
# 缺点：
#   - 上下文严重缺失：一条 ERROR 日志往往需要前后几行才能理解原因
#     例："Connection pool exhausted" 单行看不出是哪个服务、什么时间开始异常
#   - 语义不完整：单行日志词汇量少，向量化后语义表达弱，检索准确率低
#   - 无法关联：同一次故障触发的多行日志被切割成孤立的 Document，无法聚合分析
# =============================================================================
def _build_documents_v1(lines: list[str]) -> list[Document]:
    """
    v1：每行一个 Document。
    保留此方法作为对照基准，不建议在生产中使用。
    """
    documents = []
    for i, line in enumerate(lines):
        documents.append(Document(
            page_content=line,
            metadata={
                "source": "app.log",
                "line_number": i + 1,
                # 提取日志级别方便过滤
                "level": next(
                    (lvl for lvl in ("ERROR", "WARN", "INFO") if lvl in line),
                    "UNKNOWN"
                ),
                "chunk_strategy": "per_line",  # 标记使用的策略，方便对比
            }
        ))
    return documents


# =============================================================================
# 【新版本 v2】滑动窗口（Sliding Window）Chunk 策略
#
# 实现方式：
#   以 window 行为一个 chunk，每次向前滑动 step 行。
#   相邻 chunk 之间有 (window - step) 行重叠，保证边界处的上下文不丢失。
#
#   示意图（window=5, step=3）：
#     行号:  1  2  3  4  5  6  7  8  9  10
#     chunk1:[1  2  3  4  5]
#     chunk2:         [4  5  6  7  8]       ← 4、5 行重复出现（overlap）
#     chunk3:                  [7  8  9  10]
#
# 优点：
#   - 上下文完整：ERROR 前后几行（触发原因、后续影响）都包含在同一个 chunk 里
#   - overlap 机制：避免关键信息恰好落在 chunk 边界被切断
#   - 检索质量更高：chunk 词汇量更丰富，向量语义更准确
#
# 缺点：
#   - Document 数量增多（约为 v1 的 window/step 倍），索引时间更长
#   - 同一行日志可能出现在多个 chunk 中，LLM 可能看到重复内容
#   - window/step 需要根据日志格式调参，没有通用最优值
# =============================================================================
def _build_documents_v2(lines: list[str], window: int = 5, step: int = 3) -> list[Document]:
    """
    v2：滑动窗口，每个 chunk 包含 window 行，每次滑动 step 行。

    参数说明：
      window: 每个 chunk 包含的行数，越大上下文越完整，但噪音也越多
      step:   每次滑动的行数，越小 chunk 越密集（重叠越多），索引越慢
    推荐起点：window=5, step=3（重叠 2 行）
    """
    documents = []
    for i in range(0, len(lines), step):
        chunk_lines = lines[i:i + window]
        if not chunk_lines:
            continue

        content = "\n".join(chunk_lines)

        # 取这个 chunk 里最高优先级的日志级别作为 metadata
        # 优先级：ERROR > WARN > INFO > UNKNOWN
        level = "UNKNOWN"
        for lvl in ("ERROR", "WARN", "INFO"):
            if any(lvl in line for line in chunk_lines):
                level = lvl
                break

        documents.append(Document(
            page_content=content,
            metadata={
                "source": "app.log",
                "start_line": i + 1,
                "end_line": i + len(chunk_lines),
                "level": level,
                "chunk_strategy": "sliding_window",  # 标记使用的策略
            }
        ))
    return documents


def index_logs(force: bool = False, strategy: str = "sliding_window") -> int:
    """
    把日志文件的每一行存入向量数据库。

    force=True    ：清空已有数据重新索引
    strategy      ：chunk 策略，可选 "per_line"（v1）或 "sliding_window"（v2，默认）
    返回：本次索引的行数（Document 数量）
    """
    vectorstore = get_vectorstore()

    # 检查是否已有数据
    if not force and vectorstore._collection.count() > 0:
        count = vectorstore._collection.count()
        logger.info(f"向量库已有 {count} 条数据，跳过索引（传 force=True 可强制重建）")
        return 0

    # 清空旧数据
    if force:
        vectorstore._collection.delete(where={"source": "app.log"})

    # 读取日志，过滤空行
    with open(settings.log_file, "r") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]

    # 根据策略选择 chunk 方式
    if strategy == "per_line":
        # v1：每行一个 Document，保留作为对照
        documents = _build_documents_v1(lines)
        logger.info(f"使用 v1（per_line）策略，共 {len(documents)} 个 Document")
    else:
        # v2：滑动窗口（默认），上下文更完整
        documents = _build_documents_v2(lines, window=5, step=3)
        logger.info(f"使用 v2（sliding_window）策略，共 {len(documents)} 个 Document（原始日志 {len(lines)} 行）")

    vectorstore.add_documents(documents)
    logger.info(f"索引完成，共写入 {len(documents)} 条 Document")
    return len(documents)


def search_similar_logs(query: str, k: int = 5, level: str = "") -> list[Document]:
    """
    语义检索：找到与 query 最相似的 k 条日志。
    level：可选过滤级别（ERROR / WARN / INFO）
    """
    vectorstore = get_vectorstore()
    filter_dict = {"level": level} if level else None
    return vectorstore.similarity_search(query, k=k, filter=filter_dict)
