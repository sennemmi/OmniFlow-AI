"""
设计师 Agent
基于 LangGraph 状态机实现，继承 BaseAgent 统一调用逻辑

职责：
1. 分析 ArchitectAgent 的输出
2. 结合项目文件树（特别是 backend/app/api/ 风格）
3. 结合代码库上下文（语义检索 + 完整文件内容）
4. 输出详细的技术设计方案

使用 Instructor 强制执行结构化输出
"""

import json
import logging
import time
from typing import Dict, Optional, Any

import instructor
from instructor import Mode
import litellm

from app.agents.base import LangGraphAgent
from app.agents.schemas import DesignerOutput
from app.agents.designer_prompts import SYSTEM_PROMPT
from app.agents.schemas import DesignerOutputV2
from app.core.config import settings

logger = logging.getLogger(__name__)


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
        return SYSTEM_PROMPT
    
    def build_user_prompt(self, state: Dict[str, Any]) -> str:
        """
        构建用户 Prompt

        Args:
            state: 包含 architect_output, related_code_context, full_files_context 的状态
        """
        architect_output = state.get("architect_output", {})
        related_code_context = state.get("related_code_context")
        full_files_context = state.get("full_files_context")

        architect_str = json.dumps(architect_output, indent=2, ensure_ascii=False)

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
            # 【改进2】生成现有函数复用表，强制对齐
            reuse_table = self._build_reuse_table(full_files_context)
            if reuse_table:
                code_context_section += f"""
{reuse_table}

"""
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
        related_code_context: Optional[str] = None,
        full_files_context: Optional[Dict[str, str]] = None,
        pipeline_id: int = 0,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        使用 Instructor 强制执行的结构化设计

        特点：
        1. 使用 Instructor 在 API 层强制约束输出格式为 DesignerOutputV2
        2. contract_alignment 成为必填字段，在 API 层就验证
        3. 无需手动解析 JSON，直接返回校验后的 Pydantic 对象
        4. 生成后自动验证验收标准对齐

        Args:
            architect_output: ArchitectAgent 的输出内容（必须包含 acceptance_criteria）
            related_code_context: 语义检索结果（代码片段）
            full_files_context: 完整文件内容映射
            pipeline_id: Pipeline ID
            max_retries: Instructor 最大重试次数

        Returns:
            Dict: 包含设计结果或错误信息
        """
        from app.core.sse_log_buffer import push_log
        
        # 记录开始时间
        start_time = time.perf_counter()
        
        await push_log(pipeline_id, "info", "结构化设计师 Agent 开始工作（Instructor 模式）...", stage="DESIGN")
        
        # ========== 1. 前置静态检查 ==========
        acceptance_criteria = architect_output.get("acceptance_criteria", [])
        if not acceptance_criteria:
            error_msg = "Missing acceptance_criteria in architect_output，无法执行契约对齐设计"
            logger.error(f"[DesignerAgent] {error_msg}")
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": None
            }
        
        logger.info(f"[DesignerAgent] 验收标准数量: {len(acceptance_criteria)}")
        await push_log(pipeline_id, "info", f"检测到 {len(acceptance_criteria)} 条验收标准，开始结构化设计...", stage="DESIGN")
        
        # ========== 2. 准备 Prompt ==========
        initial_state = {
            "architect_output": architect_output,
            "related_code_context": related_code_context,
            "full_files_context": full_files_context
        }
        user_prompt = self.build_user_prompt(initial_state)
        
        # 在 Prompt 中注入验收标准数量提醒
        user_prompt += f"""

