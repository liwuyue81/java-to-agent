import re
import logging
from pathlib import Path
from langchain.tools import tool
from config import settings

logger = logging.getLogger(__name__)


def _parse_date(raw: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def _parse_value(raw: str) -> str:
    match = re.search(r'=\s*["\']?([^"\'=\s]+)["\']?', raw)
    return match.group(1) if match else raw.strip()


def _read_lines(date: str = "") -> list[str]:
    try:
        with open(settings.log_file, "r") as f:
            lines = f.readlines()
        if date:
            lines = [l for l in lines if l.startswith(date)]
        return lines
    except FileNotFoundError:
        logger.error(f"日志文件不存在: {settings.log_file}")
        return []
    except Exception as e:
        logger.error(f"读取日志文件失败: {e}")
        return []


# ── 方案 A：Tool 返回结构化数据（dict），Agent 自行格式化 ──────────────

@tool
def get_error_logs_structured(date: str = "") -> dict:
    """
    获取 ERROR 级别日志，返回结构化数据。
    可传入日期前缀如 '2026-03-30'，不传则返回所有 ERROR。
    """
    try:
        date = _parse_date(date)
        lines = [l.strip() for l in _read_lines(date) if "ERROR" in l]

        errors = []
        for line in lines:
            m = re.match(r"(\S+ \S+)\s+ERROR\s+(\w+)\s+-\s+(.+)", line)
            if m:
                errors.append({
                    "time": m.group(1),
                    "service": m.group(2),
                    "message": m.group(3),
                })

        return {"error_count": len(errors), "errors": errors}
    except Exception as e:
        logger.error(f"get_error_logs_structured 执行失败: {e}")
        return {"error": str(e)}


@tool
def get_log_summary_structured(date: str = "") -> dict:
    """
    统计日志各级别数量，返回结构化数据。
    可传入日期前缀，不传则统计全部。
    """
    try:
        date = _parse_date(date)
        lines = _read_lines(date)
        counts = {level: sum(1 for l in lines if level in l)
                  for level in ("INFO", "WARN", "ERROR")}
        return counts
    except Exception as e:
        logger.error(f"get_log_summary_structured 执行失败: {e}")
        return {"error": str(e)}


@tool
def get_top_error_services(top_n: str = "3") -> dict:
    """
    统计报错最多的服务 Top N，返回结构化数据。
    传入数字字符串如 '3'，默认 Top 3。
    """
    try:
        top_n = _parse_value(top_n)
        n = int(re.search(r"\d+", top_n).group()) if re.search(r"\d+", top_n) else 3
        errors = [l for l in _read_lines() if "ERROR" in l]

        service_count: dict[str, int] = {}
        for line in errors:
            m = re.search(r"ERROR\s+(\w+)\s+-", line)
            if m:
                svc = m.group(1)
                service_count[svc] = service_count.get(svc, 0) + 1

        ranked = sorted(service_count.items(), key=lambda x: x[1], reverse=True)[:n]
        return {"ranking": [{"service": s, "count": c} for s, c in ranked]}
    except Exception as e:
        logger.error(f"get_top_error_services 执行失败: {e}")
        return {"error": str(e)}


@tool
def get_log_context_structured(keyword: str) -> dict:
    """
    根因分析：找到包含关键词的 ERROR 行，返回上下文（前后各 2 行）。
    """
    try:
        keyword = _parse_value(keyword)
        all_lines = _read_lines()
        blocks = []
        for i, line in enumerate(all_lines):
            if keyword.lower() in line.lower() and "ERROR" in line:
                start = max(0, i - 2)
                end = min(len(all_lines), i + 3)
                blocks.append({
                    "error_line": all_lines[i].strip(),
                    "context": [all_lines[j].strip() for j in range(start, end)],
                })
        if not blocks:
            return {"found": False, "keyword": keyword}
        return {"found": True, "keyword": keyword, "blocks": blocks}
    except Exception as e:
        logger.error(f"get_log_context_structured 执行失败: {e}")
        return {"error": str(e)}
