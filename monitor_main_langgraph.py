"""
LangGraph 版监控入口，与 monitor_main.py 完全对应，方便对比两种写法。
"""
import time
import logging
from alert.monitor_langgraph import run_once_langgraph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30


if __name__ == "__main__":
    print("=" * 60)
    print("  日志告警监控已启动（LangGraph 版）")
    print(f"  检测间隔：{CHECK_INTERVAL} 秒")
    print(f"  触发阈值：新增 ERROR >= 2 条")
    print(f"  告警冷却：5 分钟内同类问题不重复推送")
    print("=" * 60)
    print("\n提示：在另一个终端运行以下命令模拟新增 ERROR 日志：")
    print("  .venv/bin/python log_simulator.py\n")

    while True:
        logger.info("开始本轮检测...")
        try:
            run_once_langgraph()
        except Exception as e:
            logger.error(f"检测异常: {e}")
        logger.info(f"等待 {CHECK_INTERVAL} 秒后进行下一轮检测")
        time.sleep(CHECK_INTERVAL)
