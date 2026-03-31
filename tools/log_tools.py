import re
from pathlib import Path
from langchain.tools import tool

LOG_FILE = Path(__file__).parent.parent / "logs" / "app.log"


def _parse_date(raw: str) -> str:
    """从模型输出中提取真实日期值，兼容 '2026-03-30' 和 "date: '2026-03-30'" 两种格式。"""
    if not raw:
        return ""
    # 提取形如 YYYY-MM-DD 的日期
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def _read_lines(date: str = "") -> list[str]:
    """读取日志行，可按日期前缀过滤。"""
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    if date:
        lines = [l for l in lines if l.startswith(date)]
    return lines


@tool
def get_error_logs(date: str = "") -> str:
    """获取 ERROR 级别日志，可传入日期前缀如 '2026-03-30'，不传则返回所有 ERROR。"""
    errors = [l.strip() for l in _read_lines(_parse_date(date)) if "ERROR" in l]
    if not errors:
        return "未找到 ERROR 日志。"
    return f"共 {len(errors)} 条 ERROR：\n" + "\n".join(errors)


@tool
def get_log_summary(date: str = "") -> str:
    """统计日志各级别数量（INFO/WARN/ERROR），可传入日期前缀，不传则统计全部。"""
    lines = _read_lines(_parse_date(date))
    counts = {level: sum(1 for l in lines if level in l) for level in ("INFO", "WARN", "ERROR")}
    return f"日志统计：INFO={counts['INFO']}，WARN={counts['WARN']}，ERROR={counts['ERROR']}"


@tool
def search_logs(keyword: str) -> str:
    """在日志文件中搜索包含指定关键词的日志行。"""
    results = [l.strip() for l in _read_lines() if keyword.lower() in l.lower()]
    if not results:
        return f"未找到包含 '{keyword}' 的日志。"
    return f"找到 {len(results)} 条：\n" + "\n".join(results)
