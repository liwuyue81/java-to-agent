"""
日志模拟器：向 app.log 追加新的日志行，模拟真实系统写日志。
在另一个终端运行此脚本，观察 monitor_main.py 是否触发告警。
"""
import time
from datetime import datetime
from config import settings

SIMULATE_LINES = [
    "INFO  AuthService - Token refresh success: userId=2001",
    "WARN  DBPool - Connection pool usage 85%, threshold=75%",
    "ERROR DBPool - Connection pool exhausted, max=50 reached",
    "ERROR OrderService - Create order failed: cause=DB connection timeout",
    "ERROR PaymentService - Payment gateway timeout: orderId=9001",
    "INFO  DBPool - Connection pool recovered, current usage 30%",
]


def append_log(line: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_line = f"{now} {line}\n"
    with open(settings.log_file, "a") as f:
        f.write(full_line)
    print(f"写入日志: {full_line.strip()}")


if __name__ == "__main__":
    print("日志模拟器启动，每 3 秒写入一条日志...\n")
    for line in SIMULATE_LINES:
        append_log(line)
        time.sleep(3)
    print("\n模拟完成，共写入 6 条日志（含 3 条 ERROR）")
