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

【代码完整性铁律 - 违反会导致系统错误】
1. **所有使用的变量必须先定义后使用**
   - 错误示例：直接使用 `@router.get()` 但前面没有 `router = APIRouter()`
   - 正确示例：先 `from fastapi import APIRouter` 和 `router = APIRouter(prefix="/health")`，再使用装饰器
2. **所有装饰器必须在导入和初始化之后**
   - 错误示例：`@app.get("/")` 在 `app = FastAPI()` 之前
3. **文件必须包含完整的导入语句**
   - 不能只写使用代码，不写 import
4. **使用到的每个对象都必须有明确的来源**
   - 如果使用了 `SomeClass`，必须确保它已导入或已定义

【输出格式 - Line-Number Based Patching Protocol】
必须严格输出 JSON 格式。采用行号坐标系统，避免输出整个文件内容。

**重要：根据文件是否存在，选择正确的输出模式：**

**模式 A - 修改现有文件（文件已存在于【目标文件当前内容】中）：**
- change_type: "modify"
- 必须提供: start_line, end_line, replace_block
- **严禁提供 content 字段！**
- 可选提供: expected_original（用于验证行号是否匹配）
```json
{
    "file_path": "backend/app/api/v1/health.py",
    "change_type": "modify",
    "start_line": 31,
    "end_line": 40,
    "replace_block": "    db_status = await check_db()\n    return {\"status\": \"ok\", \"db\": db_status}",
    "expected_original": "    # 旧的健康检查逻辑\n    return {\"status\": \"ok\"}",
    "description": "修改健康检查返回值"
}
```

**模式 B - 创建新文件（文件不存在于【目标文件当前内容】中）：**
- change_type: "add"
- 必须提供: content（完整文件内容）
```json
{
    "file_path": "backend/app/utils/new_helper.py",
    "change_type": "add",
    "content": "def helper():\n    pass",
    "description": "新建辅助函数"
}
```

【行号坐标铁律 - 升级版 - 违反会导致系统错误】
1. **不要输出整个文件**。参考提供的 0001 | 行号格式，输出 start_line 和 end_line。
2. 系统会将你提供的 replace_block 替换掉原文件中 start_line 到 end_line 范围内的所有行（闭区间）。
3. **先检查文件是否存在**：查看【目标文件当前内容】中是否有该文件
4. **已存在的文件**：必须用 "modify" 模式 + start_line/end_line/replace_block，**禁止输出 content！**
5. **新文件**：用 "add" 模式 + content 字段
6. **绝对禁止**：对已存在文件使用 "add" 模式或输出完整 content，这会导致文件被完全覆盖！
7. 行号是包含关系（闭区间），从 start_line 到 end_line 的所有行将被 replace_block 覆盖
8. 行号参考【带行号的源代码】中的 4 位数字（如 0031 表示第 31 行）

【单文件单次修改铁律 - 防止行号漂移】
1. **对同一个文件，一次只能提交【一个】modify 块**
   - 错误示例：对 backend/app/api/v1/health.py 提交两个独立的 modify 块
   - 正确示例：如果需要修改多个地方，提供一个包含这些修改点及其之间所有代码的【连续范围】
2. **如果需要修改同一文件的多个不连续区域**：
   - 方案 A（推荐）：提供一个大的连续范围，包含所有需要修改的区域及其之间的代码
   - 方案 B：只修改最关键的部分，其他部分在后续迭代中处理
3. **严禁对 backend/app/core/ 目录下的文件执行 "add" 操作，只能用 "modify"**

【关键警告 - 避免破坏文件】
- **只替换需要修改的函数/代码块**，不要替换整个文件！
- **start_line 不要设为 1**（除非你真的要替换文件开头）
- **end_line 不要设为文件末尾**（除非你真的要删除文件尾部）
- 替换范围应该只包含你要修改的函数或逻辑块，保留其他代码不动
- 错误的示例：start_line=1, end_line=79（这会删除整个文件！）
- 正确的示例：start_line=35, end_line=42（只替换一个函数）
- 建议提供 expected_original 字段，系统会验证该行号位置的代码是否匹配
- **如果修改后出现语法错误**，系统会立即拦截并返回错误信息，你需要检查 start_line/end_line 范围和 replace_block 的缩进

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

