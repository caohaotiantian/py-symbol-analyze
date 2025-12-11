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

# 测试 super() 调用的项目结构
PARENT_CODE = '''
"""Parent module"""

class ParentClass:
    """Parent class"""
    
    def __init__(self, config):
        self.config = config
    
    def parent_method(self):
        return "parent"
'''

CHILD_CODE = '''
"""Child module"""

from parent import ParentClass
from config import ConfigManager

class ChildClass(ParentClass):
    """Child class that uses super()"""
    
    def __init__(self, value):
        super().__init__(ConfigManager.get_default())
        self.value = value
    
    def child_method(self):
        return f"child: {self.parent_method()}"
'''

CONFIG_CODE = '''
"""Config module"""

class ConfigManager:
    """Config manager class"""
    
    @staticmethod
    def get_default():
        return {"key": "value"}
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


@pytest.fixture
def temp_project_with_inheritance():
    """创建带继承关系的临时测试项目"""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "parent.py").write_text(PARENT_CODE)
        (Path(tmpdir) / "child.py").write_text(CHILD_CODE)
        (Path(tmpdir) / "config.py").write_text(CONFIG_CODE)

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

    def test_depends_and_depends_path_correspondence(self, temp_project):
        """测试 depends 和 depends_path 一一对应"""
        resolver = DependencyResolver(temp_project)
        result = resolver.analyze_class("MainClass")

        assert result is not None
        # depends 和 depends_path 长度应该相等
        assert len(result.depends) == len(result.depends_path)

    def test_super_call_resolves_parent_class(self, temp_project_with_inheritance):
        """测试 super() 调用能正确解析父类依赖"""
        resolver = DependencyResolver(temp_project_with_inheritance)
        result = resolver.analyze_function("__init__", host_class="ChildClass")

        assert result is not None
        assert result.host_class == "ChildClass"

        # 应该包含父类 ParentClass 的依赖
        parent_found = False
        for dep in result.depends:
            if "ParentClass" in dep:
                parent_found = True
                break
        assert parent_found, "Parent class should be in depends"

        # depends_path 应该包含 parent.py
        parent_path_found = False
        for path in result.depends_path:
            if "parent.py" in path:
                parent_path_found = True
                break
        assert parent_path_found, "parent.py should be in depends_path"

    def test_attribute_access_resolves_dependency(self, temp_project_with_inheritance):
        """测试属性访问（如 ConfigManager.get_default()）能正确解析依赖"""
        resolver = DependencyResolver(temp_project_with_inheritance)
        result = resolver.analyze_function("__init__", host_class="ChildClass")

        assert result is not None

        # 应该包含 ConfigManager 的依赖
        config_found = False
        for dep in result.depends:
            if "ConfigManager" in dep:
                config_found = True
                break
        assert config_found, "ConfigManager should be in depends"


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

    def test_query_method_with_host_class(self, temp_project):
        """测试查询类方法（指定所属类）"""
        analyzer = SymbolAnalyzer(temp_project)
        result = analyzer.query_function("process", host_class="MainClass")

        assert result is not None
        assert result["node_type"] == "func"
        assert result["host_class"] == "MainClass"

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

    def test_clear_cache(self, temp_project):
        """测试清空缓存"""
        analyzer = SymbolAnalyzer(temp_project)

        # 首次查询（构建索引）
        result1 = analyzer.query_class("MainClass")
        assert result1 is not None

        # 清空缓存
        analyzer.clear_cache()

        # 再次查询（应该重新构建索引）
        result2 = analyzer.query_class("MainClass")
        assert result2 is not None

    def test_query_class_depends_correspondence(self, temp_project):
        """测试查询类时 depends 和 depends_path 一一对应"""
        analyzer = SymbolAnalyzer(temp_project)
        result = analyzer.query_class("MainClass")

        assert result is not None
        assert len(result["depends"]) == len(result["depends_path"])

    def test_query_function_depends_correspondence(self, temp_project):
        """测试查询函数时 depends 和 depends_path 一一对应"""
        analyzer = SymbolAnalyzer(temp_project)
        result = analyzer.query_function("main")

        assert result is not None
        assert len(result["depends"]) == len(result["depends_path"])


class TestImportResolution:
    """测试导入解析"""

    def test_from_import_multiple_names(self, temp_project):
        """测试 from module import a, b, c 格式的导入解析"""
        resolver = DependencyResolver(temp_project)
        result = resolver.analyze_class("MainClass")

        assert result is not None
        # MainClass 使用了 HelperClass（从 utils 导入并实例化）
        # 和 helper_func（从 utils 导入并调用）
        # 注意：CustomError 只出现在 except 子句中，当前实现不提取异常类型

        utils_path_found = False
        for path in result.depends_path:
            if "utils.py" in path:
                utils_path_found = True

        assert utils_path_found, "utils.py should be in depends_path"

        # 验证 HelperClass 在依赖内容中
        helper_class_found = False
        for dep in result.depends:
            if "HelperClass" in dep:
                helper_class_found = True
                break
        assert helper_class_found, "HelperClass should be in depends"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
