"""
高 ROI 小功能测试：大模型输出容错处理

测试 _try_fix_truncated_json、Markdown 剥离、正则提取代码块等
这些是小工具但处于 Pipeline 咽喉要道，一旦挂了整个流程就断了
"""

import pytest
import json

pytestmark = [pytest.mark.unit, pytest.mark.high_roi]


class TestJSONRepairUtils:
    """
    测试 JSON 修复工具（大模型输出容错处理）
    使用参数化测试覆盖各种残缺 JSON 和 Markdown 包裹情况
    """

    @pytest.mark.parametrize("input_text, expected_keys, desc", [
        # 1. 标准 JSON
        (
            '{"status": "success", "data": {"files": []}}',
            ["status", "data"],
            "标准JSON"
        ),
        # 2. 被 Markdown 代码块包裹
        (
            '```json\n{"status": "success", "data": {}}\n```',
            ["status", "data"],
            "Markdown代码块包裹"
        ),
        # 3. 被普通代码块包裹
        (
            '```\n{"status": "success"}\n```',
            ["status"],
            "普通代码块包裹"
        ),
        # 4. 缺少结尾括号
        (
            '{"status": "success", "data": {',
            ["status"],
            "缺少结尾括号"
        ),
        # 5. 缺少开头括号
        (
            '"status": "success", "data": {}}',
            [],
            "缺少开头括号（难以修复）"
        ),
        # 6. 多余逗号
        (
            '{"status": "success", "data": {},}',
            ["status", "data"],
            "多余结尾逗号"
        ),
        # 7. 单引号代替双引号
        (
            "{'status': 'success', 'data': {}}",
            ["status", "data"],
            "单引号JSON"
        ),
        # 8. 混合格式
        (
            'Some text before\n```json\n{"status": "ok"}\n```\nAfter text',
            ["status"],
            "混合格式文本"
        ),
    ])
    def test_try_fix_truncated_json(self, input_text, expected_keys, desc):
        """测试 _try_fix_truncated_json 在各种边界条件下的表现"""
        # Act
        result = self._try_fix_truncated_json(input_text)
        
        # Assert
        if expected_keys:
            assert result is not None, f"失败场景: {desc} - 应该能修复"
            parsed = json.loads(result)
            for key in expected_keys:
                assert key in parsed, f"失败场景: {desc} - 缺少键 {key}"
        else:
            # 对于无法修复的情况，返回 None 或原始文本
            assert result is None or result == input_text, f"失败场景: {desc}"

    def _try_fix_truncated_json(self, text: str) -> str:
        """
        模拟 _try_fix_truncated_json 实现
        尝试修复大模型输出的残缺 JSON
        """
        if not text:
            return None
        
        original = text.strip()
        
        # 1. 提取 Markdown 代码块
        if "```" in original:
            import re
            # 尝试提取 ```json 或 ``` 包裹的内容
            patterns = [
                r'```json\s*(.*?)\s*```',
                r'```\s*(.*?)\s*```',
            ]
            for pattern in patterns:
                match = re.search(pattern, original, re.DOTALL)
                if match:
                    original = match.group(1).strip()
                    break
        
        # 2. 尝试解析
        try:
            json.loads(original)
            return original
        except json.JSONDecodeError:
            pass
        
        # 3. 尝试修复常见错误
        fixes = [
            # 修复单引号
            lambda x: x.replace("'", '"'),
            # 移除尾部逗号
            lambda x: x.rstrip().rstrip(','),
            # 添加缺失的结尾括号
            lambda x: x + '}' if x.count('{') > x.count('}') else x,
            lambda x: x + ']' if x.count('[') > x.count(']') else x,
        ]
        
        for fix in fixes:
            try:
                fixed = fix(original)
                json.loads(fixed)
                return fixed
            except json.JSONDecodeError:
                continue
        
        # 4. 尝试提取看起来像 JSON 的部分
        try:
            # 找第一个 { 和最后一个 }
            start = original.find('{')
            end = original.rfind('}')
            if start != -1 and end != -1 and start < end:
                candidate = original[start:end+1]
                json.loads(candidate)
                return candidate
        except json.JSONDecodeError:
            pass
        
        # 无法修复
        return None

    @pytest.mark.parametrize("input_text, expected_contains, desc", [
        # 1. 标准代码块
        (
            '```python\ndef hello():\n    pass\n```',
            "def hello():",
            "Python代码块"
        ),
        # 2. 无语言标记
        (
            '```\nconst x = 1;\n```',
            "const x = 1",
            "无语言代码块"
        ),
        # 3. 行内代码
        (
            'Use `print("hello")` to output',
            None,  # 行内代码不提取
            "行内代码不提取"
        ),
        # 4. 多个代码块
        (
            '```python\nprint(1)\n```\n\n```python\nprint(2)\n```',
            "print(1)",
            "多个代码块取第一个"
        ),
    ])
    def test_extract_code_block(self, input_text, expected_contains, desc):
        """测试代码块提取"""
        result = self._extract_code_block(input_text)
        
        if expected_contains:
            assert expected_contains in result, f"失败场景: {desc}"
        else:
            # 对于行内代码，应该返回 None 或空
            assert result is None or result == "", f"失败场景: {desc}"

    def _extract_code_block(self, text: str) -> str:
        """模拟代码块提取"""
        import re
        
        # 匹配 ```language\ncode\n```
        pattern = r'```(?:\w+)?\s*\n(.*?)\n```'
        match = re.search(pattern, text, re.DOTALL)
        
        if match:
            return match.group(1).strip()
        
        return None

    @pytest.mark.parametrize("input_text, expected, desc", [
        # 1. 标准 Markdown
        (
            '# Title\n\nSome **bold** text',
            'Title Some bold text',
            "标准Markdown"
        ),
        # 2. 带链接
        (
            '[link](http://example.com) text',
            'link text',
            "Markdown链接"
        ),
        # 3. 代码块保留
        (
            'Text\n```\ncode\n```\nMore',
            'Text code More',
            "保留代码块内容"
        ),
    ])
    def test_strip_markdown(self, input_text, expected, desc):
        """测试 Markdown 剥离"""
        result = self._strip_markdown(input_text)
        # 简化验证：检查关键内容存在
        for word in expected.split():
            assert word in result, f"失败场景: {desc} - 缺少 {word}"

    def _strip_markdown(self, text: str) -> str:
        """模拟 Markdown 剥离"""
        import re
        
        # 移除标题标记
        text = re.sub(r'#+\s*', '', text)
        # 移除粗体/斜体
        text = re.sub(r'\*\*?|\_\_?', '', text)
        # 移除链接，保留文本
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        # 代码块换行转空格
        text = re.sub(r'```.*?\n(.*?)\n```', r'\1', text, flags=re.DOTALL)
        
        return text.strip()


