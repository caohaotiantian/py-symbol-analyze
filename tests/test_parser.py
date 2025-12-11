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

# 测试 super() 调用和属性访问的代码
INHERITANCE_CODE = '''
"""Test inheritance and super() calls"""

from a.b.c.demo import ddd
from base import ParentClass

class ChildClass(ParentClass):
    """Child class that uses super()"""
    
    def __init__(self, value):
        super().__init__(ddd.config)
        self.value = value
        self.data = ddd.get_data()
    
    def process(self):
        result = ddd.transform(self.value)
        return result
'''

# 测试多导入的代码
MULTI_IMPORT_CODE = '''
"""Test multiple imports from same module"""

from utils import func_a, func_b, ClassA
from other.module import helper as h, processor

def test_func():
    a = func_a()
    b = func_b()
    obj = ClassA()
    h.do_something()
    processor.run()
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

    def test_extract_imports_multiple(self, parser):
        """测试提取多个导入（from module import a, b, c）"""
        tree = parser.parse_source(MULTI_IMPORT_CODE)
        source_bytes = bytes(MULTI_IMPORT_CODE, "utf-8")
        imports = parser.extract_imports(tree, source_bytes)

        # 验证所有导入都被正确解析
        assert imports.get("func_a") == "utils.func_a"
        assert imports.get("func_b") == "utils.func_b"
        assert imports.get("ClassA") == "utils.ClassA"
        assert imports.get("h") == "other.module.helper"
        assert imports.get("processor") == "other.module.processor"

    def test_find_classes(self, parser):
        """测试查找类"""
        tree = parser.parse_source(SAMPLE_CODE)
        source_bytes = bytes(SAMPLE_CODE, "utf-8")
        classes = parser.find_classes(tree, source_bytes, "test.py")

        assert len(classes) == 2
        class_names = [c.name for c in classes]
        assert "MyClass" in class_names
        assert "HelperClass" in class_names

    def test_find_classes_with_base_classes(self, parser):
        """测试类的父类提取"""
        tree = parser.parse_source(SAMPLE_CODE)
        source_bytes = bytes(SAMPLE_CODE, "utf-8")
        classes = parser.find_classes(tree, source_bytes, "test.py")

        my_class = next(c for c in classes if c.name == "MyClass")
        assert "BaseClass" in my_class.base_classes

        helper_class = next(c for c in classes if c.name == "HelperClass")
        assert len(helper_class.base_classes) == 0

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

    def test_extract_callees_attribute_access(self, parser):
        """测试提取属性访问作为参数/赋值值的符号"""
        tree = parser.parse_source(INHERITANCE_CODE)
        source_bytes = bytes(INHERITANCE_CODE, "utf-8")
        functions = parser.find_functions(tree, source_bytes, "test.py")

        # 查找 ChildClass.__init__
        init_func = next(
            f for f in functions if f.name == "__init__" and f.host_class == "ChildClass"
        )
        # ddd.config 和 ddd.get_data() 都应该提取出 ddd
        assert "ddd" in init_func.callees

        # 查找 process 方法
        process_func = next(
            f for f in functions if f.name == "process" and f.host_class == "ChildClass"
        )
        # ddd.transform() 应该提取出 ddd
        assert "ddd" in process_func.callees

    def test_calls_super_flag(self, parser):
        """测试 calls_super 标志"""
        tree = parser.parse_source(INHERITANCE_CODE)
        source_bytes = bytes(INHERITANCE_CODE, "utf-8")
        functions = parser.find_functions(tree, source_bytes, "test.py")

        # ChildClass.__init__ 调用了 super()
        init_func = next(
            f for f in functions if f.name == "__init__" and f.host_class == "ChildClass"
        )
        assert init_func.calls_super is True

        # process 方法没有调用 super()
        process_func = next(
            f for f in functions if f.name == "process" and f.host_class == "ChildClass"
        )
        assert process_func.calls_super is False

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

    def test_get_all_symbols(self, temp_project):
        """测试获取所有符号"""
        parser = ProjectParser(temp_project)

        all_classes = parser.get_all_symbols("class")
        all_functions = parser.get_all_symbols("function")

        assert len(all_classes) >= 2  # MyClass, HelperClass, BaseClass
        assert len(all_functions) >= 5

    def test_cache_persistence(self, temp_project):
        """测试缓存持久化"""
        # 第一次解析
        parser1 = ProjectParser(temp_project)
        parser1.build_index()
        symbol1 = parser1.find_symbol("MyClass")
        assert symbol1 is not None

        # 创建新的解析器实例（应该从缓存加载）
        parser2 = ProjectParser(temp_project)
        symbol2 = parser2.find_symbol("MyClass")
        assert symbol2 is not None
        assert symbol1.name == symbol2.name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
