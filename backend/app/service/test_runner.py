"""
测试执行服务
在指定目录下运行 pytest 并捕获结果

核心功能：
1. 安全执行 shell 命令（pytest）
2. 捕获 stdout/stderr 输出
3. 解析测试结果
4. 支持超时控制
5. 智能错误分析（语法错误 vs 测试失败）
6. 详细日志记录（前后端同步）
"""

import asyncio
import logging
import os
from typing import Dict, Any, Optional, List
from pathlib import Path

# 获取 logger
logger = logging.getLogger(__name__)


class TestRunnerService:
    """测试执行器：在指定目录下运行 pytest 并捕获结果"""

    @classmethod
    async def run_tests(
        cls,
        project_path: str,
        timeout: int = 120,  # 放宽超时时间到 120 秒
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

        # 确保目录存在
        cwd.mkdir(parents=True, exist_ok=True)

        # --- 核心修复 1：严格限制 __init__.py 的生成范围 ---
        def ensure_init_files(current_dir: Path):
            # 必须跳过虚拟环境、隐藏目录、前端构建目录等！
            skip_dirs = {"__pycache__", "venv", ".venv", "env", "node_modules", "dist", "build", ".git", ".idea", ".vscode"}
            for item in current_dir.iterdir():
                if item.is_dir() and item.name not in skip_dirs and not item.name.startswith("."):
                    (item / "__init__.py").touch(exist_ok=True)
                    ensure_init_files(item)

        # 【修改】智能检测项目结构，找到真正的根目录和 tests/
        # 情况1: cwd 是项目根目录 (包含 tests/ 和 backend/)
        # 情况2: cwd 是 backend/ 子目录 (父目录包含 tests/)
        # 情况3: cwd 只有 tests/ 子目录

        root_tests_path = cwd / "tests"
        backend_path = cwd / "backend" if (cwd / "backend").exists() else None

        # 检测父目录是否有 tests/ (处理 cwd 是 backend/ 的情况)
        parent_tests_path = cwd.parent / "tests" if cwd.name == "backend" else None
        if parent_tests_path and parent_tests_path.exists():
            # cwd 是 backend/，但测试在父目录的 tests/
            project_root = cwd.parent
            root_tests_path = parent_tests_path
        else:
            project_root = cwd

        # 确定 backend 路径
        if backend_path is None and (project_root / "backend").exists():
            backend_path = project_root / "backend"
        elif backend_path is None:
            backend_path = project_root

        # 给 backend/app 和 backend/tests 打补丁
        if (backend_path / "app").exists():
            ensure_init_files(backend_path / "app")
        if (backend_path / "tests").exists():
            ensure_init_files(backend_path / "tests")
        # 也给根目录 tests/ 打补丁
        if root_tests_path.exists():
            ensure_init_files(root_tests_path)

        # 绝对不要在根目录或者 backend/ 下放 __init__.py
        for bad_init in [project_root / "__init__.py", backend_path / "__init__.py"]:
            if bad_init.exists():
                bad_init.unlink()

        # 确保根目录 tests/ 存在
        if not root_tests_path.exists():
            root_tests_path.mkdir(parents=True, exist_ok=True)
            (root_tests_path / "__init__.py").touch(exist_ok=True)

        # 构造命令 - 使用 python -m pytest 更可靠
        # -v: 详细模式
        # --tb=long: 长堆栈打印，获取更详细的错误信息
        # --color=no: 禁用颜色代码，便于解析

        # 【修改】智能选择测试路径
        # 优先使用 project_root/tests/ (如果存在且有测试文件)
        if root_tests_path.exists() and any(root_tests_path.iterdir()):
            # 使用项目根目录的 tests/
            run_dir = project_root
            tests_path = root_tests_path
        elif (backend_path / "tests").exists():
            # 回退到 backend/tests/
            run_dir = backend_path
            tests_path = backend_path / "tests"
        else:
            # 最后尝试根目录 tests/
            run_dir = project_root
            tests_path = root_tests_path

        cmd = ["python", "-m", "pytest"]

        if verbose:
            cmd.append("-v")

        # 核心修改：
        # --tb=short 减少堆栈长度，防止日志撑爆
        # -x 遇到第一个错误立即停止，光速暴露问题
        # --maxfail=1 确保只运行到第一个失败
        # -m "not integration" 绝对不要跑集成测试
        cmd.extend(["--tb=short", "--color=no", "-x", "--maxfail=1", "-m", "not integration"])

        # 如果指定了测试路径，添加到命令
        if test_path:
            cmd.append(test_path)
        elif tests_path.exists():
            # 默认运行 tests 目录下的测试
            cmd.append(str(tests_path))

        try:
            # --- 核心修复 2：强化 PYTHONPATH 隔离 ---
            env = os.environ.copy()

            # 【修改】根据运行目录设置 PYTHONPATH
            # 如果在项目根目录运行测试（使用 workspace/feishutemp/tests），
            # 需要把 backend/ 加入 PYTHONPATH 以便导入 app 模块
            python_path_parts = []
            if run_dir == project_root and backend_path.exists():
                # 在根目录运行，需要添加 backend/ 到路径
                python_path_parts.append(str(backend_path))
            python_path_parts.append(str(run_dir))
            if env.get('PYTHONPATH'):
                python_path_parts.append(env['PYTHONPATH'])

            env["PYTHONPATH"] = os.pathsep.join(python_path_parts)

            # 记录测试执行开始
            logger.info(
                f"[TestRunner] 开始执行测试",
                extra={
                    "project_path": str(cwd),
                    "project_root": str(project_root),
                    "run_dir": str(run_dir),
                    "tests_path": str(tests_path),
                    "command": " ".join(cmd),
                    "timeout": timeout,
                    "pythonpath": env["PYTHONPATH"][:200],  # 只记录前200字符
                    "event_loop": type(asyncio.get_event_loop()).__name__
                }
            )

            # 使用 asyncio 创建子进程
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(run_dir),  # 从 backend/ 目录运行
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env  # <--- 注入环境变量
                )
            except NotImplementedError as e:
                # Windows 事件循环兼容性错误
                error_msg = (
                    "当前事件循环不支持子进程。"
                    "在 Windows 上，请确保使用了 ProactorEventLoop。"
                    "请在 main.py 开头添加: asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())"
                )
                logger.error(
                    f"[TestRunner] 事件循环不支持子进程",
                    extra={
                        "project_path": str(cwd),
                        "error": str(e),
                        "event_loop": type(asyncio.get_event_loop()).__name__,
                        "solution": "在 main.py 中设置 WindowsProactorEventLoopPolicy"
                    },
                    exc_info=True
                )
                return {
                    "success": False,
                    "exit_code": -1,
                    "logs": error_msg,
                    "summary": "环境兼容性错误: 事件循环不支持子进程",
                    "error": error_msg,
                    "error_type": "environment_error",
                    "failed_tests": []
                }

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

            # 记录测试执行结果
            if success:
                logger.info(
                    f"[TestRunner] 测试执行成功",
                    extra={
                        "project_path": str(cwd),
                        "exit_code": process.returncode,
                        "summary": summary,
                        "logs_preview": full_logs[:500] if full_logs else ""
                    }
                )
            else:
                # 测试失败 - 记录详细错误信息
                error_message = cls._extract_error_message(full_logs)
                logger.error(
                    f"[TestRunner] 测试执行失败",
                    extra={
                        "project_path": str(cwd),
                        "exit_code": process.returncode,
                        "error_type": error_type,
                        "summary": summary,
                        "error_message": error_message,
                        "failed_tests": failed_tests,
                        "logs": full_logs[:3000],  # 记录前3000字符的日志
                        "stderr": error_logs[:1000] if error_logs else ""
                    }
                )

            # 【利益隔离】TestRunner 只提供事实，不做任何推断或建议
            result = {
                "success": success,
                "exit_code": process.returncode,
                "verdict": "PASS" if success else "FAIL",  # 明确的判定结果
                "logs": full_logs,
                "summary": summary,
                "error": None if success else error_message,
                "error_type": error_type,
                "failed_tests": failed_tests,
                # 【证据包】供 Verification Agent 引用的原始事实
                "evidence": {
                    "failed_output": "" if success else full_logs[-2000:],  # 仅失败时的日志片段
                    "key_errors": cls._extract_key_errors(full_logs) if not success else [],
                    "test_count": cls._extract_test_count(summary)
                }
            }

            return result

        except asyncio.TimeoutError:
            # 超时处理：尝试终止进程
            logger.error(
                f"[TestRunner] 测试执行超时",
                extra={
                    "project_path": str(cwd),
                    "timeout": timeout,
                    "command": " ".join(cmd)
                }
            )
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
            logger.error(
                f"[TestRunner] pytest 未找到",
                extra={
                    "project_path": str(cwd),
                    "command": " ".join(cmd),
                    "suggestion": "请安装 pytest: pip install pytest pytest-asyncio"
                }
            )
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
            logger.error(
                f"[TestRunner] 测试执行异常",
                extra={
                    "project_path": str(cwd),
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "command": " ".join(cmd)
                },
                exc_info=True
            )
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
    def _extract_key_errors(cls, logs: str) -> List[str]:
        """
        提取关键错误消息（供 Verification Agent 使用）

        【利益隔离】只提取事实，不做解释
        """
        key_errors = []
        if not logs:
            return key_errors

        lines = logs.split('\n')

        for line in lines:
            line = line.strip()

            # 提取 FAILED 行
            if line.startswith('FAILED'):
                key_errors.append(line)

            # 提取 ERROR 行
            elif line.startswith('ERROR'):
                key_errors.append(line)

            # 提取关键异常类型
            elif any(err in line for err in [
                'SyntaxError:', 'IndentationError:', 'ImportError:',
                'ModuleNotFoundError:', 'NameError:', 'AttributeError:',
                'TypeError:', 'AssertionError:'
            ]):
                # 限制长度，避免上下文爆炸
                if len(line) > 200:
                    line = line[:200] + '...'
                key_errors.append(line)

        # 去重并保持顺序
        seen = set()
        unique_errors = []
        for err in key_errors:
            if err not in seen:
                seen.add(err)
                unique_errors.append(err)

        return unique_errors[:10]  # 最多返回10个关键错误

    @classmethod
    def _extract_test_count(cls, summary: str) -> Dict[str, int]:
        """
        从总结中提取测试数量

        【利益隔离】只提取事实数字
        """
        import re
        counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0}

        if not summary:
            return counts

        # 匹配类似 "3 passed, 1 failed, 2 skipped"
        patterns = [
            (r'(\d+)\s+passed', 'passed'),
            (r'(\d+)\s+failed', 'failed'),
            (r'(\d+)\s+error', 'error'),
            (r'(\d+)\s+skipped', 'skipped'),
        ]

        for pattern, key in patterns:
            match = re.search(pattern, summary, re.IGNORECASE)
            if match:
                counts[key] = int(match.group(1))

        counts['total'] = sum(counts.values()) - counts.get('skipped', 0)
        return counts

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
