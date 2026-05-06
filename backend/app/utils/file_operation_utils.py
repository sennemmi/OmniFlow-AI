"""
文件操作工具函数

提供文件路径处理、内容操作等通用工具
"""

import difflib
import logging
from typing import Dict, List, Optional, Tuple

from app.service.sandbox_file_service import SandboxFileService

logger = logging.getLogger(__name__)


def normalize_file_path(file_path: str) -> str:
    """
    标准化文件路径，移除 backend/ 前缀和反斜杠

    Args:
        file_path: 原始文件路径

    Returns:
        标准化后的文件路径
    """
    return file_path.replace("backend/", "").replace("backend\\", "").replace("\\", "/")


def clean_backend_prefix(file_path: str) -> str:
    """
    移除 backend/ 前缀和开头的斜杠

    Args:
        file_path: 原始文件路径

    Returns:
        清理后的文件路径
    """
    return file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")


def group_files_by_change_type(code_files: List[Dict]) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
    """
    按 change_type 对文件进行分组

    Args:
        code_files: 代码文件列表

    Returns:
        (merged_by_file, add_files) - modify 文件按路径分组，add 文件单独列表
    """
    merged_by_file: Dict[str, List[Dict]] = {}
    add_files: List[Dict] = []

    for fc in code_files:
        fp = normalize_file_path(fc.get("file_path", ""))
        change_type = fc.get("change_type")

        if change_type == "add":
            add_files.append(fc)
        elif change_type == "modify":
            if fp not in merged_by_file:
                merged_by_file[fp] = []
            merged_by_file[fp].append(fc)

    return merged_by_file, add_files


async def apply_modify_with_fallback(
    file_service: SandboxFileService,
    file_path: str,
    search_block: str,
    replace_block: str,
    current_content: str,
    retry_callback: Optional[callable] = None
) -> Tuple[bool, str]:
    """
    应用 modify 操作，支持自适应匹配回退和重试

    Args:
        file_service: 文件服务
        file_path: 文件路径
        search_block: 搜索块
        replace_block: 替换块
        current_content: 当前文件内容
        retry_callback: 重试回调函数，当 search_block 不匹配时调用

    Returns:
        (success, new_content) - 是否成功，新内容
    """
    if not search_block:
        return False, current_content

    if search_block in current_content:
        new_content = current_content.replace(search_block, replace_block, 1)
        return True, new_content

    # 自适应匹配
    current_lines = current_content.splitlines(keepends=True)
    search_lines = search_block.splitlines(keepends=True)

    best_match_start = -1
    best_ratio = 0.0
    min_match_len = len(search_lines)

    if len(current_lines) < min_match_len:
        # 自适应匹配失败，尝试重试
        if retry_callback:
            return await retry_callback(file_path, search_block, replace_block, current_content)
        return False, current_content

    for i in range(len(current_lines) - min_match_len + 1):
        window = ''.join(current_lines[i:i + min_match_len])
        ratio = difflib.SequenceMatcher(None, search_block, window).ratio()
        if ratio > best_ratio and ratio > 0.6:
            best_ratio = ratio
            best_match_start = i

    if best_match_start >= 0:
        actual_match = ''.join(current_lines[best_match_start:best_match_start + len(search_lines)])
        if actual_match.strip():
            new_content = current_content.replace(actual_match, replace_block, 1)
            return True, new_content

    # 自适应匹配失败，尝试重试
    if retry_callback:
        return await retry_callback(file_path, search_block, replace_block, current_content)

    return False, current_content


