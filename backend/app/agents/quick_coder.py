"""
QuickCoderAgent - 轻量级代码修改 Agent

用于直接修改单个元素，不走完整 Pipeline。
特点：
- 无需 ArchitectAgent 设计阶段
- 直接根据用户指令和源码上下文生成代码变更
- 快速响应，适合小范围修改
"""

import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from app.agents.base import BaseAgent
from app.core.logging import logger, info, error


class QuickCoderOutput(BaseModel):
    """QuickCoder 输出格式"""
    files: List[Dict[str, Any]] = Field(default_factory=list, description="变更的文件列表")
    summary: str = Field(default="", description="变更摘要")


class QuickCoderAgent(BaseAgent[QuickCoderOutput]):
    """轻量级代码修改 Agent"""

    def __init__(self):
        super().__init__(agent_name="QuickCoder")

    @property
    def system_prompt(self) -> str:
        return """你是一个专业的前端代码修改助手。

你的任务是根据用户指令和源码上下文，直接生成代码变更。

## 输出格式
必须返回 JSON 格式：
{
    "files": [
        {
            "file_path": "src/components/Button.tsx",
            "content": "完整的文件内容"
        }
    ],
    "summary": "变更摘要"
}

## 核心规则
1. **只修改与选中元素相关的代码** - 根据提供的 HTML 片段定位要修改的组件/元素
2. **保持原有代码风格** - 不要改变未涉及部分的格式
3. **返回完整的文件内容** - 不是 diff，是完整文件
4. **样式修改优先用 Tailwind 类名** - 不是内联样式
5. **确保代码语法正确**
6. **重要**: 无论是否能确定具体修改位置，都必须返回 files 数组

## 定位策略
- 使用元素的 tag、id、class、text 内容来定位
- 如果提供了 outerHTML，优先匹配这个结构
- 在周围代码(surrounding_code)中查找匹配的元素
- 如果找不到精确匹配，修改最可能相关的部分

## 示例
用户指令：将按钮颜色改为蓝色
选中元素：`<button class="bg-red-500">提交</button>`
周围代码包含：`className="bg-red-500"`
输出：将 `className="bg-red-500"` 改为 `className="bg-blue-500"`

用户指令：将"研发"改为"开发"
选中元素文本："研发流程引擎"
周围代码包含：`<h1>研发流程引擎</h1>`
输出：`<h1>开发流程引擎</h1>`
"""

    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """构建用户 Prompt"""
        user_instruction = state.get("user_instruction", "")
        file_path = state.get("file_path", "")
        file_content = state.get("file_content", "")
        surrounding_code = state.get("surrounding_code", "")
        element_context = state.get("element_context", {})
        line = state.get("line", 0)
        
        # 【调试】打印 state 内容
        logger.info(f"[QuickCoder] build_user_prompt state keys: {list(state.keys())}")
        logger.info(f"[QuickCoder] user_instruction: {user_instruction[:50]}...")
        logger.info(f"[QuickCoder] file_path: {file_path}")
        logger.info(f"[QuickCoder] file_content length: {len(file_content)}")
        logger.info(f"[QuickCoder] surrounding_code length: {len(surrounding_code)}")

        element_info = f"""
【选中元素信息 - 这是你要修改的目标】
- 标签: {element_context.get('tag', 'N/A')}
- ID: {element_context.get('id', 'N/A')}
- Class: {element_context.get('class_name', 'N/A')}
- 文本内容: {element_context.get('text', 'N/A')}
- 完整HTML: {element_context.get('outer_html', 'N/A')[:500]}

【重要】你的任务是修改与上述元素相关的代码，不要修改文件的其他部分。
"""

        prompt = f"""【用户指令】
{user_instruction}

【目标文件】
{file_path}

【修改位置参考】
第 {line} 行附近

【周围代码 - 重点查看此区域】
```
{surrounding_code}
```

【完整文件内容 - 用于参考上下文】
```
{file_content}
```
{element_info}

【任务要求】
1. 根据"选中元素信息"定位要修改的代码
2. 只修改与该元素相关的部分
3. 返回完整的文件内容（未修改部分保持原样）
4. 确保修改后的代码能正确渲染出用户期望的效果

请生成修改后的完整文件内容。
"""
        logger.info(f"[QuickCoder] Prompt length: {len(prompt)}")
        return prompt

    def parse_output(self, response: str) -> Dict[str, Any]:
        """解析 LLM 输出"""
        import re
        # 去除 Markdown 代码块标记
        json_str = re.sub(r'^```json\s*', '', response.strip())
        json_str = re.sub(r'^```\s*', '', json_str)
        json_str = re.sub(r'```\s*$', '', json_str)
        json_str = json_str.strip()
        
        # 【调试】打印原始响应
        logger.info(f"[QuickCoder] LLM 原始响应: {response[:500]}...")
        logger.info(f"[QuickCoder] 解析后 JSON: {json_str[:500]}...")
        
        return json.loads(json_str)

    def validate_output(self, output: Dict[str, Any]) -> QuickCoderOutput:
        """校验输出"""
        return QuickCoderOutput(**output)

    async def generate_code(
        self,
        user_instruction: str,
        file_path: str,
        file_content: str,
        surrounding_code: str,
        element_context: Dict[str, Any],
        line: int,
    ) -> Dict[str, Any]:
        """
        生成代码变更

        Args:
            user_instruction: 用户修改指令
            file_path: 文件路径
            file_content: 完整文件内容
            surrounding_code: 周围代码（用于定位）
            element_context: 元素上下文
            line: 行号

        Returns:
            Dict: 包含 files 和 summary 的结果
        """
        info("QuickCoder 开始生成代码", 
             file_path=file_path, 
             instruction=user_instruction[:50],
             file_content_length=len(file_content),
             surrounding_code_length=len(surrounding_code))

        try:
            # 构建初始状态
            initial_state = {
                "user_instruction": user_instruction,
                "file_path": file_path,
                "file_content": file_content,
                "surrounding_code": surrounding_code,
                "element_context": element_context,
                "line": line,
            }

            # 执行 Agent（使用 pipeline_id=0 表示轻量级修改）
            result = await self.execute(
                pipeline_id=0,
                stage_name="QUICK_MODIFY",
                initial_state=initial_state
            )

            if result["success"]:
                output = result["output"]
                files = output.get("files", []) if output else []
                info("QuickCoder 代码生成完成", 
                     files_count=len(files),
                     files=[f.get("file_path") for f in files],
                     output_keys=list(output.keys()) if output else [])
                return {
                    "success": True,
                    "output": output,
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "未知错误"),
                }

        except Exception as e:
            error("QuickCoder 代码生成失败", error=str(e), exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }


# 全局实例
quick_coder_agent = QuickCoderAgent()
