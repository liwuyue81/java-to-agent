"""
告警监控核心逻辑，分三层：
  1. 增量读取：记录 offset，每次只读新增的行
  2. 硬规则检测：新增行里 ERROR 数超过阈值，立即触发
  3. LLM 分析：把新增 ERROR 交给模型，生成根因摘要
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from langchain_ollama import ChatOllama
from config import settings

logger = logging.getLogger(__name__)

# 告警阈值：新增日志里 ERROR 数量超过此值触发告警
ERROR_THRESHOLD = 2

# 告警冷却时间（分钟）：同一关键词在冷却期内不重复告警
COOLDOWN_MINUTES = 5

# 状态文件：持久化 offset 和告警历史，程序重启后不丢失
STATE_FILE = Path(__file__).parent / "state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"offset": 0, "alerted": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def read_new_lines() -> tuple[list[str], int]:
    """
    增量读取：从上次 offset 开始读，返回新增行和新的 offset。
    类比 MySQL binlog 消费：记住上次消费到哪里，下次从那里继续。
    """
    state = _load_state()
    offset = state["offset"]

    with open(settings.log_file, "r") as f:
        all_lines = f.readlines()

    new_lines = all_lines[offset:]
    new_offset = len(all_lines)
    return new_lines, new_offset


def detect_errors(lines: list[str]) -> list[str]:
    """硬规则：从新增行里提取 ERROR 日志。"""
    return [l.strip() for l in lines if "ERROR" in l]


def is_in_cooldown(keyword: str, alerted: dict) -> bool:
    """
    告警去重：检查该关键词是否在冷却期内。
    防止同一个问题每轮都推告警。
    """
    if keyword not in alerted:
        return False
    last_alert_time = datetime.fromisoformat(alerted[keyword])
    return datetime.now() - last_alert_time < timedelta(minutes=COOLDOWN_MINUTES)


def llm_analyze(error_lines: list[str]) -> str:
    """用 LLM 分析 ERROR 日志，生成根因摘要。"""
    llm = ChatOllama(model=settings.model_name, temperature=0, timeout=settings.timeout)
    log_text = "\n".join(error_lines)
    prompt = f"""以下是最新检测到的 ERROR 日志：

{log_text}

请用 2-3 句话简要分析：根因是什么？影响了哪些服务？建议排查方向？"""
    response = llm.invoke(prompt)
    return response.content


def send_alert(error_lines: list[str], analysis: str) -> None:
    """推送告警（当前为终端打印，后续可替换为钉钉/企业微信）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    border = "=" * 60
    print(f"\n{border}")
    print(f"  ⚠️  异常告警  {now}")
    print(border)
    print(f"检测到 {len(error_lines)} 条新 ERROR：")
    for line in error_lines:
        print(f"  {line}")
    print(f"\n【LLM 根因分析】\n{analysis}")
    print(f"{border}\n")


def run_once() -> None:
    """
    执行一次监控检测，供定时器循环调用。
    流程：增量读取 → 硬规则检测 → 去重 → LLM 分析 → 推送告警
    """
    state = _load_state()
    new_lines, new_offset = read_new_lines()

    if not new_lines:
        logger.debug("无新增日志")
        _save_state({**state, "offset": new_offset})
        return

    logger.info(f"读取到 {len(new_lines)} 条新日志")
    error_lines = detect_errors(new_lines)

    # 硬规则：ERROR 数不超过阈值，不触发告警
    if len(error_lines) < ERROR_THRESHOLD:
        logger.info(f"新增 ERROR {len(error_lines)} 条，未达阈值 {ERROR_THRESHOLD}，跳过")
        _save_state({**state, "offset": new_offset})
        return

    # 提取告警关键词（用第一条 ERROR 的服务名作为去重 key）
    import re
    m = re.search(r"ERROR\s+(\w+)", error_lines[0])
    alert_key = m.group(1) if m else "UNKNOWN"

    # 告警去重
    if is_in_cooldown(alert_key, state["alerted"]):
        logger.info(f"{alert_key} 在冷却期内，跳过告警")
        _save_state({**state, "offset": new_offset})
        return

    # LLM 分析 + 推送
    logger.info("触发告警，调用 LLM 分析...")
    analysis = llm_analyze(error_lines)
    send_alert(error_lines, analysis)

    # 更新状态
    state["alerted"][alert_key] = datetime.now().isoformat()
    state["offset"] = new_offset
    _save_state(state)
