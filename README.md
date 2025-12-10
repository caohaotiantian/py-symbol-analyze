# Python Symbol Analyzer MCP Server

一个基于 MCP (Model Context Protocol) 的 Python 代码符号分析服务器，使用 tree-sitter 进行语法解析，使用 jedi 进行符号解析。

## 功能特性

- **查询类信息**: 获取类的完整源代码及其依赖的其他类/函数
- **查询函数信息**: 获取函数的完整源代码及其依赖（支持模块级函数和类方法）
- **依赖分析**: 自动分析并返回符号所依赖的其他符号的完整内容
- **父类依赖**: 自动解析 `super()` 调用，返回父类的完整内容
- **符号索引**: 快速构建和查询项目级符号索引
- **SQLite 缓存**: 使用 SQLite 持久化存储符号索引，提升查询性能

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

## 快速开始

```bash
# 安装后直接运行（默认使用 SSE 模式，端口 8000）
py-symbol-analyze

# 指定端口
py-symbol-analyze --port 9000

# 指定地址和端口
py-symbol-analyze --host 0.0.0.0 --port 8080

# 指定缓存目录
py-symbol-analyze --cache-dir /var/cache/py-symbol-analyze
```

服务启动后，可以通过以下端点访问：

- 健康检查: http://127.0.0.1:8000/health
- 服务器信息: http://127.0.0.1:8000/info
- SSE 端点: http://127.0.0.1:8000/sse
- 消息端点: http://127.0.0.1:8000/messages

## 传输模式

服务器支持两种传输模式：

### 1. SSE 模式（默认）

HTTP SSE (Server-Sent Events) 流式传输模式，适用于远程调用或 Web 集成。

```bash
# 启动 SSE 模式（默认）
py-symbol-analyze

# 指定端口
py-symbol-analyze --port 9000

# 指定地址和端口
py-symbol-analyze --host 0.0.0.0 --port 8080
```

#### HTTP 端点

| 端点        | 方法 | 描述         |
| ----------- | ---- | ------------ |
| `/health`   | GET  | 健康检查     |
| `/info`     | GET  | 服务器信息   |
| `/sse`      | GET  | SSE 连接端点 |
| `/messages` | POST | MCP 消息端点 |

### 2. stdio 模式

标准输入输出模式，适用于与 IDE 或桌面应用集成。

```bash
# 启动 stdio 模式
py-symbol-analyze --transport stdio
```

#### 命令行参数

```
usage: py-symbol-analyze [-h] [--transport {stdio,sse}]
                         [--host HOST] [--port PORT]
                         [--log-dir LOG_DIR] [--cache-dir CACHE_DIR]

参数:
  --transport, -t    传输方式: sse (默认) 或 stdio
  --host, -H         SSE 模式监听地址 (默认: 127.0.0.1)
  --port, -p         SSE 模式监听端口 (默认: 8000)
  --log-dir, -l      日志文件存储目录 (默认: 当前目录下的 logs 文件夹)
  --cache-dir, -c    符号缓存存储目录 (默认: 当前目录下的 cache 文件夹)
```

## 配置 MCP

### 方式一：HTTP 模式配置（推荐）

首先启动 HTTP 服务器：

```bash
# 默认方式启动
py-symbol-analyze

# 或指定端口
py-symbol-analyze --port 8000
```

然后在 MCP 客户端配置中使用 SSE 连接：

