"""
测试 Tool 函数的核心逻辑。
使用 tmp_path 创建临时日志文件，不依赖真实文件，测试完自动清理。
"""
import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


SAMPLE_LOG = """\
2026-03-31 08:00:00 INFO  UserService - User login success: userId=1001
2026-03-31 08:10:00 WARN  DBPool - Connection pool usage 80%
2026-03-31 08:15:00 ERROR DBPool - Connection pool exhausted
2026-03-31 08:15:01 ERROR OrderService - Create order failed: cause=DB timeout
2026-03-31 08:15:02 ERROR PaymentService - Payment failed
2026-03-31 09:00:00 INFO  HealthCheck - Service health check passed
"""


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """创建临时日志文件，并把 settings.log_file 指向它"""
    f = tmp_path / "app.log"
    f.write_text(SAMPLE_LOG, encoding="utf-8")

    # 用 monkeypatch 替换配置里的日志路径，不影响真实文件
    import config
    monkeypatch.setattr(config.settings, "log_file", f)
    return f


class TestGetErrorLogsStructured:
    def test_returns_correct_count(self, log_file):
        from tools.log_tools_stage4 import get_error_logs_structured
        result = get_error_logs_structured.invoke("2026-03-31")
        assert result["error_count"] == 3

    def test_returns_error_list(self, log_file):
        from tools.log_tools_stage4 import get_error_logs_structured
        result = get_error_logs_structured.invoke("2026-03-31")
        services = [e["service"] for e in result["errors"]]
        assert "DBPool" in services
        assert "OrderService" in services

    def test_no_error_on_wrong_date(self, log_file):
        from tools.log_tools_stage4 import get_error_logs_structured
        result = get_error_logs_structured.invoke("2000-01-01")
        assert result["error_count"] == 0

    def test_file_not_found_returns_empty(self, monkeypatch):
        """日志文件不存在时，返回空结果而不是抛异常"""
        import config
        monkeypatch.setattr(config.settings, "log_file", Path("/nonexistent/app.log"))
        from tools.log_tools_stage4 import get_error_logs_structured
        result = get_error_logs_structured.invoke("")
        assert result["error_count"] == 0


class TestGetLogSummaryStructured:
    def test_counts_all_levels(self, log_file):
        from tools.log_tools_stage4 import get_log_summary_structured
        result = get_log_summary_structured.invoke("")
        assert result["INFO"] == 2
        assert result["WARN"] == 1
        assert result["ERROR"] == 3

    def test_filter_by_date(self, log_file):
        from tools.log_tools_stage4 import get_log_summary_structured
        result = get_log_summary_structured.invoke("2026-03-31")
        assert result["ERROR"] == 3


class TestGetTopErrorServices:
    def test_top1(self, log_file):
        from tools.log_tools_stage4 import get_top_error_services
        result = get_top_error_services.invoke("1")
        assert len(result["ranking"]) == 1
        assert result["ranking"][0]["service"] == "DBPool"
        assert result["ranking"][0]["count"] == 1

    def test_default_top3(self, log_file):
        from tools.log_tools_stage4 import get_top_error_services
        result = get_top_error_services.invoke("3")
        assert len(result["ranking"]) <= 3


class TestGetLogContextStructured:
    def test_found(self, log_file):
        from tools.log_tools_stage4 import get_log_context_structured
        result = get_log_context_structured.invoke("DBPool")
        assert result["found"] is True
        assert len(result["blocks"]) >= 1

    def test_not_found(self, log_file):
        from tools.log_tools_stage4 import get_log_context_structured
        result = get_log_context_structured.invoke("NonExistentService")
        assert result["found"] is False

    def test_context_includes_surrounding_lines(self, log_file):
        from tools.log_tools_stage4 import get_log_context_structured
        result = get_log_context_structured.invoke("DBPool")
        # 上下文应包含出错行本身
        block = result["blocks"][0]
        assert any("DBPool" in line for line in block["context"])
