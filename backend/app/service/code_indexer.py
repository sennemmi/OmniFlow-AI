"""
代码库语义索引服务 - 企业级向量检索版
实现 RAG (Retrieval-Augmented Generation) 流程

核心功能：
1. 解析（Parsing）：利用 AST 将代码拆解为语义单元
2. 向量化（Embedding）：将代码块转化为向量（支持 litellm/ChromaDB）
3. 索引（Indexing）：存储在 ChromaDB 向量数据库中
4. 检索（Retrieval）：混合检索（关键词 + 向量相似度）

企业级特性：
- 持久化向量数据库（ChromaDB）
- 混合检索策略（关键词 + 向量）
- 增量索引更新（基于文件哈希）
- 两阶段上下文管理（签名 + 完整代码）
"""

import os
import ast
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict

import litellm
from app.core.config import settings

# 尝试导入 ChromaDB，如果未安装则使用降级方案
try:
    import chromadb
    from chromadb.utils import embedding_functions
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("警告: ChromaDB 未安装，将使用降级方案（仅关键词检索）")


@dataclass
class CodeChunk:
    """代码块数据类"""
    file_path: str
    name: str
    content: str
    type: str  # "function", "class", "method"
    start_line: int
    end_line: int
    docstring: Optional[str] = None
    signature: Optional[str] = None  # 函数/类签名

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_searchable_text(self) -> str:
        """获取用于向量检索的文本（包含名称、文档、签名）"""
        parts = [self.name, self.type]
        if self.docstring:
            parts.append(self.docstring)
        if self.signature:
            parts.append(self.signature)
        # 添加代码内容的前 500 字符作为上下文
        parts.append(self.content[:500])
        return "\n".join(parts)


