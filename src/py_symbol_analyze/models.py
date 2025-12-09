"""
数据模型定义
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ClassAnalysisResult(BaseModel):
    """类分析结果"""

    node_type: Literal["class"] = "class"
    class_content: str = Field(..., description="类的完整内容")
    file_path: str = Field(..., description="类所在的文件路径")
    depends: List[str] = Field(default_factory=list, description="依赖的类或函数内容")
    depends_path: List[str] = Field(
        default_factory=list, description="依赖所在的文件路径"
    )


class FunctionAnalysisResult(BaseModel):
    """函数分析结果"""

    node_type: Literal["func"] = "func"
    function_content: str = Field(..., description="函数的完整内容")
    host_class: Optional[str] = Field(None, description="函数所属的类名（如果在类内）")
    file_path: str = Field(..., description="函数所在的文件路径")
    depends: List[str] = Field(default_factory=list, description="依赖的类或函数内容")
    depends_path: List[str] = Field(
        default_factory=list, description="依赖所在的文件路径"
    )


class SymbolLocation(BaseModel):
    """符号位置信息"""

    name: str
    file_path: str
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    node_type: str  # "class", "function", "method"
    host_class: Optional[str] = None  # 如果是方法，记录所属类


class Dependency(BaseModel):
    """依赖信息"""

    name: str
    qualified_name: Optional[str] = None
    file_path: Optional[str] = None
    content: Optional[str] = None
    is_class: bool = False
    host_class: Optional[str] = None
