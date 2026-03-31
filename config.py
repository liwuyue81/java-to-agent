from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # 模型配置
    model_name: str = "qwen2.5:7b"
    temperature: float = 0
    timeout: int = 60
    max_iterations: int = 6

    # 日志文件路径
    log_file: Path = Path(__file__).parent / "logs" / "app.log"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# 全局单例，其他文件 from config import settings 直接用
settings = Settings()
