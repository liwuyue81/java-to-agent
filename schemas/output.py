from typing import List, Literal
from pydantic import BaseModel


class ErrorLogItem(BaseModel):
    time: str       # 发生时间，如 "08:15:22"
    service: str    # 服务名，如 "DBPool"
    message: str    # 错误信息


class LogAnalysisResult(BaseModel):
    """Agent 分析结果的结构化输出 schema"""
    error_count: int                        # ERROR 总数
    top_service: str                        # 报错最多的服务
    errors: List[ErrorLogItem]              # ERROR 列表
    summary: str                            # 自然语言总结
    severity: Literal["low", "medium", "high"]  # 整体严重程度
