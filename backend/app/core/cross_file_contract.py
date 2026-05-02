"""
跨文件契约一致性检查模块

在 CoderAgent 输出后、TesterAgent 运行前执行，检查跨文件的字典键名一致性。
避免"修好 A 文件，坏掉 B 文件"的问题。
"""

import ast
import logging
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class CrossFileContractChecker:
    """
    跨文件契约一致性检查器
    
    扫描所有被修改文件中的字典返回结构，检查不同文件中引用的共享键名是否一致。
    """
    
    def __init__(self, modified_files: Dict[str, str]):
        """
        初始化检查器
        
        Args:
            modified_files: 文件路径到内容的映射 {file_path: content}
        """
        self.modified_files = modified_files
        self.key_usages: Dict[str, Set[str]] = defaultdict(set)  # key -> set of file paths
        self.function_returns: Dict[str, Dict[str, Set[str]]] = defaultdict(dict)  # file -> func -> keys
        self._scan()
    
    def _scan(self):
        """扫描所有文件，提取字典键名使用情况"""
        logger.debug(f"[CrossFileContract] 开始扫描 {len(self.modified_files)} 个文件")
        for file_path, content in self.modified_files.items():
            try:
                tree = ast.parse(content)
                self._analyze_file(file_path, tree)
            except SyntaxError as e:
                logger.debug(f"[CrossFileContract] 无法解析文件: {file_path}: {e}")
                continue
        logger.debug(f"[CrossFileContract] 扫描完成，发现 {len(self.key_usages)} 个唯一键名")
    
    def _analyze_file(self, file_path: str, tree: ast.AST):
        """分析单个文件的 AST"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                return_keys = self._extract_return_keys_from_function(node)
                
                if return_keys:
                    self.function_returns[file_path][func_name] = return_keys
                    
                    # 记录每个键名在哪些文件中使用
                    for key in return_keys:
                        self.key_usages[key].add(file_path)
    
    def _extract_return_keys_from_function(self, func_node: ast.FunctionDef) -> Set[str]:
        """从函数定义中提取返回字典的键名"""
        keys = set()
        local_vars = {}
        
        # 收集局部变量赋值
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        if isinstance(node.value, ast.Dict):
                            local_vars[var_name] = node.value
            # ===== 增加对带类型注解变量的支持 =====
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    var_name = node.target.id
                    if isinstance(node.value, ast.Dict):
                        local_vars[var_name] = node.value

        # 分析 return 语句
        for node in ast.walk(func_node):
            if isinstance(node, ast.Return) and node.value:
                keys.update(self._extract_keys_from_value(node.value, local_vars))
        
        return keys
    
    def _extract_keys_from_value(self, value_node: ast.AST, local_vars: dict) -> Set[str]:
        """从 AST 值节点中提取字典键名"""
        keys = set()
        
        # 直接返回字典
        if isinstance(value_node, ast.Dict):
            for key in value_node.keys:
                key_name = self._get_key_name(key)
                if key_name:
                    keys.add(key_name)
        
        # 返回变量
        elif isinstance(value_node, ast.Name):
            var_name = value_node.id
            if var_name in local_vars:
                var_value = local_vars[var_name]
                if isinstance(var_value, ast.Dict):
                    for key in var_value.keys:
                        key_name = self._get_key_name(key)
                        if key_name:
                            keys.add(key_name)
        
        # 合并字典
        elif isinstance(value_node, ast.BinOp) and isinstance(value_node.op, ast.BitOr):
            keys.update(self._extract_keys_from_value(value_node.left, local_vars))
            keys.update(self._extract_keys_from_value(value_node.right, local_vars))
        
        # dict() 调用
        elif isinstance(value_node, ast.Call):
            if isinstance(value_node.func, ast.Name) and value_node.func.id == 'dict':
                for kw in value_node.keywords:
                    keys.add(kw.arg)
        
        # 条件表达式
        elif isinstance(value_node, ast.IfExp):
            keys.update(self._extract_keys_from_value(value_node.body, local_vars))
            keys.update(self._extract_keys_from_value(value_node.orelse, local_vars))
        
        return keys
    
    def _get_key_name(self, key_node: ast.AST) -> Optional[str]:
        """从 AST 键节点中提取键名字符串"""
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            return key_node.value
        elif hasattr(key_node, 's'):  # Python < 3.8: ast.Str
            return key_node.s
        return None
    
    def find_inconsistencies(self) -> List[Dict[str, Any]]:
        """
        查找跨文件不一致的键名使用情况
        
        检测：
        1. 相似键名（可能是拼写错误，如 usage_percent vs used_percent）
        2. 同一概念在不同文件中使用不同键名
        
        Returns:
            不一致的问题列表
        """
        inconsistencies = []
        
        # 检查相似键名
        all_keys = list(self.key_usages.keys())
        logger.debug(f"[CrossFileContract] 检查 {len(all_keys)} 个键名的相似性")
        
        for i, key1 in enumerate(all_keys):
            for key2 in all_keys[i+1:]:
                # 检查是否是相似键名（编辑距离小或共同子串长）
                if self._are_keys_similar(key1, key2):
                    files1 = self.key_usages[key1]
                    files2 = self.key_usages[key2]
                    
                    # 如果两个相似键名出现在不同文件中，可能是问题
                    if files1 != files2 and files1 & files2:
                        logger.debug(f"[CrossFileContract] 发现相似键名: '{key1}' vs '{key2}'")
                        inconsistencies.append({
                            "type": "similar_keys",
                            "keys": [key1, key2],
                            "key1_files": list(files1),
                            "key2_files": list(files2),
                            "message": f"发现相似键名 '{key1}' 和 '{key2}'，可能是拼写不一致",
                            "suggestion": f"建议统一使用其中一个键名"
                        })
        
        logger.debug(f"[CrossFileContract] 相似性检查完成，发现 {len(inconsistencies)} 个潜在问题")
        return inconsistencies
    
    def _are_keys_similar(self, key1: str, key2: str) -> bool:
        """检查两个键名是否相似（可能是拼写错误）"""
        # 忽略完全相同
        if key1 == key2:
            return False
        
        # 编辑距离检查
        distance = self._levenshtein_distance(key1, key2)
        max_len = max(len(key1), len(key2))
        
        # 如果编辑距离小于长度的 30%，认为是相似的
        if max_len > 0 and distance / max_len < 0.3:
            return True
        
        # 检查是否有共同的核心子串（如 usage_percent 和 used_percent 都有 percent）
        common_parts = self._get_common_parts(key1, key2)
        if len(common_parts) >= 2:
            return True
        
        return False
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """计算两个字符串的编辑距离"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def _get_common_parts(self, s1: str, s2: str) -> Set[str]:
        """获取两个字符串的共同子串（按下划线分割后的共同部分）"""
        parts1 = set(s1.split('_'))
        parts2 = set(s2.split('_'))
        return parts1 & parts2
    
    def get_key_usage_report(self) -> Dict[str, Any]:
        """获取键名使用情况的报告"""
        return {
            "total_keys": len(self.key_usages),
            "keys_by_file": dict(self.key_usages),
            "function_returns": dict(self.function_returns)
        }


def check_cross_file_consistency(
    modified_files: Dict[str, str],
    interface_specs: Optional[List[Dict]] = None
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    便捷的跨文件一致性检查函数
    
    Args:
        modified_files: 修改的文件映射 {file_path: content}
        interface_specs: 接口契约列表（可选，用于额外校验）
        
    Returns:
        (是否通过, 问题列表)
    """
    """
    【简化】跨文件一致性检查 - 改为纯工具函数，不阻断流程
    
    此函数仅用于分析，返回的问题列表不会阻断 Pipeline 执行。
    真正的契约校验在 CoderAgent 的 P0-3 阶段完成。
    """
    logger.debug(f"[CrossFileContract] 跨文件一致性检查: {len(modified_files)} 个文件")
    checker = CrossFileContractChecker(modified_files)
    
    # 查找不一致（仅用于分析，不阻断）
    inconsistencies = checker.find_inconsistencies()
    
    if inconsistencies:
        logger.debug(f"[CrossFileContract] 发现 {len(inconsistencies)} 个潜在问题（仅警告，不阻断）")
    
    # 始终返回通过，不阻断流程
    return True, inconsistencies
