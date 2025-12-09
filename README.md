# Python Symbol Analyzer MCP Server

一个基于 MCP (Model Context Protocol) 的 Python 代码符号分析服务器，使用 tree-sitter 进行语法解析，使用 jedi 进行符号解析。

## 功能特性

- **查询类信息**: 获取类的完整源代码及其依赖的其他类/函数
- **查询函数信息**: 获取函数的完整源代码及其依赖（支持模块级函数和类方法）
- **依赖分析**: 自动分析并返回符号所依赖的其他符号的完整内容
- **符号索引**: 快速构建和查询项目级符号索引

## 安装

### 使用 pip

```bash
cd py_symbol_analyze
pip install -e .
```

### 使用 uv

```bash
cd py_symbol_analyze
uv pip install -e .
```

## 配置 MCP

### Cursor 配置

在 `~/.cursor/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "py-symbol-analyze": {
      "command": "python",
      "args": ["-m", "py_symbol_analyze.server"],
      "cwd": "/path/to/py_symbol_analyze"
    }
  }
}
```

或者如果你使用 uv：

```json
{
  "mcpServers": {
    "py-symbol-analyze": {
      "command": "uv",
      "args": ["run", "python", "-m", "py_symbol_analyze.server"],
      "cwd": "/path/to/py_symbol_analyze"
    }
  }
}
```

### Claude Desktop 配置

在 `~/Library/Application Support/Claude/claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "py-symbol-analyze": {
      "command": "python",
      "args": ["-m", "py_symbol_analyze.server"],
      "cwd": "/path/to/py_symbol_analyze"
    }
  }
}
```

## 可用工具

### 1. query_class

查询 Python 类的内容和依赖关系。

**参数:**
- `project_root` (必需): Python 项目的根目录路径
- `class_name` (必需): 要查询的类名
- `file_path` (可选): 类所在的文件路径，用于精确定位

**返回示例:**
```json
{
    "node_type": "class",
    "class_content": "class MyClass:\n    def __init__(self):\n        pass",
    "file_path": "/path/to/project/module.py",
    "depends": [
        "class BaseClass:\n    ..."
    ],
    "depends_path": [
        "/path/to/project/base.py"
    ]
}
```

### 2. query_function

查询 Python 函数的内容和依赖关系。

**参数:**
- `project_root` (必需): Python 项目的根目录路径
- `function_name` (必需): 要查询的函数名
- `file_path` (可选): 函数所在的文件路径，用于精确定位
- `host_class` (可选): 如果是类方法，指定所属的类名

**返回示例:**
```json
{
    "node_type": "func",
    "function_content": "def my_function():\n    return helper()",
    "host_class": null,
    "file_path": "/path/to/project/module.py",
    "depends": [
        "def helper():\n    ..."
    ],
    "depends_path": [
        "/path/to/project/utils.py"
    ]
}
```

### 3. list_symbols

列出项目或文件中的所有类和函数。

**参数:**
- `project_root` (必需): Python 项目的根目录路径
- `file_path` (可选): 如果指定，只列出该文件中的符号

### 4. rebuild_index

重建项目的符号索引。当项目文件发生变化后使用。

**参数:**
- `project_root` (必需): Python 项目的根目录路径

## 使用示例

### 场景一：查询类的依赖

```
使用 query_class 工具:
- project_root: /path/to/your/python/project
- class_name: AsyncOBSUtil
```

### 场景二：查询模块级函数的依赖

```
使用 query_function 工具:
- project_root: /path/to/your/python/project
- function_name: init_db_connections
```

### 场景三：查询类方法的依赖

```
使用 query_function 工具:
- project_root: /path/to/your/python/project
- function_name: __init__
- host_class: InterruptException
```

## 日志配置

项目运行时会自动记录日志，同时输出到控制台和本地文件。

### 日志文件位置

日志文件保存在 `~/.py_symbol_analyze/logs/` 目录下，按日期命名：

```
~/.py_symbol_analyze/logs/
├── py_symbol_analyze_20251209.log      # 主日志
├── py_symbol_analyze.parser_20251209.log   # 解析器日志
└── py_symbol_analyze.resolver_20251209.log # 解析器日志
```

### 日志格式

**控制台输出格式:**
```
2025-12-09 09:51:14 | INFO     | py_symbol_analyze | 消息内容
```

**文件日志格式（包含更多调试信息）:**
```
2025-12-09 09:51:14 | INFO     | py_symbol_analyze | logger.py:84 | 消息内容
```

### 日志级别

默认日志级别为 INFO，记录以下内容：
- 服务器启动/关闭
- 工具调用请求
- 索引构建进度
- 符号查询结果
- 警告和错误信息

### 自定义日志配置

可以通过代码自定义日志配置：

```python
from py_symbol_analyze.logger import setup_logger
import logging

# 设置 DEBUG 级别以查看详细信息
logger = setup_logger(
    name="py_symbol_analyze",
    level=logging.DEBUG,
    log_dir=Path("/custom/log/path"),  # 自定义日志目录
    console_output=True,   # 是否输出到控制台
    file_output=True,      # 是否输出到文件
    max_file_size=10 * 1024 * 1024,  # 单个文件最大 10MB
    backup_count=5,        # 保留 5 个备份文件
)
```

### 日志轮转

日志文件支持自动轮转：
- 单个文件最大 10MB
- 最多保留 5 个备份文件
- 超出后自动删除最旧的日志

## 技术实现

- **tree-sitter**: 用于快速、准确的 Python 语法解析
- **jedi**: 用于更精确的符号定义查找和类型推断
- **pydantic**: 用于数据模型定义和验证
- **MCP SDK**: 实现标准 MCP 协议

## 开发

### 运行测试

```bash
pytest
```

### 项目结构

```
py_symbol_analyze/
├── src/
│   └── py_symbol_analyze/
│       ├── __init__.py      # 包初始化
│       ├── server.py        # MCP Server 主入口
│       ├── parser.py        # tree-sitter 解析器
│       ├── resolver.py      # 符号解析和依赖分析
│       ├── models.py        # 数据模型定义
│       └── logger.py        # 日志配置模块
├── tests/                   # 测试用例
├── pyproject.toml           # 项目配置
├── requirements.txt         # 依赖列表
└── README.md               # 说明文档
```

## 许可证

MIT License

