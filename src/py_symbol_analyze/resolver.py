"""
符号解析和依赖分析器

使用 jedi 进行精确的符号解析，结合 tree-sitter 的解析结果。
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import jedi

from .logger import get_logger
from .models import (
    ClassAnalysisResult,
    Dependency,
    FunctionAnalysisResult,
)
from .parser import ParsedSymbol, ProjectParser

logger = get_logger("py_symbol_analyze.resolver")


class DependencyResolver:
    """依赖解析器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.project_parser = ProjectParser(project_root)
        # 添加项目路径到 sys.path 以便 jedi 能正确解析
        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))
        logger.debug(f"初始化依赖解析器，项目路径: {self.project_root}")

    def _resolve_import_path(
        self, import_path: str, current_file: str
    ) -> Optional[str]:
        """
        解析导入路径，返回实际文件路径

        Args:
            import_path: 如 "jiuwen.common.store.obs"
            current_file: 当前文件路径，用于解析相对导入
        """
        # 处理相对导入
        if import_path.startswith("."):
            current_dir = Path(current_file).parent
            # 计算相对层级
            level = 0
            for char in import_path:
                if char == ".":
                    level += 1
                else:
                    break

            # 向上移动目录
            base_dir = current_dir
            for _ in range(level - 1):
                base_dir = base_dir.parent

            # 剩余的模块路径
            remaining = import_path[level:]
            if remaining:
                parts = remaining.split(".")
                potential_path = base_dir / "/".join(parts)
            else:
                potential_path = base_dir

            # 检查是否是文件或包
            if potential_path.with_suffix(".py").exists():
                return str(potential_path.with_suffix(".py"))
            if (potential_path / "__init__.py").exists():
                return str(potential_path / "__init__.py")

        # 处理绝对导入
        parts = import_path.split(".")

        # 尝试在项目根目录下查找
        for i in range(len(parts), 0, -1):
            potential_path = self.project_root / "/".join(parts[:i])

            # 检查是否是 .py 文件
            py_file = potential_path.with_suffix(".py")
            if py_file.exists():
                return str(py_file)

            # 检查是否是包目录
            init_file = potential_path / "__init__.py"
            if init_file.exists():
                return str(init_file)

        return None

    def _use_jedi_to_resolve(
        self,
        symbol_name: str,
        source_code: str,
        file_path: str,
        line: int = 1,
        column: int = 0,
    ) -> List[Tuple[str, str]]:
        """
        使用 jedi 解析符号定义位置

        Returns:
            List of (name, file_path) tuples
        """
        results = []
        try:
            script = jedi.Script(
                source_code,
                path=file_path,
                project=jedi.Project(path=str(self.project_root)),
            )

            # 在源代码中查找符号的使用位置
            for i, line_content in enumerate(source_code.split("\n"), 1):
                col = line_content.find(symbol_name)
                if col >= 0:
                    try:
                        definitions = script.goto(i, col)
                        for d in definitions:
                            if d.module_path:
                                results.append((d.name, str(d.module_path)))
                                break
                    except Exception:
                        pass
                    if results:
                        break

        except Exception:
            pass

        return results

    def resolve_dependencies(self, symbol: ParsedSymbol) -> List[Dependency]:
        """
        解析符号的所有依赖

        遍历符号的 callees，尝试找到每个被调用符号的定义。
        """
        logger.debug(f"解析符号依赖: {symbol.name}, callees: {symbol.callees}")
        dependencies = []
        seen_symbols = set()

        for callee_name in symbol.callees:
            if callee_name in seen_symbols:
                continue
            seen_symbols.add(callee_name)

            # 跳过内置类型和常见名称
            if callee_name in (
                "str",
                "int",
                "float",
                "bool",
                "list",
                "dict",
                "set",
                "tuple",
                "None",
                "True",
                "False",
                "print",
                "len",
                "range",
                "enumerate",
                "zip",
                "map",
                "filter",
                "super",
                "type",
                "isinstance",
                "hasattr",
                "getattr",
                "setattr",
                "Exception",
                "ValueError",
                "TypeError",
                "KeyError",
                "IndexError",
                "AttributeError",
                "RuntimeError",
            ):
                continue

            dep = self._resolve_single_dependency(callee_name, symbol)
            if dep and dep.file_path:
                dependencies.append(dep)

        return dependencies

    def _resolve_single_dependency(
        self, callee_name: str, context_symbol: ParsedSymbol
    ) -> Optional[Dependency]:
        """解析单个依赖"""
        # 首先检查导入信息
        if callee_name in context_symbol.imports:
            import_path = context_symbol.imports[callee_name]
            file_path = self._resolve_import_path(import_path, context_symbol.file_path)

            if file_path:
                # 在目标文件中查找符号
                found_symbol = self._find_symbol_in_file(callee_name, file_path)
                if found_symbol:
                    return Dependency(
                        name=callee_name,
                        qualified_name=import_path,
                        file_path=file_path,
                        content=found_symbol.content,
                        is_class=found_symbol.node_type == "class",
                        host_class=found_symbol.host_class,
                    )

        # 尝试在项目中全局查找
        found_symbol = self.project_parser.find_symbol(callee_name)
        if found_symbol:
            return Dependency(
                name=callee_name,
                file_path=found_symbol.file_path,
                content=found_symbol.content,
                is_class=found_symbol.node_type == "class",
                host_class=found_symbol.host_class,
            )

        # 使用 jedi 尝试解析
        jedi_results = self._use_jedi_to_resolve(
            callee_name, context_symbol.content, context_symbol.file_path
        )
        for name, file_path in jedi_results:
            if file_path and Path(file_path).exists():
                found_symbol = self._find_symbol_in_file(name, file_path)
                if found_symbol:
                    return Dependency(
                        name=name,
                        file_path=file_path,
                        content=found_symbol.content,
                        is_class=found_symbol.node_type == "class",
                        host_class=found_symbol.host_class,
                    )

        return None

    def _find_symbol_in_file(
        self, symbol_name: str, file_path: str
    ) -> Optional[ParsedSymbol]:
        """在指定文件中查找符号"""
        classes, functions = self.project_parser.get_file_symbols(file_path)

        # 先查找类
        for cls in classes:
            if cls.name == symbol_name:
                return cls

        # 再查找函数
        for func in functions:
            if func.name == symbol_name:
                return func

        return None

    def analyze_class(
        self, class_name: str, file_path: Optional[str] = None
    ) -> Optional[ClassAnalysisResult]:
        """
        分析类及其依赖

        Args:
            class_name: 类名
            file_path: 可选，指定文件路径
        """
        logger.info(f"分析类: {class_name}, 文件提示: {file_path}")
        # 查找类定义
        symbol = self.project_parser.find_symbol(
            class_name, symbol_type="class", file_hint=file_path
        )
        if not symbol:
            logger.warning(f"未找到类: {class_name}")
            return None
        logger.debug(f"找到类定义位置: {symbol.file_path}:{symbol.start_line}")

        # 解析依赖
        dependencies = self.resolve_dependencies(symbol)

        # 构建结果
        depends = []
        depends_path = []

        for dep in dependencies:
            if dep.content:
                # 如果依赖是方法，获取其所属类的完整内容
                if dep.host_class and dep.file_path:
                    host_class_symbol = self._find_symbol_in_file(
                        dep.host_class, dep.file_path
                    )
                    if host_class_symbol:
                        depends.append(host_class_symbol.content)
                    else:
                        depends.append(dep.content)
                else:
                    depends.append(dep.content)

                if dep.file_path and dep.file_path not in depends_path:
                    depends_path.append(dep.file_path)

        return ClassAnalysisResult(
            class_content=symbol.content,
            file_path=symbol.file_path,
            depends=depends,
            depends_path=depends_path,
        )

    def analyze_function(
        self,
        function_name: str,
        file_path: Optional[str] = None,
        host_class: Optional[str] = None,
    ) -> Optional[FunctionAnalysisResult]:
        """
        分析函数及其依赖

        Args:
            function_name: 函数名
            file_path: 可选，指定文件路径
            host_class: 可选，如果是类方法，指定类名
        """
        logger.info(
            f"分析函数: {function_name}, 文件提示: {file_path}, 所属类: {host_class}"
        )
        # 查找函数定义
        candidates = self.project_parser.find_all_symbols(function_name)
        candidates = [c for c in candidates if c.node_type in ("function", "method")]

        if host_class:
            candidates = [c for c in candidates if c.host_class == host_class]

        if file_path:
            candidates = [c for c in candidates if file_path in c.file_path]

        if not candidates:
            logger.warning(f"未找到函数: {function_name}")
            return None

        symbol = candidates[0]
        logger.debug(f"找到函数定义位置: {symbol.file_path}:{symbol.start_line}")

        # 解析依赖
        dependencies = self.resolve_dependencies(symbol)

        # 构建结果
        depends = []
        depends_path = []

        for dep in dependencies:
            if dep.content:
                # 如果依赖是方法，获取其所属类的完整内容
                if dep.host_class and dep.file_path:
                    host_class_symbol = self._find_symbol_in_file(
                        dep.host_class, dep.file_path
                    )
                    if host_class_symbol:
                        depends.append(host_class_symbol.content)
                    else:
                        depends.append(dep.content)
                else:
                    depends.append(dep.content)

                if dep.file_path and dep.file_path not in depends_path:
                    depends_path.append(dep.file_path)

        return FunctionAnalysisResult(
            function_content=symbol.content,
            host_class=symbol.host_class,
            file_path=symbol.file_path,
            depends=depends,
            depends_path=depends_path,
        )


class SymbolAnalyzer:
    """
    符号分析器 - 对外暴露的主要接口
    """

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.resolver = DependencyResolver(project_root)
        logger.info(f"符号分析器初始化完成，项目路径: {project_root}")

    def query_class(
        self, class_name: str, file_path: Optional[str] = None
    ) -> Optional[Dict]:
        """
        查询类的内容和依赖

        Args:
            class_name: 类名
            file_path: 可选，类所在的文件路径

        Returns:
            包含类内容和依赖信息的字典
        """
        result = self.resolver.analyze_class(class_name, file_path)
        if result:
            return result.model_dump()
        return None

    def query_function(
        self,
        function_name: str,
        file_path: Optional[str] = None,
        host_class: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        查询函数的内容和依赖

        Args:
            function_name: 函数名
            file_path: 可选，函数所在的文件路径
            host_class: 可选，如果是类方法，指定类名

        Returns:
            包含函数内容和依赖信息的字典
        """
        result = self.resolver.analyze_function(function_name, file_path, host_class)
        if result:
            return result.model_dump()
        return None

    def rebuild_index(self):
        """重建符号索引"""
        self.resolver.project_parser.build_index(force=True)
