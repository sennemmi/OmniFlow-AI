"""
架构师 Agent
基于 LangGraph 状态机实现，继承 BaseAgent 统一调用逻辑

职责：
1. 分析用户需求
2. 结合项目上下文（文件树）
3. 输出结构化设计方案
"""

import json
from typing import Dict, List, Optional, Any

from app.agents.base import LangGraphAgent
from app.agents.schemas import ArchitectOutput


class ArchitectAgent(LangGraphAgent[ArchitectOutput]):
    """
    架构师 Agent
    
    分析需求并输出技术设计方案
    继承 LangGraphAgent，只需实现业务差异部分
    """
    
    def __init__(self):
        super().__init__(agent_name="ArchitectAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 包含八荣八耻准则"""
        return """你是 OmniFlowAI 的架构师 Agent，负责分析需求并输出技术设计方案。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻  
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

【任务要求】
1. 仔细阅读用户需求
2. 分析项目文件树结构，理解现有代码组织
3. 输出结构化的 JSON 格式方案，包含：
   - feature_description: 功能描述（简洁明了）
   - affected_files: 受影响文件列表（相对路径）
   - estimated_effort: 预估工作量（如：2小时、1天）
   - technical_design: 技术设计方案（可选，详细描述）

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "feature_description": "...",
    "affected_files": ["file1.py", "file2.py"],
    "estimated_effort": "...",
    "technical_design": "..."
}

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 文件路径使用相对路径
- 遵循项目现有的架构分层规范
"""
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt
        
        Args:
            state: 包含 requirement, file_tree, element_context 的状态
        """
        requirement = state.get("requirement", "")
        file_tree = state.get("file_tree", {})
        element_context = state.get("element_context")
        
        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
        
        # 构建 element_context 部分
        element_context_str = ""
        if element_context:
            element_context_str = f"""
【页面元素上下文】
- HTML: {element_context.get('html', 'N/A')}
- XPath: {element_context.get('xpath', 'N/A')}
- 数据源: {element_context.get('data_source', 'N/A')}

请根据以上元素上下文进行精准修复。
"""
        
        return f"""【用户需求】
{requirement}

【项目文件树】
```
{file_tree_str}
```
{element_context_str}

请根据以上信息，输出结构化的技术设计方案（JSON 格式）。
"""
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)
    
    def validate_output(self, output: Dict[str, Any]) -> ArchitectOutput:
        """校验输出为 ArchitectOutput 模型"""
        return ArchitectOutput(**output)
    
    async def analyze(
        self,
        requirement: str,
        file_tree: Dict[str, Any],
        element_context: Optional[Dict[str, Any]] = None,
        pipeline_id: int = 0
    ) -> Dict[str, Any]:
        """
        分析需求并输出方案
        
        Args:
            requirement: 用户需求描述
            file_tree: 项目文件树字典
            element_context: 页面元素上下文（可选）
            pipeline_id: Pipeline ID
            
        Returns:
            Dict: 包含分析结果或错误信息
        """
        initial_state = {
            "requirement": requirement,
            "file_tree": file_tree,
            "element_context": element_context
        }
        
        result = await self.execute(
            pipeline_id=pipeline_id,
            stage_name="ARCHITECT",
            initial_state=initial_state
        )
        
        return result


# 单例实例
architect_agent = ArchitectAgent()
