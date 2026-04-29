"""
Import 检查拦截器
在代码写入磁盘前，自动修正常见的 import 错误

不依赖 AI，纯规则替换，100% 可靠
"""

import re
from pathlib import Path
from typing import List, Dict, Tuple, Any


class ImportSanitizer:
    """
    在代码写入磁盘前，自动修正常见的 import 错误

    不依赖 AI，纯规则替换，100% 可靠
    """

    # 错误模式 -> 正确模式 的映射
    # 使用 [\w.]+ 来匹配多级路径，如 api.v1.users
    IMPORT_FIXES = [
        # from core.xxx -> from app.core.xxx
        (r'from core\.([\w.]+) import', r'from app.core.\1 import'),
        # from models.xxx -> from app.models.xxx
        (r'from models\.([\w.]+) import', r'from app.models.\1 import'),
        # from service.xxx -> from app.service.xxx
        (r'from service\.([\w.]+) import', r'from app.service.\1 import'),
        # from api.xxx -> from app.api.xxx (支持多级路径如 api.v1.users)
        (r'from api\.([\w.]+) import', r'from app.api.\1 import'),
        # from db.xxx -> from app.db.xxx
        (r'from db\.([\w.]+) import', r'from app.db.\1 import'),
        # from utils.xxx -> from app.utils.xxx
        (r'from utils\.([\w.]+) import', r'from app.utils.\1 import'),
        # from agents.xxx -> from app.agents.xxx
        (r'from agents\.([\w.]+) import', r'from app.agents.\1 import'),
        # import core.xxx -> import app.core.xxx
        (r'^import core\.', 'import app.core.'),
        # import models.xxx -> import app.models.xxx
        (r'^import models\.', 'import app.models.'),
        # import service.xxx -> import app.service.xxx
        (r'^import service\.', 'import app.service.'),
    ]

    @classmethod
    def sanitize_file(cls, content: str, file_path: str) -> Tuple[str, List[str]]:
        """
        修正单个文件的 import 语句

        Args:
            content: 文件内容
            file_path: 文件路径

        Returns:
            Tuple[str, List[str]]: (修正后的内容, 修正记录列表)
        """
        if not file_path.endswith('.py'):
            return content, []

        fixes_applied = []
        lines = content.split('\n')
        fixed_lines = []

        for i, line in enumerate(lines):
            original = line
            for pattern, replacement in cls.IMPORT_FIXES:
                line = re.sub(pattern, replacement, line)
            if line != original:
                fixes_applied.append(
                    f"Line {i+1}: '{original.strip()}' -> '{line.strip()}'"
                )
            fixed_lines.append(line)

        return '\n'.join(fixed_lines), fixes_applied

    @classmethod
    def sanitize_files(cls, files: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
        """
        批量修正文件列表中的 import 错误

        Args:
            files: [{"file_path": str, "content": str, ...}, ...]

        Returns:
            Tuple[List[Dict], Dict]: (修正后的 files, 修正报告)
        """
        report: Dict[str, List[str]] = {}
        sanitized: List[Dict[str, Any]] = []

        for f in files:
            content = f.get('content', '')
            file_path = f.get('file_path', '')

            fixed_content, fixes = cls.sanitize_file(content, file_path)

            if fixes:
                report[file_path] = fixes

            sanitized.append({**f, 'content': fixed_content})

        return sanitized, report
