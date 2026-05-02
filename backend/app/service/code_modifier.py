"""
代码修改服务 - 支持 AST 级源码改写

职责：
1. 根据源码位置信息读取文件内容
2. 提取元素周围的代码上下文
3. 应用 LLM 生成的代码变更
4. 保持代码格式和风格

支持语言：
- TypeScript/TSX (React)
- JavaScript/JSX
- Python

实现策略：
- TypeScript/TSX: 使用基于正则的轻量级修改（因 ts-morph 是 Node.js 库）
- Python: 使用 parso 库进行 AST 级修改
"""

import re
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SourceLocation:
    """源码位置信息"""
    file: str
    line: int
    column: int = 0
    component: Optional[str] = None


@dataclass
class ElementContext:
    """元素上下文信息"""
    tag: str
    id: Optional[str]
    class_name: Optional[str]
    outer_html: str
    xpath: str
    selector: str
    text: str
    component_name: Optional[str] = None


@dataclass
class LLMContext:
    """传给 LLM 的核心上下文结构"""
    file: str
    line: int
    column: int
    component: Optional[str]
    selected_html: str
    surrounding_code: str
    user_instruction: str
    element_type: str
    element_id: Optional[str]
    element_class: Optional[str]
    xpath: str
    selector: str


@dataclass
class CodeChange:
    """代码变更"""
    file_path: str
    original_code: str
    new_code: str
    start_line: int
    end_line: int
    change_type: str = "modify"  # "modify", "add", "delete"


