"""
契约校验器

对 DesignerAgent 输出的 interface_specs 进行确定性校验
"""

from typing import Dict, List, Any


class ContractValidator:
    """
    对 DesignerAgent 输出的 interface_specs 进行确定性校验
    """

    # IO 操作关键词列表
    IO_KEYWORDS = [
        "database", "session", "disk", "memory", "cpu",
        "http", "request", "file", "read", "write", "psutil",
        "sqlalchemy", "socket", "subprocess", "datetime.now"
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
            if any(kw in signature.lower() for kw in ContractValidator.IO_KEYWORDS) and not mock_deps:
                errors.append(
                    f"[{symbol}] 函数签名暗示需要 IO 操作，但未声明 mock_dependencies"
                )

            # 3. 建议有 error_responses（非强制，仅警告）
            # 暂时不添加为错误，避免过于严格

        return errors
