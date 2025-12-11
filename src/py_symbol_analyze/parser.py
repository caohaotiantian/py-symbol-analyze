"""
使用 tree-sitter 解析 Python 代码
"""

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, Tree

from .cache import SymbolCache
from .logger import get_logger


def _get_logger():
    """获取 logger（延迟初始化）"""
    return get_logger("py_symbol_analyze.parser")


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
    # 父类列表（仅对 class 类型有效）
    base_classes: List[str] = field(default_factory=list)
    # 是否调用了 super()（仅对 method 类型有效）
    calls_super: bool = False


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
            _get_logger().debug(f"成功解析文件: {file_path}")
            return self.parser.parse(bytes(source_code, "utf-8"))
        except Exception as e:
            _get_logger().error(f"解析文件失败 {file_path}: {e}")
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
                # 对于 import a.b.c，代码中通过 a.b.c.xxx 使用
                # 存储完整路径作为 key 避免覆盖（如 import a.b 和 import a.c）
                for child in node.children:
                    if child.type == "dotted_name":
                        name = self.get_node_text(child, source_bytes)
                        # 使用完整路径作为 key，避免多个导入冲突
                        imports[name] = name
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
                # 首先找到模块名（在 'import' 关键字之前的 dotted_name 或 relative_import）
                module = None
                import_keyword_found = False

                for child in node.children:
                    if child.type == "import":
                        import_keyword_found = True
                        continue

                    if not import_keyword_found:
                        # import 关键字之前的是模块名
                        if child.type == "dotted_name":
                            module = self.get_node_text(child, source_bytes)
                        elif child.type == "relative_import":
                            module = self.get_node_text(child, source_bytes)
                    else:
                        # import 关键字之后的是导入的名称
                        if child.type == "dotted_name":
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
                                full_path = (
                                    f"{module}.{original}" if module else original
                                )
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

    def extract_callees(
        self, node: Node, source_bytes: bytes
    ) -> Tuple[List[str], bool]:
        """
        从函数/方法/类体中提取调用的符号名称

        Returns:
            (callees_list, calls_super): 被调用的符号列表和是否调用了 super()
        """
        callees = set()
        calls_super = False

        def extract_attribute_root(attr_node: Node) -> Optional[str]:
            """
            从 attribute 节点提取根对象名称

            如 ddd.xxx.yyy -> 返回 'ddd'
            如 self.xxx -> 返回 None (跳过 self/cls)
            """
            # 递归找到最左边的 identifier
            current = attr_node
            while current.type == "attribute":
                obj = current.child_by_field_name("object")
                if obj:
                    current = obj
                else:
                    break

            if current.type == "identifier":
                name = self.get_node_text(current, source_bytes)
                if name not in ("self", "cls"):
                    return name
            elif current.type == "call":
                # 处理 super().xxx 这种情况
                func = current.child_by_field_name("function")
                if func and func.type == "identifier":
                    return self.get_node_text(func, source_bytes)

            return None

        def extract_attribute_chain(
            attr_node: Node, include_last: bool = False
        ) -> Optional[str]:
            """
            从 attribute 节点提取完整的属性链

            Args:
                attr_node: attribute 类型的节点
                include_last: 是否包含最后一部分（方法名/属性名）

            如 a.b.c.func() 的 func_node 是 attribute:
                - include_last=False: 返回 'a.b.c'
                - include_last=True: 返回 'a.b.c.func'
            如 obj.method() 返回 'obj'（无论 include_last）
            如 self.xxx -> 返回 None (跳过 self/cls)
            如 obj.method().sub() -> 返回 None (根是 call 节点，无法追踪)
            如 无法追踪到根标识符 -> 返回 None
            """
            parts = []
            current = attr_node
            has_root = False  # 标记是否成功找到根标识符

            # 收集属性链的所有部分
            while current.type == "attribute":
                attr_name = current.child_by_field_name("attribute")
                if attr_name:
                    parts.insert(0, self.get_node_text(attr_name, source_bytes))

                obj = current.child_by_field_name("object")
                if obj:
                    current = obj
                else:
                    break

            # 获取根标识符
            if current.type == "identifier":
                root = self.get_node_text(current, source_bytes)
                if root in ("self", "cls"):
                    return None
                parts.insert(0, root)
                has_root = True
            elif current.type == "call":
                # 链式调用如 obj.method().sub_method()
                # 根是一个 call 节点，无法追踪到原始对象
                return None
            # 其他类型（如 subscript、tuple 等）无法追踪，has_root 保持 False

            if not parts or not has_root:
                return None

            # 根据 include_last 决定是否包含最后一部分
            if include_last:
                return ".".join(parts)
            elif len(parts) > 1:
                return ".".join(parts[:-1])
            else:
                # 只有根标识符（如 obj.method() 返回 'obj'）
                return parts[0]

        def traverse(n: Node):
            nonlocal calls_super

            if n.type == "call":
                # 获取被调用的函数/方法名
                func_node = n.child_by_field_name("function")
                if func_node:
                    if func_node.type == "identifier":
                        # 直接调用: foo()
                        func_name = self.get_node_text(func_node, source_bytes)
                        # super() 使用 calls_super 标志跟踪，不加入 callees
                        if func_name == "super":
                            calls_super = True
                        else:
                            callees.add(func_name)
                    elif func_node.type == "attribute":
                        # 属性调用: obj.method() 或 a.b.c.func()
                        # 提取完整的属性链（不包括方法名）
                        chain = extract_attribute_chain(func_node)
                        if chain:
                            # super() 使用 calls_super 标志跟踪，不加入 callees
                            if chain == "super":
                                calls_super = True
                            else:
                                callees.add(chain)

            elif n.type == "attribute":
                # 处理属性访问: a.b.CONSTANT 作为参数或赋值值
                # 检查父节点，确保不是 call 的 function 部分（那部分已经处理了）
                parent = n.parent
                if parent and parent.type != "attribute":
                    # 不是嵌套的 attribute，检查是否是有意义的上下文
                    if parent.type in (
                        "argument_list",
                        "assignment",
                        "expression_statement",
                        "return_statement",
                        "yield",
                        "comparison_operator",
                        "binary_operator",
                        "boolean_operator",
                        "conditional_expression",
                        "tuple",
                        "list",
                        "dictionary",
                        "set",
                        "subscript",
                    ):
                        # 使用 extract_attribute_chain 提取完整的属性链
                        # include_last=True 因为这是属性访问，最后一部分是属性名
                        # 但对于 import 匹配，我们只需要模块路径部分
                        chain = extract_attribute_chain(n, include_last=False)
                        if chain and chain != "super":
                            callees.add(chain)

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
                    if name and name[0].isupper():
                        callees.add(name)

            for child in n.children:
                traverse(child)

        traverse(node)
        return list(callees), calls_super

    def extract_base_classes(self, node: Node, source_bytes: bytes) -> List[str]:
        """
        从类定义节点中提取父类列表

        Args:
            node: class_definition 节点
            source_bytes: 源代码字节

        Returns:
            父类名称列表
        """
        base_classes = []

        # 查找 argument_list（继承列表）
        for child in node.children:
            if child.type == "argument_list":
                # 遍历继承列表中的所有参数
                for arg in child.children:
                    if arg.type == "identifier":
                        # 简单继承: class Foo(Bar)
                        base_classes.append(self.get_node_text(arg, source_bytes))
                    elif arg.type == "attribute":
                        # 模块.类继承: class Foo(module.Bar)
                        attr_text = self.get_node_text(arg, source_bytes)
                        base_classes.append(attr_text)
                    elif arg.type == "call":
                        # 泛型或特殊继承: class Foo(Generic[T])
                        func_node = arg.child_by_field_name("function")
                        if func_node:
                            base_classes.append(
                                self.get_node_text(func_node, source_bytes)
                            )

        return base_classes

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
                    callees, _ = self.extract_callees(node, source_bytes)
                    base_classes = self.extract_base_classes(node, source_bytes)

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
                            base_classes=base_classes,
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
                    callees, calls_super = self.extract_callees(node, source_bytes)

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
                            calls_super=calls_super,
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


