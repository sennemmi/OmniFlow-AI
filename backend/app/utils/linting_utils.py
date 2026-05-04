"""
Linting 工具函数

提供统一的 Linting 检查和自动修复功能
与 E2E 测试脚本和 Pipeline 保持一致
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Tuple, Optional, Callable
import inspect

from app.service.sandbox_manager import sandbox_manager

logger = logging.getLogger(__name__)


async def run_linting_check(
    code_files: List[Dict],
    pipeline_id: int,
    max_retries: int = 3,
    log_callback: Optional[Callable[[str, str], Any]] = None,
    enabled: bool = True
) -> Tuple[bool, List[Dict]]:
    """
    运行 Linting 检查并尝试自动修复
    
    【与 E2E 测试脚本保持一致】
    
    Args:
        code_files: 代码文件列表
        pipeline_id: Pipeline ID
        max_retries: 最大修复重试次数
        log_callback: 日志回调函数 (level, message) -> None
        enabled: 是否启用 Linting 检查
        
    Returns:
        (是否通过, 错误信息列表)
    """
    if not enabled:
        return True, []
    
    async def log(level: str, message: str):
        if log_callback:
            # 检查回调是否是异步函数
            if inspect.iscoroutinefunction(log_callback):
                await log_callback(level, message)
            else:
                log_callback(level, message)
        else:
            getattr(logger, level.lower(), logger.info)(message)
    
    await log("info", "🔍 运行 Linting 检查...")
    
    # 尝试运行 ruff 检查
    linting_errors = []
    checked_files = set()  # 用于去重，避免重复检查同一文件
    
    for file_obj in code_files:
        file_path = file_obj.get("file_path", "")
        if not file_path.endswith(".py"):
            continue
            
        # 转换为沙箱中的路径（相对于 /workspace/backend）
        if file_path.startswith("backend/"):
            sandbox_path = file_path
            normalized_path = file_path
        else:
            sandbox_path = f"backend/{file_path}"
            normalized_path = sandbox_path
        
        # 去重检查：如果已经检查过这个文件，跳过
        if normalized_path in checked_files:
            continue
        checked_files.add(normalized_path)
        
        # 尝试运行 ruff check
        try:
            result = await sandbox_manager.exec(
                pipeline_id,
                f"cd /workspace && ruff check {sandbox_path} --output-format=json 2>&1 || true",
                timeout=30
            )
            
            if result.stdout:
                try:
                    errors = json.loads(result.stdout)
                    if errors:
                        # 过滤掉 "文件不存在" 错误 (E902) 和语法错误无法自动修复的
                        real_errors = [e for e in errors if e.get("code") not in ("E902",)]
                        # 过滤掉 invalid-syntax 错误
                        real_errors = [e for e in real_errors if "invalid-syntax" not in str(e.get("code", "")).lower()]
                        if real_errors:
                            linting_errors.append({
                                "file": file_path,
                                "sandbox_path": sandbox_path,
                                "errors": real_errors
                            })
                except json.JSONDecodeError:
                    pass
                    
        except Exception as e:
            await log("warning", f"Linting 检查失败 {file_path}: {e}")
    
    if not linting_errors:
        await log("info", "✅ Linting 检查通过")
        return True, []
        
    await log("warning", f"发现 {len(linting_errors)} 个文件有 Linting 错误")
    
    # 尝试自动修复
    for attempt in range(max_retries):
        await log("info", f"🔄 Linting 自动修复尝试 {attempt + 1}/{max_retries}...")
        
        try:
            # 使用 set 去重，避免重复修复同一文件
            fixed_paths = set()
            for error_info in linting_errors:
                sandbox_path = error_info.get("sandbox_path", error_info["file"])
                
                # 去重：如果已经修复过这个文件，跳过
                if sandbox_path in fixed_paths:
                    continue
                fixed_paths.add(sandbox_path)
                
                # 运行 ruff fix
                fix_result = await sandbox_manager.exec(
                    pipeline_id,
                    f"cd /workspace && ruff check {sandbox_path} --fix 2>&1 || true",
                    timeout=30
                )
                
                output = fix_result.stdout[:200] if fix_result.stdout else "无输出"
                # 过滤掉文件不存在的错误信息和语法错误
                if "E902" not in output and "invalid-syntax" not in output.lower():
                    await log("info", f"修复 {sandbox_path}: {output}")
                
            # 重新检查
            remaining_errors = []
            checked_remaining = set()  # 去重集合
            for error_info in linting_errors:
                sandbox_path = error_info.get("sandbox_path", error_info["file"])
                
                # 去重
                if sandbox_path in checked_remaining:
                    continue
                checked_remaining.add(sandbox_path)
                
                result = await sandbox_manager.exec(
                    pipeline_id,
                    f"cd /workspace && ruff check {sandbox_path} --output-format=json 2>&1 || true",
                    timeout=30
                )
                
                if result.stdout:
                    try:
                        errors = json.loads(result.stdout)
                        if errors:
                            # 过滤掉 "文件不存在" 错误和语法错误
                            real_errors = [e for e in errors if e.get("code") not in ("E902",)]
                            real_errors = [e for e in real_errors if "invalid-syntax" not in str(e.get("code", "")).lower()]
                            if real_errors:
                                remaining_errors.append({
                                    "file": error_info["file"],
                                    "sandbox_path": sandbox_path,
                                    "errors": real_errors
                                })
                    except json.JSONDecodeError:
                        pass
            
            if not remaining_errors:
                await log("info", "✅ Linting 修复完成")
                return True, []
                
            linting_errors = remaining_errors
            
        except Exception as e:
            await log("warning", f"Linting 自动修复失败: {e}")
            break
    
    if linting_errors:
        await log("warning", f"Linting 检查后仍有 {len(linting_errors)} 个文件有问题")
        for err in linting_errors:
            await log("warning", f"  - {err['file']}: {len(err['errors'])} 个错误")
    
    # 返回 True 允许继续，但记录警告
    return True, linting_errors
