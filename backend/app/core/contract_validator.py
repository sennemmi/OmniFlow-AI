"""
契约校验器

对 DesignerAgent 输出的 interface_specs 进行确定性校验
"""

import ast
import re
from typing import Dict, List, Any, Optional


class ContractValidator:
    """
    对 DesignerAgent 输出的 interface_specs 进行确定性校验
    """

    # IO 操作关键词列表
    # 【修复】移除 "request"，因为 request: Request 是 FastAPI 路由参数，不是 IO 操作
    # 【修复】使用更精确的匹配模式，避免误伤参数名
    IO_PATTERNS = [
        r'\bdatabase\b', r'\bsession\b', r'\bdisk\b',
        r'\bmemory\b', r'\bcpu\b', r'\bpsutil\b',
        r'\bsqlalchemy\b', r'\bsocket\b', r'\bsubprocess\b',
        r'datetime\.now', r'\bread\b', r'\bwrite\b',
        r'\bfile\b', r'\bhttp\b(?!_)',  # 匹配 http 但不匹配 http_client 中的 http
    ]

    @staticmethod
    def validate_interface_specs(design_output: Dict[str, Any]) -> List[str]:
        """
        校验 interface_specs 的完整性

        返回错误列表，空列表表示全部通过

        Args:
            design_output: DesignerAgent 的输出

        Returns:
            List[str]: 错误信息列表
        """
        errors = []
        specs = design_output.get("interface_specs", [])

        if not specs:
            errors.append("interface_specs 为空，必须至少包含一个接口契约")
            return errors

        for idx, spec in enumerate(specs):
            symbol = spec.get("symbol_name", f"spec[{idx}]")
            return_type = spec.get("return_type", "").lower()
            return_fields = spec.get("return_fields", [])
            mock_deps = spec.get("mock_dependencies", [])
            error_responses = spec.get("error_responses", [])
            signature = spec.get("signature", "")

            # 1. 返回 dict 必须声明 return_fields
            if "dict" in return_type and not return_fields:
                errors.append(
                    f"[{symbol}] 返回类型为 dict，但 return_fields 为空"
                )

            # 2. 签名中包含 IO 关键词的，必须 mock
            # 【修复】使用正则表达式进行精确匹配，避免误伤参数名
            sig_lower = signature.lower()
            has_io_keyword = any(re.search(pattern, sig_lower) for pattern in ContractValidator.IO_PATTERNS)
            if has_io_keyword and not mock_deps:
                errors.append(
                    f"[{symbol}] 函数签名暗示需要 IO 操作，但未声明 mock_dependencies"
                )

            # 3. 建议有 error_responses（非强制，仅警告）
            # 暂时不添加为错误，避免过于严格

            # 4. 【新增】检查 API 端点是否包含 request: Request 参数
            module = spec.get("module", "")
            if "api/" in module.lower():
                # 【修复】只检查函数签名，跳过变量赋值（如 router = APIRouter()）
                # 函数签名应该以 "def " 或 "async def " 开头
                is_function_signature = (
                    signature.strip().startswith("def ") or
                    signature.strip().startswith("async def ")
                )
                if is_function_signature and "request" not in signature.lower():
                    errors.append(
                        f"[{symbol}] API 端点必须在签名中包含 request: Request 参数，"
                        f"当前签名: {signature}"
                    )

        return errors

    @staticmethod
    def validate_code_against_contract(
        code_files: List[Dict[str, Any]],
        interface_specs: List[Dict[str, Any]]
    ) -> List[str]:
        """
        【新增】校验 Coder 生成的代码是否符合 Designer 的契约

        检查项：
        1. 契约中声明的函数是否在代码中存在
        2. 函数签名是否与契约一致（特别是 request 参数）
        3. 错误响应是否设置了正确的 HTTP 状态码

        Args:
            code_files: Coder 生成的代码文件列表
            interface_specs: Designer 定义的接口契约

        Returns:
            List[str]: 不一致的错误列表
        """
        errors = []

        # 构建代码中的函数签名映射
        code_signatures = {}
        status_code_issues = []

        for code_file in code_files:
            file_path = code_file.get("file_path", "")
            content = code_file.get("content", "")

            if not content or not file_path.endswith(".py"):
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    func_name = node.name
                    # 提取函数签名信息
                    args = []
                    for arg in node.args.args:
                        arg_name = arg.arg
                        arg_type = ""
                        if arg.annotation:
                            if isinstance(arg.annotation, ast.Name):
                                arg_type = arg.annotation.id
                            elif isinstance(arg.annotation, ast.Attribute):
                                arg_type = arg.annotation.attr
                        args.append(f"{arg_name}: {arg_type}" if arg_type else arg_name)

                    # 检查是否有 request 参数
                    has_request_param = any("request" in arg.lower() for arg in args)

                    # 检查错误响应是否设置了状态码
                    # 简化检查：查找 JSONResponse 和 status_code 模式
                    func_content = ast.unparse(node)
                    has_error_response = "error_response" in func_content
                    has_json_response = "JSONResponse" in func_content
                    has_status_code = "status_code" in func_content

                    code_signatures[func_name] = {
                        "args": args,
                        "has_request_param": has_request_param,
                        "has_error_status_code": has_json_response and has_status_code,
                        "file_path": file_path,
                    }

        # 对比契约和代码
        for spec in interface_specs:
            symbol_name = spec.get("symbol_name", "")
            module = spec.get("module", "")
            signature = spec.get("signature", "")

            # 跳过类定义
            if "class " in signature:
                continue

            # 检查函数是否在代码中存在
            if symbol_name not in code_signatures:
                errors.append(
                    f"[{symbol_name}] 契约中声明的函数在生成的代码中未找到"
                )
                continue

            code_sig = code_signatures[symbol_name]

            # 检查 API 端点是否有 request 参数
            if "api/" in module.lower():
                if not code_sig["has_request_param"]:
                    errors.append(
                        f"[{symbol_name}] API 端点实现缺少 request 参数，"
                        f"与契约签名不一致: {signature}"
                    )

                # 检查错误响应是否设置了状态码
                if not code_sig["has_error_status_code"]:
                    status_code_issues.append(
                        f"[{symbol_name}] 错误响应未设置 HTTP 状态码，"
                        f"建议使用 JSONResponse(status_code=500, content=...)"
                    )

        # 状态码问题作为警告添加（非致命错误）
        if status_code_issues:
            errors.extend([f"[警告] {issue}" for issue in status_code_issues])

        return errors

    @staticmethod
    def validate_router_registration(
        main_py_content: str,
        interface_specs: List[Dict[str, Any]]
    ) -> List[str]:
        """
        验证新增的 router 是否在 main.py 中注册了 include_router
        """
        errors = []

        for spec in interface_specs:
            symbol = spec.get("symbol_name", "")
            module = spec.get("module", "")
            signature = spec.get("signature", "")

            # 只检查 router/APIRouter 类型的变量
            if not ("router" in symbol.lower() or "APIRouter()" in signature):
                continue
            # 只检查 api/ 路径下的模块
            if "api/" not in module.lower():
                continue

            # 检查 main.py 里是否有 include_router(symbol_name
            if f"include_router({symbol}" not in main_py_content:
                errors.append(
                    f"[{symbol}] 在 main.py 中未找到 include_router({symbol}...)，"
                    f"路由未注册，请在 main.py 中添加注册代码"
                )

        return errors
