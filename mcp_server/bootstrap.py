"""
MCP Server 启动前检查。

两件事：
  1. logs/app.log 不存在 → exit(1)，stderr 打印清晰错误
  2. chroma_db/ 不存在 → 仅 warning（RAG Tool 首次调用会自动建库）

日志全部写 stderr：stdout 是 MCP 协议通道，不能污染。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def check_environment(project_root: Path) -> None:
    """启动前检查。不通过 → exit(1)。"""
    log_file = project_root / "logs" / "app.log"
    chroma_dir = project_root / "chroma_db"

    # 1. 日志文件必须存在（stage4 Tool 全都依赖它）
    if not log_file.exists():
        logger.error("=" * 60)
        logger.error(f"日志文件不存在：{log_file}")
        logger.error("MCP Server 依赖本文件提供日志数据，请确保已生成或手动放置。")
        logger.error("=" * 60)
        sys.exit(1)

    logger.info(f"✓ 日志文件就绪：{log_file} ({log_file.stat().st_size} bytes)")

    # 2. 向量库存在性检查（RAG Tool 用）
    if not chroma_dir.exists():
        logger.warning(
            f"⚠ 向量库目录不存在：{chroma_dir}。"
            " 首次调用 semantic_search_* 会自动 index（约 5 秒），之后就快了。"
        )
    else:
        # 粗略估计体积
        try:
            size = sum(f.stat().st_size for f in chroma_dir.rglob("*") if f.is_file())
            logger.info(f"✓ 向量库就绪：{chroma_dir} (~{size // 1024} KB)")
        except Exception:
            logger.info(f"✓ 向量库目录存在：{chroma_dir}")
