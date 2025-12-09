"""
使用 tree-sitter 解析 Python 代码
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree

from .logger import get_logger

logger = get_logger("py_symbol_analyze.parser")


@dataclass
class ParsedSymbol:
    """解析后的符号信息"""

    name: str
    node_type: str  # "class", "function", "method"
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    content: str
    file_path: str
    host_class: Optional[str] = None
    # 符号内调用的其他符号（名称列表）
    callees: List[str] = field(default_factory=list)
    # 导入信息
    imports: Dict[str, str] = field(default_factory=dict)  # alias -> module.name


class PythonParser:
    """Python 代码解析器"""

    def __init__(self):
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)

    def parse_file(self, file_path: str) -> Optional[Tree]:
        """解析单个文件"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()
            logger.debug(f"成功解析文件: {file_path}")
            return self.parser.parse(bytes(source_code, "utf-8"))
        except Exception as e:
            logger.error(f"解析文件失败 {file_path}: {e}")
            return None

    def parse_source(self, source_code: str) -> Tree:
        """解析源代码字符串"""
        return self.parser.parse(bytes(source_code, "utf-8"))

    def get_node_text(self, node: Node, source_bytes: bytes) -> str:
        """获取节点对应的源代码文本"""
        return source_bytes[node.start_byte : node.end_byte].decode("utf-8")

    def extract_imports(self, tree: Tree, source_bytes: bytes) -> Dict[str, str]:
        """
        提取文件中的所有导入信息
        返回: {别名或名称: 完整模块路径}
        """
        imports = {}
        root = tree.root_node

        def process_import(node: Node):
            if node.type == "import_statement":
                # import foo, bar as b
                for child in node.children:
                    if child.type == "dotted_name":
                        name = self.get_node_text(child, source_bytes)
                        imports[name.split(".")[-1]] = name
                    elif child.type == "aliased_import":
                        dotted = None
                        alias = None
                        for c in child.children:
                            if c.type == "dotted_name":
                                dotted = self.get_node_text(c, source_bytes)
                            elif c.type == "identifier":
                                alias = self.get_node_text(c, source_bytes)
                        if dotted and alias:
                            imports[alias] = dotted

            elif node.type == "import_from_statement":
                # from foo import bar, baz as z
                module = None
                for child in node.children:
                    if child.type == "dotted_name":
                        module = self.get_node_text(child, source_bytes)
                    elif child.type == "relative_import":
                        # 处理相对导入 from . import xxx 或 from ..foo import xxx
                        module = self.get_node_text(child, source_bytes)

                # 提取导入的名称
                for child in node.children:
                    if child.type == "dotted_name" and child != node.children[1]:
                        name = self.get_node_text(child, source_bytes)
                        full_path = f"{module}.{name}" if module else name
                        imports[name.split(".")[-1]] = full_path
                    elif child.type == "aliased_import":
                        original = None
                        alias = None
                        for c in child.children:
                            if (
                                c.type in ("dotted_name", "identifier")
                                and original is None
                            ):
                                original = self.get_node_text(c, source_bytes)
                            elif c.type == "identifier":
                                alias = self.get_node_text(c, source_bytes)
                        if original:
                            full_path = f"{module}.{original}" if module else original
                            imports[alias or original] = full_path
                    elif child.type == "identifier":
                        name = self.get_node_text(child, source_bytes)
                        if name not in ("from", "import", "as"):
                            full_path = f"{module}.{name}" if module else name
                            imports[name] = full_path

        def traverse(node: Node):
            process_import(node)
            for child in node.children:
                traverse(child)

        traverse(root)
        return imports

    def extract_callees(self, node: Node, source_bytes: bytes) -> List[str]:
        """
        从函数/方法/类体中提取调用的符号名称
        """
        callees = set()

        def traverse(n: Node):
            if n.type == "call":
                # 获取被调用的函数/方法名
                func_node = n.child_by_field_name("function")
                if func_node:
                    if func_node.type == "identifier":
                        # 直接调用: foo()
                        callees.add(self.get_node_text(func_node, source_bytes))
                    elif func_node.type == "attribute":
                        # 属性调用: obj.method() 或 Class.method()
                        # 获取整个属性链
                        attr_text = self.get_node_text(func_node, source_bytes)
                        parts = attr_text.split(".")
                        # 添加第一个部分（可能是类名或实例名）
                        if parts[0] not in ("self", "cls"):
                            callees.add(parts[0])
                        # 如果是 ClassName.method() 形式，添加类名
                        if len(parts) >= 2 and parts[0][0].isupper():
                            callees.add(parts[0])

            elif n.type == "identifier":
                # 检查是否是类实例化或引用
                parent = n.parent
                if parent and parent.type in (
                    "argument_list",
                    "assignment",
                    "expression_statement",
                ):
                    name = self.get_node_text(n, source_bytes)
                    # 首字母大写通常是类名
                    if name[0].isupper() if name else False:
                        callees.add(name)

            for child in n.children:
                traverse(child)

        traverse(node)
        return list(callees)

    def find_classes(
        self, tree: Tree, source_bytes: bytes, file_path: str
    ) -> List[ParsedSymbol]:
        """查找所有类定义"""
        classes = []
        imports = self.extract_imports(tree, source_bytes)

        def traverse(node: Node):
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self.get_node_text(name_node, source_bytes)
                    content = self.get_node_text(node, source_bytes)
                    callees = self.extract_callees(node, source_bytes)

                    classes.append(
                        ParsedSymbol(
                            name=name,
                            node_type="class",
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            start_col=node.start_point[1],
                            end_col=node.end_point[1],
                            content=content,
                            file_path=file_path,
                            callees=callees,
                            imports=imports,
                        )
                    )

            for child in node.children:
                traverse(child)

        traverse(tree.root_node)
        return classes

    def find_functions(
        self, tree: Tree, source_bytes: bytes, file_path: str
    ) -> List[ParsedSymbol]:
        """查找所有函数定义（包括类内方法和模块级函数）"""
        functions = []
        imports = self.extract_imports(tree, source_bytes)

        def traverse(node: Node, current_class: Optional[str] = None):
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                class_name = (
                    self.get_node_text(name_node, source_bytes) if name_node else None
                )
                for child in node.children:
                    traverse(child, class_name)
                return

            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self.get_node_text(name_node, source_bytes)
                    content = self.get_node_text(node, source_bytes)
                    callees = self.extract_callees(node, source_bytes)

                    functions.append(
                        ParsedSymbol(
                            name=name,
                            node_type="method" if current_class else "function",
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            start_col=node.start_point[1],
                            end_col=node.end_point[1],
                            content=content,
                            file_path=file_path,
                            host_class=current_class,
                            callees=callees,
                            imports=imports,
                        )
                    )

            for child in node.children:
                traverse(child, current_class)

        traverse(tree.root_node)
        return functions

    def find_symbol_by_name(
        self,
        tree: Tree,
        source_bytes: bytes,
        file_path: str,
        symbol_name: str,
        symbol_type: Optional[str] = None,  # "class", "function", or None for any
    ) -> Optional[ParsedSymbol]:
        """根据名称查找符号"""
        if symbol_type in (None, "class"):
            classes = self.find_classes(tree, source_bytes, file_path)
            for cls in classes:
                if cls.name == symbol_name:
                    return cls

        if symbol_type in (None, "function"):
            functions = self.find_functions(tree, source_bytes, file_path)
            for func in functions:
                if func.name == symbol_name:
                    return func

        return None