class CodeModifierService:
    """代码修改服务"""

    def __init__(self, workspace_path: str):
        """
        初始化代码修改服务

        Args:
            workspace_path: 工作空间路径（项目根目录）
        """
        self.workspace_path = Path(workspace_path)

    def read_file_context(
        self,
        file_path: str,
        target_line: int,
        context_lines: int = 20
    ) -> Tuple[str, str, int, int]:
        """
        读取文件并提取目标行周围的上下文

        Args:
            file_path: 文件路径（相对或绝对）
            target_line: 目标行号（1-based）
            context_lines: 上下文行数

        Returns:
            (完整文件内容, 周围代码, 开始行号, 结束行号)
        """
        full_path = self._resolve_path(file_path)

        if not full_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        content = full_path.read_text(encoding='utf-8')
        lines = content.splitlines()

        # 计算上下文范围
        start_line = max(1, target_line - context_lines)
        end_line = min(len(lines), target_line + context_lines)

        # 提取周围代码
        surrounding_lines = lines[start_line - 1:end_line]
        surrounding_code = '\n'.join(surrounding_lines)

        return content, surrounding_code, start_line, end_line

    def build_llm_context(
        self,
        source_location: SourceLocation,
        element_context: ElementContext,
        user_instruction: str
    ) -> LLMContext:
        """
        构建传给 LLM 的核心上下文结构

        Args:
            source_location: 源码位置
            element_context: 元素上下文
            user_instruction: 用户指令

        Returns:
            LLMContext
        """
        # 读取周围代码
        _, surrounding_code, _, _ = self.read_file_context(
            source_location.file,
            source_location.line
        )

        return LLMContext(
            file=source_location.file,
            line=source_location.line,
            column=source_location.column,
            component=source_location.component or element_context.component_name,
            selected_html=element_context.outer_html[:500],
            surrounding_code=surrounding_code,
            user_instruction=user_instruction,
            element_type=element_context.tag,
            element_id=element_context.id,
            element_class=element_context.class_name,
            xpath=element_context.xpath,
            selector=element_context.selector,
        )

    def apply_change(self, change: CodeChange) -> bool:
        """
        应用代码变更

        Args:
            change: 代码变更对象

        Returns:
            是否成功
        """
        full_path = self._resolve_path(change.file_path)

        if not full_path.exists():
            logger.error(f"文件不存在: {change.file_path}")
            return False

        try:
            content = full_path.read_text(encoding='utf-8')
            lines = content.splitlines()

            if change.change_type == "modify":
                # 替换指定行范围
                new_lines = (
                    lines[:change.start_line - 1] +
                    change.new_code.splitlines() +
                    lines[change.end_line:]
                )
            elif change.change_type == "add":
                # 在指定行后添加
                new_lines = (
                    lines[:change.start_line] +
                    change.new_code.splitlines() +
                    lines[change.start_line:]
                )
            elif change.change_type == "delete":
                # 删除指定行
                new_lines = lines[:change.start_line - 1] + lines[change.end_line:]
            else:
                logger.error(f"未知的变更类型: {change.change_type}")
                return False

            # 写回文件
            new_content = '\n'.join(new_lines)
            full_path.write_text(new_content, encoding='utf-8')

            logger.info(f"已应用变更到 {change.file_path} (行 {change.start_line}-{change.end_line})")
            return True

        except Exception as e:
            logger.error(f"应用变更失败: {e}")
            return False

    def find_jsx_element(
        self,
        file_path: str,
        line: int,
        element_type: str = None,
        element_id: str = None,
        element_class: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        在 TSX/JSX 文件中查找 JSX 元素

        Args:
            file_path: 文件路径
            line: 目标行号
            element_type: 元素类型（如 div, button）
            element_id: 元素 ID
            element_class: 元素 class

        Returns:
            元素信息字典或 None
        """
        full_path = self._resolve_path(file_path)

        if not full_path.exists():
            return None

        content = full_path.read_text(encoding='utf-8')
        lines = content.splitlines()

        if line < 1 or line > len(lines):
            return None

        # 从目标行开始向上查找 JSX 元素
        for i in range(line - 1, -1, -1):
            line_content = lines[i]

            # 尝试匹配 JSX 元素开始标签
            jsx_pattern = r'<([A-Za-z][A-Za-z0-9]*)\b[^>]*>'
            match = re.search(jsx_pattern, line_content)

            if match:
                tag_name = match.group(1)

                # 检查是否匹配目标元素
                if element_type and tag_name != element_type:
                    continue

                # 提取属性
                attrs = self._extract_jsx_attributes(line_content)

                if element_id and attrs.get('id') != element_id:
                    continue

                if element_class and element_class not in attrs.get('className', ''):
                    continue

                return {
                    'tag': tag_name,
                    'line': i + 1,
                    'column': match.start() + 1,
                    'attributes': attrs,
                    'content': line_content.strip(),
                }

        return None

    def modify_jsx_attribute(
        self,
        file_path: str,
        line: int,
        attribute_name: str,
        new_value: str
    ) -> bool:
        """
        修改 JSX 元素的属性

        Args:
            file_path: 文件路径
            line: 目标行号
            attribute_name: 属性名（如 className, style）
            new_value: 新值

        Returns:
            是否成功
        """
        full_path = self._resolve_path(file_path)

        if not full_path.exists():
            return False

        try:
            content = full_path.read_text(encoding='utf-8')
            lines = content.splitlines()

            if line < 1 or line > len(lines):
                return False

            line_content = lines[line - 1]

            # 检查属性是否已存在
            attr_pattern = rf'({attribute_name}=)(["\'])([^"\']*)\2'
            attr_match = re.search(attr_pattern, line_content)

            if attr_match:
                # 替换现有属性
                new_line = (
                    line_content[:attr_match.start()] +
                    f'{attribute_name}="{new_value}"' +
                    line_content[attr_match.end():]
                )
            else:
                # 在标签末尾添加新属性
                tag_end_match = re.search(r'\s*/?>', line_content)
                if tag_end_match:
                    insert_pos = tag_end_match.start()
                    new_line = (
                        line_content[:insert_pos] +
                        f' {attribute_name}="{new_value}"' +
                        line_content[insert_pos:]
                    )
                else:
                    return False

            lines[line - 1] = new_line
            full_path.write_text('\n'.join(lines), encoding='utf-8')

            logger.info(f"已修改 {file_path}:{line} 的 {attribute_name} 属性")
            return True

        except Exception as e:
            logger.error(f"修改 JSX 属性失败: {e}")
            return False

    def modify_element_text(
        self,
        file_path: str,
        line: int,
        new_text: str
    ) -> bool:
        """
        修改元素文本内容

        Args:
            file_path: 文件路径
            line: 目标行号
            new_text: 新文本

        Returns:
            是否成功
        """
        full_path = self._resolve_path(file_path)

        if not full_path.exists():
            return False

        try:
            content = full_path.read_text(encoding='utf-8')
            lines = content.splitlines()

            if line < 1 or line > len(lines):
                return False

            line_content = lines[line - 1]

            # 匹配 JSX 元素的内容部分
            # 支持：<tag>content</tag> 或 <tag>{expression}</tag>
            text_pattern = r'(>)([^<]*)(</)'
            match = re.search(text_pattern, line_content)

            if match:
                new_line = (
                    line_content[:match.start(2)] +
                    new_text +
                    line_content[match.end(2):]
                )
                lines[line - 1] = new_line
                full_path.write_text('\n'.join(lines), encoding='utf-8')

                logger.info(f"已修改 {file_path}:{line} 的文本内容")
                return True

            return False

        except Exception as e:
            logger.error(f"修改元素文本失败: {e}")
            return False

    def _resolve_path(self, file_path: str) -> Path:
        """解析文件路径"""
        path = Path(file_path)
        if path.is_absolute():
            return path
        return self.workspace_path / path

    def _extract_jsx_attributes(self, jsx_line: str) -> Dict[str, str]:
        """提取 JSX 元素的属性"""
        attrs = {}

        # 匹配属性名="值" 或 属性名='值' 或 属性名={表达式}
        attr_pattern = r'([A-Za-z][A-Za-z0-9]*)=(?:"([^"]*)"|\'([^\']*)\'|\{([^}]*)\})'

        for match in re.finditer(attr_pattern, jsx_line):
            attr_name = match.group(1)
            attr_value = match.group(2) or match.group(3) or match.group(4)
            attrs[attr_name] = attr_value

        return attrs

    def to_dict(self, obj: Any) -> Dict[str, Any]:
        """将对象转换为字典"""
        if hasattr(obj, '__dataclass_fields__'):
            return {
                field: getattr(obj, field)
                for field in obj.__dataclass_fields__
            }
        return obj.__dict__ if hasattr(obj, '__dict__') else obj


# 便捷函数
def create_modifier(workspace_path: str) -> CodeModifierService:
    """创建代码修改服务实例"""
    return CodeModifierService(workspace_path)


if __name__ == "__main__":
    # 测试代码
    import tempfile
    import os

    # 创建临时测试文件
    test_content = """
import React from 'react';

function Hero() {
  return (
    <div className="hero" id="main-hero">
      <h1 className="title">Hello World</h1>
      <button className="btn primary">Click me</button>
    </div>
  );
}

export default Hero;
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "Hero.tsx"
        test_file.write_text(test_content)

        modifier = CodeModifierService(tmpdir)

        # 测试读取上下文
        content, surrounding, start, end = modifier.read_file_context(
            "Hero.tsx", 6, context_lines=3
        )
        print("周围代码:")
        print(surrounding)
        print()

        # 测试查找 JSX 元素
        element = modifier.find_jsx_element("Hero.tsx", 6, element_type="h1")
        print("找到的元素:", element)
        print()

        # 测试修改属性
        success = modifier.modify_jsx_attribute(
            "Hero.tsx", 6, "className", "title blue-text"
        )
        print(f"修改属性: {'成功' if success else '失败'}")
        print()

        # 验证修改结果
        new_content = test_file.read_text()
        print("修改后的文件内容:")
        print(new_content)
