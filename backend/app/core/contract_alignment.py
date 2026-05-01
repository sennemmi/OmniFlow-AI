"""
契约对齐校验模块

用于强制对齐 ArchitectAgent 和 DesignerAgent 的输出，
确保 DesignerAgent 的 interface_specs 包含 ArchitectAgent 要求的所有符号。
"""

from typing import List, Dict, Any, Tuple, Set
import logging

logger = logging.getLogger(__name__)


class ContractMisalignmentError(Exception):
    """契约对齐错误"""
    
    def __init__(self, message: str, missing_symbols: List[str] = None, extra_symbols: List[str] = None, 
                 missing_criteria: List[int] = None):
        super().__init__(message)
        self.missing_symbols = missing_symbols or []
        self.extra_symbols = extra_symbols or []
        self.missing_criteria = missing_criteria or []


class CriteriaAlignmentError(Exception):
    """验收标准对齐错误"""
    
    def __init__(self, message: str, missing_criteria: List[int] = None, 
                 invalid_mappings: List[Dict[str, Any]] = None):
        super().__init__(message)
        self.missing_criteria = missing_criteria or []
        self.invalid_mappings = invalid_mappings or []


def verify_contract_alignment(
    required_symbols: List[Dict[str, Any]], 
    interface_specs: List[Dict[str, Any]]
) -> Tuple[bool, List[str], List[str]]:
    """
    校验 required_symbols 和 interface_specs 是否对齐
    
    Args:
        required_symbols: ArchitectAgent 要求的必需符号列表
        interface_specs: DesignerAgent 生成的接口契约列表
        
    Returns:
        Tuple[bool, List[str], List[str]]: 
            - 是否对齐
            - 缺失的符号列表
            - 额外的符号列表（可选，用于调试）
            
    示例:
        >>> required = [{"name": "check_db", "type": "function", "module": "app/health.py"}]
        >>> specs = [{"symbol_name": "check_db", "module": "app/health.py"}]
        >>> verify_contract_alignment(required, specs)
        (True, [], [])
    """
    # 提取 required_symbols 中的符号名
    required_names: Set[str] = set()
    for sym in required_symbols:
        name = sym.get("name", "")
        if name:
            required_names.add(name)
    
    # 提取 interface_specs 中的符号名
    spec_names: Set[str] = set()
    for spec in interface_specs:
        name = spec.get("symbol_name", "")
        if name:
            spec_names.add(name)
    
    # 计算差异
    missing = required_names - spec_names  # 必需但未实现的
    extra = spec_names - required_names    # 实现但非必需的（可接受）
    
    # 判断是否对齐：必须包含所有 required_names
    is_aligned = len(missing) == 0
    
    if not is_aligned:
        logger.warning(f"[ContractAlignment] 契约未对齐，缺失符号: {missing}")
    else:
        logger.info(f"[ContractAlignment] 契约对齐成功，共 {len(spec_names)} 个符号")
        if extra:
            logger.debug(f"[ContractAlignment] 额外符号（可接受）: {extra}")
    
    return is_aligned, list(missing), list(extra)


def build_alignment_feedback(missing_symbols: List[str], required_symbols: List[Dict[str, Any]]) -> str:
    """
    构建对齐失败的反馈信息，用于重试时注入 DesignerAgent
    
    Args:
        missing_symbols: 缺失的符号列表
        required_symbols: 必需的符号列表（用于查找详细信息）
        
    Returns:
        str: 反馈信息
    """
    if not missing_symbols:
        return ""
    
    # 构建缺失符号的详细信息
    missing_details = []
    for sym_name in missing_symbols:
        # 查找该符号的详细信息
        for req in required_symbols:
            if req.get("name") == sym_name:
                module = req.get("module", "未知模块")
                sym_type = req.get("type", "未知类型")
                signature = req.get("signature", "")
                desc = req.get("description", "")
                
                detail = f"- {sym_name} ({sym_type})"
                if module:
                    detail += f" in {module}"
                if signature:
                    detail += f": {signature}"
                if desc:
                    detail += f" - {desc}"
                missing_details.append(detail)
                break
        else:
            # 如果没找到详细信息，只显示名称
            missing_details.append(f"- {sym_name}")
    
    feedback = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    【契约对齐失败 - 上次设计遗漏了以下必需符号】                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

{chr(10).join(missing_details)}

【修正要求】
1. 必须在 interface_specs 中包含上述所有符号
2. 每个符号必须包含正确的 symbol_name、module、signature
3. 重新输出完整的技术设计（JSON）

【重要提示】
- 不要遗漏任何必需符号
- 符号名称必须与上述列表完全一致
- 模块路径必须正确
"""
    return feedback


def validate_symbol_format(symbol: Dict[str, Any]) -> Tuple[bool, str]:
    """
    验证单个符号的格式是否正确
    
    Args:
        symbol: 符号定义
        
    Returns:
        Tuple[bool, str]: 是否有效，错误信息
    """
    name = symbol.get("name", "")
    module = symbol.get("module", "")
    
    if not name:
        return False, "符号名称不能为空"
    
    if not module:
        return False, "模块路径不能为空"
    
    # 检查是否包含点分符号（如 ClassName.method）
    if "." in name:
        return False, f"符号名称不能包含点分格式: {name}"
    
    return True, ""


def filter_valid_symbols(symbols: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    过滤掉格式不正确的符号
    
    Args:
        symbols: 符号列表
        
    Returns:
        Tuple[List[Dict], List[str]]: 有效符号列表，错误信息列表
    """
    valid = []
    errors = []
    
    for sym in symbols:
        is_valid, error = validate_symbol_format(sym)
        if is_valid:
            valid.append(sym)
        else:
            errors.append(f"符号 {sym.get('name', 'unknown')}: {error}")
    
    return valid, errors


