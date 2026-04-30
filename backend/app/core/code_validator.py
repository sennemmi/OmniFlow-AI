"""
代码验证器

提供 AST 语法预检、结构完整性检查和后置钩子验证
"""

import ast
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


class CodeValidator:
    """代码验证器 - 在写入前检查代码质量"""

    @staticmethod
    def pre_flight_check(code: str) -> Optional[str]:
        """
        语法预检闸门 - 在写入磁盘前检查 Python 语法

        Args:
            code: 要检查的代码字符串

        Returns:
            Optional[str]: 如果有语法错误，返回错误信息；否则返回 None
        """
        try:
            ast.parse(code)
            return None
        except SyntaxError as e:
            return f"SyntaxError at line {e.lineno}: {e.msg}"
        except Exception as e:
            return f"Parse error: {str(e)}"

    @staticmethod
    def validate_code_structure(code: str, file_path: str) -> Optional[str]:
        """
        验证代码结构完整性 - 检查常见的 AI 生成错误

        Args:
            code: 代码内容
            file_path: 文件路径

        Returns:
            Optional[str]: 如果结构有问题，返回错误信息；否则返回 None
        """
        lines = code.splitlines()

        # 1. 检查 FastAPI 路由文件是否缺少 router 定义
        if file_path.endswith('.py') and 'router' in code:
            has_router_import = any('APIRouter' in line for line in lines)
            has_router_init = any('router = APIRouter' in line or '= APIRouter(' in line for line in lines)
            has_decorator = any('@router.' in line for line in lines)

            if has_decorator and not (has_router_import and has_router_init):
                missing = []
                if not has_router_import:
                    missing.append("from fastapi import APIRouter")
                if not has_router_init:
                    missing.append("router = APIRouter(...)")
                return f"结构错误: 使用了 @router. 装饰器但缺少: {', '.join(missing)}"

        # 2. 检查使用了未定义的变量（简单检查）
        import re
        defined_names = set()
        imported_names = set()

        for line in lines:
            # 收集导入的名称
            if 'import ' in line:
                # from x import y
                match = re.match(r'from\s+\S+\s+import\s+(.+)', line)
                if match:
                    imports = match.group(1).split(',')
                    for imp in imports:
                        name = imp.strip().split()[0]
                        imported_names.add(name)
                # import x
                match = re.match(r'import\s+(.+)', line)
                if match:
                    imports = match.group(1).split(',')
                    for imp in imports:
                        imported_names.add(imp.strip().split('.')[0])

            # 收集定义的变量
            match = re.match(r'^(\w+)\s*=', line)
            if match:
                defined_names.add(match.group(1))

        # 检查装饰器使用的名称是否已定义
        for line in lines:
            match = re.match(r'@(\w+)\.', line)
            if match:
                name = match.group(1)
                if name not in defined_names and name not in imported_names and name not in ['staticmethod', 'classmethod', 'property']:
                    return f"结构错误: 使用了未定义的 '{name}' 对象（在装饰器中）"

        return None

    @staticmethod
    def post_write_hook(file_path: str, content: str) -> Optional[str]:
        """
        确定性后置钩子：写入后验证代码关键约束

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            Optional[str]: 如果检查失败，返回错误信息；否则返回 None
        """
        if not file_path.endswith('.py'):
            logger.debug(f"[PostWriteHook] 跳过非 Python 文件: {file_path}")
            return None

        lines = content.splitlines()
        total_lines = len(lines)
        logger.info(f"[PostWriteHook] 开始检查文件: {file_path} ({total_lines} 行)")

        # 1. FastAPI 路由完整性检查
        has_router_import = any('APIRouter' in line for line in lines)
        has_router_init = any('router = APIRouter' in line for line in lines)
        has_decorator = any('@router.' in line for line in lines)

        if has_decorator:
            logger.info(f"[PostWriteHook] 检测到 FastAPI 路由装饰器 (@router.)")
            if not (has_router_import and has_router_init):
                missing = []
                if not has_router_import:
                    missing.append("from fastapi import APIRouter")
                    logger.error(f"[PostWriteHook] 缺少 APIRouter 导入")
                if not has_router_init:
                    missing.append("router = APIRouter(...)")
                    logger.error(f"[PostWriteHook] 缺少 router = APIRouter() 初始化")
                return f"FastAPI 路由文件缺少: {', '.join(missing)}"
            logger.info(f"[PostWriteHook] FastAPI 路由完整性检查通过")

        # 2. 检查使用了 @app. 但没有 FastAPI 实例
        has_app_decorator = any('@app.' in line for line in lines)
        has_app_init = any('app = FastAPI' in line for line in lines) or 'FastAPI(' in ''.join(lines)

        if has_app_decorator:
            logger.info(f"[PostWriteHook] 检测到 FastAPI 应用装饰器 (@app.)")
            if not has_app_init:
                logger.error(f"[PostWriteHook] 缺少 app = FastAPI() 初始化")
                return "使用了 @app. 装饰器但缺少 app = FastAPI() 初始化"
            logger.info(f"[PostWriteHook] FastAPI 应用完整性检查通过")

        # 3. 检查 SQLModel 模型缺少导入
        has_model_def = any('class ' in line and '(SQLModel' in line for line in lines)
        has_sqlmodel_import = any('SQLModel' in line and 'import' in line for line in lines)

        if has_model_def:
            logger.info(f"[PostWriteHook] 检测到 SQLModel 模型定义")
            if not has_sqlmodel_import:
                logger.error(f"[PostWriteHook] 缺少 SQLModel 导入")
                return "SQLModel 模型定义缺少 from sqlmodel import SQLModel"
            logger.info(f"[PostWriteHook] SQLModel 导入检查通过")

        # 4. 检查使用了 async def 但可能缺少 await（简单启发式）
        has_async_def = any('async def ' in line for line in lines)
        has_await = any('await ' in line for line in lines)

        if has_async_def and not has_await:
            logger.warning(f"[PostWriteHook] [{file_path}] 包含 async def 但没有使用 await，请检查是否需要异步")

        # 5. 模块导出契约检查 - 防止破坏公共 API
        if 'app/core/database.py' in file_path:
            logger.info(f"[PostWriteHook] 检查核心模块导出契约: app/core/database.py")
            has_get_session = 'def get_session' in content
            if not has_get_session:
                logger.error(f"[PostWriteHook] [严重错误] app/core/database.py 缺少 get_session 函数！")
                return "[严重错误] 禁止删除 app/core/database.py 中的 get_session 函数！"
            logger.info(f"[PostWriteHook] app/core/database.py 导出契约检查通过")

        if 'app/core/response.py' in file_path:
            logger.info(f"[PostWriteHook] 检查核心模块导出契约: app/core/response.py")
            has_success_response = 'def success_response' in content
            has_error_response = 'def error_response' in content
            if not has_success_response:
                logger.error(f"[PostWriteHook] [严重错误] app/core/response.py 缺少 success_response 函数！")
                return "[严重错误] 禁止删除 app/core/response.py 中的 success_response 函数！"
            if not has_error_response:
                logger.error(f"[PostWriteHook] [严重错误] app/core/response.py 缺少 error_response 函数！")
                return "[严重错误] 禁止删除 app/core/response.py 中的 error_response 函数！"
            logger.info(f"[PostWriteHook] app/core/response.py 导出契约检查通过")

        # 6. 检查 @router. 装饰器是否在 router = APIRouter() 之后
        if has_decorator and has_router_init:
            router_init_line = -1
            first_decorator_line = -1

            for i, line in enumerate(lines):
                if router_init_line == -1 and 'router = APIRouter' in line:
                    router_init_line = i
                if first_decorator_line == -1 and '@router.' in line:
                    first_decorator_line = i

            if router_init_line != -1 and first_decorator_line != -1:
                if first_decorator_line < router_init_line:
                    logger.error(f"[PostWriteHook] [严重错误] @router. 装饰器（第 {first_decorator_line+1} 行）出现在 router = APIRouter()（第 {router_init_line+1} 行）之前")
                    return f"[严重错误] @router. 装饰器（第 {first_decorator_line+1} 行）出现在 router = APIRouter()（第 {router_init_line+1} 行）之前！"
                logger.debug(f"[PostWriteHook] @router. 装饰器位置检查通过")

        # 7. 检查 @app. 装饰器是否在 app = FastAPI() 之后
        if has_app_decorator and has_app_init:
            app_init_line = -1
            first_app_decorator_line = -1

            for i, line in enumerate(lines):
                if app_init_line == -1 and ('app = FastAPI' in line or 'FastAPI(' in line):
                    app_init_line = i
                if first_app_decorator_line == -1 and '@app.' in line:
                    first_app_decorator_line = i

            if app_init_line != -1 and first_app_decorator_line != -1:
                if first_app_decorator_line < app_init_line:
                    logger.error(f"[PostWriteHook] [严重错误] @app. 装饰器（第 {first_app_decorator_line+1} 行）出现在 app = FastAPI()（第 {app_init_line+1} 行）之前")
                    return f"[严重错误] @app. 装饰器（第 {first_app_decorator_line+1} 行）出现在 app = FastAPI()（第 {app_init_line+1} 行）之前！"
                logger.debug(f"[PostWriteHook] @app. 装饰器位置检查通过")

        logger.info(f"[PostWriteHook] 文件检查通过: {file_path}")
        return None


# 单例实例
code_validator = CodeValidator()
