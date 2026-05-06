"""
修复循环工具

提供各类自动修复循环的通用逻辑
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from app.agents.coder import coder_agent, CoderAgent, CoderOutput
from app.agents.tester import tester_agent
from app.service.sandbox_file_service import SandboxFileService

if TYPE_CHECKING:
    from app.utils.agent_debug_utils import AgentDebugger

logger = logging.getLogger(__name__)


async def run_syntax_fix_loop(
    syntax_errors: List[Dict],
    files_to_check: List[Tuple[str, str]],
    file_service: SandboxFileService,
    design_output: Dict,
    max_retries: int = 3,
    debugger: Optional["AgentDebugger"] = None,
    coder_system_prompt: Optional[str] = None,
    pipeline_id: Optional[int] = None,
) -> Dict[str, str]:
    """
    运行语法错误修复循环

    Args:
        syntax_errors: 语法错误列表
        files_to_check: 待检查文件列表 [(file_path, content), ...]
        file_service: 文件服务
        design_output: 设计输出
        max_retries: 最大重试次数
        pipeline_id: Pipeline ID（用于沙箱内语法检查）

    Returns:
        修复后的文件字典 {file_path: content}
    """
    from app.service.code_validation_service import code_validation_service
    from app.utils.file_operation_utils import build_fix_instruction_with_context

    fixed_files = {}

    for attempt in range(max_retries):
        logger.info(f"语法错误自动修复 第 {attempt + 1}/{max_retries} 次")

        # 收集错误文件
        error_files = {}
        for err in syntax_errors:
            fp = err.get("file", "")
            if fp:
                for check_fp, content in files_to_check:
                    if check_fp == fp:
                        error_files[fp] = content
                        break

        if not error_files:
            logger.info("没有需要修复的语法错误文件")
            return fixed_files

        # 构建修复指令
        force_full_file = attempt >= 1
        fix_instruction = build_fix_instruction_with_context(
            error_files, syntax_errors, force_full_file
        )

        # 构建定向设计输出
        # 【修复】保留 interface_specs 和 required_symbols，让 CoderAgent 在修复语法错误时仍有契约约束
        # 【新增】添加 syntax_fix_mode 标识，让 CoderAgent 知道这是语法修复模式
        targeted_design = {
            **design_output,
            "affected_files": list(error_files.keys()),
            "fix_mode": True,
            "syntax_fix_mode": True,  # 明确告知 CoderAgent 这是语法修复模式
            "force_full_file": force_full_file,
            "fix_instruction": fix_instruction,
            "syntax_errors": syntax_errors
        }

        # 调用 CoderAgent
        fix_input = {
            "design_output": targeted_design,
            "pipeline_id": design_output.get("pipeline_id", 0),
            "injected_files": error_files,
            "error_context": fix_instruction
        }
        fix_result = await coder_agent.generate_code(**fix_input)

        # 保存调试信息
        if debugger:
            debugger.save_agent_io(
                agent_name="CoderAgent",
                stage="syntax_fix",
                input_data=fix_input,
                output_data=fix_result,
                metadata={"attempt": attempt + 1, "max_retries": max_retries},
                success=fix_result.get("success", False),
                error=fix_result.get("error"),
                tool_calls=fix_result.get("tool_results", []),
                system_prompt=coder_system_prompt
            )

        if not fix_result.get("success"):
            logger.warning(f"CoderAgent 语法修复调用失败: {fix_result.get('error')}")
            continue

        # 处理修复结果
        fix_output = fix_result.get("output", {})
        fix_files = _extract_files_from_output(fix_output)

        if not fix_files:
            logger.warning("CoderAgent 未生成任何修复文件")
            continue

        # 应用修复
        for fc in fix_files:
            fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
            change_type = fc.get("change_type")
            search_block = fc.get("search_block", "")
            replace_block = fc.get("replace_block", "")
            content = fc.get("content", "")

            if force_full_file and change_type != "add":
                continue

            current_content = error_files.get(fp, "")
            new_content = None

            if change_type == "modify" and search_block and current_content:
                new_content = current_content.replace(search_block, replace_block, 1)

                # 【修复】检测 search_block 是否匹配成功
                if new_content == current_content:
                    logger.warning(f"search_block 未匹配到内容: {fp}，尝试使用全量替换")
                    # 降级策略1：如果提供了 content，使用全量替换
                    if content and content != current_content:
                        new_content = content
                    # 降级策略2：检查 replace_block 是否像完整文件
                    elif _looks_like_complete_file(replace_block):
                        logger.info(f"使用 replace_block 作为完整文件内容: {fp}")
                        new_content = replace_block
                    else:
                        logger.warning(f"未提供有效的全量替换内容，跳过: {fp}")
                        continue
            elif content:
                new_content = content

            if not new_content:
                logger.warning(f"没有生成有效内容: {fp}")
                # 【关键修复】当没有生成有效内容时，记录为修复失败
                # 但不立即退出，让后续的统一错误检查来处理
                continue

            # 【关键修复1】将修复后的内容写入沙箱，并检查返回值
            write_result = await file_service.write_file(fp, new_content)
            if not write_result.get("success"):
                logger.error(f"写入沙箱失败: {fp} - {write_result.get('error')}")
                continue

            # 【关键修复2】回读验证 - 确保写入成功
            read_result = await file_service.read_file(fp)
            if not read_result.exists:
                logger.error(f"回读文件失败: {fp}")
                continue

            actual_content = read_result.content
            if actual_content != new_content:
                logger.error(f"写入验证失败: {fp} - 内容不匹配")
                logger.debug(f"期望长度: {len(new_content)}, 实际长度: {len(actual_content)}")
                # 使用实际内容继续
                new_content = actual_content

            # 【关键修复3】使用沙箱内语法检查（避免宿主机编码问题）
            check_result = await code_validation_service.check_syntax_in_sandbox(
                file_path=fp,
                pipeline_id=pipeline_id,
                content=new_content
            )

            # 更新内存中的文件内容（使用回读后的实际内容）
            _update_files_to_check(files_to_check, fp, new_content)

            if not check_result:
                fixed_files[fp] = new_content
                logger.info(f"语法修复成功: {fp}")
            else:
                logger.warning(f"修复后仍有语法错误: {fp} - {check_result.error}")

        # 【关键修复4】检查剩余错误时，使用沙箱内语法检查
        remaining_errors = await _check_remaining_syntax_errors(
            syntax_errors, file_service, pipeline_id
        )

        if not remaining_errors:
            logger.info("所有语法错误修复成功！")
            return fixed_files

        syntax_errors = remaining_errors

    return fixed_files


async def run_test_import_fix_loop(
    test_files: List[Dict],
    import_errors: List[str],
    file_service: SandboxFileService,
    design_output: Dict,
    code_output: Dict,
    max_retries: int = 2,
    debugger: Optional["AgentDebugger"] = None,
    tester_system_prompt: Optional[str] = None
) -> bool:
    """
    运行测试导入错误修复循环

    Args:
        test_files: 测试文件列表
        import_errors: 导入错误列表
        file_service: 文件服务
        design_output: 设计输出
        code_output: 代码输出
        max_retries: 最大重试次数

    Returns:
        是否修复成功
    """
    from app.service.code_validation_service import CodeValidationService
    from app.utils.agent_instruction_utils import build_test_import_fix_instruction
    from app.utils.file_operation_utils import normalize_file_path

    validation_service = CodeValidationService()

    for attempt in range(max_retries):
        logger.info(f"导入错误修复 第 {attempt + 1}/{max_retries} 次")

        fix_instruction = build_test_import_fix_instruction(import_errors)

        # 读取当前测试文件
        injected_files = {}
        for tf in test_files:
            fp = normalize_file_path(tf.get("file_path", ""))
            read_res = await file_service.read_file(fp)
            if read_res.exists:
                injected_files[fp] = read_res.content

        # 调用 TesterAgent
        fix_input = {
            "design_output": {
                **design_output,
                "fix_mode": True,
                "fix_instruction": fix_instruction,
                "existing_test_files": test_files
            },
            "code_output": code_output,
            "pipeline_id": design_output.get("pipeline_id", 0)
        }
        fix_result = await tester_agent.generate_tests(**fix_input)

        # 保存调试信息
        if debugger:
            debugger.save_agent_io(
                agent_name="TesterAgent",
                stage="import_fix",
                input_data=fix_input,
                output_data=fix_result,
                metadata={"attempt": attempt + 1, "max_retries": max_retries, "import_errors": import_errors},
                success=fix_result.get("success", False),
                error=fix_result.get("error"),
                tool_calls=fix_result.get("tool_results", []),
                system_prompt=tester_system_prompt
            )

        if not fix_result.get("success"):
            logger.warning(f"TesterAgent 修复调用失败: {fix_result.get('error')}")
            continue

        fixed_test_files = fix_result.get("output", {}).get("test_files", [])

        if not fixed_test_files:
            logger.warning("TesterAgent 未生成修复后的测试文件")
            continue

        # 写入修复后的文件
        for tf in fixed_test_files:
            fp = tf.get("file_path", "")
            content = tf.get("content", "")
            if content:
                await file_service.write_file(fp, content)

        # 重新验证
        remaining_errors = await validation_service.validate_test_imports(
            fixed_test_files, file_service
        )

        if not remaining_errors:
            logger.info("所有导入错误已修复")
            return True

        import_errors = remaining_errors
        test_files = fixed_test_files

    return False


async def run_test_syntax_fix_loop(
    test_files: List[Dict],
    syntax_errors: List[Dict],
    file_service: SandboxFileService,
    design_output: Dict,
    code_output: Dict,
    max_retries: int = 2,
    debugger: Optional["AgentDebugger"] = None,
    tester_system_prompt: Optional[str] = None
) -> List[Dict]:
    """
    运行测试语法错误修复循环

    Args:
        test_files: 测试文件列表
        syntax_errors: 语法错误列表
        file_service: 文件服务
        design_output: 设计输出
        code_output: 代码输出
        max_retries: 最大重试次数

    Returns:
        修复后的测试文件列表
    """
    from app.service.code_validation_service import CodeValidationService
    from app.utils.agent_instruction_utils import build_test_syntax_fix_instruction

    validation_service = CodeValidationService()

    for attempt in range(max_retries):
        logger.info(f"测试语法错误修复 第 {attempt + 1}/{max_retries} 次")

        fix_instruction = build_test_syntax_fix_instruction(syntax_errors)

        fix_input = {
            "design_output": {
                **design_output,
                "fix_mode": True,
                "fix_instruction": fix_instruction,
                "existing_test_files": test_files
            },
            "code_output": code_output,
            "pipeline_id": design_output.get("pipeline_id", 0)
        }
        fix_result = await tester_agent.generate_tests(**fix_input)

        # 保存调试信息
        if debugger:
            debugger.save_agent_io(
                agent_name="TesterAgent",
                stage="test_syntax_fix",
                input_data=fix_input,
                output_data=fix_result,
                metadata={"attempt": attempt + 1, "max_retries": max_retries, "syntax_errors": syntax_errors},
                success=fix_result.get("success", False),
                error=fix_result.get("error"),
                tool_calls=fix_result.get("tool_results", []),
                system_prompt=tester_system_prompt
            )

        if not fix_result.get("success"):
            logger.warning(f"TesterAgent 语法修复调用失败: {fix_result.get('error')}")
            continue

        fixed_test_files = fix_result.get("output", {}).get("test_files", [])

        if not fixed_test_files:
            logger.warning("TesterAgent 未生成修复后的测试文件")
            continue

        # 写入修复后的文件
        for tf in fixed_test_files:
            fp = tf.get("file_path", "")
            content = tf.get("content", "")
            if content:
                await file_service.write_file(fp, content)

        # 重新验证语法
        remaining_errors = await validation_service.check_syntax_with_py_compile(
            [{"file_path": tf.get("file_path", ""), "change_type": "add", "content": tf.get("content", "")}
             for tf in fixed_test_files],
            file_service
        )

        if not remaining_errors:
            logger.info("所有测试语法错误已修复")
            return fixed_test_files

        syntax_errors = [err.to_dict() for err in remaining_errors]
        test_files = fixed_test_files

    return test_files


def _extract_files_from_output(output: Any) -> List[Dict]:
    """从 Agent 输出中提取文件列表"""
    if isinstance(output, CoderOutput):
        return [f.model_dump() for f in output.files]
    elif isinstance(output, dict):
        return output.get("files", [])
    return []


def _looks_like_complete_file(code: str) -> bool:
    """
    简单判断一个代码块是否像是完整的 Python 文件（包含导入或函数定义）
    
    用于 search_block 匹配失败时的回退策略
    """
    if not code or not isinstance(code, str):
        return False
    
    lines = code.strip().splitlines()
    if len(lines) < 2:
        return False
    
    # 检查是否包含 import 或 def 或 class 关键字
    has_import = any(
        line.lstrip().startswith('import ') or line.lstrip().startswith('from ')
        for line in lines
    )
    has_def = any('def ' in line or 'class ' in line for line in lines)
    
    return has_import or has_def


def _update_files_to_check(files_to_check: List[Tuple[str, str]], file_path: str, new_content: str):
    """更新 files_to_check 中的文件内容"""
    for i, (check_fp, _) in enumerate(files_to_check):
        if check_fp == file_path:
            files_to_check[i] = (file_path, new_content)
            break


async def _check_remaining_syntax_errors(
    syntax_errors: List[Dict],
    file_service: SandboxFileService,
    pipeline_id: Optional[int] = None,
) -> List[Dict]:
    """
    检查剩余的语法错误
    
    【关键修复】使用沙箱内语法检查，避免宿主机编码问题
    """
    from app.service.code_validation_service import code_validation_service
    
    remaining = []
    checked_files = set()
    
    for err in syntax_errors:
        fp = err.get("file", "")
        if fp in checked_files:
            continue
        checked_files.add(fp)
        
        # 【关键】从沙箱重新读取文件内容
        read_result = await file_service.read_file(fp)
        if not read_result.exists:
            logger.warning(f"无法读取文件进行语法检查: {fp}")
            remaining.append(err)
            continue
            
        check_content = read_result.content
        
        if check_content:
            # 使用沙箱内语法检查
            check_result = await code_validation_service.check_syntax_in_sandbox(
                file_path=fp,
                pipeline_id=pipeline_id,
                content=check_content
            )
            if check_result:
                logger.warning(f"仍有语法错误: {fp} - {check_result.error}")
                remaining.append({
                    "file": fp,
                    "error": check_result.error,
                    "line": check_result.line
                })
        else:
            logger.warning(f"文件内容为空: {fp}")
            remaining.append(err)

    return remaining
