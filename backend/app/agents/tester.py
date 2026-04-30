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

【分层测试策略 - 快速失败原则】
测试按照"发现问题速度"和"修复成本"分层执行：

Layer 1 - 语法检查（毫秒级）：
- 使用 ast.parse 检查新生成代码的语法
- 失败立即返回，不进入后续层

Layer 2 - 防御性测试（秒级，核心保护机制）：
- 位于 backend/tests/unit/defense/ 目录
- 是系统的"免疫系统"，包含 4 层防线：
  * 代码修改与沙箱防线：文件回滚、路径安全、导入清理
  * 测试运行器与决策防线：语法拦截、回归保护
  * 多 Agent 协作与状态机防线：Pydantic 校验、重试限制、JSON 剥离
  * 工作流与状态持久化防线：状态流转、反馈传递
- 【关键】防御性测试失败 = 代码破坏了核心保护机制
- 【关键】防御性测试失败必须人工介入，不能 Auto-Fix

Layer 3 - 新测试（秒级，功能验证）：
- 位于 backend/tests/ai_generated/ 目录（你生成的测试）
- 验证新生成功能是否符合预期
- 失败可进入 Auto-Fix 循环自动修复

Layer 4 - 健康检查（服务启动验证）：
- 验证代码是否能正常启动服务

【重要】你生成的新测试必须：
- 放置于 backend/tests/ai_generated/ 目录
- 通过 Layer 1 语法检查（ast.parse 秒级完成）
- 通过 Layer 2 防御性测试（不能破坏核心保护机制）
- 不能与 backend/tests/unit/defense/ 中的防御性测试冲突
- 不能修改 backend/tests/unit/ 和 backend/tests/integration/ 下的旧测试（受保护层）
- 如果测试失败，系统会告诉你具体的失败测试名称和错误日志

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
            "file_path": "backend/tests/ai_generated/test_example.py",
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
- 必须使用完整的文件路径（包含 backend/ 前缀，如 backend/tests/ai_generated/test_xxx.py）
- 严禁修改 backend/tests/unit/defense/ 下的防御性测试
"""
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt

        Args:
            state: 包含 design_output, code_output 的状态
        """
        design_output = state.get("design_output", {})
        code_output = state.get("code_output", {})
        design_str = json.dumps(design_output, indent=2, ensure_ascii=False)

        # ── 骨架模式 ──────────────────────────────────────────────────────
        if state.get("skeleton_mode"):
            return f"""【任务】基于技术设计方案生成测试骨架（不需要实现断言，用 TODO 占位）。

【技术设计方案】
{design_str}

请输出 JSON，test_files[].content 中每个测试函数体写 `assert True  # TODO: fill after code`。
输出格式与正常模式完全相同。"""

        # ── 填充模式 ──────────────────────────────────────────────────────
        if state.get("fill_mode"):
            skeleton_output = state.get("skeleton_output", {})
            skeleton_str = json.dumps(skeleton_output, indent=2, ensure_ascii=False)
            code_str = json.dumps(code_output, indent=2, ensure_ascii=False)
            return f"""【任务】将以下测试骨架的 TODO 替换为真实断言。

【测试骨架（待填充）】
{skeleton_str}

【CoderAgent 生成的代码】
{code_str}

【重要 - 使用工具读取目标文件】
在填充断言前，请使用以下工具读取目标文件的最新内容：
1. glob("app/**/*.py") - 发现相关文件
2. read_file("app/xxx.py", 1, 50) - 读取文件内容

请输出完整的测试文件（JSON 格式），不要保留任何 TODO 占位。"""

        # ── 原有完整模式（兜底）─────────────────────────────────────────
        code_str = json.dumps(code_output, indent=2, ensure_ascii=False)
        return f"""【技术设计方案】
{design_str}

【CoderAgent 生成的代码】
{code_str}

【重要 - 使用工具读取目标文件】
在编写测试前，请使用以下工具读取目标文件的最新内容：
1. glob("app/**/*.py") - 发现相关文件
2. read_file("app/xxx.py", 1, 50) - 读取文件内容

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
    
    async def generate_skeleton(
        self,
        design_output: Dict[str, Any],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        第一阶段：仅基于 design_output 生成测试骨架。
        不依赖 CoderAgent 输出，可与 CoderAgent 并发执行。
        骨架包含：测试文件结构、测试函数签名、TODO 占位断言。
        """
        from app.core.sse_log_buffer import push_log
        if pipeline_id:
            await push_log(pipeline_id, "info", "TestAgent 开始生成测试骨架...", stage="CODING")

        initial_state = {
            "design_output": design_output,
            "code_output": {},      # 空，此时代码还没生成
            "target_files": {},
            "skeleton_mode": True,  # 告知 build_user_prompt 进入骨架模式
        }
        result = await self.execute(
            pipeline_id=pipeline_id or 0,
            stage_name="CODING",
            initial_state=initial_state
        )
        return result

    async def fill_assertions(
        self,
        skeleton_output: Dict[str, Any],
        code_output: Dict[str, Any],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        第二阶段：拿到 CoderAgent 的代码后，填充骨架里的 TODO 断言。
        串行执行（必须等 CoderAgent 完成）。

        【改造】不再传入 target_files，使用工具按需读取文件
        """
        from app.core.sse_log_buffer import push_log
        if pipeline_id:
            await push_log(pipeline_id, "info", "TestAgent 填充测试断言...", stage="CODING")

        initial_state = {
            "design_output": {},
            "code_output": code_output,
            "skeleton_output": skeleton_output,  # 传入骨架
            "fill_mode": True,
        }
        result = await self.execute(
            pipeline_id=pipeline_id or 0,
            stage_name="CODING",
            initial_state=initial_state
        )
        return result

    async def generate_tests(
        self,
        design_output: Dict[str, Any],
        code_output: Dict[str, Any],
        pipeline_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        根据设计方案和生成的代码生成测试

        【改造】TestAgent 现在使用工具按需读取文件，不再依赖预加载的 target_files

        Args:
            design_output: DesignerAgent 的输出内容
            code_output: CoderAgent 的输出内容
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
            "code_output": code_output
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
