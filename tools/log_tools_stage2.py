import re
from pathlib import Path
from langchain.tools import tool

LOG_FILE = Path(__file__).parent.parent / "logs" / "app.log"


def _parse_date(raw: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    return match.group(0) if match else ""


def _parse_value(raw: str) -> str:
    """从模型输出中提取实际值，兼容 'DBPool' 和 'keyword="DBPool"' 两种格式。"""
    # 提取引号内的内容，如 keyword="DBPool" 或 keyword='DBPool'
    match = re.search(r'=\s*["\']?([^"\'=\s]+)["\']?', raw)
    if match:
        return match.group(1)
    return raw.strip()


def _read_lines(date: str = "") -> list[str]:
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
    keyword = _parse_value(keyword)
    results = [l.strip() for l in _read_lines() if keyword.lower() in l.lower()]
    if not results:
        return f"未找到包含 '{keyword}' 的日志。"
    return f"找到 {len(results)} 条：\n" + "\n".join(results)


# ── 第二阶段新增 Tools ──────────────────────────────────────────


@tool
def filter_logs_by_time(time_range: str) -> str:
    """
    按时间范围过滤日志，格式为 'HH:MM-HH:MM'，如 '08:00-09:00'。
    返回该时间段内所有日志行。
    """
    match = re.search(r"(\d{2}:\d{2})-(\d{2}:\d{2})", time_range)
    if not match:
        return "时间格式错误，请使用 HH:MM-HH:MM，如 '08:00-09:00'。"

    start, end = match.group(1), match.group(2)
    results = []
    for line in _read_lines():
        # 日志格式：2026-03-30 08:15:22 ...
        t_match = re.search(r"\d{4}-\d{2}-\d{2} (\d{2}:\d{2})", line)
        if t_match:
            t = t_match.group(1)
            if start <= t <= end:
                results.append(line.strip())

    if not results:
        return f"在 {start}~{end} 时间段内未找到日志。"
    return f"{start}~{end} 共 {len(results)} 条日志：\n" + "\n".join(results)


@tool
def top_error_services(top_n: str = "3") -> str:
    """
    统计报错最多的服务 Top N，传入数字字符串如 '3'，默认 Top 3。
    帮助快速定位问题最集中的服务。
    """
    top_n = _parse_value(top_n)
    n = int(re.search(r"\d+", top_n).group()) if re.search(r"\d+", top_n) else 3
    errors = [l for l in _read_lines() if "ERROR" in l]

    # 提取服务名：日志格式中第三列为服务名，如 "ERROR DBPool -"
    service_count: dict[str, int] = {}
    for line in errors:
        m = re.search(r"ERROR\s+(\w+)\s+-", line)
        if m:
            service = m.group(1)
            service_count[service] = service_count.get(service, 0) + 1

    if not service_count:
        return "未找到 ERROR 日志。"

    ranked = sorted(service_count.items(), key=lambda x: x[1], reverse=True)[:n]
    lines = [f"  {i+1}. {svc}：{cnt} 条" for i, (svc, cnt) in enumerate(ranked)]
    return f"报错最多的服务 Top {n}：\n" + "\n".join(lines)


@tool
def get_log_context(keyword: str) -> str:
    """
    根因分析：找到包含关键词的 ERROR 行，并返回其前 2 行和后 2 行上下文。
    适合分析某个错误发生前后发生了什么。
    """
    keyword = _parse_value(keyword)
    all_lines = _read_lines()
    results = []
    for i, line in enumerate(all_lines):
        if keyword.lower() in line.lower() and "ERROR" in line:
            start = max(0, i - 2)
            end = min(len(all_lines), i + 3)
            block = [f"  {'>>>' if j == i else '   '} {all_lines[j].strip()}" for j in range(start, end)]
            results.append("\n".join(block))

    if not results:
        return f"未找到包含 '{keyword}' 的 ERROR 日志。"
    return f"找到 {len(results)} 处，上下文如下：\n\n" + "\n\n---\n\n".join(results)
