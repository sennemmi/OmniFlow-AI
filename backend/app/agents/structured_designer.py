"""
结构化设计师 Agent（Instructor 版）

使用 Instructor 库强制 LLM 输出符合 Pydantic Schema 的结构化数据。
从根本上杜绝输出格式随意性，让接口契约与验收标准的映射成为代码可验证的事实。
"""

import json
import logging
from typing import Dict, Optional, Any

from app.agents.schemas import DesignerOutputV2
from app.core.structured_llm import generate_structured_output
from app.core.sse_log_buffer import push_log

logger = logging.getLogger(__name__)


class StructuredDesignerAgent:
    """
    结构化设计师 Agent
    
    使用 Instructor 库实现，强制输出符合 DesignerOutputV2 Schema。
    与原版 DesignerAgent 的区别：
    1. 使用 Instructor 在 API 层强制约束输出格式
    2. 无需手动解析 JSON，直接返回校验后的 Pydantic 对象
    3. contract_alignment 成为必填字段，在 API 层就验证
    """
    
    def __init__(self):
        self.agent_name = "StructuredDesignerAgent"
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调结构化输出和契约对齐"""
        return """你是 OmniFlowAI 的结构化设计师 Agent，负责根据架构师的分析输出详细的技术设计方案。

【核心职责】
你的输出将被 Instructor 库严格约束为 JSON Schema 格式。你必须确保：
1. 所有必填字段都有有效值
2. contract_alignment 必须包含每条验收标准的映射
3. interface_specs 中的符号必须在 contract_alignment 中被引用

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

【contract_alignment 填写指南 - 极其重要】
这是 Instructor 强制约束的必填字段，必须逐条填写：

1. 从 architect_output 的 acceptance_criteria 中复制每一条标准
2. 为每条标准确定需要实现的接口符号（来自 interface_specs）
3. 在 mapping_reason 中具体说明：该接口如何满足该标准（至少20字）

示例：
如果验收标准是："API 返回健康状态字段 overall_health"
那么 contract_alignment 条目应该是：
{
  "acceptance_criteria": "API 返回健康状态字段 overall_health",
  "interface_specs": ["health_check", "HealthService"],
  "mapping_reason": "health_check 是 API 入口函数，返回包含 overall_health 字段的字典；HealthService 负责计算该字段的值"
}

【字段填写要求】
- technical_design: 2-3句话概述整体方案
- api_endpoints: 列出所有新增/修改的 API 端点
- interface_specs: 每个符号必须包含 symbol_name, module, signature, expected_behavior
- contract_alignment: 【必填】每条验收标准对应一个条目
- summary: 一句话总结