class CodeIndexerService:
    """代码库语义索引服务 - 企业级向量检索版"""

    def __init__(self, project_path: str, index_dir: Optional[str] = None):
        """
        初始化索引服务

        Args:
            project_path: 目标项目路径
            index_dir: 索引缓存目录，默认为项目根目录下的 .omniflow_index
        """
        self.project_path = Path(project_path)
        self.index_dir = Path(index_dir) if index_dir else self.project_path / ".omniflow_index"
        self.index_file = self.index_dir / "code_index.json"
        self.chunks: List[CodeChunk] = []

        # 初始化 ChromaDB 向量数据库
        self.chroma_client = None
        self.collection = None
        if CHROMADB_AVAILABLE:
            try:
                vector_db_path = self.index_dir / "vector_db"
                self.chroma_client = chromadb.PersistentClient(path=str(vector_db_path))
                self.collection = self.chroma_client.get_or_create_collection(
                    name="code_chunks",
                    metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
                )
                print(f"ChromaDB 向量数据库已初始化: {vector_db_path}")
            except Exception as e:
                print(f"ChromaDB 初始化失败: {e}，将使用降级方案")
                self.chroma_client = None
                self.collection = None

    def _get_file_hash(self, file_path: Path) -> str:
        """计算文件 MD5 哈希值"""
        try:
            content = file_path.read_bytes()
            return hashlib.md5(content).hexdigest()
        except Exception:
            return ""

    def _load_index_cache(self) -> Optional[Dict[str, Any]]:
        """加载索引缓存"""
        if not self.index_file.exists():
            return None

        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载索引缓存失败: {e}")
            return None

    def _save_index_cache(self, index_data: Dict[str, Any]):
        """保存索引缓存"""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存索引缓存失败: {e}")

    def _is_index_stale(self, cached_hashes: Dict[str, str]) -> bool:
        """检查索引是否过期（文件是否有变化）"""
        for root, _, files in os.walk(self.project_path):
            # 跳过索引目录和隐藏目录
            if '.omniflow_index' in root or '__pycache__' in root:
                continue

            for file in files:
                if file.endswith('.py'):
                    file_path = Path(root) / file
                    rel_path = str(file_path.relative_to(self.project_path))
                    current_hash = self._get_file_hash(file_path)

                    # 如果文件不在缓存中或哈希值不同，说明索引过期
                    if rel_path not in cached_hashes:
                        return True
                    if cached_hashes[rel_path] != current_hash:
                        return True

        return False

    def _extract_signature(self, node: ast.AST, content: str) -> str:
        """提取函数/类的签名（不包含实现）"""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 提取函数定义行
            start_line = node.lineno
            lines = content.splitlines()
            # 找到函数定义结束的位置（冒号处）
            for i in range(start_line - 1, min(start_line + 5, len(lines))):
                line = lines[i]
                if ':' in line and not line.strip().startswith('#'):
                    # 返回函数定义（到冒号为止）
                    return line.strip()
            return f"def {node.name}(...)"

        elif isinstance(node, ast.ClassDef):
            # 提取类定义行
            start_line = node.lineno
            lines = content.splitlines()
            for i in range(start_line - 1, min(start_line + 5, len(lines))):
                line = lines[i]
                if ':' in line and line.strip().startswith('class'):
                    return line.strip()
            return f"class {node.name}(...)"

        return ""

    def extract_code_units(self, force_refresh: bool = False) -> List[CodeChunk]:
        """
        使用 AST 解析代码库，提取函数和类

        Args:
            force_refresh: 强制刷新索引，忽略缓存

        Returns:
            List[CodeChunk]: 代码块列表
        """
        # 尝试加载缓存
        if not force_refresh:
            cached_data = self._load_index_cache()
            if cached_data:
                cached_hashes = cached_data.get('file_hashes', {})
                if not self._is_index_stale(cached_hashes):
                    print("使用缓存的代码索引...")
                    chunks_data = cached_data.get('chunks', [])
                    self.chunks = [CodeChunk(**chunk) for chunk in chunks_data]
                    return self.chunks

        print("正在重新构建代码索引...")
        self.chunks = []
        file_hashes = {}

        for root, _, files in os.walk(self.project_path):
            # 跳过索引目录、隐藏目录和测试目录
            if any(skip in root for skip in ['.omniflow_index', '__pycache__', '.git', 'tests', 'test']):
                continue

            for file in files:
                if file.endswith('.py'):
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(self.project_path)

                    # 记录文件哈希
                    file_hashes[str(rel_path)] = self._get_file_hash(file_path)

                    try:
                        content = file_path.read_text(encoding='utf-8')
                        tree = ast.parse(content)

                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                # 提取代码块内容
                                start_line = node.lineno
                                end_line = getattr(node, 'end_lineno', start_line + 5)
                                chunk_content = "\n".join(content.splitlines()[start_line-1:end_line])

                                # 提取 docstring
                                docstring = ast.get_docstring(node)

                                # 提取签名
                                signature = self._extract_signature(node, content)

                                # 确定类型
                                if isinstance(node, ast.ClassDef):
                                    chunk_type = "class"
                                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                                    # 检查是否是方法（在类内部）
                                    chunk_type = "method" if self._is_method(node, tree) else "function"
                                else:
                                    chunk_type = "unknown"

                                self.chunks.append(CodeChunk(
                                    file_path=str(rel_path),
                                    name=node.name,
                                    content=chunk_content,
                                    type=chunk_type,
                                    start_line=start_line,
                                    end_line=end_line,
                                    docstring=docstring,
                                    signature=signature
                                ))
                    except SyntaxError as e:
                        print(f"语法错误，跳过文件 {rel_path}: {e}")
                    except Exception as e:
                        print(f"解析文件 {rel_path} 失败: {e}")

        # 保存索引缓存
        index_data = {
            'file_hashes': file_hashes,
            'chunks': [chunk.to_dict() for chunk in self.chunks],
            'total_files': len(file_hashes),
            'total_chunks': len(self.chunks)
        }
        self._save_index_cache(index_data)
        print(f"代码索引构建完成: {len(self.chunks)} 个代码块来自 {len(file_hashes)} 个文件")

        # 同步到向量数据库
        if self.collection:
            self._index_to_vector_db()

        return self.chunks

    def _is_method(self, node: ast.FunctionDef, tree: ast.Module) -> bool:
        """检查函数是否是类方法"""
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef):
                for child in ast.iter_child_nodes(parent):
                    if child is node:
                        return True
        return False

    def _index_to_vector_db(self):
        """将代码块索引到 ChromaDB 向量数据库"""
        if not self.collection or not self.chunks:
            return

        try:
            print("正在同步到向量数据库...")

            # 准备数据
            ids = []
            documents = []
            metadatas = []

            for chunk in self.chunks:
                # 使用 文件名:名称:行号 确保 ID 绝对唯一
                # 避免不同类中的同名方法（如 __init__）导致 ID 冲突
                chunk_id = f"{chunk.file_path}:{chunk.name}:{chunk.start_line}"
                ids.append(chunk_id)
                documents.append(chunk.get_searchable_text())
                metadatas.append({
                    "file_path": chunk.file_path,
                    "name": chunk.name,
                    "type": chunk.type,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "signature": chunk.signature or "",
                    "docstring": chunk.docstring or ""
                })

            # 分批添加（避免单次请求过大）
            batch_size = 100
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i+batch_size]
                batch_docs = documents[i:i+batch_size]
                batch_metas = metadatas[i:i+batch_size]

                self.collection.add(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_metas
                )

            print(f"向量数据库同步完成: {len(ids)} 个代码块")

        except Exception as e:
            print(f"向量数据库同步失败: {e}")

    async def get_embedding(self, text: str) -> List[float]:
        """
        获取文本的向量嵌入

        Args:
            text: 输入文本

        Returns:
            List[float]: 向量嵌入
        """
        try:
            # 使用 litellm 调用 embedding 模型
            response = await litellm.aembedding(
                model="text-embedding-3-small",  # 或其他 embedding 模型
                input=text[:8000]  # 限制长度
            )
            return response.data[0].embedding
        except Exception as e:
            print(f"获取 embedding 失败: {e}")
            # 返回零向量作为 fallback
            return [0.0] * 1536  # text-embedding-3-small 的维度

    def _calculate_keyword_similarity(self, query: str, chunk: CodeChunk) -> float:
        """
        计算关键词相似度分数

        Args:
            query: 查询词
            chunk: 代码块

        Returns:
            float: 相似度分数
        """
        score = 0.0
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        # 1. 名称匹配（高权重）
        name_lower = chunk.name.lower()
        if query_lower in name_lower:
            score += 10.0
        elif any(term in name_lower for term in query_terms):
            score += 5.0

        # 2. 签名匹配
        if chunk.signature:
            sig_lower = chunk.signature.lower()
            if query_lower in sig_lower:
                score += 8.0
            elif any(term in sig_lower for term in query_terms):
                score += 4.0

        # 3. Docstring 匹配
        if chunk.docstring:
            docstring_lower = chunk.docstring.lower()
            if query_lower in docstring_lower:
                score += 8.0
            elif any(term in docstring_lower for term in query_terms):
                score += 4.0

        # 4. 内容匹配
        content_lower = chunk.content.lower()
        if query_lower in content_lower:
            score += 3.0
        elif any(term in content_lower for term in query_terms):
            score += 1.0

        # 5. 文件路径匹配
        path_lower = chunk.file_path.lower()
        if any(term in path_lower for term in query_terms):
            score += 2.0

        return score

    async def _vector_search(self, query: str, top_k: int = 10) -> List[Tuple[CodeChunk, float]]:
        """
        向量相似度搜索

        Args:
            query: 查询词
            top_k: 返回前 k 个结果

        Returns:
            List[Tuple[CodeChunk, float]]: 代码块和相似度分数列表
        """
        if not self.collection:
            return []

        try:
            # 查询向量数据库
            results = self.collection.query(
                query_texts=[query],
                n_results=min(top_k * 2, len(self.chunks)),  # 多取一些用于混合排序
                include=["metadatas", "distances"]
            )

            vector_results = []
            if results and results['ids']:
                for i, chunk_id in enumerate(results['ids'][0]):
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i]

                    # 找到对应的 CodeChunk（使用新的 ID 格式匹配）
                    for chunk in self.chunks:
                        expected_id = f"{chunk.file_path}:{chunk.name}:{chunk.start_line}"
                        if expected_id == chunk_id:
                            # 将距离转换为相似度分数（余弦距离 -> 相似度）
                            similarity = 1.0 - distance
                            vector_results.append((chunk, similarity))
                            break

            return vector_results

        except Exception as e:
            print(f"向量搜索失败: {e}")
            return []

    async def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        chunk_types: Optional[List[str]] = None,
        use_vector: bool = True,
        use_keyword: bool = True
    ) -> str:
        """
        语义搜索：混合检索（关键词 + 向量相似度）

        Args:
            query: 查询词
            top_k: 返回前 k 个结果
            chunk_types: 过滤的代码块类型，如 ["function", "class"]
            use_vector: 是否使用向量检索
            use_keyword: 是否使用关键词检索

        Returns:
            str: 格式化的相关代码上下文
        """
        if not self.chunks:
            self.extract_code_units()

        # 过滤代码块类型
        filtered_chunks = self.chunks
        if chunk_types:
            filtered_chunks = [c for c in self.chunks if c.type in chunk_types]

        # 混合检索结果
        all_results: Dict[str, Tuple[CodeChunk, float]] = {}

        # 1. 关键词检索
        if use_keyword:
            for chunk in filtered_chunks:
                score = self._calculate_keyword_similarity(query, chunk)
                if score > 0:
                    chunk_id = f"{chunk.file_path}:{chunk.name}"
                    if chunk_id in all_results:
                        # 加权合并
                        _, existing_score = all_results[chunk_id]
                        all_results[chunk_id] = (chunk, existing_score + score * 0.3)
                    else:
                        all_results[chunk_id] = (chunk, score * 0.3)

        # 2. 向量检索
        if use_vector and self.collection:
            vector_results = await self._vector_search(query, top_k * 2)
            for chunk, similarity in vector_results:
                if chunk_types and chunk.type not in chunk_types:
                    continue

                chunk_id = f"{chunk.file_path}:{chunk.name}"
                if chunk_id in all_results:
                    # 加权合并（向量权重更高）
                    _, existing_score = all_results[chunk_id]
                    all_results[chunk_id] = (chunk, existing_score + similarity * 10.0)
                else:
                    all_results[chunk_id] = (chunk, similarity * 10.0)

        # 如果没有结果，降级到纯关键词检索
        if not all_results and not use_keyword:
            return await self.semantic_search(query, top_k, chunk_types, use_vector=False, use_keyword=True)

        # 按分数排序
        sorted_results = sorted(all_results.values(), key=lambda x: x[1], reverse=True)

        # 格式化输出
        results = []
        for i, (chunk, score) in enumerate(sorted_results[:top_k], 1):
            result_text = f"""--- 相关代码片段 #{i} (相关度: {score:.2f}) ---
文件: {chunk.file_path} (第 {chunk.start_line}-{chunk.end_line} 行)
类型: {chunk.type}
名称: {chunk.name}
"""
            if chunk.signature:
                result_text += f"签名: {chunk.signature}\n"

            if chunk.docstring:
                result_text += f"文档: {chunk.docstring}\n"

            result_text += f"```python\n{chunk.content}\n```"
            results.append(result_text)

        return "\n\n".join(results) if results else "未找到相关代码片段。"

    async def search_signatures(
        self,
        query: str,
        top_k: int = 10
    ) -> str:
        """
        两阶段检索 - 阶段 1：仅返回签名和文档（广度搜索）

        Args:
            query: 查询词
            top_k: 返回前 k 个结果

        Returns:
            str: 格式化的签名列表
        """
        if not self.chunks:
            self.extract_code_units()

        # 计算相关性
        scored_chunks = []
        for chunk in self.chunks:
            score = self._calculate_keyword_similarity(query, chunk)
            if score > 0:
                scored_chunks.append((chunk, score))

        # 按分数排序
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # 格式化输出（仅签名）
        results = []
        for i, (chunk, score) in enumerate(scored_chunks[:top_k], 1):
            result_text = f"{i}. [{chunk.type}] {chunk.name}"
            if chunk.signature:
                result_text += f" - {chunk.signature}"
            if chunk.docstring:
                # 只取 docstring 的第一行
                doc_first_line = chunk.docstring.split('\n')[0][:80]
                result_text += f"\n   文档: {doc_first_line}..."
            result_text += f" ({chunk.file_path}:{chunk.start_line})"
            results.append(result_text)

        return "\n".join(results) if results else "未找到相关代码签名。"

    async def get_full_implementation(self, file_path: str, name: str) -> Optional[str]:
        """
        两阶段检索 - 阶段 2：根据签名获取完整实现（深度搜索）

        Args:
            file_path: 文件路径
            name: 函数/类名称

        Returns:
            Optional[str]: 完整代码实现
        """
        for chunk in self.chunks:
            if chunk.file_path == file_path and chunk.name == name:
                return chunk.content
        return None

    def get_project_structure(self) -> str:
        """获取项目结构摘要"""
        if not self.chunks:
            self.extract_code_units()

        files = set(chunk.file_path for chunk in self.chunks)
        classes = [c.name for c in self.chunks if c.type == "class"]
        functions = [c.name for c in self.chunks if c.type == "function"]
        methods = [c.name for c in self.chunks if c.type == "method"]

        return f"""项目结构摘要:
- 文件数: {len(files)}
- 类数: {len(classes)}
- 函数数: {len(functions)}
- 方法数: {len(methods)}

主要类: {', '.join(classes[:10])}{'...' if len(classes) > 10 else ''}
主要函数: {', '.join(functions[:10])}{'...' if len(functions) > 10 else ''}
"""


# 全局索引服务实例缓存
_indexer_cache: Dict[str, CodeIndexerService] = {}


def get_indexer(project_path: str) -> CodeIndexerService:
    """
    获取或创建索引服务实例（带缓存）

    Args:
        project_path: 项目路径

    Returns:
        CodeIndexerService: 索引服务实例
    """
    if project_path not in _indexer_cache:
        _indexer_cache[project_path] = CodeIndexerService(project_path)
    return _indexer_cache[project_path]
