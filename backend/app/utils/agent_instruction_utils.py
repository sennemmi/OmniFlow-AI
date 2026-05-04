"""
Agent 指令构建工具

提供构建各类修复指令的模板函数
"""

import json
from typing import Dict, List, Optional


def build_key_mismatch_fix_instruction(
    key_mismatches: List[Dict],
    injected_files: Dict[str, str]
) -> str:
    """
    构建返回键名不匹配的修复指令

    Args:
        key_mismatches: 键名不匹配列表
        injected_files: 注入的文件内容

    Returns:
        修复指令字符串
    """
    from app.utils.file_operation_utils import extract_function_source

    instruction = "关键问题：以下函数缺少必需的返回字段：\n"

    for mismatch in key_mismatches:
        symbol = mismatch.get('symbol', '')
        missing = mismatch.get('missing_keys', [])
        file_path = mismatch.get('file', '')

        instruction += f"\n\n=== 函数: {symbol} (文件: {file_path}) ==="
        instruction += f"\n缺少字段: {missing}"

        if file_path and file_path in injected_files:
            content = injected_files[file_path]
            func_code = extract_function_source(content, symbol)
            if func_code:
                instruction += f"\n\n当前函数源代码:\n```python\n{func_code}\n```"
            else:
                instruction += f"\n\n当前文件内容（部分）:\n```python\n{content[:1000]}\n```"

    return instruction


def build_retry_fix_instruction(
    retry_attempt: int,
    max_retries: int,
    key_mismatch_instruction: str
) -> tuple[str, bool]:
    """
    构建重试修复指令

    Args:
        retry_attempt: 当前重试次数（从0开始）
        max_retries: 最大重试次数
        key_mismatch_instruction: 键名不匹配的基础指令

    Returns:
        (instruction, force_full_file) - 完整指令和是否强制完整文件
    """
    instruction = key_mismatch_instruction

    if retry_attempt == 0:
        instruction += """

【修复要求 - 第1次尝试】
1. 为每个缺失字段的函数生成 search_block + replace_block
2. search_block 必须是函数的完整当前代码（从 def 到函数结束）
3. replace_block 必须在返回字典中追加所有缺失的字段
4. 如果无法找到合适的 search_block，直接用 change_type="add" 输出完整文件内容

【重要】
- 不要省略任何缺失的字段
- 保留原有字段不变
- 新字段的值根据函数逻辑合理计算
"""
        force_full_file = False
    elif retry_attempt == max_retries - 2:
        instruction += """

【修复要求 - 第2次尝试】
由于第1次尝试失败，现在强制使用完整文件覆盖：
1. 使用 change_type="add" 输出完整文件内容
2. 确保所有函数返回字典包含所有必需字段
3. 不要输出 search_block/replace_block
4. 这是倒数第二次机会！
"""
        force_full_file = True
    else:
        instruction += """

【修复要求 - 最后机会】
这是最后一次尝试！必须成功：
1. 使用 change_type="add" 输出完整文件内容
2. 仔细检查每个函数的返回字典，确保包含所有必需字段
3. 如果仍然失败，整个工作将被拒绝
4. 系统会跳过静态检查，直接信任你的输出
"""
        force_full_file = True

    return instruction, force_full_file


def build_test_import_fix_instruction(import_errors: List[str]) -> str:
    """
    构建测试导入错误修复指令

    Args:
        import_errors: 导入错误列表

    Returns:
        修复指令字符串
    """
    return (
        f"测试文件存在以下导入错误，请修正 import 语句:\n\n"
        + "\n".join(import_errors)
        + "\n\n要求:\n"
        + "1. 只导入实际存在的模块和符号\n"
        + "2. 如果符号不存在，修改测试代码以使用正确的符号\n"
        + "3. 不要修改被测代码，只修改测试文件\n"
    )


def build_test_syntax_fix_instruction(syntax_errors: List[Dict]) -> str:
    """
    构建测试语法错误修复指令

    Args:
        syntax_errors: 语法错误列表

    Returns:
        修复指令字符串
    """
    instruction = "测试文件存在以下 Python 语法错误，请修正:\n\n"

    for err in syntax_errors:
        instruction += f"文件: {err.get('file', '')}\n"
        instruction += f"错误: {err.get('error', '')}\n"
        instruction += f"行号: {err.get('line', 0)}\n"
        instruction += f"附近代码:\n{err.get('context', '')}\n\n"

    instruction += """
要求:
1. 修复所有语法错误（缩进、括号匹配、冒号等）
2. 确保修复后的代码可以通过 python -m py_compile 检查
3. 只修改语法错误，不要改变测试逻辑
4. 保持原有的测试结构和断言
"""

    return instruction


