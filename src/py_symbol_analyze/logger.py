"""
日志配置模块

提供统一的日志记录功能，支持控制台输出和文件保存。
"""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# 默认日志目录（当前工作目录下的 logs 文件夹）
DEFAULT_LOG_DIR = Path.cwd() / "logs"

# 全局日志目录配置（可通过 set_log_dir 修改）
_configured_log_dir: Optional[Path] = None

# 日志格式
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
FILE_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def set_log_dir(log_dir: Optional[str | Path]) -> Path:
    """
    设置全局日志目录

    Args:
        log_dir: 日志目录路径，None 表示使用默认目录

    Returns:
        设置后的日志目录路径
    """
    global _configured_log_dir
    if log_dir is None:
        _configured_log_dir = None
        return DEFAULT_LOG_DIR
    _configured_log_dir = Path(log_dir).resolve()
    return _configured_log_dir


def get_log_dir() -> Path:
    """
    获取当前日志目录

    Returns:
        当前配置的日志目录路径
    """
    return _configured_log_dir or DEFAULT_LOG_DIR


def setup_logger(
    name: str = "py_symbol_analyze",
    level: int = logging.INFO,
    log_dir: Optional[Path] = None,
    console_output: bool = True,
    file_output: bool = True,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    配置并返回日志记录器

    Args:
        name: 日志记录器名称
        level: 日志级别
        log_dir: 日志文件保存目录（None 则使用全局配置或默认目录）
        console_output: 是否输出到控制台
        file_output: 是否输出到文件
        max_file_size: 单个日志文件最大大小（字节）
        backup_count: 保留的日志文件数量

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 控制台输出
    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_formatter = logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # 文件输出
    if file_output:
        # 优先使用传入的 log_dir，其次使用全局配置，最后使用默认目录
        actual_log_dir = log_dir or get_log_dir()
        actual_log_dir.mkdir(parents=True, exist_ok=True)

        # 按日期命名日志文件
        log_file = actual_log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_formatter = logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 记录日志文件位置
        logger.info(f"日志文件保存位置: {log_file}")

    return logger


def get_logger(name: str = "py_symbol_analyze") -> logging.Logger:
    """
    获取日志记录器

    如果日志记录器尚未配置，会自动进行默认配置。

    Args:
        name: 日志记录器名称

    Returns:
        日志记录器
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # 自动配置
        setup_logger(name)
    return logger


# 模块级别的便捷方法
_default_logger: Optional[logging.Logger] = None


def _get_default_logger() -> logging.Logger:
    """获取默认日志记录器"""
    global _default_logger
    if _default_logger is None:
        _default_logger = setup_logger()
    return _default_logger


def debug(msg: str, *args, **kwargs):
    """记录 DEBUG 级别日志"""
    _get_default_logger().debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    """记录 INFO 级别日志"""
    _get_default_logger().info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    """记录 WARNING 级别日志"""
    _get_default_logger().warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    """记录 ERROR 级别日志"""
    _get_default_logger().error(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs):
    """记录 ERROR 级别日志并附带异常堆栈"""
    _get_default_logger().exception(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    """记录 CRITICAL 级别日志"""
    _get_default_logger().critical(msg, *args, **kwargs)
