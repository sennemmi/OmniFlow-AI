"""
编码 Agent
基于 LangGraph 状态机实现，继承 BaseAgent 统一调用逻辑

职责：
1. 分析 DesignerAgent 的技术方案
2. 读取目标文件当前内容
3. 生成符合项目风格的代码
"""

import json
import logging
from typing import Dict, Optional, Any

from app.agents.base import LangGraphAgent
from app.agents.schemas import CoderOutput

logger = logging.getLogger(__name__)


class CoderAgent(LangGraphAgent[CoderOutput]):
    """
    编码 Agent
    
    根据设计方案生成代码变更
    继承 LangGraphAgent，只需实现业务差异部分
    """
    
    def __init__(self):
        super().__init__(agent_name="CoderAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调保持架构和风格"""
        return """你是 OmniFlowAI 的编码 Agent，负责根据技术设计方案生成代码。

【八荣八耻准则】
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻
以状态管理为荣，以随意变更全局为耻
以认真查询为荣，以随意假设为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以单元测试为荣，以手工验证为耻
以监控告警为荣，以故障未知为耻

【核心铁律】
以破坏架构为耻！

【任务要求】
1. 仔细阅读 DesignerAgent 的技术方案（API 端点、函数变更、逻辑流）
2. 分析目标文件的当前内容和代码风格
3. 生成代码时必须遵守：
   - 保持原有的缩进风格（空格/Tab 数量）
   - 保持原有的注释风格（# 或三引号）
   - 保持架构分层（api/service/model 分离）
   - 复用现有的工具函数和模式
   - 遵循项目的命名规范
   - 不要修改与需求无关的代码

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "files": [
        {
            "file_path": "app/api/v1/example.py",
            "content": "完整的文件内容...",
            "change_type": "add",
            "description": "新增示例 API"
        }
    ],
    "summary": "本次变更添加了用户认证功能，包含登录和注册接口",
    "dependencies_added": [],
    "tests_included": false
}

【风格保持原则】
- 如果原文件使用 4 空格缩进，新代码也必须使用 4 空格
- 如果原文件使用双引号字符串，新代码也使用双引号
- 如果原文件有特定的导入排序风格，保持相同风格
- 如果原文件使用特定的错误处理方式，保持相同方式
- 遵循 FastAPI 和 SQLModel 的最佳实践

【Import 铁律 - 违反视为严重错误】
项目的包结构是 backend/app/...，pytest 从 backend/ 目录运行，PYTHONPATH 包含 backend/。

所有业务代码文件必须使用如下 import 方式：
  from app.core.database import get_session
  from app.models.user import User
  from app.service.user import UserService

绝对不允许使用以下错误的 import 方式：
  from core.database import get_session     # ❌ 错误！缺少 app 前缀
  from models.user import User              # ❌ 错误！缺少 app 前缀
  from service.user import UserService      # ❌ 错误！缺少 app 前缀
  import core.database                      # ❌ 错误！不能这样导入

【环境约束 - 重要】
- 仅允许使用 Python 标准库和项目已有的库（FastAPI, SQLModel, Pydantic, pytest 等）
- 严禁引入未安装的第三方库（如 numpy, pandas, PIL, requests 等），除非需求明确要求且你确定环境已提供
- 必须使用 target_files 中提供的完整文件路径（包含 backend/ 前缀，如 backend/app/xxx.py）

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 文件内容必须是完整的，不是 diff 格式
- 优先复用现有的接口和模式
- 保持代码的可读性和可维护性
"""
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt
        
        Args:
            state: 包含 design_output, target_files, error_context 的状态
        """
        design_output = state.get("design_output", {})
        target_files = state.get("target_files", {})
        error_context = state.get("error_context")
        
        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)
        
        # 构建文件内容部分
        files_content = []
        for file_path, content in target_files.items():
            files_content.append(f"""【文件: {file_path}】
```python
{content}
```""")
        
        files_str = "\n\n".join(files_content)
        
        # 基础提示
        prompt = f"""【技术设计方案】
{design_str}

【目标文件当前内容】
{files_str}

请根据技术设计方案，生成需要修改或新增的代码。
注意保持原有代码的缩进风格、注释风格和架构分层。
输出完整的文件内容（不是 diff 格式）。
"""
        
        # 如果有报错上下文，注入到 Prompt 头部，强制 Agent 进入修复模式
        if error_context:
            prompt = f"""【！！！修复任务！！！】
你之前的代码在执行测试时失败了。以下是 pytest 的报错信息：

```text
{error_context}
```

请仔细分析报错原因（是语法错误、逻辑错误还是测试用例不匹配），并给出修复后的完整代码。

---

{prompt}"""
        
        return prompt
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)
    
    def validate_output(self, output: Dict[str, Any]) -> CoderOutput:
        """校验输出为 CoderOutput 模型"""
        return CoderOutput(**output)
    
    async def generate_code(
        self,
        design_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None,
        error_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        根据设计方案生成代码

        Args:
            design_output: DesignerAgent 的输出内容
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录
            error_context: 测试失败的错误上下文（用于修复模式）

        Returns:
            Dict: 包含生成结果或错误信息
        """
        from app.core.sse_log_buffer import push_log
        
        files_count = len(target_files)
        logger.info(f"CoderAgent 开始生成代码", extra={
            "pipeline_id": pipeline_id,
            "files_count": files_count,
            "target_files": list(target_files.keys())
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"CoderAgent 开始生成代码，共 {files_count} 个文件...", stage="CODING")
        
        initial_state = {
            "design_output": design_output,
            "target_files": target_files,
            "error_context": error_context
        }
        
        result = await self.execute(
            pipeline_id=pipeline_id or 0,
            stage_name="CODING",
            initial_state=initial_state
        )
        
        if result.get("success"):
            output_files = result.get("output", {}).get("files", [])
            logger.info(f"CoderAgent 代码生成完成", extra={
                "pipeline_id": pipeline_id,
                "generated_files_count": len(output_files),
                "generated_files": [f.get("file_path") for f in output_files]
            })
            if pipeline_id:
                await push_log(pipeline_id, "info", f"代码生成完成，共 {len(output_files)} 个文件", stage="CODING")
        else:
            logger.error(f"CoderAgent 代码生成失败", extra={
                "pipeline_id": pipeline_id,
                "error": result.get("error")
            })
            if pipeline_id:
                await push_log(pipeline_id, "error", f"代码生成失败: {result.get('error', '')}", stage="CODING")
        
        return result


# 单例实例
coder_agent = CoderAgent()
