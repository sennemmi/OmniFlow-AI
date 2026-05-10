"""
Code indexer cache and factory functions
"""

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

from app.service.code_indexer_models import CodeChunk, FileContext


class IndexerCache:
    """
    带 LRU 淘汰机制的索引器缓存
    
    特性：
    - 最大缓存数量限制（默认 10 个）
    - LRU 淘汰策略
    - 自动清理被移除索引器的资源
    - 线程安全
    """
    
    def __init__(self, max_size: int = 10):
        self._cache: OrderedDict[str, CodeIndexerService] = OrderedDict()
        self._locks: Dict[str, asyncio.Lock] = {}
        self._max_size = max_size
        self._global_lock = asyncio.Lock()
        self._last_access_time: Dict[str, float] = {}
    
    async def get(self, cache_key: str) -> Optional[CodeIndexerService]:
        """获取索引器，更新访问时间"""
        async with self._global_lock:
            if cache_key in self._cache:
                # 移动到末尾（最近使用）
                self._cache.move_to_end(cache_key)
                self._last_access_time[cache_key] = time.time()
                return self._cache[cache_key]
            return None
    
    async def set(self, cache_key: str, indexer: CodeIndexerService) -> asyncio.Lock:
        """设置索引器，如果超出限制则淘汰最久未使用的"""
        async with self._global_lock:
            if cache_key in self._cache:
                # 已存在，更新并移动到末尾
                self._cache.move_to_end(cache_key)
                self._cache[cache_key] = indexer
                self._last_access_time[cache_key] = time.time()
                return self._locks[cache_key]
            
            # 检查是否需要淘汰
            while len(self._cache) >= self._max_size:
                await self._evict_oldest()
            
            # 添加新索引器
            self._cache[cache_key] = indexer
            self._locks[cache_key] = asyncio.Lock()
            self._last_access_time[cache_key] = time.time()
            return self._locks[cache_key]
    
    async def _evict_oldest(self):
        """淘汰最久未使用的索引器"""
        if not self._cache:
            return
        
        # 获取最久未使用的 key
        oldest_key = next(iter(self._cache))
        oldest_indexer = self._cache[oldest_key]
        
        # 清理资源
        try:
            oldest_indexer.clear_cache()
            logger.info(f"[IndexerCache] 淘汰缓存: {oldest_key}")
        except Exception as e:
            logger.warning(f"[IndexerCache] 清理缓存失败 {oldest_key}: {e}")
        
        # 从缓存中移除
        self._cache.pop(oldest_key)
        self._locks.pop(oldest_key, None)
        self._last_access_time.pop(oldest_key, None)
    
    def get_lock(self, cache_key: str) -> asyncio.Lock:
        """获取指定索引器的锁，如果不存在返回新锁"""
        return self._locks.get(cache_key, asyncio.Lock())
    
    async def clear(self):
        """清除所有缓存"""
        async with self._global_lock:
            for indexer in self._cache.values():
                try:
                    indexer.clear_cache()
                except Exception as e:
                    logger.warning(f"[IndexerCache] 清理缓存失败: {e}")
            self._cache.clear()
            self._locks.clear()
            self._last_access_time.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "keys": list(self._cache.keys()),
            "last_access_times": self._last_access_time.copy()
        }


# 全局索引器缓存实例（最大缓存 10 个项目）
_indexer_cache_manager = IndexerCache(max_size=10)


async def get_indexer(project_path: str, include_tests: bool = False) -> CodeIndexerService:
    """
    获取或创建索引服务实例（带 LRU 缓存，线程安全）

    Args:
        project_path: 项目路径
        include_tests: 是否包含测试目录，默认为 False

    Returns:
        CodeIndexerService: 索引服务实例
    """
    cache_key = f"{project_path}:{include_tests}"
    
    # 尝试从缓存获取
    indexer = await _indexer_cache_manager.get(cache_key)
    if indexer is not None:
        return indexer
    
    # 创建新索引器并加入缓存
    indexer = CodeIndexerService(project_path, include_tests=include_tests)
    await _indexer_cache_manager.set(cache_key, indexer)
    return indexer


def get_indexer_lock(project_path: str, include_tests: bool = False) -> asyncio.Lock:
    """
    获取索引器的更新锁

    Args:
        project_path: 项目路径
        include_tests: 是否包含测试目录

    Returns:
        asyncio.Lock: 锁对象
    """
    cache_key = f"{project_path}:{include_tests}"
    return _indexer_cache_manager.get_lock(cache_key)


