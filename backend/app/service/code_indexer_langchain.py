"""
代码库语义索引服务 - LangChain 重构版
使用 LangChain 生态简化实现

核心改进：
1. 使用 DirectoryLoader 自动加载文件（替代手写 os.walk）
2. 使用 RecursiveCharacterTextSplitter 分割代码（替代手写 AST 解析）
3. 使用 Chroma 向量存储（简化向量操作）
4. 使用 ParentDocumentRetriever 实现两层检索

依赖：
pip install langchain langchain-community chromadb tree-sitter tree-sitter-python
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from app.core.config import settings

# LangChain 导入
try:
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from langchain.text_splitter import RecursiveCharacterTextSplitter, Language
    from langchain_community.vectorstores import Chroma
    from langchain_community.embeddings import OpenAIEmbeddings
    from langchain.retrievers import ParentDocumentRetriever
    from langchain.storage import InMemoryStore
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    print("警告: LangChain 未安装，将回退到旧版 code_indexer")


@dataclass
class CodeSearchResult:
    """代码搜索结果"""
    file_path: str
    content: str
    score: float
    start_line: int = 0
    end_line: int = 0


class LangChainCodeIndexer:
    """
    基于 LangChain 的代码索引服务
    
    简化实现，核心功能：
    1. 自动加载项目文件
    2. 智能代码分割（支持 Python、JS、TS）
    3. 向量存储和检索
    4. 两层检索（代码块 → 完整文件）
    """
    
    def __init__(
        self,
        project_path: str,
        index_dir: Optional[str] = None,
        include_tests: bool = False
    ):
        """
        初始化索引服务
        
        Args:
            project_path: 目标项目路径
            index_dir: 索引缓存目录
            include_tests: 是否包含测试目录
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError("LangChain 未安装，请运行: pip install langchain langchain-community chromadb")
        
        self.project_path = Path(project_path)
        self.index_dir = Path(index_dir) if index_dir else self.project_path / ".omniflow_index"
        self.include_tests = include_tests
        
        # 初始化嵌入模型
        self.embeddings = self._create_embeddings()
        
        # 向量存储路径
        self.vector_db_path = self.index_dir / "langchain_vector_db"
        
        # 文档存储（用于 ParentDocumentRetriever）
        self.docstore = InMemoryStore()
        
        # 子文档存储（用于检索）
        self.child_vectorstore = None
        
        # 检索器
        self.retriever = None
        
    def _create_embeddings(self):
        """创建嵌入模型"""
        # 使用 OpenAI 嵌入（可通过 litellm 路由）
        # 安全访问配置
        use_modelscope = getattr(settings, 'USE_MODELSCOPE', True)
        return OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=settings.llm_api_key,
            openai_api_base=settings.llm_api_base if not use_modelscope else None
        )
    
    def _get_loader_kwargs(self) -> Dict[str, Any]:
        """获取 DirectoryLoader 参数"""
        # 全局跳过目录
        glob_ignore = [
            "**/.omniflow_index/**",
            "**/__pycache__/**",
            "**/.git/**",
            "**/node_modules/**",
            "**/.venv/**",
            "**/venv/**",
        ]
        
        if not self.include_tests:
            glob_ignore.extend([
                "**/tests/**",
                "**/test/**",
                "**/*_test.py",
                "**/test_*.py"
            ])
        
        return {
            "glob": "**/*.{py,js,ts,tsx,jsx}",
            "exclude": glob_ignore,
            "show_progress": True,
            "use_multithreading": True,
        }
    
    def _get_text_splitter(self, file_path: str) -> RecursiveCharacterTextSplitter:
        """
        根据文件类型获取合适的文本分割器
        
        Args:
            file_path: 文件路径
            
        Returns:
            RecursiveCharacterTextSplitter: 文本分割器
        """
        suffix = Path(file_path).suffix.lower()
        
        if suffix == '.py':
            # Python 代码使用 Python 特定的分割器
            return RecursiveCharacterTextSplitter.from_language(
                language=Language.PYTHON,
                chunk_size=1000,
                chunk_overlap=200
            )
        elif suffix in ['.js', '.jsx']:
            return RecursiveCharacterTextSplitter.from_language(
                language=Language.JS,
                chunk_size=1000,
                chunk_overlap=200
            )
        elif suffix in ['.ts', '.tsx']:
            return RecursiveCharacterTextSplitter.from_language(
                language=Language.TS,
                chunk_size=1000,
                chunk_overlap=200
            )
        else:
            # 通用分割器
            return RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=200,
                separators=["\nclass ", "\ndef ", "\nfunction ", "\n\n", "\n", " ", ""]
            )
    
    async def build_index(self, force_refresh: bool = False) -> bool:
        """
        构建代码索引
        
        Args:
            force_refresh: 强制刷新索引
            
        Returns:
            bool: 是否成功
        """
        try:
            # 检查是否已有索引且不需要刷新
            if not force_refresh and self.vector_db_path.exists():
                print("加载已有索引...")
                self._load_existing_index()
                return True
            
            print("构建代码索引...")
            
            # 1. 加载所有文件
            loader_kwargs = self._get_loader_kwargs()
            loader = DirectoryLoader(
                str(self.project_path),
                loader_cls=TextLoader,
                loader_kwargs={"encoding": "utf-8"},
                **loader_kwargs
            )
            
            documents = loader.load()
            print(f"加载了 {len(documents)} 个文件")
            
            if not documents:
                print("未找到可索引的文件")
                return False
            
            # 2. 创建父文档存储（完整文件）
            self.docstore = InMemoryStore()
            for doc in documents:
                self.docstore.mset([(doc.metadata["source"], doc)])
            
            # 3. 创建子文档（代码块）向量存储
            # 使用较小的 chunk 用于检索
            child_splitter = RecursiveCharacterTextSplitter(
                chunk_size=400,
                chunk_overlap=50,
                separators=["\nclass ", "\ndef ", "\nfunction ", "\n\n", "\n", " ", ""]
            )
            
            # 分割文档
            child_docs = []
            for doc in documents:
                splits = child_splitter.split_documents([doc])
                child_docs.extend(splits)
            
            print(f"分割为 {len(child_docs)} 个代码块")
            
            # 4. 创建向量存储
            self.child_vectorstore = Chroma.from_documents(
                documents=child_docs,
                embedding=self.embeddings,
                persist_directory=str(self.vector_db_path)
            )
            
            # 5. 创建 ParentDocumentRetriever
            # 父分割器（用于获取完整文件）
            parent_splitter = RecursiveCharacterTextSplitter(
                chunk_size=2000,  # 较大的块，接近完整文件
                chunk_overlap=0,
                separators=["\n\n", "\n", ""]
            )
            
            self.retriever = ParentDocumentRetriever(
                vectorstore=self.child_vectorstore,
                docstore=self.docstore,
                child_splitter=child_splitter,
                parent_splitter=parent_splitter,
                search_kwargs={"k": 10}
            )
            
            # 添加文档到检索器
            self.retriever.add_documents(documents)
            
            # 持久化向量存储
            self.child_vectorstore.persist()
            
            print(f"索引构建完成: {len(documents)} 个文件, {len(child_docs)} 个代码块")
            return True
            
        except Exception as e:
            print(f"构建索引失败: {e}")
            return False
    
    def _load_existing_index(self):
        """加载已有索引"""
        try:
            # 加载向量存储
            self.child_vectorstore = Chroma(
                persist_directory=str(self.vector_db_path),
                embedding_function=self.embeddings
            )
            
            # 重新创建检索器（docstore 需要重新填充）
            # 注意：这里简化处理，实际应该持久化 docstore
            print("注意：重新加载索引时，完整文件上下文可能需要重新构建")
            
        except Exception as e:
            print(f"加载索引失败: {e}")
    
    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        return_full_files: bool = True
    ) -> str:
        """
        语义搜索
        
        Args:
            query: 查询词
            top_k: 返回结果数量
            return_full_files: 是否返回完整文件内容
            
        Returns:
            str: 格式化的搜索结果
        """
        if not self.child_vectorstore:
            success = await self.build_index()
            if not success:
                return "索引构建失败，无法搜索"
        
        try:
            # 使用相似度搜索
            results = self.child_vectorstore.similarity_search_with_score(
                query=query,
                k=top_k
            )
            
            if not results:
                return "未找到相关代码片段"
            
            # 格式化结果
            formatted_results = []
            for i, (doc, score) in enumerate(results, 1):
                file_path = doc.metadata.get("source", "unknown")
                content = doc.page_content
                
                # 计算行号（粗略估计）
                lines_before = doc.metadata.get("start_index", 0)
                start_line = content[:lines_before].count("\n") + 1 if lines_before else 1
                end_line = start_line + content.count("\n")
                
                result_text = f"""--- 相关代码片段 #{i} (相似度: {1-score:.2f}) ---
文件: {file_path} (第 {start_line}-{end_line} 行)
```python
{content[:800]}{"..." if len(content) > 800 else ""}
```"""
                formatted_results.append(result_text)
            
            return "\n\n".join(formatted_results)
            
        except Exception as e:
            return f"搜索失败: {e}"
    
    async def get_related_files_full_content(
        self,
        query: str,
        top_k: int = 5,
        include_related: bool = True
    ) -> Dict[str, Any]:
        """
        获取与查询相关的完整文件内容
        
        Args:
            query: 查询词
            top_k: 返回代码块数量
            include_related: 是否包含相关文件
            
        Returns:
            Dict[str, Any]: 包含语义结果和完整文件内容
        """
        if not self.child_vectorstore:
            await self.build_index()
        
        try:
            # 1. 语义搜索获取代码块
            results = self.child_vectorstore.similarity_search_with_score(
                query=query,
                k=top_k
            )
            
            # 2. 获取相关文件
            related_files = {}
            file_paths_seen = set()
            
            for doc, score in results:
                file_path = doc.metadata.get("source", "")
                if file_path and file_path not in file_paths_seen:
                    # 读取完整文件
                    full_path = self.project_path / file_path
                    if full_path.exists():
                        try:
                            content = full_path.read_text(encoding="utf-8")
                            related_files[file_path] = content
                            file_paths_seen.add(file_path)
                        except Exception:
                            pass
            
            # 3. 生成文件摘要
            file_summaries = []
            for file_path, content in related_files.items():
                lines = content.splitlines()
                file_summaries.append({
                    "file_path": file_path,
                    "total_lines": len(lines),
                    "preview": "\n".join(lines[:30]) + ("\n..." if len(lines) > 30 else "")
                })
            
            # 4. 格式化语义结果
            semantic_results = await self.semantic_search(query, top_k, return_full_files=False)
            
            return {
                "success": True,
                "error": None,
                "related_code_context": semantic_results,
                "full_files_context": related_files,
                "file_summaries": file_summaries,
                "project_structure_summary": self.get_project_structure(),
                "related_chunks": [],
                "related_files": {}
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "related_code_context": None,
                "full_files_context": None,
                "file_summaries": [],
                "project_structure_summary": None,
                "related_chunks": [],
                "related_files": {}
            }
    
    def get_project_structure(self) -> str:
        """获取项目结构摘要"""
        try:
            py_files = list(self.project_path.rglob("*.py"))
            js_files = list(self.project_path.rglob("*.js"))
            ts_files = list(self.project_path.rglob("*.ts"))
            
            # 过滤跳过目录
            skip_patterns = ['.omniflow_index', '__pycache__', '.git', 'node_modules']
            py_files = [f for f in py_files if not any(p in str(f) for p in skip_patterns)]
            
            return f"""项目结构摘要:
- Python 文件: {len(py_files)}
- JavaScript 文件: {len(js_files)}
- TypeScript 文件: {len(ts_files)}
- 总计: {len(py_files) + len(js_files) + len(ts_files)} 个代码文件
"""
        except Exception:
            return "项目结构摘要: 无法获取"
    
    def get_file_content(self, file_path: str) -> Optional[str]:
        """获取完整文件内容"""
        full_path = self.project_path / file_path
        try:
            if full_path.exists():
                return full_path.read_text(encoding="utf-8")
        except Exception:
            pass
        return None


# 全局索引服务实例缓存
_indexer_cache: Dict[str, LangChainCodeIndexer] = {}


async def get_langchain_indexer(
    project_path: str,
    include_tests: bool = False,
    use_langchain: bool = True
) -> Any:
    """
    获取索引服务实例（线程安全）
    
    Args:
        project_path: 项目路径
        include_tests: 是否包含测试目录
        use_langchain: 是否使用 LangChain 版本（否则回退到旧版）
        
    Returns:
        索引服务实例
    """
    if not use_langchain or not LANGCHAIN_AVAILABLE:
        # 回退到旧版
        from app.service.code_indexer import get_indexer
        return await get_indexer(project_path, include_tests)
    
    # 使用锁保护缓存操作
    from app.service.code_indexer import _global_lock
    async with _global_lock:
        cache_key = f"langchain:{project_path}:{include_tests}"
        if cache_key not in _indexer_cache:
            _indexer_cache[cache_key] = LangChainCodeIndexer(
                project_path,
                include_tests=include_tests
            )
        return _indexer_cache[cache_key]


def clear_langchain_indexer_cache():
    """清除所有索引器缓存"""
    global _indexer_cache
    _indexer_cache.clear()