class ProjectParser:
    """项目级别的解析器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.parser = PythonParser()
        # 缓存：文件路径 -> (修改时间, 解析结果)
        self._file_cache: Dict[str, Tuple[float, Tree, bytes]] = {}
        # 符号索引：符号名 -> [ParsedSymbol, ...]
        self._symbol_index: Dict[str, List[ParsedSymbol]] = {}
        self._indexed = False

    def _get_python_files(self) -> List[Path]:
        """获取项目中所有 Python 文件"""
        python_files = []
        for root, dirs, files in os.walk(self.project_root):
            # 跳过常见的非源码目录
            dirs[:] = [
                d
                for d in dirs
                if d
                not in (
                    "__pycache__",
                    ".git",
                    ".venv",
                    "venv",
                    "node_modules",
                    ".tox",
                    "build",
                    "dist",
                    ".eggs",
                )
            ]
            for file in files:
                if file.endswith(".py"):
                    python_files.append(Path(root) / file)
        return python_files

    def _parse_file_cached(self, file_path: Path) -> Optional[Tuple[Tree, bytes]]:
        """带缓存的文件解析"""
        file_str = str(file_path)
        mtime = file_path.stat().st_mtime if file_path.exists() else 0

        if file_str in self._file_cache:
            cached_mtime, tree, source_bytes = self._file_cache[file_str]
            if cached_mtime == mtime:
                return tree, source_bytes

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()
            source_bytes = bytes(source_code, "utf-8")
            tree = self.parser.parser.parse(source_bytes)
            self._file_cache[file_str] = (mtime, tree, source_bytes)
            logger.debug(f"缓存解析结果: {file_path}")
            return tree, source_bytes
        except Exception as e:
            logger.error(f"解析文件失败 {file_path}: {e}")
            return None

    def build_index(self, force: bool = False):
        """构建符号索引"""
        if self._indexed and not force:
            logger.debug("使用已有索引")
            return

        logger.info(f"开始构建符号索引，项目路径: {self.project_root}")
        self._symbol_index.clear()
        python_files = self._get_python_files()
        logger.info(f"发现 {len(python_files)} 个 Python 文件")

        class_count = 0
        func_count = 0

        for file_path in python_files:
            result = self._parse_file_cached(file_path)
            if not result:
                continue

            tree, source_bytes = result
            file_str = str(file_path)

            # 索引类
            classes = self.parser.find_classes(tree, source_bytes, file_str)
            for cls in classes:
                if cls.name not in self._symbol_index:
                    self._symbol_index[cls.name] = []
                self._symbol_index[cls.name].append(cls)
                class_count += 1

            # 索引函数
            functions = self.parser.find_functions(tree, source_bytes, file_str)
            for func in functions:
                if func.name not in self._symbol_index:
                    self._symbol_index[func.name] = []
                self._symbol_index[func.name].append(func)
                func_count += 1

        self._indexed = True
        logger.info(f"索引构建完成: {class_count} 个类, {func_count} 个函数")

    def find_symbol(
        self,
        name: str,
        symbol_type: Optional[str] = None,
        file_hint: Optional[str] = None,
    ) -> Optional[ParsedSymbol]:
        """
        查找符号

        Args:
            name: 符号名称
            symbol_type: 可选，"class" 或 "function"
            file_hint: 可选，优先在此文件中查找
        """
        self.build_index()

        candidates = self._symbol_index.get(name, [])

        if symbol_type:
            if symbol_type == "class":
                candidates = [c for c in candidates if c.node_type == "class"]
            elif symbol_type == "function":
                candidates = [
                    c for c in candidates if c.node_type in ("function", "method")
                ]

        if not candidates:
            return None

        # 如果有文件提示，优先返回该文件中的符号
        if file_hint:
            for c in candidates:
                if file_hint in c.file_path:
                    return c

        # 返回第一个匹配
        return candidates[0]

    def find_all_symbols(self, name: str) -> List[ParsedSymbol]:
        """查找所有同名符号"""
        self.build_index()
        return self._symbol_index.get(name, [])

    def get_file_symbols(
        self, file_path: str
    ) -> Tuple[List[ParsedSymbol], List[ParsedSymbol]]:
        """获取文件中的所有类和函数"""
        path = Path(file_path)
        result = self._parse_file_cached(path)
        if not result:
            return [], []

        tree, source_bytes = result
        classes = self.parser.find_classes(tree, source_bytes, file_path)
        functions = self.parser.find_functions(tree, source_bytes, file_path)
        return classes, functions
