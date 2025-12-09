"""
MCP Server 主入口

提供 Python 代码符号分析功能。
支持两种传输方式：
1. streamable-http - HTTP 流式传输（默认）
2. stdio - 标准输入输出
"""

import argparse
import json
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    TextContent,
    Tool,
)

from .logger import get_logger
from .resolver import SymbolAnalyzer

# 获取日志记录器
logger = get_logger("py_symbol_analyze.server")

# 默认配置
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# 全局分析器实例
_analyzer: Optional[SymbolAnalyzer] = None


def get_analyzer(project_root: str) -> SymbolAnalyzer:
    """获取或创建分析器实例"""
    global _analyzer
    if _analyzer is None or _analyzer.project_root != project_root:
        logger.info(f"创建新的分析器实例，项目路径: {project_root}")
        _analyzer = SymbolAnalyzer(project_root)
    return _analyzer


# 创建 MCP Server
server = Server("py-symbol-analyze")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用的工具"""
    return [
        Tool(
            name="query_class",
            description="""查询 Python 类的内容和依赖关系。

返回类的完整源代码内容，以及该类所依赖的其他类或函数的内容。
这对于理解一个类的完整上下文非常有用。

参数:
- project_root: Python 项目的根目录路径
- class_name: 要查询的类名
- file_path: (可选) 类所在的文件路径，用于精确定位

返回:
- node_type: "class"
- class_content: 类的完整源代码
- file_path: 类所在的文件路径
- depends: 依赖的类或函数的源代码列表
- depends_path: 依赖所在的文件路径列表""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {
                        "type": "string",
                        "description": "Python 项目的根目录路径",
                    },
                    "class_name": {"type": "string", "description": "要查询的类名"},
                    "file_path": {
                        "type": "string",
                        "description": "(可选) 类所在的文件路径，用于精确定位",
                    },
                },
                "required": ["project_root", "class_name"],
            },
        ),
        Tool(
            name="query_function",
            description="""查询 Python 函数的内容和依赖关系。

返回函数的完整源代码内容，以及该函数所依赖的其他类或函数的内容。
支持查询模块级函数和类内方法。

参数:
- project_root: Python 项目的根目录路径
- function_name: 要查询的函数名
- file_path: (可选) 函数所在的文件路径，用于精确定位
- host_class: (可选) 如果是类方法，指定所属的类名

返回:
- node_type: "func"
- function_content: 函数的完整源代码
- host_class: (如果是类方法) 所属类名
- file_path: 函数所在的文件路径
- depends: 依赖的类或函数的源代码列表
- depends_path: 依赖所在的文件路径列表""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {
                        "type": "string",
                        "description": "Python 项目的根目录路径",
                    },
                    "function_name": {
                        "type": "string",
                        "description": "要查询的函数名",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "(可选) 函数所在的文件路径，用于精确定位",
                    },
                    "host_class": {
                        "type": "string",
                        "description": "(可选) 如果是类方法，指定所属的类名",
                    },
                },
                "required": ["project_root", "function_name"],
            },
        ),
        Tool(
            name="rebuild_index",
            description="""重建项目的符号索引。

当项目文件发生变化后，可以调用此工具重新扫描并建立符号索引。

参数:
- project_root: Python 项目的根目录路径""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {
                        "type": "string",
                        "description": "Python 项目的根目录路径",
                    }
                },
                "required": ["project_root"],
            },
        ),
        Tool(
            name="list_symbols",
            description="""列出项目或文件中的所有类和函数。

可以用于浏览项目结构，了解有哪些可查询的符号。

参数:
- project_root: Python 项目的根目录路径
- file_path: (可选) 如果指定，只列出该文件中的符号

返回:
- classes: 类名列表
- functions: 函数名列表""",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_root": {
                        "type": "string",
                        "description": "Python 项目的根目录路径",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "(可选) 只列出该文件中的符号",
                    },
                },
                "required": ["project_root"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """处理工具调用"""
    logger.info(f"收到工具调用请求: {name}, 参数: {arguments}")
    try:
        if name == "query_class":
            result = await handle_query_class(arguments)
        elif name == "query_function":
            result = await handle_query_function(arguments)
        elif name == "rebuild_index":
            result = await handle_rebuild_index(arguments)
        elif name == "list_symbols":
            result = await handle_list_symbols(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
        logger.info(f"工具 {name} 执行成功")
        return result

    except KeyError as e:
        logger.error(f"Missing required parameter: {e}")
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": f"Missing required parameter: {e}",
                        "code": INVALID_PARAMS,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        ]
    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}", exc_info=True)
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {"error": str(e), "code": INTERNAL_ERROR},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        ]


async def handle_query_class(arguments: dict) -> list[TextContent]:
    """处理查询类的请求"""
    project_root = arguments["project_root"]
    class_name = arguments["class_name"]
    file_path = arguments.get("file_path")

    analyzer = get_analyzer(project_root)
    result = analyzer.query_class(class_name, file_path)

    if result is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": f"Class '{class_name}' not found in project",
                        "suggestion": "Please check the class name or try rebuilding the index with rebuild_index tool",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        ]

    return [
        TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))
    ]


