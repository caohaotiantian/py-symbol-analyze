"""
SQLite3 缓存管理模块

用于持久化存储文件解析结果和符号索引。
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from .logger import get_logger


def _get_logger():
    """获取 logger（延迟初始化）"""
    return get_logger("py_symbol_analyze.cache")


# 全局缓存目录配置
_cache_dir: Optional[str] = None


def set_cache_dir(cache_dir: Optional[str]) -> str:
    """
    设置全局缓存目录

    Args:
        cache_dir: 缓存目录路径，如果为 None 则使用默认路径（当前目录下的 cache 文件夹）

    Returns:
        实际使用的缓存目录路径
    """
    global _cache_dir
    if cache_dir:
        _cache_dir = str(Path(cache_dir).resolve())
    else:
        _cache_dir = str(Path.cwd() / "cache")

    # 确保缓存目录存在
    Path(_cache_dir).mkdir(parents=True, exist_ok=True)
    _get_logger().info(f"缓存目录: {_cache_dir}")
    return _cache_dir


def get_cache_dir() -> str:
    """
    获取全局缓存目录

    Returns:
        缓存目录路径
    """
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = str(Path.cwd() / "cache")
        Path(_cache_dir).mkdir(parents=True, exist_ok=True)
    return _cache_dir


def generate_cache_filename(project_root: str) -> str:
    """
    根据项目路径生成缓存文件名

    格式: {项目名}_{项目绝对路径的md5值}.db

    Args:
        project_root: 项目根目录

    Returns:
        缓存文件名
    """
    project_path = Path(project_root).resolve()
    project_name = project_path.name
    path_hash = hashlib.md5(str(project_path).encode("utf-8")).hexdigest()[:12]
    return f"{project_name}_{path_hash}.db"


class SymbolCache:
    """符号缓存管理器 - 使用 SQLite3 进行持久化存储"""

    def __init__(
        self,
        project_root: str,
        cache_dir: Optional[str] = None,
        db_path: Optional[str] = None,
    ):
        """
        初始化缓存管理器

        Args:
            project_root: 项目根目录
            cache_dir: 缓存目录路径，如果为 None 则使用全局缓存目录
            db_path: 数据库文件完整路径，如果指定则忽略 cache_dir
        """
        self.project_root = Path(project_root).resolve()

        if db_path:
            # 直接指定数据库路径
            self.db_path = Path(db_path)
        else:
            # 使用缓存目录 + 生成的文件名
            if cache_dir:
                cache_directory = Path(cache_dir)
            else:
                cache_directory = Path(get_cache_dir())

            # 确保缓存目录存在
            cache_directory.mkdir(parents=True, exist_ok=True)

            # 生成缓存文件名
            cache_filename = generate_cache_filename(project_root)
            self.db_path = cache_directory / cache_filename

        self._init_db()
        _get_logger().debug(f"初始化 SQLite 缓存: {self.db_path}")

    def _init_db(self):
        """初始化数据库表结构"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 创建文件缓存表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_cache (
                    file_path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_code TEXT NOT NULL
                )
            """)

            # 创建符号索引表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS symbol_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    start_col INTEGER NOT NULL,
                    end_col INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    host_class TEXT,
                    callees TEXT,
                    imports TEXT,
                    base_classes TEXT,
                    calls_super INTEGER DEFAULT 0,
                    UNIQUE(name, file_path, start_line, node_type)
                )
            """)

            # 尝试添加新列（用于升级旧数据库）
            try:
                cursor.execute("ALTER TABLE symbol_index ADD COLUMN base_classes TEXT")
            except sqlite3.OperationalError:
                pass  # 列已存在

            try:
                cursor.execute(
                    "ALTER TABLE symbol_index ADD COLUMN calls_super INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass  # 列已存在

            # 创建索引以加速查询
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol_name 
                ON symbol_index(name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol_file 
                ON symbol_index(file_path)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_symbol_type 
                ON symbol_index(node_type)
            """)

            # 创建元数据表，记录索引状态
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _compute_hash(self, content: str) -> str:
        """计算内容的哈希值"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    # ==================== 文件缓存操作 ====================

    def get_file_cache(self, file_path: str) -> Optional[Tuple[float, str, str]]:
        """
        获取文件缓存

        Returns:
            (mtime, content_hash, source_code) 或 None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT mtime, content_hash, source_code 
                FROM file_cache 
                WHERE file_path = ?
                """,
                (file_path,),
            )
            row = cursor.fetchone()
            if row:
                return (row["mtime"], row["content_hash"], row["source_code"])
            return None

    def set_file_cache(self, file_path: str, mtime: float, source_code: str):
        """设置文件缓存"""
        content_hash = self._compute_hash(source_code)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO file_cache 
                (file_path, mtime, content_hash, source_code)
                VALUES (?, ?, ?, ?)
                """,
                (file_path, mtime, content_hash, source_code),
            )
            conn.commit()

    def is_file_cache_valid(self, file_path: str, current_mtime: float) -> bool:
        """检查文件缓存是否有效"""
        cache = self.get_file_cache(file_path)
        if cache is None:
            return False
        cached_mtime, _, _ = cache
        return cached_mtime == current_mtime

    def remove_file_cache(self, file_path: str):
        """移除文件缓存"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM file_cache WHERE file_path = ?",
                (file_path,),
            )
            conn.commit()

    # ==================== 符号索引操作 ====================

    def add_symbol(self, symbol_data: Dict[str, Any]):
        """
        添加符号到索引

        Args:
            symbol_data: 符号数据字典，包含以下字段：
                - name, node_type, start_line, end_line, start_col, end_col
                - content, file_path, host_class, callees, imports
                - base_classes, calls_super
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO symbol_index 
                (name, node_type, start_line, end_line, start_col, end_col, 
                 content, file_path, host_class, callees, imports,
                 base_classes, calls_super)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol_data["name"],
                    symbol_data["node_type"],
                    symbol_data["start_line"],
                    symbol_data["end_line"],
                    symbol_data["start_col"],
                    symbol_data["end_col"],
                    symbol_data["content"],
                    symbol_data["file_path"],
                    symbol_data.get("host_class"),
                    json.dumps(symbol_data.get("callees", [])),
                    json.dumps(symbol_data.get("imports", {})),
                    json.dumps(symbol_data.get("base_classes", [])),
                    1 if symbol_data.get("calls_super", False) else 0,
                ),
            )
            conn.commit()

    def add_symbols_batch(self, symbols: List[Dict[str, Any]]):
        """批量添加符号到索引"""
        if not symbols:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT OR REPLACE INTO symbol_index 
                (name, node_type, start_line, end_line, start_col, end_col, 
                 content, file_path, host_class, callees, imports,
                 base_classes, calls_super)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s["name"],
                        s["node_type"],
                        s["start_line"],
                        s["end_line"],
                        s["start_col"],
                        s["end_col"],
                        s["content"],
                        s["file_path"],
                        s.get("host_class"),
                        json.dumps(s.get("callees", [])),
                        json.dumps(s.get("imports", {})),
                        json.dumps(s.get("base_classes", [])),
                        1 if s.get("calls_super", False) else 0,
                    )
                    for s in symbols
                ],
            )
            conn.commit()

    def find_symbols_by_name(
        self,
        name: str,
        symbol_type: Optional[str] = None,
        file_hint: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        根据名称查找符号

        Args:
            name: 符号名称
            symbol_type: 可选，"class"、"function" 或 "method"
            file_hint: 可选，优先返回匹配此文件的符号

        Returns:
            符号数据列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM symbol_index WHERE name = ?"
            params: List[Any] = [name]

            if symbol_type:
                if symbol_type == "function":
                    query += " AND node_type IN ('function', 'method')"
                else:
                    query += " AND node_type = ?"
                    params.append(symbol_type)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for row in rows:
                results.append(self._row_to_symbol_dict(row))

            # 如果有文件提示，优先排序
            if file_hint and results:
                results.sort(key=lambda x: 0 if file_hint in x["file_path"] else 1)

            return results

    def find_symbols_by_file(self, file_path: str) -> List[Dict[str, Any]]:
        """获取文件中的所有符号"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM symbol_index WHERE file_path = ?",
                (file_path,),
            )
            rows = cursor.fetchall()
            return [self._row_to_symbol_dict(row) for row in rows]

    def get_all_symbols(
        self, symbol_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取所有符号

        Args:
            symbol_type: 可选，"class"、"function" 或 "method"

        Returns:
            符号数据列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if symbol_type:
                if symbol_type == "function":
                    cursor.execute(
                        "SELECT * FROM symbol_index WHERE node_type IN ('function', 'method')"
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM symbol_index WHERE node_type = ?",
                        (symbol_type,),
                    )
            else:
                cursor.execute("SELECT * FROM symbol_index")

            rows = cursor.fetchall()
            return [self._row_to_symbol_dict(row) for row in rows]

    def remove_symbols_by_file(self, file_path: str):
        """移除文件的所有符号"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM symbol_index WHERE file_path = ?",
                (file_path,),
            )
            conn.commit()

    def _row_to_symbol_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为符号字典"""
        # 安全获取可能不存在的列（兼容旧数据库）
        base_classes_raw = row["base_classes"] if "base_classes" in row.keys() else None
        calls_super_raw = row["calls_super"] if "calls_super" in row.keys() else 0

        return {
            "name": row["name"],
            "node_type": row["node_type"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "start_col": row["start_col"],
            "end_col": row["end_col"],
            "content": row["content"],
            "file_path": row["file_path"],
            "host_class": row["host_class"],
            "callees": json.loads(row["callees"]) if row["callees"] else [],
            "imports": json.loads(row["imports"]) if row["imports"] else {},
            "base_classes": json.loads(base_classes_raw) if base_classes_raw else [],
            "calls_super": bool(calls_super_raw),
        }

    # ==================== 元数据操作 ====================

    def is_indexed(self) -> bool:
        """检查是否已建立索引"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM metadata WHERE key = 'indexed'")
            row = cursor.fetchone()
            return row is not None and row["value"] == "true"

    def set_indexed(self, value: bool):
        """设置索引状态"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO metadata (key, value) 
                VALUES ('indexed', ?)
                """,
                ("true" if value else "false",),
            )
            conn.commit()

    def get_indexed_file_count(self) -> int:
        """获取已索引的文件数量"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT file_path) FROM symbol_index")
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_symbol_count(self) -> Tuple[int, int]:
        """
        获取符号数量

        Returns:
            (class_count, function_count)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM symbol_index WHERE node_type = 'class'"
            )
            class_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM symbol_index WHERE node_type IN ('function', 'method')"
            )
            func_count = cursor.fetchone()[0]

            return class_count, func_count

    # ==================== 清理操作 ====================

    def clear_all(self):
        """清空所有缓存数据"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM file_cache")
            cursor.execute("DELETE FROM symbol_index")
            cursor.execute("DELETE FROM metadata")
            conn.commit()
        _get_logger().info("已清空所有缓存数据")

    def clear_symbols(self):
        """清空符号索引"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM symbol_index")
            cursor.execute("DELETE FROM metadata WHERE key = 'indexed'")
            conn.commit()
        _get_logger().debug("已清空符号索引")

    def vacuum(self):
        """压缩数据库文件"""
        with self._get_connection() as conn:
            conn.execute("VACUUM")
        _get_logger().debug("数据库已压缩")