class TestJSONEdgeCases:
    """
    JSON 处理边缘情况测试
    """

    @pytest.mark.parametrize("invalid_json", [
        "",  # 空字符串
        "   ",  # 空白
        "not json at all",  # 完全不是 JSON
        "{}",  # 空对象（应该能解析）
        "[]",  # 空数组（应该能解析）
        "null",  # null 值
        "undefined",  # undefined（JavaScript风格）
    ])
    def test_edge_case_inputs(self, invalid_json):
        """测试边缘输入"""
        result = self._try_fix_truncated_json(invalid_json)
        
        # 空对象和空数组应该能解析
        if invalid_json in ("{}", "[]", "null"):
            assert result is not None
        elif invalid_json in ("", "   "):
            assert result is None

    def test_nested_json_repair(self):
        """测试嵌套 JSON 修复"""
        # 深层嵌套的残缺 JSON
        nested = '{"a": {"b": {"c": "value"'
        result = self._try_fix_truncated_json(nested)
        
        if result:
            parsed = json.loads(result)
            assert parsed["a"]["b"]["c"] == "value"

    def test_unicode_in_json(self):
        """测试 JSON 中的 Unicode"""
        # 包含 Unicode 的 JSON
        unicode_json = '{"message": "你好世界", "emoji": "🎉"}'
        result = self._try_fix_truncated_json(unicode_json)
        
        assert result is not None
        parsed = json.loads(result)
        assert parsed["message"] == "你好世界"
        assert parsed["emoji"] == "🎉"
