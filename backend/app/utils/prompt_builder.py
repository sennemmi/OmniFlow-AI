"""
Agent Prompt 构建工具类

提供统一的公共 Prompt 模板，减少各 Agent 中重复的 JSON 输出要求、错误示例等文本。
"""

from typing import Dict, List, Optional


class AgentPromptBuilder:
    """
    Agent Prompt 构建器
    
    统一管理和组合各 Agent 的公共 Prompt 部分。
    """
    
    # 公共的 JSON 输出要求
    JSON_OUTPUT_REQUIREMENTS = """
【强制：JSON 输出格式】
你必须直接输出纯 JSON，不要包含任何其他文本（如 markdown 代码块标记、解释性文字等）。

✅ 正确示例：
{
  "field1": "value1",
  "field2": "value2"
}

❌ 错误示例（不要这样做）：
```json
{
  "field1": "value1"
}
```

❌ 错误示例（不要这样做）：
以下是输出结果：
{
  "field1": "value1"
}

【强制要求】
1. 只输出 JSON，不要有任何前缀或后缀
2. 确保 JSON 格式合法（使用双引号、正确的逗号分隔等）
3. 如果字段是列表，即使是空列表也要输出 []
4. 如果字段是字符串，确保转义特殊字符
"""

    # 公共的代码修改格式要求
    CODE_CHANGE_FORMAT = """
【强制：代码修改格式】
所有代码修改必须使用 search_block 和 replace_block 格式：

{
  "file_path": "backend/app/example.py",
  "change_type": "modify",
  "search_block": "旧代码内容（必须完全匹配原文件）",
  "replace_block": "新代码内容",
  "description": "修改说明"
}

【search_block 匹配规则】
1. 必须与原文件内容完全一致（包括空格、缩进、换行）
2. 建议包含足够的上下文（前后3-5行）以确保唯一匹配
3. 如果多次匹配失败，改用 change_type: "add" 输出完整文件内容
"""

    # 公共的错误处理要求
    ERROR_HANDLING = """
【错误处理】
1. 如果无法完成任务，返回明确的错误信息
2. 不要编造不存在的数据或代码
3. 如果不确定，说明不确定的原因
4. 保持诚实，不要假装完成了实际未完成的工作
"""

    # 各 Agent 角色的特定说明模板
    ROLE_SPECIFIC_TEMPLATES = {
        "architect": """
你是 OmniFlowAI 的架构师 Agent。

【职责】
1. 分析用户需求，设计技术方案
2. 定义必需实现的符号（函数、类、API 端点）
3. 规划文件结构和模块依赖

【输出要求】
- required_symbols: 必需实现的符号清单
- affected_files: 受影响的文件列表
- acceptance_criteria: 可验证的验收标准
""",
        "designer": """
你是 OmniFlowAI 的设计师 Agent。

【职责】
1. 基于架构师输出，设计详细的技术方案
2. 定义接口契约（interface_specs）
3. 规划 API 端点和数据模型

【输出要求】
- interface_specs: 接口契约清单（必须包含 symbol_name, module, return_fields）
- api_endpoints: API 端点定义
- affected_files: 受影响的文件列表
""",
        "coder": """
你是 OmniFlowAI 的代码生成 Agent。

【职责】
1. 基于设计方案，生成可运行的代码
2. 实现所有 interface_specs 中定义的接口
3. 确保代码符合项目规范

【输出要求】
- files: 代码文件列表（使用 search_block/replace_block 格式）
- summary: 代码生成总结
""",
        "tester": """
你是 OmniFlowAI 的测试生成 Agent。

【职责】
1. 基于接口契约，生成测试用例
2. 使用 pytest 框架
3. 正确配置 mock 依赖

【输出要求】
- test_files: 测试文件列表
- coverage: 测试覆盖的接口清单
""",
        "repairer": """
你是 OmniFlowAI 的代码修复 Agent。

【职责】
1. 分析测试失败日志
2. 修复代码逻辑错误
3. 可以修改被测代码或测试代码

【修复优先级】
1. 先检查是否是 Mock 配置错误（改测试代码）
2. 再检查是否是业务逻辑错误（改被测代码）
3. 严禁删除测试断言来通过测试
"""
    }

    @classmethod
    def get_common_prompt(cls) -> str:
        """
        获取公共 Prompt 部分
        
        包含 JSON 输出要求、代码修改格式、错误处理等。
        
        Returns:
            str: 公共 Prompt 文本
        """
        return f"""
{cls.JSON_OUTPUT_REQUIREMENTS}

{cls.CODE_CHANGE_FORMAT}

{cls.ERROR_HANDLING}
""".strip()

    @classmethod
    def get_role_prompt(cls, agent_role: str) -> str:
        """
        获取特定角色的 Prompt
        
        Args:
            agent_role: Agent 角色（architect/designer/coder/tester/repairer）
            
        Returns:
            str: 角色特定的 Prompt 文本
        """
        role_prompt = cls.ROLE_SPECIFIC_TEMPLATES.get(agent_role, "")
        if not role_prompt:
            raise ValueError(f"未知的 Agent 角色: {agent_role}，可用角色: {list(cls.ROLE_SPECIFIC_TEMPLATES.keys())}")
        
        return role_prompt.strip()

    @classmethod
    def build_full_prompt(cls, agent_role: str, additional_instructions: Optional[str] = None) -> str:
        """
        构建完整的 Prompt
        
        组合公共 Prompt 和角色特定 Prompt。
        
        Args:
            agent_role: Agent 角色
            additional_instructions: 额外的特定说明（可选）
            
        Returns:
            str: 完整的 Prompt 文本
        """
        parts = [
            cls.get_role_prompt(agent_role),
            "",
            cls.get_common_prompt()
        ]
        
        if additional_instructions:
            parts.extend([
                "",
                "【特定说明】",
                additional_instructions
            ])
        
        return "\n".join(parts)

    @classmethod
    def get_json_schema_instruction(cls, schema_description: str, example: Optional[Dict] = None) -> str:
        """
        获取 JSON Schema 说明
        
        用于指导 LLM 输出特定格式的 JSON。
        
        Args:
            schema_description: Schema 描述文本
            example: 示例字典（可选）
            
        Returns:
            str: JSON Schema 说明文本
        """
        instruction = f"""
【输出 Schema】
{schema_description}
""".strip()
        
        if example:
            import json
            example_str = json.dumps(example, ensure_ascii=False, indent=2)
            instruction += f"""

【示例】
{example_str}
"""
        
        return instruction


# 便捷函数
def get_common_prompt() -> str:
    """获取公共 Prompt"""
    return AgentPromptBuilder.get_common_prompt()


def build_agent_prompt(agent_role: str, additional_instructions: Optional[str] = None) -> str:
    """构建 Agent 完整 Prompt"""
    return AgentPromptBuilder.build_full_prompt(agent_role, additional_instructions)
