"""
测试 Agent
基于 LangGraph 状态机实现，继承 BaseAgent 统一调用逻辑

职责：
1. 分析 DesignerAgent 的技术方案
2. 分析 CoderAgent 生成的代码
3. 生成符合项目风格的单元测试代码
"""

import json
import logging
from typing import Dict, Optional, Any

from app.agents.base import LangGraphAgent
from app.agents.schemas import TesterOutput

logger = logging.getLogger(__name__)


class TesterAgent(LangGraphAgent[TesterOutput]):
    """
    测试 Agent
    
    根据设计方案和生成的代码编写单元测试
    继承 LangGraphAgent，只需实现业务差异部分
    """
    
    def __init__(self):
        super().__init__(agent_name="TesterAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调测试覆盖和代码风格"""
        return """你是 OmniFlowAI 的测试 Agent，负责根据技术设计方案和生成的代码编写单元测试。

【八荣八耻准则】
以单元测试为荣，以手工验证为耻
以架构分层为荣，以循环依赖为耻
以接口抽象为荣，以硬编码为耻
以详实文档为荣，以口口相传为耻
以版本锁定为荣，以依赖混乱为耻
以监控告警为荣，以故障未知为耻

【核心铁律】
以单元测试为荣！

【任务要求】
1. 仔细阅读 DesignerAgent 的技术方案（API 端点、函数变更、逻辑流）
2. 仔细阅读 CoderAgent 生成的代码
3. 生成测试代码时必须遵守：
   - 使用 pytest 框架
   - 保持与主代码相同的缩进风格（空格或Tab数量）
   - 保持与主代码相同的注释风格（井号或三引号）
   - 测试函数名以 test_ 开头
   - 使用 pytest-asyncio 测试异步函数
   - 使用 pytest-mock 进行必要的 mock
   - 覆盖正常路径和异常路径
   - 测试边界条件和错误处理
   - 不要测试与需求无关的代码

【IMPORT 规范 - 绝对遵守】
所有测试文件必须使用如下 import 方式（从 app 包导入）：
  from app.main import app
  from app.core.database import get_session
  from app.models.user import User

绝对不允许使用以下错误的 import 方式：
  from main import app              # ❌ 错误！缺少 app 前缀
  import main                       # ❌ 错误！不能导入 main 模块
  from backend.app.main import app  # ❌ 错误！不需要 backend 前缀

【输出格式】
必须严格输出 JSON 格式，不要包含 Markdown 代码块标记：
{
    "test_files": [
        {
            "file_path": "tests/test_example.py",
            "content": "完整的测试文件内容...",
            "target_module": "app.api.v1.example",
            "test_cases_count": 5
        }
    ],
    "summary": "本次生成了 5 个测试用例，覆盖了用户认证功能的正常路径和异常路径",
    "coverage_targets": [
        "用户登录接口 - 正常登录",
        "用户登录接口 - 密码错误",
        "用户登录接口 - 用户不存在"
    ],
    "dependencies_added": ["pytest", "pytest-asyncio", "pytest-mock"]
}

【测试编写原则】
- 每个测试函数只测试一个概念
- 使用 Arrange-Act-Assert 结构
- 使用描述性的测试函数名
- 使用 fixtures 共享测试数据
- 使用 parametrize 测试多组数据
- 测试异步函数时使用 @pytest.mark.asyncio
- 测试数据库操作时使用 mock 或测试数据库

【注意事项】
- 只输出 JSON，不要有其他解释性文字
- 确保 JSON 格式合法，可以被解析
- 测试文件内容必须是完整的，不是 diff 格式
- 测试代码必须可以直接运行
- 优先使用 pytest 的最佳实践
- 必须使用完整的文件路径（包含 backend/ 前缀，如 backend/tests/test_xxx.py）
"""
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt
        
        Args:
            state: 包含 design_output, code_output, target_files 的状态
        """
        design_output = state.get("design_output", {})
        code_output = state.get("code_output", {})
        target_files = state.get("target_files", {})
        
        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)
        code_str = json.dumps(code_output, indent=2, ensure_ascii=False)
        
        # 构建文件内容部分
        files_content = []
        for file_path, content in target_files.items():
            files_content.append(f"""【文件: {file_path}】
```python
{content}
```""")
        
        files_str = "\n\n".join(files_content)
        
        return f"""【技术设计方案】
{design_str}

【CoderAgent 生成的代码】
{code_str}

【目标文件当前内容】
{files_str}

请根据技术设计方案和生成的代码，编写完整的单元测试。
注意：
1. 使用 pytest 框架
2. 保持与主代码相同的缩进风格和注释风格
3. 覆盖正常路径、异常路径和边界条件
4. 测试代码必须可以直接运行
"""
    
    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出为字典"""
        return self._parse_json_response(response)
    
    def validate_output(self, output: Dict[str, Any]) -> TesterOutput:
        """校验输出为 TesterOutput 模型"""
        return TesterOutput(**output)
    
    async def generate_tests(
        self,
        design_output: Dict[str, Any],
        code_output: Dict[str, Any],
        target_files: Dict[str, str],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        根据设计方案和生成的代码生成测试

        Args:
            design_output: DesignerAgent 的输出内容
            code_output: CoderAgent 的输出内容
            target_files: 目标文件路径到内容的映射
            pipeline_id: Pipeline ID，用于日志记录

        Returns:
            Dict: 包含生成结果或错误信息
        """
        from app.core.sse_log_buffer import push_log
        
        code_files_count = len(code_output.get("files", [])) if isinstance(code_output, dict) else 0
        logger.info(f"TesterAgent 开始生成测试", extra={
            "pipeline_id": pipeline_id,
            "code_files_count": code_files_count
        })

        if pipeline_id:
            await push_log(pipeline_id, "info", f"TesterAgent 开始生成测试代码...", stage="TESTING")
        
        initial_state = {
            "design_output": design_output,
            "code_output": code_output,
            "target_files": target_files
        }
        
        result = await self.execute(
            pipeline_id=pipeline_id or 0,
            stage_name="TESTING",
            initial_state=initial_state
        )
        
        if result.get("success"):
            test_files = result.get("output", {}).get("test_files", [])
            logger.info(f"TesterAgent 测试生成完成", extra={
                "pipeline_id": pipeline_id,
                "test_files_count": len(test_files)
            })
            if pipeline_id:
                await push_log(pipeline_id, "info", f"测试生成完成，共 {len(test_files)} 个测试文件", stage="TESTING")
        else:
            logger.error(f"TesterAgent 测试生成失败", extra={
                "pipeline_id": pipeline_id,
                "error": result.get("error")
            })
            if pipeline_id:
                await push_log(pipeline_id, "error", f"测试生成失败: {result.get('error', '')}", stage="TESTING")
        
        return result


# 单例实例
tester_agent = TesterAgent()

# 向后兼容的别名
test_agent = tester_agent
