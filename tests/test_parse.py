"""
测试 _parse_value 和 _parse_date 辅助函数的边界情况。
覆盖：正常输入、带参数名的输入、带引号的输入、空字符串。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.log_tools_stage4 import _parse_value, _parse_date


class TestParseValue:
    def test_plain_value(self):
        """直接传值，原样返回"""
        assert _parse_value("DBPool") == "DBPool"

    def test_with_key_double_quote(self):
        """模型传 keyword="DBPool" 格式"""
        assert _parse_value('keyword="DBPool"') == "DBPool"

    def test_with_key_single_quote(self):
        """模型传 keyword='DBPool' 格式"""
        assert _parse_value("keyword='DBPool'") == "DBPool"

    def test_with_key_no_quote(self):
        """模型传 keyword=DBPool 格式"""
        assert _parse_value("keyword=DBPool") == "DBPool"

    def test_empty_string(self):
        """空字符串返回空字符串"""
        assert _parse_value("") == ""

    def test_number_string(self):
        """数字字符串"""
        assert _parse_value("top_n=3") == "3"


class TestParseDate:
    def test_plain_date(self):
        """直接传日期"""
        assert _parse_date("2026-03-31") == "2026-03-31"

    def test_date_in_key_value(self):
        """模型传 date='2026-03-31' 格式"""
        assert _parse_date("date='2026-03-31'") == "2026-03-31"

    def test_empty_string(self):
        """空字符串返回空字符串"""
        assert _parse_date("") == ""

    def test_invalid_date(self):
        """无效日期返回空字符串"""
        assert _parse_date("not-a-date") == ""