async def merge_and_write_files(
    code_files: List[Dict],
    file_service: SandboxFileService,
    retry_callback: Optional[callable] = None
) -> tuple[int, List[str]]:
    """
    合并并写入文件（处理 modify 和 add）

    Args:
        code_files: 代码文件列表
        file_service: 文件服务
        retry_callback: search_block 不匹配时的重试回调函数

    Returns:
        (成功写入的文件数, 失败的变更列表)
    """
    written_count = 0
    failed_changes: List[str] = []
    merged_by_file, add_files = group_files_by_change_type(code_files)

    print(f"   [文件写入] 开始处理: {len(merged_by_file)} 个 modify 文件, {len(add_files)} 个 add 文件")

    # 处理 modify 文件
    for fp, changes in merged_by_file.items():
        print(f"   [文件写入] 处理 modify: {fp} (共 {len(changes)} 个变更)")
        read_r = await file_service.read_file(fp)
        if not read_r.exists:
            logger.warning(f"跳过 modify: {fp} (文件不存在)")
            print(f"   ⚠️ 跳过 modify: {fp} (文件不存在)")
            failed_changes.append(f"modify 失败: {fp} 不存在")
            continue

        current_content = read_r.content
        print(f"   [文件写入] 读取原文件: {fp} ({len(current_content)} 字符)")
        file_modified = False

        for i, fc in enumerate(changes, 1):
            search_block = fc.get("search_block", "")
            replace_block = fc.get("replace_block", "")
            content = fc.get("content", "")

            print(f"   [文件写入] 应用变更 {i}/{len(changes)}: search_block={bool(search_block)}, content={bool(content)}")

            if search_block:
                success, new_content = await apply_modify_with_fallback(
                    file_service, fp, search_block, replace_block, current_content, retry_callback
                )
                if success:
                    current_content = new_content
                    file_modified = True
                    print(f"   ✅ modify(搜索替换): {fp}")
                else:
                    # 记录失败，不再静默跳过
                    failed_changes.append(
                        f"modify 失败: {fp} 的 search_block 无法匹配\n"
                        f"  search_block 前50字符: {repr(search_block[:50])}"
                    )
                    print(f"   ❌ modify(搜索块不匹配): {fp}")
            elif content:
                current_content = content
                file_modified = True
                print(f"   ✅ modify(完整覆盖): {fp}")

        if file_modified:
            await file_service.write_file(fp, current_content)
            written_count += 1
            print(f"   [文件写入] 已写入: {fp} ({len(current_content)} 字符)")

    # 处理 add 文件
    for fc in add_files:
        fp = normalize_file_path(fc.get("file_path", ""))
        content = fc.get("content", "")
        if content:
            await file_service.write_file(fp, content)
            written_count += 1
            print(f"   ✅ add: {fp} ({len(content)} 字符)")
        else:
            logger.warning(f"⚠️ 跳过 add: {fp} (无 content)")
            print(f"   ⚠️ 跳过 add: {fp} (无 content)")
            failed_changes.append(f"add 失败: {fp} 无 content")

    # 处理 delete 类型（仅记录，不执行）
    for fc in code_files:
        if fc.get("change_type") == "delete":
            fp = normalize_file_path(fc.get("file_path", ""))
            logger.warning(f"⚠️ 跳过 delete: {fp} (测试环境不支持删除)")
            print(f"   ⚠️ 跳过 delete: {fp} (测试环境不支持删除)")

    print(f"   [文件写入] 总计: {written_count} 个文件写入成功 (合并了 {len(merged_by_file)} 个文件的多项修改)")
    if failed_changes:
        print(f"   [文件写入] 失败: {len(failed_changes)} 个变更")
    return written_count, failed_changes


def extract_function_source(content: str, func_name: str) -> Optional[str]:
    """
    从代码内容中提取函数源代码

    Args:
        content: Python 代码内容
        func_name: 函数名

    Returns:
        函数源代码或 None
    """
    import re

    func_pattern = rf"(async\s+)?def\s+{re.escape(func_name)}\s*\([^)]*\)(\s*->\s*[^:]+)?:\s*\n"
    match = re.search(func_pattern, content)

    if not match:
        return None

    start_idx = match.start()
    lines = content[start_idx:].split('\n')
    func_lines = [lines[0]]

    if len(lines) > 1:
        base_indent = len(lines[1]) - len(lines[1].lstrip())
        for i, line in enumerate(lines[1:], 1):
            if line.strip() and not line.startswith(' ' * base_indent) and not line.startswith('\t'):
                if line.strip().startswith(('def ', 'class ', '@')):
                    break
            func_lines.append(line)

    return '\n'.join(func_lines)


