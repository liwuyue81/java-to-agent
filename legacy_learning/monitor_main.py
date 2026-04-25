"""
告警监控入口：每 30 秒执行一次检测。

同时提供一个日志模拟器，方便测试时手动写入新的 ERROR 日志来触发告警。
"""
import time
import logging
from datetime import datetime
from alert.monitor import run_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # 检测间隔（秒）


if __name__ == "__main__":
    print("=" * 60)
    print("  日志告警监控已启动")
    print(f"  检测间隔：{CHECK_INTERVAL} 秒")
    print(f"  触发阈值：新增 ERROR >= 2 条")
    print(f"  告警冷却：5 分钟内同类问题不重复推送")
    print("=" * 60)
    print("\n提示：在另一个终端运行以下命令模拟新增 ERROR 日志：")
    print("  python log_simulator.py\n")

    while True:
        logger.info("开始本轮检测...")
        try:
            run_once()
        except Exception as e:
            logger.error(f"检测异常: {e}")
        logger.info(f"等待 {CHECK_INTERVAL} 秒后进行下一轮检测")
        time.sleep(CHECK_INTERVAL)
