"""
设计师 Agent
基于 LangGraph 状态机实现，继承 BaseAgent 统一调用逻辑

职责：
1. 分析 ArchitectAgent 的输出
2. 结合项目文件树（特别是 backend/app/api/ 风格）
3. 结合代码库上下文（语义检索 + 完整文件内容）
4. 输出详细的技术设计方案
"""

import json
from typing import Dict, Optional, Any

from app.agents.base import LangGraphAgent
from app.agents.schemas import DesignerOutput


class DesignerAgent(LangGraphAgent[DesignerOutput]):
    """
    设计师 Agent
    
    根据架构师输出进行详细技术设计
    继承 LangGraphAgent，只需实现业务差异部分
    """
    
    def __init__(self):
        super().__init__(agent_name="DesignerAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调复用现有风格"""
        return """你是 OmniFlowAI 的设计师 Agent，负责根据架构师的分析输出详细的技术设计方案。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻  
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

【核心原则】
以创造接口为耻，以复用现有为荣！

【任务要求】
1. 仔细阅读 ArchitectAgent 的输出（功能描述、受影响文件列表）
2. 分析项目文件树，特别是 backend/app/api/ 目录下的现有 API 风格
3. 【重要】仔细阅读提供的代码上下文（related_code_context 和 full_files_context）
4. 参考现有代码的组织方式、命名规范和实现风格
5. 输出详细的技术设计方案，包含：
   - technical_design: 技术设计方案概述
   - api_endpoints: API 端点列表（包含 method, path, description）
   - function_changes: 函数修改列表（包含 file, function, action: add/modify/delete, description）
   - logic_flow: 逻辑流图（文本描述形式）
   - dependencies: 新增依赖列表
   - affected_files: 受影响文件列表（相对路径）

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "technical_design": "...",
    "api_endpoints": [
        {"method": "POST", "path": "/api/v1/...", "description": "..."}
    ],
    "function_changes": [
        {"file": "backend/app/...", "function": "...", "action": "add", "description": "..."}
    ],
    "logic_flow": "...",
    "dependencies": ["..."],
    "affected_files": ["backend/app/..."]
}

【风格参考】
- 路由层：backend/app/api/v1/*.py，使用 FastAPI APIRouter
- 业务层：backend/app/service/*.py，实现业务逻辑
- 模型层：backend/app/models/*.py，使用 SQLModel
- 所有 API 返回统一格式：{success, data, error, request_id}

【代码上下文参考 - 重要】
我们为你检索了项目中相关的现有代码片段（在 related_code_context 字段中）。
同时提供了完整文件内容（在 full_files_context 字段中）。

核心铁律：
- 以复用现有逻辑为荣，以重复造轮子为耻！
- 请务必参考这些片段的风格、类定义和工具函数来设计你的方案
- 如果检索到的代码中有类似的实现，请优先复用或扩展，而不是从头创建
- 注意保持与现有代码的命名规范、参数风格和错误处理方式一致
- 仔细阅读完整文件内容，理解现有代码的架构和模式

【项目结构参考】
在 project_structure_summary 字段中提供了项目整体结构摘要，帮助你理解代码库规模和组织方式。

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 优先复用现有的接口和模式（参考 related_code_context）
- 遵循项目现有的架构分层规范
- 如果检索到的代码中有可用的工具函数或类，请在设计中明确引用
- affected_files 必须包含所有需要修改或新增的文件路径
"""
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt
        
        Args:
            state: 包含 architect_output, file_tree, related_code_context, full_files_context 的状态
        """
        architect_output = state.get("architect_output", {})
        file_tree = state.get("file_tree", {})
        related_code_context = state.get("related_code_context")
        full_files_context = state.get("full_files_context")
        
        architect_str = json.dumps(architect_output, indent=2, ensure_ascii=False)
        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
        
        # 构建代码上下文部分
        code_context_section = ""
        
        # 第一层：语义检索结果
        if related_code_context:
            code_context_section += f"""
【相关代码片段 - 语义检索结果】
以下是通过 RAG 检索到的与需求相关的代码片段：

{related_code_context}
"""
        
        # 第二层：完整文件内容
        if full_files_context:
            files_content = []
            for file_path, content in full_files_context.items():
                # 限制每个文件的内容长度，避免超出 token 限制
                max_content_length = 3000  # 约 1000 tokens
                truncated_content = content[:max_content_length]
                if len(content) > max_content_length:
                    truncated_content += f"\n... (文件剩余 {len(content) - max_content_length} 字符已省略)"
                
                files_content.append(f"""--- 文件: {file_path} ---
```python
{truncated_content}
```""")
            
            full_files_str = "\n\n".join(files_content)
            code_context_section += f"""
【完整文件内容】
以下是相关文件的完整内容（用于理解代码风格和架构）：

{full_files_str}
"""
        
        return f"""【ArchitectAgent 输出】
{architect_str}

【项目文件树】
```
{file_tree_str}
```
{code_context_section}

请根据以上信息，输出详细的技术设计方案（JSON 格式）。
注意参考 backend/app/api/ 目录下的现有 API 风格，优先复用现有接口和模式。
"""
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)
    
    def validate_output(self, output: Dict[str, Any]) -> DesignerOutput:
        """校验输出为 DesignerOutput 模型"""
        return DesignerOutput(**output)
    
    async def design(
        self,
        architect_output: Dict[str, Any],
        file_tree: Dict[str, Any],
        related_code_context: Optional[str] = None,
        full_files_context: Optional[Dict[str, str]] = None,
        pipeline_id: int = 0
    ) -> Dict[str, Any]:
        """
        根据架构师输出进行技术设计
        
        Args:
            architect_output: ArchitectAgent 的输出内容
            file_tree: 项目文件树
            related_code_context: 语义检索结果（代码片段）
            full_files_context: 完整文件内容映射
            pipeline_id: Pipeline ID
            
        Returns:
            Dict: 包含设计结果或错误信息
        """
        initial_state = {
            "architect_output": architect_output,
            "file_tree": file_tree,
            "related_code_context": related_code_context,
            "full_files_context": full_files_context
        }
        
        result = await self.execute(
            pipeline_id=pipeline_id,
            stage_name="DESIGN",
            initial_state=initial_state
        )
        
        return result


# 单例实例
designer_agent = DesignerAgent()