def build_fix_instruction_with_context(
    error_files: Dict[str, str],
    syntax_errors: List[Dict],
    force_full_file: bool = False
) -> str:
    """
    构建带上下文的修复指令

    Args:
        error_files: 错误文件字典 {file_path: content}
        syntax_errors: 语法错误列表
        force_full_file: 是否强制完整文件

    Returns:
        修复指令字符串
    """
    instruction = f"""你是一个代码修复专家。以下文件存在 Python 语法错误，你必须修复它。

【强制规则 - 违反会导致修复失败】
1. {'输出完整的文件内容（change_type="add"），禁止输出 search_block/replace_block' if force_full_file else '优先使用完整文件覆盖（change_type="add"），如果必须用 modify，确保 search_block 精确匹配'}
2. 仅修复语法错误（删除多余括号、补齐缺失括号、修正缩进等）
3. 不要修改任何业务逻辑、函数名、变量名
4. 确保修复后的代码可以通过 python -m py_compile 检查
5. 【极其重要】每个 Python 文件的最后一行必须是换行符（\n），否则会导致语法错误！

【常见语法错误类型】
- 多余括号：}} 或 ) 或 ] 重复
- 缺失括号：{{ 或 ( 或 [ 不匹配
- 缩进错误：混用空格和 Tab
- 冒号缺失：if/for/while/def/class 语句后缺少 :
- 缺少换行：文件末尾没有换行符（特别是 if __name__ == "__main__": 语句前）
- 字符串未闭合：' 或 " 不匹配

【错误详情】
"""

    for err in syntax_errors:
        fp = err.get("file", "")
        error_msg = err.get("error", "")
        line_no = err.get("line", 0)

        instruction += f"\n文件: {fp}\n"
        instruction += f"  错误: {error_msg}\n"
        instruction += f"  行号: {line_no}\n"

        if fp in error_files:
            content = error_files[fp]
            lines = content.splitlines()
            if 0 < line_no <= len(lines):
                context_start = max(0, line_no - 5)
                context_end = min(len(lines), line_no + 3)
                instruction += f"  上下文:\n"
                for i in range(context_start, context_end):
                    marker = ">>> " if i == line_no - 1 else "    "
                    line_content = lines[i] if i < len(lines) else "<空行>"
                    # 显示行尾空格和换行问题
                    visible_content = line_content.replace(' ', '·')
                    instruction += f"{marker}{i+1}: {visible_content}\n"
                
                # 【新增】针对特定错误的详细分析
                if line_no > 0 and line_no <= len(lines):
                    current_line = lines[line_no - 1]
                    instruction += f"\n  【错误分析】\n"
                    
                    # 分析括号匹配
                    open_brackets = current_line.count('(') + current_line.count('[') + current_line.count('{')
                    close_brackets = current_line.count(')') + current_line.count(']') + current_line.count('}')
                    if open_brackets != close_brackets:
                        instruction += f"    ⚠️ 括号不匹配: 开括号 {open_brackets} 个, 闭括号 {close_brackets} 个\n"
                    
                    # 分析缩进
                    if current_line.strip():
                        leading_spaces = len(current_line) - len(current_line.lstrip())
                        if leading_spaces % 4 != 0:
                            instruction += f"    ⚠️ 缩进可能错误: {leading_spaces} 个空格（应为4的倍数）\n"
                    
                    # 检查行尾
                    if current_line.rstrip() != current_line:
                        instruction += f"    ⚠️ 行尾有多余空格\n"
                    
                    # 检查特定语法结构
                    if 'if __name__' in current_line and not current_line.strip().endswith(':'):
                        instruction += f"    ⚠️ if __name__ 语句缺少冒号\n"
                    
                    # 检查上一行（可能是缺少换行）
                    if line_no > 1:
                        prev_line = lines[line_no - 2]
                        if prev_line.strip() and not prev_line.rstrip().endswith((':', '{', '[', '(', '\\', ')', ']', '}')):
                            if current_line.strip().startswith(('if ', 'for ', 'while ', 'def ', 'class ', 'elif ', 'else:', 'except', 'finally:')):
                                instruction += f"    ⚠️ 第 {line_no-1} 行和第 {line_no} 行之间可能缺少换行符\n"

    instruction += f"""
【原始文件内容】
"""
    for fp, content in error_files.items():
        instruction += f"\n=== {fp} ===\n"
        # 显示带行号的内容，并标记行尾
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            # 标记行尾空格
            if line.rstrip() != line:
                line = line.rstrip() + "␣␣␣"  # 标记多余空格
            instruction += f"{i:4d}: {line}\n"
        # 检查文件末尾是否有换行
        if content and not content.endswith('\n'):
            instruction += "⚠️ 文件末尾缺少换行符！\n"
        instruction += "\n"

    if force_full_file:
        instruction += """
【逃生舱模式 - 极其重要】
由于前几次修复失败，现在进入强制完整文件覆盖模式（如果你需要修改的文件极长，请酌情使用 modify）：
1. 必须输出 change_type="add" 和完整的 content
2. 不要输出 search_block 或 replace_block
3. 仔细检查所有括号是否匹配（每有一个 { 必须有一个 }）
4. 【关键】确保文件内容以换行符（\n）结尾
5. 这是最后一次机会，如果仍然失败，工作将被拒绝！
6. 【重要】如果文件超过 300 行或 6000 字符，不要使用 add 模式输出完整内容，改用 modify 模式分段修复

【修复 checklist】
□ 所有括号 {} () [] 都正确匹配
□ 所有 if/for/while/def/class 语句后都有冒号
□ 缩进使用4个空格，没有混用 Tab
□ 字符串引号 ' 或 " 正确闭合
□ 文件末尾有换行符
□ 修复后的代码可以通过 python -m py_compile 检查
"""
    else:
        instruction += """
【修复 checklist】
□ 准确定位语法错误位置
□ 只修改语法错误，不改动业务逻辑
□ 确保 search_block 精确匹配（如果使用 modify）
□ 文件末尾有换行符
"""

    return instruction