【风格参考】
- 路由层：backend/app/api/v1/*.py，使用 FastAPI APIRouter
- 业务层：backend/app/service/*.py，实现业务逻辑
- 模型层：backend/app/models/*.py，使用 SQLModel
- 所有 API 返回统一格式：{success, data, error, request_id}

【注意事项】
- 不要输出任何解释性文字，只输出 JSON
- 确保所有必填字段都有值
- contract_alignment 必须与 acceptance_criteria 一一对应
- interface_specs 中的符号名不能包含点分格式（如 ClassName.method）
"""
    
    def build_user_prompt(
        self,
        architect_output: Dict[str, Any],
        file_tree: Dict[str, Any],
        related_code_context: Optional[str] = None,
        full_files_context: Optional[Dict[str, str]] = None
    ) -> str:
        """构建用户 Prompt"""
        
        # 提取验收标准，用于指导 contract_alignment 填写
        acceptance_criteria = architect_output.get("acceptance_criteria", [])
        criteria_section = ""
        if acceptance_criteria:
            criteria_lines = []
            for i, criteria in enumerate(acceptance_criteria, 1):
                criteria_lines.append(f"{i}. {criteria}")
            criteria_section = f"""
【验收标准列表 - 必须在 contract_alignment 中逐条映射】
{chr(10).join(criteria_lines)}

重要：contract_alignment 列表长度必须等于上述验收标准的数量（{len(acceptance_criteria)} 条）。
"""
        
        architect_str = json.dumps(architect_output, indent=2, ensure_ascii=False)
        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)
        
        # 构建代码上下文部分
        code_context_section = ""
        
        if related_code_context:
            code_context_section += f"""
【相关代码片段 - 语义检索结果】
{related_code_context}
"""
        
        if full_files_context:
            files_content = []
            for file_path, content in full_files_context.items():
                # 限制每个文件的内容长度
                max_content_length = 3000
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
{full_files_str}
"""
        
        return f"""【ArchitectAgent 输出】
{architect_str}

【项目文件树】
```
{file_tree_str}
```
{code_context_section}
{criteria_section}

请根据以上信息，输出符合 Schema 的技术设计方案。
记住：
1. contract_alignment 必须包含每条验收标准的映射
2. 每个映射的 mapping_reason 至少20字
3. interface_specs 中的符号必须在 contract_alignment 中被引用
"""
    
    async def design(
        self,
        architect_output: Dict[str, Any],
        file_tree: Dict[str, Any],
        related_code_context: Optional[str] = None,
        full_files_context: Optional[Dict[str, str]] = None,
        pipeline_id: int = 0
    ) -> Dict[str, Any]:
        """
        执行结构化技术设计
        
        使用 Instructor 强制 LLM 输出符合 DesignerOutputV2 Schema。
        
        Args:
            architect_output: ArchitectAgent 的输出（包含 acceptance_criteria）
            file_tree: 项目文件树
            related_code_context: 语义检索结果
            full_files_context: 完整文件内容
            pipeline_id: Pipeline ID
            
        Returns:
            Dict: 包含设计结果或错误信息
        """
        await push_log(pipeline_id, "info", "结构化设计师 Agent 开始工作...", stage="DESIGN")
        
        try:
            # 构建 Prompt
            system_prompt = self.system_prompt
            user_prompt = self.build_user_prompt(
                architect_output=architect_output,
                file_tree=file_tree,
                related_code_context=related_code_context,
                full_files_context=full_files_context
            )
            
            # 使用 Instructor 生成结构化输出
            output, metadata = await generate_structured_output(
                response_model=DesignerOutputV2,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_retries=3  # Instructor 会自动重试格式错误的输出
            )
            
            # 验证 contract_alignment 与 acceptance_criteria 对齐
            acceptance_criteria = architect_output.get("acceptance_criteria", [])
            contract_alignment = output.contract_alignment
            
            if len(contract_alignment) != len(acceptance_criteria):
                error_msg = f"contract_alignment 数量不匹配：期望 {len(acceptance_criteria)} 条，实际 {len(contract_alignment)} 条"
                await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
                return {
                    "success": False,
                    "error": error_msg,
                    "output": output.model_dump()
                }
            
            # 验证每条验收标准都有对应映射
            aligned_criteria = {item.acceptance_criteria for item in contract_alignment}
            missing_criteria = set(acceptance_criteria) - aligned_criteria
            
            if missing_criteria:
                error_msg = f"以下验收标准缺少映射: {missing_criteria}"
                await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
                return {
                    "success": False,
                    "error": error_msg,
                    "output": output.model_dump()
                }
            
            # 成功
            await push_log(
                pipeline_id, 
                "info", 
                f"✅ 结构化设计完成（{len(output.interface_specs)} 个接口，{len(output.contract_alignment)} 个映射）", 
                stage="DESIGN"
            )
            
            return {
                "success": True,
                "output": output.model_dump(),
                "input_tokens": metadata["input_tokens"],
                "output_tokens": metadata["output_tokens"],
                "total_tokens": metadata["total_tokens"]
            }
            
        except Exception as e:
            error_msg = f"结构化设计失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg
            }


# 单例实例
structured_designer_agent = StructuredDesignerAgent()