【重要提醒】
本次设计必须包含 {len(acceptance_criteria)} 条验收标准的映射（contract_alignment 列表长度必须等于 {len(acceptance_criteria)}）。
"""
        
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # ========== 3. 创建 Instructor 客户端（使用 TOOLS 模式兼容 MiniMax） ==========
        client = instructor.from_litellm(
            litellm.acompletion,
            mode=Mode.TOOLS  # 使用工具调用模式，兼容不支持 response_format 的模型
        )
        
        # ========== 4. 调用 LLM，强制输出 DesignerOutputV2 ==========
        try:
            logger.info(f"[DesignerAgent] 调用 Instructor 生成结构化输出...")
            await push_log(pipeline_id, "info", "调用 LLM 生成结构化设计方案...", stage="DESIGN")
            
            designer_output = await client.chat.completions.create(
                model=f"openai/{settings.llm_model}",
                messages=messages,
                response_model=DesignerOutputV2,
                temperature=0.0,
                max_retries=max_retries,
                max_tokens=8192,
                api_key=settings.llm_api_key,
                api_base=settings.llm_api_base
            )
            
            logger.info(f"[DesignerAgent] Instructor 输出成功，接口数量: {len(designer_output.interface_specs)}")
            await push_log(
                pipeline_id, 
                "info", 
                f"LLM 输出完成（{len(designer_output.interface_specs)} 个接口，{len(designer_output.contract_alignment)} 个映射）", 
                stage="DESIGN"
            )
            
        except Exception as e:
            error_msg = f"Instructor 结构化输出失败: {str(e)}"
            logger.error(f"[DesignerAgent] {error_msg}", exc_info=True)
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": None
            }
        
        # ========== 5. 生成后对齐校验 ==========
        is_aligned, missing_criteria = self._validate_contract_alignment(
            designer_output, acceptance_criteria
        )
        
        if not is_aligned:
            error_msg = f"契约对齐校验失败，缺失 {len(missing_criteria)} 条验收标准映射: {missing_criteria}"
            logger.error(f"[DesignerAgent] {error_msg}")
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": designer_output.model_dump()
            }
        
        logger.info(f"[DesignerAgent] 契约对齐校验通过，所有 {len(acceptance_criteria)} 条验收标准已映射")
        await push_log(pipeline_id, "info", "✅ 契约对齐校验通过，所有验收标准已映射到接口契约", stage="DESIGN")

        # ========== 6. 【关键修复】验证并自动修正 interface_specs 符号 ==========
        # 确保所有 symbol_name 都是模块级可导入的（类或模块级函数），而不是类方法
        # 如果发现类方法被错误地作为独立符号，自动将其转换为类名
        corrected_specs, correction_log = self._auto_correct_interface_specs(
            designer_output.interface_specs, full_files_context
        )
        if correction_log:
            logger.warning(f"[DesignerAgent] 自动修正契约符号: {correction_log}")
            await push_log(pipeline_id, "warning", f"自动修正契约符号: {correction_log}", stage="DESIGN")
            # 更新 interface_specs 为修正后的版本
            designer_output.interface_specs = corrected_specs

        # 再次验证，确保修正后没有错误
        import_errors = self._validate_interface_specs_importable(
            designer_output.interface_specs, full_files_context
        )
        if import_errors:
            error_msg = f"契约符号不可直接导入（必须是模块级函数或类，不能是类方法）: {import_errors}"
            logger.error(f"[DesignerAgent] {error_msg}")
            await push_log(pipeline_id, "error", error_msg, stage="DESIGN")
            return {
                "success": False,
                "error": error_msg,
                "output": designer_output.model_dump()
            }

        # ========== 7. 【新增】契约-现有代码对齐检查（仅警告，不阻断）==========
        if full_files_context:
            alignment_errors = self._validate_interface_specs_alignment(
                designer_output.interface_specs, full_files_context
            )
            if alignment_errors:
                # 【修改】将错误降级为警告，不阻断流程
                # 因为现有代码可能需要演进，新设计可能与旧实现不同
                warning_msg = f"契约与现有代码存在差异（将作为架构演进处理）: {len(alignment_errors)} 处"
                logger.warning(f"[DesignerAgent] {warning_msg}")
                for err in alignment_errors:
                    logger.warning(f"  - {err['symbol']}: {err['error']}")
                    logger.warning(f"    现有: {err.get('existing_keys', [])}")
                    logger.warning(f"    契约: {err.get('required_keys', [])}")
                await push_log(pipeline_id, "warning", warning_msg, stage="DESIGN")
                # 【重要】将差异信息附加到输出中，供 CoderAgent 参考
                designer_output._alignment_warnings = alignment_errors
            else:
                logger.info("[DesignerAgent] 契约-现有代码对齐检查通过")
                await push_log(pipeline_id, "info", "✅ 契约-现有代码对齐检查通过", stage="DESIGN")
        
        # ========== 7. 返回与原有接口兼容的结果 ==========
        # 计算耗时
        end_time = time.perf_counter()
        duration_ms = int((end_time - start_time) * 1000)
        
        return {
            "success": True,
            "output": designer_output.model_dump(),
            "error": None,
            "input_tokens": 0,  # Instructor 暂不直接返回 usage，可从 litellm 全局统计获取
            "output_tokens": 0,
            "duration_ms": duration_ms,
            "total_tokens": 0,
            "interface_specs_count": len(designer_output.interface_specs),
            "contract_alignment_count": len(designer_output.contract_alignment)
        }
    
    def _validate_contract_alignment(
        self,
        output: DesignerOutputV2,
        acceptance_criteria: list
    ) -> tuple[bool, list]:
        """
        检查每条验收标准是否都有对应的接口契约
        
        Args:
            output: DesignerOutputV2 输出
            acceptance_criteria: 验收标准列表
            
        Returns:
            tuple[是否对齐, 缺失的标准列表]
        """
        # 提取已映射的验收标准
        covered = set()
        for item in output.contract_alignment:
            if item.acceptance_criteria:
                covered.add(item.acceptance_criteria.strip())
        
        # 找出未映射的标准
        missing = [c for c in acceptance_criteria if c.strip() not in covered]
        
        if missing:
            logger.warning(f"[DesignerAgent] Missing alignment for criteria: {missing}")
            return False, missing
        
        return True, []
    
    def _build_reuse_table(self, full_files_context: Dict[str, str]) -> str:
        """
        【改进2】从 full_files_context 构建现有函数复用表
        """
        import re
        
        if not full_files_context:
            return ""
        
        lines = ["【现有函数复用表 - 设计时必须参考，优先复用而非创建新函数】\n"]
        
        for file_path, content in full_files_context.items():
            lines.append(f"\n### {file_path}")
            func_pattern = r"(?P<async>async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)(?:\s*->\s*(?P<ret>[^:]+))?:\s*"
            for m in re.finditer(func_pattern, content):
                func_name = m.group("name")
                is_async = "async " if m.group("async") else ""
                params = m.group("params").strip()
                ret_type = m.group("ret").strip() if m.group("ret") else "Any"
                
                # 提取函数返回字典的键名
                return_keys = []
                func_body = content[m.end():]
                brace_match = re.search(r'return\s+\{([^}]*(?:\{[^}]*\}[^}]*)*)\}', func_body, re.DOTALL)
                if brace_match:
                    keys = re.findall(r"['\"](\w+)['\"]\s*:", brace_match.group(1))
                    return_keys = list(dict.fromkeys(keys))[:8]
                
                args_str = params[:80] + ("..." if len(params) > 80 else "")
                lines.append(f"  - {is_async}def {func_name}({args_str}) -> {ret_type}")
                if return_keys:
                    lines.append(f"    return_keys: [{', '.join(return_keys)}]")
        
        return "\n".join(lines)

    def _classify_interface_symbol(
        self,
        symbol_name: str,
        module: str,
        full_files_context: Dict[str, str]
    ) -> tuple[bool, bool, str | None, str | None]:
        """
        【抽取】对 interface_spec 符号进行 AST 分类

        返回:
            (is_module_level, is_class_method, parent_class, file_content)
            - is_module_level: 是否是模块级可导入符号（函数/类）
            - is_class_method: 是否是类方法
            - parent_class: 如果是类方法，返回类名
            - file_content: 文件内容（用于上层复用）
        """
        import ast

        if not symbol_name or not module:
            return False, False, None, None

        # 标准化模块路径
        clean_module = module.replace("backend/", "").replace("backend\\", "").lstrip("/")
        if not clean_module.endswith(".py"):
            clean_module += ".py"

        # 查找对应的文件内容
        file_content = None
        for path, content in full_files_context.items():
            path_clean = path.replace("backend/", "").replace("backend\\", "").lstrip("/")
            if path_clean == clean_module or path_clean == clean_module.replace(".py", ""):
                file_content = content
                break

        if not file_content:
            return False, False, None, None

        try:
            tree = ast.parse(file_content)
        except SyntaxError:
            return False, False, None, file_content

        is_module_level = False
        is_class_method = False
        parent_class = None

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
                is_module_level = True
                break
            elif isinstance(node, ast.ClassDef) and node.name == symbol_name:
                is_module_level = True
                break

        if not is_module_level:
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == symbol_name:
                            is_class_method = True
                            parent_class = node.name
                            break
                    if is_class_method:
                        break

        return is_module_level, is_class_method, parent_class, file_content

    def _auto_correct_interface_specs(
        self,
        interface_specs: list,
        full_files_context: Dict[str, str]
    ) -> tuple[list, list]:
        """
        【自动修正】将类方法符号自动转换为类名符号
        """
        import copy

        corrected_specs = copy.deepcopy(interface_specs)
        correction_log = []

        for spec in corrected_specs:
            is_object = hasattr(spec, 'symbol_name')
            symbol_name = spec.symbol_name if is_object else spec.get("symbol_name", "")
            module = spec.module if is_object else spec.get("module", "")

            is_module_level, is_class_method, parent_class, _ = self._classify_interface_symbol(
                symbol_name, module, full_files_context
            )

            if is_class_method and parent_class:
                old_symbol = symbol_name
                new_symbol = parent_class

                if is_object:
                    spec.symbol_name = new_symbol
                    old_behavior = spec.expected_behavior or ""
                    spec.expected_behavior = f"使用类 {parent_class} 的 {old_symbol} 方法。{old_behavior}"
                    spec.signature = f"class {parent_class}:"
                else:
                    spec["symbol_name"] = new_symbol
                    old_behavior = spec.get("expected_behavior", "")
                    spec["expected_behavior"] = f"使用类 {parent_class} 的 {old_symbol} 方法。{old_behavior}"
                    spec["signature"] = f"class {parent_class}:"

                correction_log.append(
                    f"'{old_symbol}' -> '{new_symbol}' (类方法转为类名)"
                )

        return corrected_specs, correction_log

    def _validate_interface_specs_importable(
        self,
        interface_specs: list,
        full_files_context: Dict[str, str]
    ) -> list:
        """
        【关键修复】验证 interface_specs 中的符号是否都是模块级可导入的
        """
        errors = []

        for spec in interface_specs:
            symbol_name = spec.symbol_name if hasattr(spec, 'symbol_name') else spec.get("symbol_name", "")
            module = spec.module if hasattr(spec, 'symbol_name') else spec.get("module", "")

            is_module_level, is_class_method, parent_class, _ = self._classify_interface_symbol(
                symbol_name, module, full_files_context
            )

            if is_class_method:
                errors.append({
                    "symbol": symbol_name,
                    "module": module,
                    "error": f"'{symbol_name}' 是类 '{parent_class}' 的方法，不是模块级符号",
                    "suggestion": f"应该改为导出类 '{parent_class}'，或者将 '{symbol_name}' 改为模块级函数"
                })

        return errors

    def _validate_interface_specs_alignment(
        self,
        interface_specs: list,
        full_files_context: Dict[str, str]
    ) -> list:
        """
        【契约-现有代码对齐检查器】
        检查 interface_specs 是否与现有代码一致
        
        检查项：
        1. 函数名是否已存在但签名不同
        2. 返回字段的键名是否与现有代码一致
        
        Args:
            interface_specs: 接口契约列表
            full_files_context: 完整文件内容映射
            
        Returns:
            list: 对齐错误列表，空列表表示无错误
        """
        import re
        errors = []
        
        for spec in interface_specs:
            # 处理 InterfaceSpec 对象或字典
            if hasattr(spec, 'symbol_name'):
                symbol_name = spec.symbol_name
                module = spec.module
                return_fields = spec.return_fields if spec.return_fields else []
            else:
                symbol_name = spec.get("symbol_name", "")
                module = spec.get("module", "")
                return_fields = spec.get("return_fields", [])
            
            if not symbol_name or not module:
                continue
            
            # 标准化模块路径
            clean_module = module.replace("backend/", "").replace("backend\\", "").lstrip("/")
            if not clean_module.endswith(".py"):
                clean_module += ".py"
            
            # 查找对应的文件内容
            file_content = None
            for path, content in full_files_context.items():
                path_clean = path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                if path_clean == clean_module or path_clean == clean_module.replace(".py", ""):
                    file_content = content
                    break
            
            if not file_content:
                continue
            
            # 检查函数是否已存在
            # 匹配函数定义：async def symbol_name( 或 def symbol_name(
            func_pattern = rf"(?:async\s+)?def\s+{re.escape(symbol_name)}\s*\("
            if re.search(func_pattern, file_content):
                # 函数已存在，检查返回字段是否一致
                if return_fields:
                    # 提取现有函数返回的字典键名
                    # 匹配 return { ... } 语句
                    return_pattern = rf"(?:async\s+)?def\s+{re.escape(symbol_name)}\s*\([^)]*\)(?:\s*->\s*[^:]+)?:\s*(?:[^#]*#.*\n|[^\n]*\n)+?(?:\s*return\s+\{{([^}}]+)\}})"
                    match = re.search(return_pattern, file_content, re.MULTILINE | re.DOTALL)
                    
                    if match:
                        # 提取现有返回字典中的键名
                        return_dict_content = match.group(1)
                        existing_keys = set(re.findall(r"['\"](\w+)['\"]\s*:", return_dict_content))
                        
                        # 提取契约要求的键名（处理 ReturnFieldSpec 对象或字典）
                        def get_field_name(f):
                            return f.name if hasattr(f, 'name') else f.get("name", "")
                        def get_field_required(f):
                            return f.required if hasattr(f, 'required') else f.get("required", True)
                        required_keys = set(get_field_name(f) for f in return_fields if get_field_required(f))
                        
                        # 检查是否有冲突
                        if existing_keys and required_keys:
                            # 如果有共同键名但可能值不同，记录警告
                            common_keys = existing_keys & required_keys
                            if common_keys:
                                logger.info(f"[DesignerAgent] 函数 {symbol_name} 已存在，键名一致: {common_keys}")
                            else:
                                # 键名完全不匹配，可能是不同的返回结构
                                logger.warning(
                                    f"[DesignerAgent] 函数 {symbol_name} 已存在但返回键名不匹配: "
                                    f"现有 {existing_keys} vs 契约要求 {required_keys}"
                                )
                                errors.append({
                                    "symbol": symbol_name,
                                    "module": module,
                                    "error": f"函数已存在但返回键名不匹配",
                                    "existing_keys": list(existing_keys),
                                    "required_keys": list(required_keys),
                                    "suggestion": f"请检查现有代码，复用已有的键名 {list(existing_keys)} 或扩展现有函数"
                                })
        
        return errors


# 单例实例
designer_agent = DesignerAgent()
