"""
测试依赖解析器
"""

import tempfile
from pathlib import Path

import pytest

from py_symbol_analyze.resolver import DependencyResolver, SymbolAnalyzer

# 测试用的示例项目结构
MAIN_CODE = '''
"""Main module"""

from utils import helper_func, HelperClass
from exceptions import CustomError

class MainClass:
    """Main class that uses helpers"""
    
    def __init__(self):
        self.helper = HelperClass()
    
    def process(self, data):
        """Process data using helper"""
        try:
            result = helper_func(data)
            return self.helper.transform(result)
        except CustomError as e:
            return None


def main():
    """Entry point"""
    obj = MainClass()
    return obj.process([1, 2, 3])
'''

UTILS_CODE = '''
"""Utility module"""

class HelperClass:
    """Helper class for data transformation"""
    
    def transform(self, value):
        """Transform a value"""
        return str(value).upper()


def helper_func(data):
    """Helper function"""
    if not data:
        raise ValueError("Empty data")
    return data[0]
'''

EXCEPTIONS_CODE = '''
"""Custom exceptions"""

class CustomError(Exception):
    """Custom error class"""
    
    def __init__(self, message):
        super().__init__(message)
        self.message = message
'''


@pytest.fixture
def temp_project():
    """创建临时测试项目"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建项目文件
        (Path(tmpdir) / "main.py").write_text(MAIN_CODE)
        (Path(tmpdir) / "utils.py").write_text(UTILS_CODE)
        (Path(tmpdir) / "exceptions.py").write_text(EXCEPTIONS_CODE)

        yield tmpdir


class TestDependencyResolver:
    """测试依赖解析器"""

    def test_analyze_class(self, temp_project):
        """测试分析类"""
        resolver = DependencyResolver(temp_project)
        result = resolver.analyze_class("MainClass")

        assert result is not None
        assert result.node_type == "class"
        assert "MainClass" in result.class_content
        assert len(result.depends) > 0
        assert len(result.depends_path) > 0

    def test_analyze_function(self, temp_project):
        """测试分析函数"""
        resolver = DependencyResolver(temp_project)
        result = resolver.analyze_function("main")

        assert result is not None
        assert result.node_type == "func"
        assert "def main" in result.function_content
        assert result.host_class is None

    def test_analyze_method(self, temp_project):
        """测试分析类方法"""
        resolver = DependencyResolver(temp_project)
        result = resolver.analyze_function("process", host_class="MainClass")

        assert result is not None
        assert result.node_type == "func"
        assert result.host_class == "MainClass"
        assert "def process" in result.function_content


class TestSymbolAnalyzer:
    """测试符号分析器"""

    def test_query_class(self, temp_project):
        """测试查询类"""
        analyzer = SymbolAnalyzer(temp_project)
        result = analyzer.query_class("MainClass")

        assert result is not None
        assert result["node_type"] == "class"
        assert "class_content" in result
        assert "depends" in result
        assert "depends_path" in result

    def test_query_function(self, temp_project):
        """测试查询函数"""
        analyzer = SymbolAnalyzer(temp_project)
        result = analyzer.query_function("main")

        assert result is not None
        assert result["node_type"] == "func"
        assert "function_content" in result

    def test_query_nonexistent(self, temp_project):
        """测试查询不存在的符号"""
        analyzer = SymbolAnalyzer(temp_project)

        result = analyzer.query_class("NonExistentClass")
        assert result is None

        result = analyzer.query_function("nonexistent_function")
        assert result is None

    def test_rebuild_index(self, temp_project):
        """测试重建索引"""
        analyzer = SymbolAnalyzer(temp_project)

        # 首次查询
        result1 = analyzer.query_class("MainClass")
        assert result1 is not None

        # 重建索引
        analyzer.rebuild_index()

        # 再次查询
        result2 = analyzer.query_class("MainClass")
        assert result2 is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