def _parsed_symbol_from_dict(data: Dict[str, Any]) -> ParsedSymbol:
    """从字典创建 ParsedSymbol 对象"""
    return ParsedSymbol(
        name=data["name"],
        node_type=data["node_type"],
        start_line=data["start_line"],
        end_line=data["end_line"],
        start_col=data["start_col"],
        end_col=data["end_col"],
        content=data["content"],
        file_path=data["file_path"],
        host_class=data.get("host_class"),
        callees=data.get("callees", []),
        imports=data.get("imports", {}),
        base_classes=data.get("base_classes", []),
        calls_super=data.get("calls_super", False),
    )


def _parsed_symbol_to_dict(symbol: ParsedSymbol) -> Dict[str, Any]:
    """将 ParsedSymbol 对象转换为字典"""
    return asdict(symbol)


class ProjectParser:
    """项目级别的解析器"""

    def __init__(
        self,
        project_root: str,
        cache_dir: Optional[str] = None,
        db_path: Optional[str] = None,
    ):
        """
        初始化项目解析器

        Args:
            project_root: 项目根目录
            cache_dir: 可选，缓存目录路径
            db_path: 可选，SQLite 数据库文件完整路径（如果指定则忽略 cache_dir）
        """
        self.project_root = Path(project_root).resolve()
        self.parser = PythonParser()
        # 使用 SQLite 缓存
        self._cache = SymbolCache(project_root, cache_dir=cache_dir, db_path=db_path)
        # 内存中的 Tree 缓存（Tree 对象无法序列化，需要保持在内存中）
        self._tree_cache: Dict[str, Tuple[float, Tree]] = {}

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

        if not file_path.exists():
            return None

        mtime = file_path.stat().st_mtime

        # 首先检查内存中的 Tree 缓存
        if file_str in self._tree_cache:
            cached_mtime, tree = self._tree_cache[file_str]
            if cached_mtime == mtime:
                # 从 SQLite 获取源代码
                cache_data = self._cache.get_file_cache(file_str)
                if cache_data:
                    _, _, source_code = cache_data
                    return tree, bytes(source_code, "utf-8")

        # 检查 SQLite 缓存
        if self._cache.is_file_cache_valid(file_str, mtime):
            cache_data = self._cache.get_file_cache(file_str)
            if cache_data:
                _, _, source_code = cache_data
                source_bytes = bytes(source_code, "utf-8")
                # 重新解析以获得 Tree 对象（Tree 无法序列化）
                tree = self.parser.parser.parse(source_bytes)
                self._tree_cache[file_str] = (mtime, tree)
                _get_logger().debug(f"从 SQLite 缓存加载: {file_path}")
                return tree, source_bytes

        # 需要重新解析文件
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()
            source_bytes = bytes(source_code, "utf-8")
            tree = self.parser.parser.parse(source_bytes)

            # 保存到 SQLite 缓存
            self._cache.set_file_cache(file_str, mtime, source_code)
            # 保存 Tree 到内存缓存
            self._tree_cache[file_str] = (mtime, tree)

            _get_logger().debug(f"解析并缓存文件: {file_path}")
            return tree, source_bytes
        except Exception as e:
            _get_logger().error(f"解析文件失败 {file_path}: {e}")
            return None

    def build_index(self, force: bool = False):
        """构建符号索引"""
        if not force and self._cache.is_indexed():
            _get_logger().debug("使用已有 SQLite 索引")
            return

        _get_logger().info(f"开始构建符号索引，项目路径: {self.project_root}")

        # 清空现有符号索引
        self._cache.clear_symbols()

        python_files = self._get_python_files()
        _get_logger().info(f"发现 {len(python_files)} 个 Python 文件")

        class_count = 0
        func_count = 0
        batch_symbols: List[Dict[str, Any]] = []
        batch_size = 100  # 批量写入的大小

        for file_path in python_files:
            result = self._parse_file_cached(file_path)
            if not result:
                continue

            tree, source_bytes = result
            file_str = str(file_path)

            # 索引类
            classes = self.parser.find_classes(tree, source_bytes, file_str)
            for cls in classes:
                batch_symbols.append(_parsed_symbol_to_dict(cls))
                class_count += 1

            # 索引函数
            functions = self.parser.find_functions(tree, source_bytes, file_str)
            for func in functions:
                batch_symbols.append(_parsed_symbol_to_dict(func))
                func_count += 1

            # 批量写入
            if len(batch_symbols) >= batch_size:
                self._cache.add_symbols_batch(batch_symbols)
                batch_symbols = []

        # 写入剩余的符号
        if batch_symbols:
            self._cache.add_symbols_batch(batch_symbols)

        self._cache.set_indexed(True)
        _get_logger().info(f"索引构建完成: {class_count} 个类, {func_count} 个函数")

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

        # 从 SQLite 缓存查询
        results = self._cache.find_symbols_by_name(name, symbol_type, file_hint)

        if not results:
            return None

        # 返回第一个匹配（已按 file_hint 排序）
        return _parsed_symbol_from_dict(results[0])

    def find_all_symbols(self, name: str) -> List[ParsedSymbol]:
        """查找所有同名符号"""
        self.build_index()
        results = self._cache.find_symbols_by_name(name)
        return [_parsed_symbol_from_dict(r) for r in results]

    def get_file_symbols(
        self, file_path: str
    ) -> Tuple[List[ParsedSymbol], List[ParsedSymbol]]:
        """获取文件中的所有类和函数"""
        path = Path(file_path)

        # 检查文件是否存在
        if not path.exists():
            return [], []

        mtime = path.stat().st_mtime

        # 如果文件缓存有效，优先从 SQLite 获取
        # 注意：空符号列表也是有效的缓存数据（文件可能没有类或函数）
        if self._cache.is_file_cache_valid(str(path), mtime):
            symbols = self._cache.find_symbols_by_file(str(path))
            classes = [
                _parsed_symbol_from_dict(s)
                for s in symbols
                if s["node_type"] == "class"
            ]
            functions = [
                _parsed_symbol_from_dict(s)
                for s in symbols
                if s["node_type"] in ("function", "method")
            ]
            return classes, functions

        # 需要重新解析文件
        result = self._parse_file_cached(path)
        if not result:
            return [], []

        tree, source_bytes = result
        classes = self.parser.find_classes(tree, source_bytes, file_path)
        functions = self.parser.find_functions(tree, source_bytes, file_path)

        # 更新 SQLite 缓存中的符号
        self._cache.remove_symbols_by_file(file_path)
        symbols_to_cache = [_parsed_symbol_to_dict(s) for s in classes + functions]
        if symbols_to_cache:
            self._cache.add_symbols_batch(symbols_to_cache)

        return classes, functions

    def invalidate_file(self, file_path: str):
        """
        使文件缓存失效

        当文件被修改时调用此方法。
        """
        self._cache.remove_file_cache(file_path)
        self._cache.remove_symbols_by_file(file_path)
        # 清除内存中的 Tree 缓存
        if file_path in self._tree_cache:
            del self._tree_cache[file_path]
        _get_logger().debug(f"已使文件缓存失效: {file_path}")

    def clear_cache(self):
        """清空所有缓存"""
        self._cache.clear_all()
        self._tree_cache.clear()
        _get_logger().info("已清空所有缓存")

    def get_all_symbols(self, symbol_type: Optional[str] = None) -> List[ParsedSymbol]:
        """
        获取项目中的所有符号

        Args:
            symbol_type: 可选，"class" 或 "function"

        Returns:
            ParsedSymbol 列表
        """
        self.build_index()
        results = self._cache.get_all_symbols(symbol_type)
        return [_parsed_symbol_from_dict(r) for r in results]