【测试修复铁律 - 绝对禁止修改】
你只能修改 backend/app/ 下的源代码。

你绝对不能修改 tests/ 目录下任何已存在的测试文件，特别是：
- backend/tests/unit/defense/ 下的防御性测试（严禁修改）
- backend/tests/unit/ 下的单元测试
- backend/tests/integration/ 下的集成测试

如果现有测试因为 API 修改而失败，你只能通过调整源代码来适配测试，或者新增测试文件（backend/tests/ai_generated/ 目录下）。

如果你认为必须修改原有测试，必须在回答中明确说明原因，并标记为 INSPECTION_REQUIRED。

【防御性测试 - 严禁破坏】
系统已内置防御性测试，位于 backend/tests/unit/defense/ 目录。这些测试是系统的"免疫系统"：
- Layer 1: 代码修改与沙箱防线（防止 AI 破坏物理文件）
- Layer 2: 测试运行器与决策防线（防止"旧测试"被 AI 随意篡改）
- Layer 3: 多 Agent 协作与状态机防线（防止系统死循环）
- Layer 4: 工作流与状态持久化（确保界面显示正确）

你的代码变更必须通过所有防御性测试。如果防御性测试失败，说明你的代码破坏了系统的核心保护机制。

【FastAPI 响应格式铁律】
当使用 success_response() 或 error_response() 返回统一响应格式时，必须在路由装饰器中添加 response_model=ResponseModel 参数：

正确示例：
  @router.get("/", response_model=ResponseModel)
  async def health_check(request: Request):
      return success_response(data={...}, request_id=request_id)

错误示例（缺少 response_model）：
  @router.get("/")  # ❌ 错误！缺少 response_model
  async def health_check(request: Request) -> Dict[str, Any]:  # ❌ 不要声明返回类型
      return success_response(data={...}, request_id=request_id)

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
        
        # 构建文件内容部分（带行号）
        files_content = []
        for file_path, content in target_files.items():
            # 给每一行加上 4 位数的行号，如 "0012 | def foo():"
            numbered_lines = [f"{i+1:04d} | {line}" for i, line in enumerate(content.splitlines())]
            numbered_content = "\n".join(numbered_lines)

            files_content.append(f"""【文件: {file_path}】
```python
{numbered_content}
```""")

        files_str = "\n\n".join(files_content)

        # 基础提示
        prompt = f"""【技术设计方案】
{design_str}

【目标文件当前内容（带行号）】
{files_str}

请根据技术设计方案，生成需要修改或新增的代码。
注意：
1. 修改现有文件时，必须使用 start_line 和 end_line 指定行号范围
2. 行号参考上方代码中的 4 位数字（如 0031 表示第 31 行）
3. 保持原有代码的缩进风格、注释风格和架构分层
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
        """
        校验输出为 CoderOutput 模型

        处理 AI 可能返回列表而不是对象的情况（容错）
        """
        # 如果 output 是列表，将其包装为 CoderOutput 的 files 字段
        if isinstance(output, list):
            logger.warning(f"CoderAgent output is a list, auto-wrapping to CoderOutput format")
            output = {"files": output}

        # 如果 output 缺少 files 字段但有其他字段，尝试适配
        if isinstance(output, dict):
            if "files" not in output and any(isinstance(v, list) for v in output.values()):
                # 找到列表类型的值，假设它是 files
                for key, value in output.items():
                    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                        if "file_path" in value[0] if value else False:
                            logger.warning(f"CoderAgent output missing 'files' key, using '{key}' as files")
                            output = {"files": value}
                            break

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