async def handle_query_function(arguments: dict) -> list[TextContent]:
    """处理查询函数的请求"""
    project_root = arguments["project_root"]
    function_name = arguments["function_name"]
    file_path = arguments.get("file_path")
    host_class = arguments.get("host_class")

    analyzer = get_analyzer(project_root)
    result = analyzer.query_function(function_name, file_path, host_class)

    if result is None:
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "error": f"Function '{function_name}' not found in project",
                        "suggestion": "Please check the function name or try rebuilding the index with rebuild_index tool",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        ]

    return [
        TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))
    ]


async def handle_rebuild_index(arguments: dict) -> list[TextContent]:
    """处理重建索引的请求"""
    project_root = arguments["project_root"]

    analyzer = get_analyzer(project_root)
    analyzer.rebuild_index()

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "status": "success",
                    "message": f"Index rebuilt for project: {project_root}",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    ]


async def handle_list_symbols(arguments: dict) -> list[TextContent]:
    """处理列出符号的请求"""
    project_root = arguments["project_root"]
    file_path = arguments.get("file_path")

    analyzer = get_analyzer(project_root)

    if file_path:
        # 列出指定文件的符号
        classes, functions = analyzer.resolver.project_parser.get_file_symbols(
            file_path
        )
        result = {
            "file_path": file_path,
            "classes": [{"name": c.name, "line": c.start_line} for c in classes],
            "functions": [
                {"name": f.name, "line": f.start_line, "host_class": f.host_class}
                for f in functions
            ],
        }
    else:
        # 列出整个项目的符号
        analyzer.resolver.project_parser.build_index()
        index = analyzer.resolver.project_parser._symbol_index

        classes = []
        functions = []

        for name, symbols in index.items():
            for s in symbols:
                if s.node_type == "class":
                    classes.append(
                        {"name": s.name, "file_path": s.file_path, "line": s.start_line}
                    )
                else:
                    functions.append(
                        {
                            "name": s.name,
                            "file_path": s.file_path,
                            "line": s.start_line,
                            "host_class": s.host_class,
                        }
                    )

        result = {
            "project_root": project_root,
            "classes": classes,
            "functions": functions,
        }

    return [
        TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))
    ]


async def run_stdio_server():
    """运行 stdio 模式的 MCP Server"""
    logger.info("正在启动 Python Symbol Analyzer MCP Server (stdio 模式)...")
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP Server 已启动，等待连接...")
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )
    logger.info("MCP Server 已关闭")


def create_starlette_app():
    """创建 Starlette 应用，用于 HTTP 传输"""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route

    # SSE 传输 - 消息端点路径
    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        """处理 SSE 连接"""
        logger.info(f"收到 SSE 连接请求: {request.client}")
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )
        # 返回空响应以避免 NoneType 错误
        return Response()

    async def health_check(request):
        """健康检查端点"""
        return JSONResponse(
            {
                "status": "healthy",
                "server": "py-symbol-analyze",
                "transport": "sse",
            }
        )

    async def server_info(request):
        """服务器信息端点"""
        return JSONResponse(
            {
                "name": "py-symbol-analyze",
                "version": "0.1.0",
                "description": "Python Symbol Analyzer MCP Server",
                "transport": "sse",
                "endpoints": {
                    "sse": "/sse",
                    "messages": "/messages",
                },
                "tools": [
                    "query_class",
                    "query_function",
                    "list_symbols",
                    "rebuild_index",
                ],
            }
        )

    # CORS 中间件配置
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    # 创建 Starlette 应用
    # 注意：/messages 使用 Mount 因为 handle_post_message 是 ASGI 应用
    app = Starlette(
        debug=True,
        middleware=middleware,
        routes=[
            Route("/health", health_check, methods=["GET"]),
            Route("/info", server_info, methods=["GET"]),
            Route("/sse", handle_sse, methods=["GET"]),
            Mount("/messages", app=sse.handle_post_message),
        ],
    )

    return app


def run_http_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
):
    """
    运行 HTTP 模式的 MCP Server

    Args:
        host: 监听地址
        port: 监听端口
    """
    import uvicorn

    logger.info("正在启动 Python Symbol Analyzer MCP Server (SSE 模式)...")
    logger.info(f"监听地址: http://{host}:{port}")
    logger.info(f"SSE 端点: http://{host}:{port}/sse")
    logger.info(f"消息端点: http://{host}:{port}/messages")
    logger.info(f"健康检查: http://{host}:{port}/health")

    app = create_starlette_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    """主入口点"""
    import asyncio

    parser = argparse.ArgumentParser(
        description="Python Symbol Analyzer MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用 SSE 模式（默认）
  py-symbol-analyze

  # 指定端口
  py-symbol-analyze --port 9000

  # 指定地址和端口
  py-symbol-analyze --host 0.0.0.0 --port 8080

  # 使用 stdio 模式
  py-symbol-analyze --transport stdio
        """,
    )

    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "sse"],
        default="sse",
        help="传输方式: sse (默认) 或 stdio",
    )

    parser.add_argument(
        "--host",
        "-H",
        default=DEFAULT_HOST,
        help=f"SSE 模式监听地址 (默认: {DEFAULT_HOST})",
    )

    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"SSE 模式监听端口 (默认: {DEFAULT_PORT})",
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        asyncio.run(run_stdio_server())
    else:
        run_http_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