def build_type_error_fix_instruction(type_errors: List) -> str:
    """
    构建类型错误修复指令（如 datetime mock 错误）

    Args:
        type_errors: 类型错误列表

    Returns:
        修复指令字符串
    """
    instruction = """修复测试文件中的类型错误。

检测到的错误：
"""
    for err in type_errors:
        instruction += f"- {err.message}\n"

    instruction += """

【重要修复要求】
1. 禁止直接 mock datetime.datetime.utcnow（datetime.datetime 是 C 扩展类型，不可变）
2. 使用以下正确方式之一：
   - 使用 freezegun 库: @freeze_time("2024-01-01")
   - 使用 unittest.mock.patch: with patch('datetime.datetime') as mock_dt:
   - 将 datetime 作为参数注入被测函数

3. 确保修复后的测试可以通过 python -m pytest 运行
4. 只修改测试文件，不要修改被测的源代码
"""

    return instruction


def build_contract_fix_instruction(missing_specs: List[Dict]) -> str:
    """
    构建契约修复指令

    Args:
        missing_specs: 缺失的契约规范列表

    Returns:
        修复指令字符串
    """
    symbol_details = []
    for spec in missing_specs:
        symbol_name = spec.get("symbol_name", "")
        module = spec.get("module", "")
        signature = spec.get("signature", "")
        symbol_type = spec.get("type", "")
        
        detail = f"  - 符号名: {symbol_name}"
        if module:
            detail += f"\n    所在文件: {module}"
        if symbol_type:
            detail += f"\n    类型: {symbol_type}"
        if signature:
            detail += f"\n    签名: {signature}"
        symbol_details.append(detail)
    
    symbol_list = "\n".join(symbol_details)
    
    return f"""【契约修复任务】以下 {len(missing_specs)} 个接口契约符号在代码中未定义，必须补全：

{symbol_list}

【关键要求】
1. 必须在指定文件中定义上述符号（函数、类或变量）
2. 符号名称必须与上述"符号名"完全一致，不能使用其他名称
3. 如果是变量（如 router），必须使用赋值语句定义，例如: `timestamp_router = APIRouter()`
4. 如果是函数，必须定义完整的函数体
5. 如果是类，必须定义完整的类

【完整契约详情】
{json.dumps(missing_specs, indent=2, ensure_ascii=False)}

请仅生成补全这些符号的代码变更，不要修改已有正确实现的代码。"""


def build_search_block_retry_instruction(
    file_path: str,
    current_content: str,
    replace_block: str
) -> str:
    """
    构建 search_block 重试指令

    Args:
        file_path: 文件路径
        current_content: 当前文件内容
        replace_block: 替换块

    Returns:
        修复指令字符串
    """
    return f"""文件 {file_path} 的 search_block 无法匹配当前文件内容。

当前文件的真实内容（部分）:
```python
{current_content[:2000]}
```

CoderAgent 原本想替换的 replace_block:
```python
{replace_block}
```

请基于当前文件的真实内容，重新生成正确的 search_block 和 replace_block。
要求：
1. search_block 必须从当前文件内容中逐字复制（包括空格和换行）
2. replace_block 实现原本想做的修改
3. 确保 search_block 在当前文件中确实存在
4. 如果无法找到合适的 search_block，可以直接返回完整的文件内容（content 字段）进行覆盖
"""


def build_key_mismatch_repair_instruction(key_mismatches: List[Dict]) -> str:
    """
    构建键名不匹配的修复指令（用于沙箱后检查）

    Args:
        key_mismatches: 键名不匹配列表

    Returns:
        修复指令字符串
    """
    instruction = "修复返回字段缺失问题:\n\n"
    for mismatch in key_mismatches:
        symbol = mismatch.get('symbol', '')
        missing = mismatch.get('missing_keys', [])
        instruction += f"- {symbol}: 缺少字段 {missing}\n"

    instruction += """

【强制要求】
1. 读取沙箱中的当前文件内容
2. 在对应函数的返回字典中**追加**缺失的字段
3. 使用 change_type: "add" 输出完整文件内容覆盖
4. 确保所有缺失字段都已添加
"""
    return instruction


def build_designer_alignment_fix_instruction(missing_criteria: List[str]) -> str:
    """
    构建 DesignerAgent 契约对齐修复指令

    Args:
        missing_criteria: 缺失的验收标准列表

    Returns:
        修复指令字符串
    """
    criteria_list = "\n".join([f"  - {c}" for c in missing_criteria])

    return f"""【契约对齐修复任务】

以下 {len(missing_criteria)} 条验收标准未被映射到接口契约：

{criteria_list}

【修复要求】
1. 在 contract_alignment 列表中，为每条缺失的验收标准添加对应的映射项
2. 每个映射项必须包含：
   - acceptance_criteria: 验收标准的原文（必须完全匹配）
   - interface_spec: 对应的接口规范（包含 symbol_name, module, signature 等）
3. 确保 interface_specs 中定义的符号能够实现对应的验收标准
4. 验收标准与接口契约的映射必须是 1:1 的，不能遗漏

【重要】
- contract_alignment 列表的长度必须等于验收标准的总数
- 每条验收标准必须在 contract_alignment 中有且仅有一个对应项
- 不要修改已经正确映射的验收标准

请重新生成完整的设计输出，确保所有验收标准都被正确映射。"""
