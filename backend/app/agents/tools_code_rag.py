"""
CodeRAG Tool - Agentic RAG 语义检索工具

当 ArchitectAgent 遇到以下情况时自动调用：
1. 用户需求不明确，无法确定相关文件
2. 项目树中没有匹配的文件
3. 需要理解代码语义而不仅是文件名

特性：
- 混合检索（关键词 + 向量相似度）
- 两阶段检索（签名 + 完整实现）
- 智能上下文组装
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from app.service.code_indexer import get_indexer, CodeIndexerService

logger = logging.getLogger(__name__)


@dataclass
class CodeRAGResult:
    """CodeRAG 检索结果"""
    query: str
    semantic_results: str  # 格式化的语义检索结果
    full_files: Dict[str, str]  # 完整文件内容
    file_summaries: List[Dict[str, Any]]  # 文件摘要
    related_chunks: List[Dict[str, Any]]  # 相关代码块
    confidence: float  # 检索置信度 (0-1)


class CodeRAGTool:
    """
    CodeRAG 语义检索工具
    
    为 ArchitectAgent 提供智能代码检索能力
    """

    def __init__(self, project_path: str):
        self.project_path = project_path
        self._indexer: Optional[CodeIndexerService] = None

    async def _get_indexer(self) -> Optional[CodeIndexerService]:
        """获取或创建索引服务（带缓存，避免重复构建）"""
        if self._indexer is None:
            try:
                self._indexer = await get_indexer(self.project_path, include_tests=False)
                # 仅当索引未缓存时才构建
                if not self._indexer.chunks:
                    self._indexer.build_index()
            except Exception as e:
                logger.warning(f"[CodeRAGTool] 初始化索引失败: {e}")
                return None
        return self._indexer

    async def search(
        self,
        query: str,
        top_k: int = 5,
        include_full_content: bool = True
    ) -> Optional[CodeRAGResult]:
        """
        执行语义检索

        Args:
            query: 查询需求（如"健康检查接口"）
            top_k: 返回前 k 个相关结果
            include_full_content: 是否包含完整文件内容

        Returns:
            CodeRAGResult: 检索结果，如果失败返回 None
        """
        indexer = await self._get_indexer()
        if not indexer:
            logger.warning("[CodeRAGTool] 索引服务不可用")
            return None

        try:
            # 执行 CodeRAG 检索
            results = await indexer.get_related_files_full_content(
                query=query,
                top_k=top_k,
                include_related=True
            )

            if not results.get("full_files"):
                logger.info(f"[CodeRAGTool] 未找到与 '{query}' 相关的代码")
                return None

            # 计算置信度（基于相关文件数量和质量）
            confidence = self._calculate_confidence(results, top_k)

            return CodeRAGResult(
                query=query,
                semantic_results=results.get("semantic_results", ""),
                full_files=results.get("full_files", {}),
                file_summaries=results.get("file_summaries", []),
                related_chunks=results.get("related_chunks", []),
                confidence=confidence
            )

        except Exception as e:
            logger.error(f"[CodeRAGTool] 检索失败: {e}")
            return None

    def _calculate_confidence(
        self,
        results: Dict[str, Any],
        top_k: int
    ) -> float:
        """
        计算检索结果的置信度

        Args:
            results: 检索结果
            top_k: 期望的结果数

        Returns:
            float: 置信度 (0-1)
        """
        full_files = results.get("full_files", {})
        related_chunks = results.get("related_chunks", [])

        if not full_files:
            return 0.0

        # 基于找到的文件数量和期望数量的比例
        file_ratio = min(len(full_files) / top_k, 1.0)

        # 基于代码块数量
        chunk_ratio = min(len(related_chunks) / (top_k * 2), 1.0)

        # 综合置信度
        confidence = (file_ratio * 0.6 + chunk_ratio * 0.4)

        return round(confidence, 2)

    def format_results_for_prompt(self, result: CodeRAGResult) -> str:
        """
        将检索结果格式化为 Prompt 可用的字符串

        Args:
            result: CodeRAG 检索结果

        Returns:
            str: 格式化的上下文字符串
        """
        sections = []

        # 1. 检索概览
        sections.append(f"【CodeRAG 语义检索结果】")
        sections.append(f"查询: {result.query}")
        sections.append(f"置信度: {result.confidence}")
        sections.append(f"找到 {len(result.full_files)} 个相关文件\n")

        # 2. 文件摘要
        sections.append("【相关文件摘要】")
        for summary in result.file_summaries[:5]:  # 最多显示5个
            file_path = summary.get("file_path", "")
            total_lines = summary.get("total_lines", 0)
            sections.append(f"- {file_path} ({total_lines} 行)")
        sections.append("")

        # 3. 语义检索详情
        if result.semantic_results:
            sections.append("【语义匹配的代码片段】")
            sections.append(result.semantic_results[:2000])  # 限制长度
            sections.append("")

        # 4. 完整文件内容（可选）
        if result.full_files:
            sections.append("【完整文件内容】")
            for file_path, content in list(result.full_files.items())[:3]:  # 最多3个
                sections.append(f"\n--- {file_path} ---")
                # 限制每个文件的内容长度
                lines = content.splitlines()
                if len(lines) > 50:
                    content = "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} 行省略)"
                sections.append(content)

        return "\n".join(sections)


class CodeRAGToolWrapper:
    """
    CodeRAG Tool 包装器 - 适配 ToolUsingAgent 的工具调用格式
    """

    def __init__(self, project_path: str):
        self.tool = CodeRAGTool(project_path)

    def get_tool_definition(self) -> Dict[str, Any]:
        """
        获取工具定义（用于 ToolUsingAgent）

        Returns:
            Dict: 工具定义
        """
        return {
            "type": "function",
            "function": {
                "name": "code_rag_search",
                "description": "使用语义检索（CodeRAG）查找与需求相关的代码。当需求不明确、项目树中没有匹配文件、或需要理解代码语义时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询，应该是对用户需求的简洁描述（如'健康检查接口'、'用户认证逻辑'）"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回的相关文件数量（默认5，范围1-10）",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 10
                        }
                    },
                    "required": ["query"]
                }
            }
        }

    async def execute(self, params: Dict[str, Any]) -> str:
        """
        执行工具调用

        Args:
            params: 工具参数

        Returns:
            str: 工具执行结果（JSON 格式）
        """
        query = params.get("query", "")
        top_k = params.get("top_k", 5)

        if not query:
            return json.dumps({
                "success": False,
                "error": "查询不能为空"
            })

        result = await self.tool.search(query, top_k)

        if not result:
            return json.dumps({
                "success": False,
                "error": f"未找到与 '{query}' 相关的代码"
            })

        return json.dumps({
            "success": True,
            "query": result.query,
            "confidence": result.confidence,
            "files_found": len(result.full_files),
            "context": self.tool.format_results_for_prompt(result)
        })


# 智能触发判断函数
def should_use_code_rag(
    requirement: str,
    file_tree: Dict[str, Any],
    min_tree_match_score: float = 0.3
) -> bool:
    """
    判断是否应使用 CodeRAG

    触发条件：
    1. 需求中包含模糊关键词（如"监控"、"管理"、"处理"等）
    2. 项目树中没有明显匹配的文件
    3. 需求描述较复杂，需要语义理解

    Args:
        requirement: 用户需求
        file_tree: 项目文件树
        min_tree_match_score: 最小匹配分数阈值

    Returns:
        bool: 是否应使用 CodeRAG
    """
    # 1. 检查模糊关键词
    vague_keywords = [
        "监控", "管理", "处理", "服务", "组件", "模块",
        "monitor", "manage", "process", "service", "component", "module"
    ]

    has_vague_keyword = any(
        keyword in requirement.lower()
        for keyword in vague_keywords
    )

    # 2. 计算项目树匹配分数
    tree_match_score = _calculate_tree_match(requirement, file_tree)

    # 3. 判断逻辑
    # - 如果有模糊关键词且项目树匹配度低，使用 CodeRAG
    # - 或者项目树匹配度极低（< 0.2），使用 CodeRAG
    if has_vague_keyword and tree_match_score < min_tree_match_score:
        return True

    if tree_match_score < 0.2:
        return True

    return False


def _calculate_tree_match(
    requirement: str,
    file_tree: Dict[str, Any]
) -> float:
    """
    计算需求与项目树的匹配分数

    Args:
        requirement: 用户需求
        file_tree: 项目文件树

    Returns:
        float: 匹配分数 (0-1)
    """
    if not file_tree:
        return 0.0

    req_lower = requirement.lower()
    req_keywords = set(req_lower.split())

    # 收集文件树中的所有文件名
    file_names = []

    def collect_files(tree: Dict[str, Any], prefix: str = ""):
        for name, value in tree.items():
            full_path = f"{prefix}/{name}" if prefix else name
            if isinstance(value, dict):
                collect_files(value, full_path)
            else:
                file_names.append(full_path.lower())

    collect_files(file_tree)

    if not file_names:
        return 0.0

    # 计算匹配度
    matches = 0
    for keyword in req_keywords:
        if len(keyword) < 3:  # 忽略短词
            continue
        for file_name in file_names:
            if keyword in file_name:
                matches += 1
                break

    # 匹配分数 = 匹配的关键词数 / 总关键词数
    meaningful_keywords = [k for k in req_keywords if len(k) >= 3]
    if not meaningful_keywords:
        return 0.0

    return matches / len(meaningful_keywords)
