"""
向量数据库三大核心操作示例
类比：向量数据库 = 支持"语义搜索"的 MySQL，存的不是行数据，而是文本的数字坐标（向量）

操作对照表：
  MySQL               向量数据库
  INSERT              add_documents()
  SELECT WHERE        similarity_search() + filter
  全文检索             similarity_search()（语义级别，不是关键词匹配）
"""
from pathlib import Path
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain.schema import Document

# ── 初始化向量数据库 ──────────────────────────────────────────────────────────
# OllamaEmbeddings：把文本转成向量的模型，类比"把文字翻译成数字坐标"
# 例如："数据库连接失败" → [0.12, 0.87, 0.34, -0.56, ...]（1024维浮点数组）
embeddings = OllamaEmbeddings(model="nomic-embed-text")

# Chroma：向量数据库实例
# persist_directory：数据持久化到磁盘，程序重启后不丢失（类比 MySQL 数据文件）
# collection_name：类比 MySQL 的表名
CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"
vectorstore = Chroma(
    persist_directory=str(CHROMA_DIR),
    embedding_function=embeddings,
    collection_name="demo_logs",
)


# ── 操作1：存数据 add_documents() ────────────────────────────────────────────
# 类比：INSERT INTO logs (content, source, line_number, level) VALUES (...)
def demo_add():
    # Document 是向量数据库的基本单元，包含两部分：
    #   page_content：正文，会被向量化（用于语义检索）
    #   metadata：附加字段，不参与向量计算，只用于过滤（类比数据库普通列）
    documents = [
        Document(
            page_content="2024-01-01 10:00:00 ERROR UserService - 数据库连接超时",
            metadata={
                "source": "app.log",   # 来源文件
                "line_number": 1,      # 行号
                "level": "ERROR",      # 日志级别，用于后续过滤
            }
        ),
        Document(
            page_content="2024-01-01 10:01:00 WARN OrderService - 库存不足，触发降级",
            metadata={
                "source": "app.log",
                "line_number": 2,
                "level": "WARN",
            }
        ),
        Document(
            page_content="2024-01-01 10:02:00 INFO PaymentService - 支付成功 orderId=9527",
            metadata={
                "source": "app.log",
                "line_number": 3,
                "level": "INFO",
            }
        ),
        Document(
            page_content="2024-01-01 10:03:00 ERROR PaymentService - Redis 连接失败，缓存不可用",
            metadata={
                "source": "app.log",
                "line_number": 4,
                "level": "ERROR",
            }
        ),
        Document(
            page_content="2024-01-01 10:04:00 ERROR UserService - NullPointerException in login()",
            metadata={
                "source": "app.log",
                "line_number": 5,
                "level": "ERROR",
            }
        ),
    ]

    # 批量写入，内部自动完成：原始文本 → Embedding模型 → 向量 → 存入ChromaDB
    # 类比：jdbcTemplate.batchUpdate(sql, documents)
    vectorstore.add_documents(documents)
    print(f"✅ 存入 {len(documents)} 条日志")


# ── 操作2：语义检索 similarity_search() ──────────────────────────────────────
# 不是关键词匹配，而是语义相似度匹配
# 类比：ES 的 match query，但更智能——即使词不同，意思近的也能找到
def demo_search():
    query = "数据库连不上"   # 注意：日志里写的是"连接超时"、"连接失败"，不是"连不上"
                             # 关键词搜索找不到，语义检索能找到

    # k=3：返回最相似的3条，类比 SQL 的 LIMIT 3
    results: list[Document] = vectorstore.similarity_search(query, k=3)

    print(f"\n🔍 语义检索：'{query}'，返回 {len(results)} 条")
    for i, doc in enumerate(results, 1):
        # doc.page_content：日志原文
        # doc.metadata：附加字段
        print(f"  [{i}] {doc.page_content}")
        print(f"       level={doc.metadata['level']}, line={doc.metadata['line_number']}")


# ── 操作3：带过滤的检索 similarity_search() + filter ─────────────────────────
# 先按 metadata 字段过滤（精确匹配），再在过滤结果里做语义检索
# 类比：SELECT * FROM logs WHERE level='ERROR' ORDER BY similarity(content, query) LIMIT 3
def demo_search_with_filter():
    query = "服务连接异常"

    # filter：对 metadata 字段做精确过滤，只在 ERROR 级别日志里检索
    # 类比 SQL：WHERE level = 'ERROR'
    filter_dict = {"level": "ERROR"}

    results: list[Document] = vectorstore.similarity_search(
        query,          # 语义检索词
        k=3,            # 返回条数
        filter=filter_dict  # metadata 过滤条件
    )

    print(f"\n🔍 带过滤检索：'{query}'，只看 ERROR 级别，返回 {len(results)} 条")
    for i, doc in enumerate(results, 1):
        print(f"  [{i}] {doc.page_content}")
        print(f"       level={doc.metadata['level']}, line={doc.metadata['line_number']}")


# ── 主流程 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== 向量数据库三大操作 Demo ===\n")

    # 步骤1：存数据
    demo_add()

    # 步骤2：语义检索（不限级别）
    demo_search()

    # 步骤3：带过滤检索（只看 ERROR）
    demo_search_with_filter()