```json
{
  "mcpServers": {
    "py-symbol-analyze": {
      "transport": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

### 方式二：stdio 模式配置

#### Cursor 配置

在 `~/.cursor/mcp.json` 中添加：

```json
{
  "mcpServers": {
    "py-symbol-analyze": {
      "command": "python",
      "args": ["-m", "py_symbol_analyze.server", "--transport", "stdio"],
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
      "args": [
        "run",
        "python",
        "-m",
        "py_symbol_analyze.server",
        "--transport",
        "stdio"
      ],
      "cwd": "/path/to/py_symbol_analyze"
    }
  }
}
```

#### Claude Desktop 配置

在 `~/Library/Application Support/Claude/claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "py-symbol-analyze": {
      "command": "python",
      "args": ["-m", "py_symbol_analyze.server", "--transport", "stdio"],
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
  "depends": ["class BaseClass:\n    ..."],
  "depends_path": ["/path/to/project/base.py"]
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
  "depends": ["def helper():\n    ..."],
  "depends_path": ["/path/to/project/utils.py"]
}
```

**注意:** 如果方法中调用了 `super().__init__()` 等父类方法，依赖中会自动包含父类的完整内容。

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

### 场景三：查询类方法的依赖（包含父类）

```
使用 query_function 工具:
- project_root: /path/to/your/python/project
- function_name: __init__
- host_class: ChildClass
```

如果 `ChildClass.__init__` 中调用了 `super().__init__()`，返回结果的 `depends` 中会包含父类的完整内容。

## 缓存配置

符号索引使用 SQLite 数据库进行持久化存储，提升重复查询的性能。

### 缓存文件位置

默认缓存文件保存在**当前工作目录**下的 `cache/` 文件夹中，每个项目使用独立的数据库文件：

```
./cache/
├── my_project_a1b2c3d4e5f6.db   # 项目 my_project 的缓存
└── another_proj_f6e5d4c3b2a1.db # 项目 another_proj 的缓存
```

文件命名格式: `{项目名}_{项目路径MD5哈希}.db`

### 自定义缓存目录

可以通过命令行参数 `--cache-dir` 指定缓存存储目录：

```bash
# 指定缓存目录
py-symbol-analyze --cache-dir /var/cache/py-symbol-analyze

# 或者使用短参数
py-symbol-analyze -c /tmp/my-cache
```

### 清空缓存

如果需要清空缓存重建索引，可以：

1. 删除缓存目录下的 `.db` 文件
2. 或调用 `rebuild_index` 工具强制重建

```bash
# 删除所有缓存
rm -rf cache/*.db
```

## 日志配置

项目运行时会自动记录日志，同时输出到控制台和本地文件。

### 日志文件位置

默认日志文件保存在**当前工作目录**下的 `logs/` 文件夹中，按日期命名：

```
./logs/
├── py_symbol_analyze.server_20251209.log   # 服务器日志
├── py_symbol_analyze.parser_20251209.log   # 解析器日志
├── py_symbol_analyze.cache_20251209.log    # 缓存日志
└── py_symbol_analyze.resolver_20251209.log # 依赖解析日志
```

### 自定义日志目录

可以通过命令行参数 `--log-dir` 指定日志存储目录：

```bash
# 指定日志目录
py-symbol-analyze --log-dir /var/log/py-symbol-analyze

# 或者使用短参数
py-symbol-analyze -l /tmp/my-logs
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

### 通过代码自定义日志配置

```python
from py_symbol_analyze.logger import set_log_dir, setup_logger
from pathlib import Path
import logging

# 方法1：设置全局日志目录（推荐）
set_log_dir("/custom/log/path")

# 方法2：创建自定义日志记录器
logger = setup_logger(
    name="py_symbol_analyze",
    level=logging.DEBUG,           # 设置 DEBUG 级别
    log_dir=Path("/custom/path"),  # 自定义日志目录
    console_output=True,           # 是否输出到控制台
    file_output=True,              # 是否输出到文件
    max_file_size=10 * 1024 * 1024,  # 单个文件最大 10MB
    backup_count=5,                # 保留 5 个备份文件
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
- **SQLite**: 用于持久化存储符号索引缓存
- **pydantic**: 用于数据模型定义和验证
- **MCP SDK**: 实现标准 MCP 协议
- **Starlette + Uvicorn**: HTTP/SSE 传输支持
- **SSE (Server-Sent Events)**: 流式传输协议

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
│       ├── cache.py         # SQLite 缓存管理
│       ├── models.py        # 数据模型定义
│       └── logger.py        # 日志配置模块
├── tests/                   # 测试用例
├── pyproject.toml           # 项目配置
├── requirements.txt         # 依赖列表
└── README.md               # 说明文档
```
