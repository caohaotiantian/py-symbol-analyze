"""
测试 Python 解析器
"""

import tempfile
from pathlib import Path

import pytest

from py_symbol_analyze.parser import ProjectParser, PythonParser

# 测试用的示例代码
SAMPLE_CODE = '''
"""Sample module"""

from typing import List, Optional
from .utils import helper_func
from base import BaseClass

class MyClass(BaseClass):
    """A sample class"""
    
    def __init__(self, name: str):
        self.name = name
        self.helper = HelperClass()
    
    def process(self, data: List[str]) -> Optional[str]:
        """Process data"""
        result = helper_func(data)
        return self.transform(result)
    
    def transform(self, value):
        return str(value)


class HelperClass:
    """Helper class"""
    
    def do_something(self):
        return "done"


def standalone_function(x: int) -> int:
    """A standalone function"""
    obj = MyClass("test")
    return x * 2
'''


@pytest.fixture
def parser():
    return PythonParser()


@pytest.fixture
def temp_project():
    """创建临时项目目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建主模块文件
        main_file = Path(tmpdir) / "main.py"
        main_file.write_text(SAMPLE_CODE)

        # 创建 utils 模块
        utils_file = Path(tmpdir) / "utils.py"
        utils_file.write_text('''
def helper_func(data):
    """Helper function"""
    return data[0] if data else None
''')

        # 创建 base 模块
        base_file = Path(tmpdir) / "base.py"
        base_file.write_text('''
class BaseClass:
    """Base class"""
    
    def base_method(self):
        pass
''')

        yield tmpdir


class TestPythonParser:
    """测试 PythonParser"""

    def test_parse_source(self, parser):
        """测试解析源代码"""
        tree = parser.parse_source(SAMPLE_CODE)
        assert tree is not None
        assert tree.root_node is not None

    def test_extract_imports(self, parser):
        """测试提取导入"""
        tree = parser.parse_source(SAMPLE_CODE)
        source_bytes = bytes(SAMPLE_CODE, "utf-8")
        imports = parser.extract_imports(tree, source_bytes)

        assert "List" in imports
        assert "Optional" in imports
        assert "helper_func" in imports
        assert "BaseClass" in imports

    def test_find_classes(self, parser):
        """测试查找类"""
        tree = parser.parse_source(SAMPLE_CODE)
        source_bytes = bytes(SAMPLE_CODE, "utf-8")
        classes = parser.find_classes(tree, source_bytes, "test.py")

        assert len(classes) == 2
        class_names = [c.name for c in classes]
        assert "MyClass" in class_names
        assert "HelperClass" in class_names

    def test_find_functions(self, parser):
        """测试查找函数"""
        tree = parser.parse_source(SAMPLE_CODE)
        source_bytes = bytes(SAMPLE_CODE, "utf-8")
        functions = parser.find_functions(tree, source_bytes, "test.py")

        # 应该找到类方法和独立函数
        func_names = [f.name for f in functions]
        assert "standalone_function" in func_names
        assert "__init__" in func_names
        assert "process" in func_names
        assert "transform" in func_names
        assert "do_something" in func_names

    def test_extract_callees(self, parser):
        """测试提取被调用的符号"""
        tree = parser.parse_source(SAMPLE_CODE)
        source_bytes = bytes(SAMPLE_CODE, "utf-8")
        functions = parser.find_functions(tree, source_bytes, "test.py")

        # 查找 process 方法
        process_func = next(f for f in functions if f.name == "process")
        assert "helper_func" in process_func.callees

    def test_class_with_callees(self, parser):
        """测试类的调用分析"""
        tree = parser.parse_source(SAMPLE_CODE)
        source_bytes = bytes(SAMPLE_CODE, "utf-8")
        classes = parser.find_classes(tree, source_bytes, "test.py")

        my_class = next(c for c in classes if c.name == "MyClass")
        # MyClass 内部使用了 HelperClass
        assert "HelperClass" in my_class.callees


class TestProjectParser:
    """测试 ProjectParser"""

    def test_build_index(self, temp_project):
        """测试构建索引"""
        parser = ProjectParser(temp_project)
        parser.build_index()

        # 检查索引是否包含预期的符号（通过 find_symbol 验证）
        assert parser.find_symbol("MyClass") is not None
        assert parser.find_symbol("HelperClass") is not None
        assert parser.find_symbol("standalone_function") is not None
        assert parser.find_symbol("helper_func") is not None
        assert parser.find_symbol("BaseClass") is not None

    def test_find_symbol(self, temp_project):
        """测试查找符号"""
        parser = ProjectParser(temp_project)

        my_class = parser.find_symbol("MyClass", symbol_type="class")
        assert my_class is not None
        assert my_class.name == "MyClass"
        assert my_class.node_type == "class"

        func = parser.find_symbol("standalone_function", symbol_type="function")
        assert func is not None
        assert func.name == "standalone_function"

    def test_get_file_symbols(self, temp_project):
        """测试获取文件符号"""
        parser = ProjectParser(temp_project)
        main_file = str(Path(temp_project) / "main.py")

        classes, functions = parser.get_file_symbols(main_file)

        assert len(classes) == 2
        assert (
            len(functions) == 5
        )  # __init__, process, transform, do_something, standalone_function


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
