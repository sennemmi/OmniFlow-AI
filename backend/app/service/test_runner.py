"""
测试执行服务
在指定目录下运行 pytest 并捕获结果

核心功能：
1. 安全执行 shell 命令（pytest）
2. 捕获 stdout/stderr 输出
3. 解析测试结果
4. 支持超时控制
5. 智能错误分析（语法错误 vs 测试失败）
"""

import asyncio
import os
from typing import Dict, Any, Optional, List
from pathlib import Path


class TestRunnerService:
    """测试执行器：在指定目录下运行 pytest 并捕获结果"""

    @classmethod
    async def run_tests(
        cls,
        project_path: str,
        timeout: int = 60,
        test_path: Optional[str] = None,
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        异步执行 pytest

        Args:
            project_path: 项目根目录路径
            timeout: 超时时间（秒）
            test_path: 指定测试文件/目录路径（相对于 project_path）
            verbose: 是否使用详细输出模式

        Returns:
            Dict: {
                "success": bool,           # 测试是否全部通过
                "exit_code": int,          # pytest 退出码
                "logs": str,               # 完整日志输出
                "summary": str,            # 简要总结
                "error": Optional[str],    # 错误信息（如果有）
                "error_type": Optional[str],  # 错误类型: syntax_error, import_error, test_failure, collection_error
                "failed_tests": List[str]  # 失败的测试列表
            }
        """
        # 确保在正确的目录下执行
        cwd = Path(project_path).resolve()

        if not cwd.exists():
            return {
                "success": False,
                "exit_code": -1,
                "logs": f"",
                "summary": "Project path does not exist",
                "error": f"Project path does not exist: {project_path}",
                "error_type": "path_error",
                "failed_tests": []
            }

        # 【新增补丁】强制创建 __init__.py 确保 Python 识别路径
        # 先确保目录存在，再创建 __init__.py
        cwd.mkdir(parents=True, exist_ok=True)
        (cwd / "__init__.py").touch(exist_ok=True)

        tests_dir = cwd / "tests"
        if tests_dir.exists() or not tests_dir.exists():
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "__init__.py").touch(exist_ok=True)

        # 构造命令 - 使用 python -m pytest 更可靠
        # -v: 详细模式
        # --tb=long: 长堆栈打印，获取更详细的错误信息
        # --color=no: 禁用颜色代码，便于解析
        cmd = ["python", "-m", "pytest"]

        if verbose:
            cmd.append("-v")

        # 使用 long traceback 获取更详细的错误信息
        cmd.extend(["--tb=long", "--color=no"])

        # 如果指定了测试路径，添加到命令
        if test_path:
            cmd.append(test_path)

        try:
            # 准备环境变量 - 将当前工作区路径加入 PYTHONPATH
            env = os.environ.copy()
            # 关键：将当前工作区路径加入 PYTHONPATH，确保 Python 能找到本地模块
            env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")

            # 使用 asyncio 创建子进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env  # <--- 注入环境变量
            )

            # 等待执行完成，带超时
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            # 解码输出
            logs = stdout.decode('utf-8', errors='replace')
            error_logs = stderr.decode('utf-8', errors='replace')

            # 合并输出
            full_logs = logs
            if error_logs:
                full_logs += "\n" + error_logs

            # 判断成功：exit_code == 0 表示所有测试通过
            success = (process.returncode == 0)

            # 提取总结信息
            summary = cls._extract_summary(full_logs)

            # 分析错误类型（仅在失败时）
            error_type = cls._analyze_error_type(full_logs) if not success else None

            # 提取失败的测试
            failed_tests = cls._extract_failed_tests(full_logs) if not success else []

            return {
                "success": success,
                "exit_code": process.returncode,
                "logs": full_logs,
                "summary": summary,
                "error": None if success else cls._extract_error_message(full_logs),
                "error_type": error_type,
                "failed_tests": failed_tests
            }

        except asyncio.TimeoutError:
            # 超时处理：尝试终止进程
            try:
                process.kill()
                await process.wait()
            except:
                pass

            return {
                "success": False,
                "exit_code": -1,
                "logs": "Test execution timed out",
                "summary": f"Tests timed out after {timeout} seconds",
                "error": f"Test execution timed out after {timeout} seconds",
                "error_type": "timeout",
                "failed_tests": []
            }

        except FileNotFoundError:
            # pytest 未安装
            return {
                "success": False,
                "exit_code": -1,
                "logs": "",
                "summary": "pytest not found",
                "error": "pytest is not installed or not in PATH. Try: pip install pytest pytest-asyncio",
                "error_type": "pytest_not_found",
                "failed_tests": []
            }

        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "logs": str(e),
                "summary": f"Test execution failed: {str(e)}",
                "error": str(e),
                "error_type": "execution_error",
                "failed_tests": []
            }

    @classmethod
    def _extract_summary(cls, logs: str) -> str:
        """
        从 pytest 输出中提取总结信息

        Args:
            logs: pytest 输出日志

        Returns:
            str: 总结信息
        """
        if not logs or not logs.strip():
            return "No summary available"

        lines = logs.strip().split('\n')

        # 优先查找包含 "passed", "failed", "error", "skipped" 的总结行
        for line in reversed(lines):
            line = line.strip()
            # 查找典型的 pytest 总结行，如 "1 passed, 2 failed in 0.05s"
            if any(keyword in line.lower() for keyword in ['passed', 'failed', 'error', 'skipped']):
                if 'in' in line and ('second' in line.lower() or 'ms' in line.lower()):
                    return line
                # 即使没有 "in X seconds"，也返回包含这些关键词的行
                if any(x in line for x in ['passed', 'failed', 'error']):
                    return line

        # 查找错误收集失败的提示
        for line in reversed(lines):
            if 'error' in line.lower() and 'collect' in line.lower():
                return line

        # 查找语法错误提示
        for line in reversed(lines):
            if 'syntaxerror' in line.lower() or 'indentationerror' in line.lower():
                return line

        # 查找导入错误
        for line in reversed(lines):
            if 'importerror' in line.lower() or 'modulenotfounderror' in line.lower():
                return line

        # 如果没有找到，返回最后几行（非空行）
        non_empty_lines = [l for l in lines if l.strip()]
        if len(non_empty_lines) >= 2:
            return non_empty_lines[-2] + " | " + non_empty_lines[-1]
        elif non_empty_lines:
            return non_empty_lines[-1]

        return "No summary available"

    @classmethod
    def _analyze_error_type(cls, logs: str) -> Optional[str]:
        """
        分析错误类型

        Args:
            logs: pytest 输出日志

        Returns:
            Optional[str]: 错误类型
        """
        if not logs:
            return None

        logs_lower = logs.lower()

        # 检查语法错误
        if 'syntaxerror' in logs_lower or 'indentationerror' in logs_lower:
            return 'syntax_error'

        # 检查导入错误
        if 'importerror' in logs_lower or 'modulenotfounderror' in logs_lower:
            return 'import_error'

        # 检查测试收集错误（pytest 无法收集测试用例）
        if 'error collecting' in logs_lower or 'collection error' in logs_lower:
            return 'collection_error'

        # 检查断言失败（正常的测试失败）
        if 'assertionerror' in logs_lower or 'failed' in logs_lower:
            return 'test_failure'

        # 检查是否根本没有测试
        if 'no tests ran' in logs_lower or 'collected 0 items' in logs_lower:
            return 'no_tests'

        return 'unknown_error'

    @classmethod
    def _extract_failed_tests(cls, logs: str) -> List[str]:
        """
        提取失败的测试名称列表

        Args:
            logs: pytest 输出日志

        Returns:
            List[str]: 失败的测试名称列表
        """
        failed_tests = []
        if not logs:
            return failed_tests

        lines = logs.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()
            # 查找 FAILED 标记的行
            if line.startswith('FAILED'):
                # 提取测试名称
                parts = line.split()
                if len(parts) >= 2:
                    test_name = parts[1]
                    failed_tests.append(test_name)
            # 查找 ERROR 标记的行
            elif line.startswith('ERROR'):
                parts = line.split()
                if len(parts) >= 2:
                    test_name = parts[1]
                    failed_tests.append(test_name)

        return failed_tests

    @classmethod
    def _extract_error_message(cls, logs: str) -> str:
        """
        提取关键错误信息（用于给 AI 的简洁错误描述）

        Args:
            logs: pytest 输出日志

        Returns:
            str: 错误信息
        """
        if not logs:
            return "Unknown error"

        lines = logs.split('\n')

        # 尝试找到具体的错误信息
        for i, line in enumerate(lines):
            # 查找 AssertionError 详情
            if 'AssertionError' in line:
                # 收集接下来的几行作为错误详情
                error_lines = [line]
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip() and not lines[j].startswith('='):
                        error_lines.append(lines[j].strip())
                    else:
                        break
                return '\n'.join(error_lines)

            # 查找 SyntaxError
            if 'SyntaxError' in line or 'IndentationError' in line:
                error_lines = [line]
                for j in range(i + 1, min(i + 3, len(lines))):
                    error_lines.append(lines[j].strip())
                return '\n'.join(error_lines)

            # 查找 ImportError
            if 'ImportError' in line or 'ModuleNotFoundError' in line:
                return line.strip()

        # 如果找不到具体错误，返回总结
        summary = cls._extract_summary(logs)
        if summary != "No summary available":
            return summary

        # 最后尝试返回最后几行非空内容
        non_empty_lines = [l.strip() for l in lines if l.strip()]
        if non_empty_lines:
            return '\n'.join(non_empty_lines[-5:])

        return "Unknown error occurred during test execution"

    @classmethod
    async def run_tests_with_coverage(
        cls,
        project_path: str,
        timeout: int = 120,
        source_dirs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        执行测试并生成覆盖率报告（需要 pytest-cov）

        Args:
            project_path: 项目根目录路径
            timeout: 超时时间（秒）
            source_dirs: 需要统计覆盖率的源代码目录列表

        Returns:
            Dict: 包含覆盖率信息的结果
        """
        cwd = Path(project_path).resolve()

        # 【新增补丁】强制创建 __init__.py 确保 Python 识别路径
        # 先确保目录存在，再创建 __init__.py
        cwd.mkdir(parents=True, exist_ok=True)
        (cwd / "__init__.py").touch(exist_ok=True)

        tests_dir = cwd / "tests"
        if tests_dir.exists() or not tests_dir.exists():
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "__init__.py").touch(exist_ok=True)

        # 构造带覆盖率的命令
        cmd = ["python", "-m", "pytest", "-v", "--tb=long", "--color=no"]

        # 添加覆盖率参数
        if source_dirs:
            for src_dir in source_dirs:
                cmd.extend(["--cov", src_dir])
        else:
            cmd.append("--cov")

        cmd.extend(["--cov-report", "term-missing"])

        try:
            # 准备环境变量 - 将当前工作区路径加入 PYTHONPATH
            env = os.environ.copy()
            env["PYTHONPATH"] = str(cwd) + os.pathsep + env.get("PYTHONPATH", "")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            logs = stdout.decode('utf-8', errors='replace')
            error_logs = stderr.decode('utf-8', errors='replace')

            full_logs = logs
            if error_logs:
                full_logs += "\n" + error_logs

            success = (process.returncode == 0)

            # 提取覆盖率信息
            coverage_info = cls._extract_coverage_info(logs)

            # 分析错误类型（仅在失败时）
            error_type = cls._analyze_error_type(full_logs) if not success else None

            # 提取失败的测试
            failed_tests = cls._extract_failed_tests(full_logs) if not success else []

            return {
                "success": success,
                "exit_code": process.returncode,
                "logs": full_logs,
                "summary": cls._extract_summary(full_logs),
                "coverage": coverage_info,
                "error": None if success else cls._extract_error_message(full_logs),
                "error_type": error_type,
                "failed_tests": failed_tests
            }

        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except:
                pass

            return {
                "success": False,
                "exit_code": -1,
                "logs": "Test execution timed out",
                "summary": f"Tests timed out after {timeout} seconds",
                "coverage": None,
                "error": f"Test execution timed out after {timeout} seconds",
                "error_type": "timeout",
                "failed_tests": []
            }

        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "logs": str(e),
                "summary": f"Test execution failed: {str(e)}",
                "coverage": None,
                "error": str(e),
                "error_type": "execution_error",
                "failed_tests": []
            }

    @classmethod
    def _extract_coverage_info(cls, logs: str) -> Optional[Dict[str, Any]]:
        """
        从 pytest-cov 输出中提取覆盖率信息

        Args:
            logs: pytest 输出日志

        Returns:
            Optional[Dict]: 覆盖率信息
        """
        lines = logs.split('\n')
        coverage_data = {}

        for line in lines:
            # 查找覆盖率总结行
            if 'TOTAL' in line and '%' in line:
                # 解析类似 "TOTAL                          100     10    90%"
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        coverage_data['total'] = parts[-1]
                        coverage_data['statements'] = parts[-3]
                        coverage_data['missing'] = parts[-2]
                    except:
                        pass
                break

        return coverage_data if coverage_data else None

    @classmethod
    async def check_pytest_installed(cls, project_path: str) -> bool:
        """
        检查 pytest 是否已安装

        Args:
            project_path: 项目路径

        Returns:
            bool: 是否已安装
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "python", "-m", "pytest", "--version",
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            return process.returncode == 0

        except:
            return False

    @classmethod
    async def check_pytest_asyncio_installed(cls, project_path: str) -> bool:
        """
        检查 pytest-asyncio 是否已安装

        Args:
            project_path: 项目路径

        Returns:
            bool: 是否已安装
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "python", "-c", "import pytest_asyncio",
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            return process.returncode == 0

        except:
            return False