def verify_criteria_alignment(
    acceptance_criteria: List[str],
    criteria_mappings: List[Dict[str, Any]],
    interface_specs: List[Dict[str, Any]]
) -> Tuple[bool, List[int], List[Dict[str, Any]]]:
    """
    校验验收标准与接口契约的对齐情况
    
    验证每条验收标准是否都有对应的接口契约映射，以及映射是否有效。
    
    Args:
        acceptance_criteria: ArchitectAgent 的验收标准列表
        criteria_mappings: DesignerAgent 生成的映射关系
        interface_specs: DesignerAgent 生成的接口契约列表
        
    Returns:
        Tuple[bool, List[int], List[Dict]]: 
            - 是否完全对齐
            - 缺失的验收标准索引列表（从1开始）
            - 无效的映射列表（包含错误原因）
    """
    if not acceptance_criteria:
        logger.info("[CriteriaAlignment] 没有验收标准，跳过对齐检查")
        return True, [], []
    
    # 提取 interface_specs 中的所有符号名
    spec_names = {spec.get("symbol_name", "") for spec in interface_specs}
    
    # 检查哪些验收标准没有被映射
    mapped_indices = set()
    invalid_mappings = []
    
    for mapping in criteria_mappings:
        criteria_index = mapping.get("criteria_index", 0)
        covered_by = mapping.get("covered_by", [])
        mapping_reason = mapping.get("mapping_reason", "")
        
        # 验证索引范围
        if criteria_index < 1 or criteria_index > len(acceptance_criteria):
            invalid_mappings.append({
                "mapping": mapping,
                "error": f"criteria_index {criteria_index} 超出范围（1-{len(acceptance_criteria)}）"
            })
            continue
        
        mapped_indices.add(criteria_index)
        
        # 验证 covered_by 中的符号是否存在于 interface_specs
        missing_symbols = [sym for sym in covered_by if sym not in spec_names]
        if missing_symbols:
            invalid_mappings.append({
                "mapping": mapping,
                "error": f"covered_by 中的符号不存在于 interface_specs: {missing_symbols}"
            })
            continue
        
        # 验证 mapping_reason 是否为空
        if not mapping_reason or len(mapping_reason) < 10:
            invalid_mappings.append({
                "mapping": mapping,
                "error": "mapping_reason 为空或太短，必须具体说明如何满足验收标准"
            })
            continue
    
    # 找出未被映射的验收标准
    all_indices = set(range(1, len(acceptance_criteria) + 1))
    missing_criteria = sorted(all_indices - mapped_indices)
    
    is_aligned = len(missing_criteria) == 0 and len(invalid_mappings) == 0
    
    if not is_aligned:
        if missing_criteria:
            logger.warning(f"[CriteriaAlignment] 缺失 {len(missing_criteria)} 条验收标准映射: {missing_criteria}")
        if invalid_mappings:
            logger.warning(f"[CriteriaAlignment] 发现 {len(invalid_mappings)} 个无效映射")
    else:
        logger.info(f"[CriteriaAlignment] 验收标准对齐成功，共 {len(acceptance_criteria)} 条标准，{len(criteria_mappings)} 个映射")
    
    return is_aligned, missing_criteria, invalid_mappings


def build_criteria_alignment_feedback(
    missing_criteria: List[int],
    invalid_mappings: List[Dict[str, Any]],
    acceptance_criteria: List[str]
) -> str:
    """
    构建验收标准对齐失败的反馈信息
    
    Args:
        missing_criteria: 缺失的验收标准索引列表
        invalid_mappings: 无效的映射列表
        acceptance_criteria: 验收标准列表
        
    Returns:
        str: 反馈信息
    """
    feedback_lines = []
    
    if missing_criteria:
        feedback_lines.append("【缺失的验收标准映射】")
        for idx in missing_criteria:
            if idx <= len(acceptance_criteria):
                feedback_lines.append(f"  - 标准 {idx}: {acceptance_criteria[idx-1]}")
            else:
                feedback_lines.append(f"  - 标准 {idx}: (索引超出范围)")
        feedback_lines.append("")
    
    if invalid_mappings:
        feedback_lines.append("【无效的映射】")
        for item in invalid_mappings:
            mapping = item.get("mapping", {})
            error = item.get("error", "")
            criteria_idx = mapping.get("criteria_index", "?")
            feedback_lines.append(f"  - 映射 {criteria_idx}: {error}")
        feedback_lines.append("")
    
    feedback = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              【验收标准对齐失败 - 必须修正以下问题】                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

{chr(10).join(feedback_lines)}
【修正要求】
1. 必须为每条验收标准创建 criteria_mappings 条目
2. covered_by 中的符号必须在 interface_specs 中定义
3. mapping_reason 必须具体说明接口如何满足验收标准（至少10个字符）
4. 对齐率必须达到 100%

【输出格式示例】
{{
  "criteria_mappings": [
    {{
      "criteria_index": 1,
      "criteria_description": "API 返回健康状态",
      "covered_by": ["health_check"],
      "mapping_reason": "health_check 函数返回包含 status 字段的字典"
    }}
  ]
}}
"""
    return feedback