def clear_indexer_cache():
    """清除所有索引器缓存"""
    # 使用 asyncio.run_coroutine_threadsafe 或确保在事件循环中运行
    try:
        loop = asyncio.get_running_loop()
        # 如果在事件循环中，创建任务
        asyncio.create_task(_indexer_cache_manager.clear())
    except RuntimeError:
        # 不在事件循环中，使用新的事件循环
        asyncio.run(_indexer_cache_manager.clear())


def get_indexer_cache_stats() -> Dict[str, Any]:
    """获取索引器缓存统计信息"""
    return _indexer_cache_manager.get_stats()


# ==================== 【新增】RAG 目标文件获取函数 ====================

async def get_target_files_with_rag(
    design_output: Dict[str, Any],
    requirement: str,
    project_path: str,
    code_executor: Any = None
) -> Dict[str, str]:
    """
    使用 CodeRAG (语义检索) 智能获取目标文件

    结合:
    1. DesignerAgent 输出的 affected_files
    2. CodeRAG 语义搜索相关代码
    3. AST 分析文件依赖

    Args:
        design_output: DesignerAgent 的输出
        requirement: 原始需求描述
        project_path: 项目路径
        code_executor: CodeExecutorService 实例（可选，用于依赖分析）

    Returns:
        Dict[str, str]: 文件路径 -> 文件内容的映射
    """
    target_files = {}

    # 1. 从 DesignerAgent 输出获取文件
    affected_files = design_output.get("affected_files", [])
    function_changes = design_output.get("function_changes", [])

    all_files_to_read = set()

    # 添加 affected_files（统一使用正斜杠）
    for file_path in affected_files:
        normalized_path = file_path.replace("\\", "/")
        all_files_to_read.add(normalized_path)

    # 添加 function_changes 中的文件（统一使用正斜杠）
    for change in function_changes:
        file_path = change.get("file", "")
        if file_path:
            normalized_path = file_path.replace("\\", "/")
            all_files_to_read.add(normalized_path)

    # 2. 使用 CodeRAG 搜索相关代码
    if not all_files_to_read:
        # 如果没有指定文件，使用 CodeRAG 根据需求搜索
        print(f"   🔍 CodeRAG 根据需求搜索相关代码...")
        indexer = await get_indexer(project_path)
        search_results = await indexer.get_related_files_full_content(requirement, top_k=10)
        full_files = search_results.get("full_files", {})
        for file_path, content in full_files.items():
            # 统一使用正斜杠
            normalized_path = file_path.replace("\\", "/")
            # 转换为 backend/ 前缀的路径
            if not normalized_path.startswith("backend/"):
                normalized_path = f"backend/{normalized_path}"
            all_files_to_read.add(normalized_path)
            target_files[normalized_path] = content

    # 3. 使用 AST 分析依赖关系
    print(f"   🔍 AST 分析文件依赖...")
    if code_executor is None:
        from app.service.code_executor import CodeExecutorService
        code_executor = CodeExecutorService(project_path)

    for file_path in list(all_files_to_read):
        # file_path 已经是正斜杠格式（上面已转换）
        clean_path = file_path.replace("backend/", "")
        content = code_executor.get_file_content(clean_path)

        if content:
            target_files[file_path] = content
            logger.info(f"[get_target_files_with_rag] 成功读取: {file_path} (clean_path: {clean_path})")
        else:
            # 【诊断】记录读取失败
            logger.warning(f"[get_target_files_with_rag] 读取失败: {file_path} (clean_path: {clean_path})")
            # 【方案3】尝试备用路径格式
            # 如果去除 backend/ 失败，尝试保留 backend/ 的路径
            if not file_path.startswith("backend/"):
                alt_path = f"backend/{file_path}"
                alt_content = code_executor.get_file_content(alt_path)
                if alt_content:
                    target_files[file_path] = alt_content
                    logger.info(f"[get_target_files_with_rag] 备用路径成功: {file_path}")
                else:
                    logger.error(f"[get_target_files_with_rag] 所有路径尝试失败: {file_path}")
            else:
                logger.error(f"[get_target_files_with_rag] 文件不存在: {file_path}")

        if content:
            # 分析依赖并添加相关文件
            related_files = code_executor.analyze_dependencies(content, file_path)
            for related_file in related_files:
                # 统一使用正斜杠
                normalized_related = related_file.replace("\\", "/")
                if normalized_related not in target_files:
                    clean_related = normalized_related.replace("backend/", "")
                    related_content = code_executor.get_file_content(clean_related)
                    if related_content:
                        target_files[normalized_related] = related_content

    print(f"   📊 共收集 {len(target_files)} 个目标文件")
    # 【诊断】打印收集的文件列表
    for fp in target_files.keys():
        content_preview = target_files[fp][:50] if target_files[fp] else "(空)"
        print(f"      - {fp}: {content_preview}...")
    return target_files

