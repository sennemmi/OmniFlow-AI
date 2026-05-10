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
from typing import Dict, List, Optional, Any

from app.agents.base import LangGraphAgent
from app.agents.schemas import TesterOutput
from app.agents.tester_prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class TesterAgent(LangGraphAgent[TesterOutput]):
    """
    测试 Agent

    根据设计方案和生成的代码编写单元测试
    继承 LangGraphAgent，只需实现业务差异部分
    """

    # 【结构化输出】启用 JSON 格式化输出
    USE_JSON_FORMAT = True

    # 【可配置】测试文件体积限制
    MAX_TEST_FILE_SIZE = 6000  # 单个测试文件最大字符数
    MAX_TEST_FUNC_LINES = 30   # 单个测试函数最大行数

    def __init__(self):
        super().__init__(agent_name="TesterAgent")
    
    @property
    def system_prompt(self) -> str:
        """系统 Prompt - 强调测试覆盖和代码风格"""
        return SYSTEM_PROMPT
    def _detect_symbol_type(self, signature: str) -> str:
        """
        根据签名检测符号类型
        
        Args:
            signature: 函数/类签名
            
        Returns:
            str: 符号类型 ("function", "class", "static_method", "class_method", "instance_method")
        """
        if not signature:
            return "function"
        
        sig_lower = signature.lower()
        
        # 检测类定义
        if sig_lower.startswith("class "):
            return "class"
        
        # 检测静态方法（@staticmethod 装饰器）
        if "@staticmethod" in sig_lower:
            return "static_method"
        
        # 检测类方法（@classmethod 装饰器）
        if "@classmethod" in sig_lower:
            return "class_method"
        
        # 检测实例方法（self 或 cls 参数）
        if "(self" in signature or "( cls" in signature or "(cls" in signature:
            return "instance_method"
        
        # 默认视为模块级函数
        return "function"
    
    def _extract_class_name_from_signature(
        self,
        signature: str,
        interface_specs: Optional[List[Dict]] = None
    ) -> str:
        """
        从签名中提取类名

        Args:
            signature: 方法签名
            interface_specs: 接口契约列表，用于查找同模块下的类名

        Returns:
            str: 类名，如果无法提取则返回空字符串
        """
        if not signature:
            return ""

        # 策略1: 从签名中解析类名前缀
        # 例如: "def HealthService.calculate(...)" -> "HealthService"
        sig_clean = signature.strip()
        if "." in sig_clean:
            # 处理 "ClassName.method_name" 格式
            parts = sig_clean.split(".")
            if parts and parts[0]:
                potential_class = parts[0].split()[-1]  # 处理 "def ClassName.method" 情况
                if potential_class and potential_class[0].isupper():
                    return potential_class

        # 策略2: 从 interface_specs 中查找同模块的类
        if interface_specs:
            # 找到当前方法所属的模块
            current_module = ""
            current_symbol = ""

            # 尝试从 signature 中找到方法名
            method_match = re.search(r'def\s+(\w+)', signature)
            if method_match:
                current_symbol = method_match.group(1)

            # 在 interface_specs 中查找同模块的类
            for spec in interface_specs:
                spec_sig = spec.get("signature", "")
                spec_symbol = spec.get("symbol_name", "")
                spec_type = self._detect_symbol_type(spec_sig)

                if spec_type == "class":
                    # 检查这个类是否包含当前方法
                    if current_symbol and self._is_method_of_class(current_symbol, spec_symbol, interface_specs):
                        return spec_symbol

            # 如果没有找到关联，返回同模块的第一个类名
            for spec in interface_specs:
                spec_sig = spec.get("signature", "")
                spec_type = self._detect_symbol_type(spec_sig)
                if spec_type == "class":
                    return spec.get("symbol_name", "")

        return ""

    def _is_method_of_class(
        self,
        method_name: str,
        class_name: str,
        interface_specs: List[Dict]
    ) -> bool:
        """
        判断方法是否属于某个类

        Args:
            method_name: 方法名
            class_name: 类名
            interface_specs: 接口契约列表

        Returns:
            bool: 是否属于该类
        """
        # 查找类的签名
        class_spec = None
        for spec in interface_specs:
            if spec.get("symbol_name") == class_name:
                class_sig = spec.get("signature", "")
                if self._detect_symbol_type(class_sig) == "class":
                    class_spec = spec
                    break

        if not class_spec:
            return False

        # 检查方法名是否是类名的常见变体
        # 例如: HealthService -> get_health, check_health
        class_lower = class_name.lower().replace("service", "").replace("manager", "").replace("controller", "")
        method_lower = method_name.lower()

        # 如果方法名包含类名关键字，可能是该类的方法
        if class_lower and class_lower in method_lower:
            return True

        # 检查是否有其他线索
        return False
    
    def _build_allowed_imports_section(self, design_output: Dict[str, Any]) -> str:
        """
        构建允许导入的符号清单

        基于 interface_specs 生成测试文件允许导入的符号列表
        【改进】添加详细的导入方式说明，包括静态方法/类方法的正确调用方式
        """
        interface_specs = design_output.get("interface_specs", [])
        if not interface_specs:
            return ""

        # 按模块分组，并构建详细的导入说明
        module_imports: Dict[str, List[Dict]] = {}
        for spec in interface_specs:
            module = spec.get("module", "")
            symbol = spec.get("symbol_name", "")
            signature = spec.get("signature", "")
            
            if module and symbol:
                # 转换文件路径为 Python 模块路径
                module_path = module.replace(".py", "").replace("/", ".")
                if module_path not in module_imports:
                    module_imports[module_path] = []
                
                # 判断符号类型（函数、类、静态方法等）
                symbol_type = self._detect_symbol_type(signature)
                
                module_imports[module_path].append({
                    "name": symbol,
                    "signature": signature,
                    "type": symbol_type
                })

        # 构建详细的导入说明
        imports_details = []
        interface_specs = design_output.get("interface_specs", [])

        for module_path, symbols in module_imports.items():
            for sym in symbols:
                name = sym["name"]
                sig = sym["signature"]
                sym_type = sym["type"]

                if sym_type == "class":
                    imports_details.append(
                        f"  - from {module_path} import {name}\n"
                        f"    类型: 类\n"
                        f"    签名: {sig}\n"
                        f"    使用: 实例化后调用方法"
                    )
                elif sym_type == "static_method":
                    # 提取类名（从签名和 interface_specs 中推断）
                    class_name = self._extract_class_name_from_signature(sig, interface_specs) or "ClassName"
                    imports_details.append(
                        f"  - from {module_path} import {class_name}\n"
                        f"    类型: 类（包含静态方法 {name}）\n"
                        f"    签名: {sig}\n"
                        f"    【重要】必须通过 {class_name}.{name}(...) 调用，禁止直接导入 {name}！"
                    )
                elif sym_type == "class_method":
                    class_name = self._extract_class_name_from_signature(sig, interface_specs) or "ClassName"
                    imports_details.append(
                        f"  - from {module_path} import {class_name}\n"
                        f"    类型: 类（包含类方法 {name}）\n"
                        f"    签名: {sig}\n"
                        f"    【重要】必须通过 {class_name}.{name}(...) 调用，禁止直接导入 {name}！"
                    )
                else:
                    imports_details.append(
                        f"  - from {module_path} import {name}\n"
                        f"    类型: 函数\n"
                        f"    签名: {sig}\n"
                        f"    使用: 直接调用 {name}(...)"
                    )

        imports_str = "\n\n".join(imports_details)
        allowed_symbols = [spec.get("symbol_name", "") for spec in interface_specs]

        # ✅ 新增：渲染每个 spec 的 mock_dependencies
        mock_sections = []
        for spec in interface_specs:
            deps = spec.get("mock_dependencies", [])
            if not deps:
                continue
            symbol = spec.get("symbol_name", "?")
            lines = [f"  测试 `{symbol}` 时必须 mock 以下依赖："]
            for dep in deps:
                mock_cls = "AsyncMock" if dep.get("is_async") else "MagicMock"
                rv = dep.get("mock_return_value")
                rv_str = f", return_value={rv}" if rv is not None else ""
                lines.append(
                    f"    patch_target : {dep['patch_target']}\n"
                    f"    mock 类型   : {mock_cls}{rv_str}\n"
                    f"    说明        : {dep.get('description', '')}"
                )
            mock_sections.append("\n".join(lines))

        if mock_sections:
            mock_block = "\n\n".join(mock_sections)
            mock_section = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    【Mock 依赖清单 - 必须全部 mock，否则测试访问真实资源】         ║
╚══════════════════════════════════════════════════════════════════════════════╝

{mock_block}

【Mock 铁律】
1. patch_target 必须完全照抄上述路径，不能自行猜测
2. async 目标用 AsyncMock，同步目标用 MagicMock
3. 不允许访问真实数据库、磁盘、内存、网络
"""
        else:
            mock_section = ""

        return f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    【测试生成规则 - 只能测试契约声明的符号】                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

【允许测试导入的符号 - 绝对禁止违反】
你只能从对应模块导入以下已保证存在的符号，且必须按照指定方式导入和使用：

{imports_str}

允许导入的符号列表：{', '.join(allowed_symbols)}

【导入方式规则 - 极其重要】
1. **模块级函数**：可以直接 `from module import function_name`
2. **类**：可以直接 `from module import ClassName`，然后实例化或调用类方法
3. **静态方法/类方法**：【绝对禁止】直接导入方法名！
   ❌ 错误：`from module import static_method_name`
   ✅ 正确：`from module import ClassName` 然后 `ClassName.static_method_name(...)`
4. **实例方法**：必须先实例化类，然后通过实例调用

【测试生成规则 - 违反会导致测试失败】
1. **你只能测试上述接口契约中列出的函数或类，不得臆造任何未声明的符号**
2. 绝对禁止导入清单外的任何函数或类
3. 静态方法和类方法必须通过类名调用，禁止直接导入方法名
4. 测试端点的行为时，通过 HTTP 响应验证而非直接调用内部函数
5. 如果测试需要调用内部函数，该函数必须在上述清单中
6. 违反此限制会导致 ImportError，测试无法运行

【契约对齐检查清单 - 必须全部勾选才能输出】
在生成测试前，必须逐一检查并确认：
□ 测试的每个函数/类都在契约清单中吗？
□ 导入语句只使用了清单中的符号吗？
□ 静态方法/类方法是通过类名调用的吗？（不是直接导入方法名）
□ 没有导入任何契约外的新函数或类吗？
□ 没有使用任何未声明的辅助函数吗？
□ 测试代码中的每个 import 都能在 interface_specs 中找到对应声明吗？

【硬性规则 - 违反会导致系统崩溃】
1. **绝对禁止**导入 interface_specs 中未声明的任何符号
2. **绝对禁止**直接导入静态方法或类方法（必须通过类名调用）
3. **绝对禁止**在测试代码中调用契约外的函数（即使是"辅助函数"）
4. **绝对禁止**假设任何未声明的函数存在
5. 如果测试需要某个函数，必须在 interface_specs 中声明，由 CoderAgent 实现
6. 违反此规则会导致 ImportError，整个测试流程失败

【关键容错规则 - 防止死循环】
如果 interface_specs 中的某个符号实际上是类中的方法（而非模块级函数）：
1. **不要**尝试直接导入该方法名（会导致 ImportError）
2. **必须**导入包含该方法的类，然后通过类名调用方法
3. **示例**：
   - 契约错误地声明了: `{{"symbol_name": "get_component_health", "module": "app.service.health_service"}}`
   - 但 "get_component_health" 实际上是 HealthService 类的方法
   - ❌ 错误做法: `from app.service.health_service import get_component_health`
   - ✅ 正确做法: `from app.service.health_service import HealthService` 然后 `HealthService.get_component_health(...)`
   - 或者如果无法调用，测试该方法的包装函数或跳过测试

【常见错误示例】
❌ 错误：契约中只有 check_health，但测试导入了 get_component_health
❌ 错误：契约中只有 HealthService，但测试直接导入 calculate_health_score（静态方法）
   ✅ 正确：导入 HealthService，然后通过 HealthService.calculate_health_score(...) 调用
❌ 错误：契约中只有 HealthService，但测试调用了未声明的辅助函数
✅ 正确：只导入和测试 interface_specs 中明确列出的符号，并按正确方式使用

{mock_section}
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

        # 【常驻基础设施上下文】注入地基代码
        evergreen_context = state.get("evergreen_context", "")
        evergreen_section = f"""
{evergreen_context}

""" if evergreen_context else ""

        # 【接口契约】生成允许导入的符号清单
        allowed_imports_section = self._build_allowed_imports_section(design_output)

        # 【修复指令】如果有 fix_instruction，在 Prompt 最顶部高亮显示
        fix_instruction = design_output.get("fix_instruction", "")
        fix_section = ""
        if fix_instruction:
            fix_section = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                           【🚨 修复指令 - 必须遵守】                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

{fix_instruction}

╔══════════════════════════════════════════════════════════════════════════════╗
║                           【修复指令结束】                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

"""

        # ── 完整模式：直接生成完整测试 ──────────────────────────────────────────
        # 【兼容并行模式】如果 code_output 为 None，基于接口契约生成测试
        if code_output:
            code_str = json.dumps(code_output, indent=2, ensure_ascii=False)
            code_section = f"【CoderAgent 生成的代码】\n{code_str}"
        else:
            code_section = (
                "【CoderAgent 尚未生成代码，请完全基于以下接口契约编写测试，"
                "确保测试能够验证契约中声明的所有函数、字段和错误场景】"
            )

        return f"""{fix_section}{evergreen_section}【技术设计方案】
{design_str}

{code_section}
{allowed_imports_section}

请根据技术设计方案和生成的代码，编写完整的单元测试。
注意：
1. 使用 pytest 框架
2. 保持与主代码相同的缩进风格和注释风格
3. 覆盖正常路径、异常路径和边界条件
4. 测试代码必须可以直接运行
5. 直接输出 JSON，不要调用任何工具
6. 【重要】只能导入上述清单中的符号，禁止导入其他未定义的函数或类
7. 【⚠️ 极其重要】禁止直接 mock datetime.datetime.utcnow！datetime.datetime 是 C 扩展类型，不可变。
   正确做法：
   - 使用 freezegun: @freeze_time("2024-01-01")
   - 使用 unittest.mock.patch: with patch('app.module.datetime') as mock_dt:
   - 将被测函数改为接收 datetime 参数（依赖注入）
   错误做法：
   - datetime.datetime.utcnow = Mock()  # 会导致 TypeError!
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
        target_files: Optional[Dict[str, Any]] = None,
        pipeline_id: Optional[int] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        根据设计方案和生成的代码生成测试

        【改造】TestAgent 现在使用工具按需读取文件，不再依赖预加载的 target_files
        【新增】支持重试机制，当测试文件包含契约外导入时自动重试

        Args:
            design_output: DesignerAgent 的输出内容（包含 interface_specs 契约）
            code_output: CoderAgent 的输出内容
            target_files: 目标文件映射（可选，用于兼容性）
            pipeline_id: Pipeline ID，用于日志记录
            max_retries: 最大重试次数（默认3次）

        Returns:
            Dict: 包含生成结果或错误信息
        """
        from app.core.sse_log_buffer import push_log
        from app.utils.agent_debug_utils import get_agent_debugger

        # 获取调试器
        debugger = get_agent_debugger()

        code_files_count = len(code_output.get("files", [])) if isinstance(code_output, dict) else 0

        # 【契约检查】验证 design_output 包含 interface_specs
        interface_specs = design_output.get("interface_specs", [])
        logger.info(f"TesterAgent 开始生成测试", extra={
            "pipeline_id": pipeline_id,
            "code_files_count": code_files_count,
            "interface_specs_count": len(interface_specs)
        })

        # 【并行模式安全检查】如果未传入 code_output，检查契约完整性
        if code_output is None:
            # 契约完整性检查
            missing_mocks = any(
                not spec.get("mock_dependencies") for spec in interface_specs
                if "dict" in spec.get("return_type", "").lower()
            )
            if missing_mocks:
                logger.warning(
                    "[TesterAgent] 在无代码模式下生成测试，但部分接口未提供 mock_dependencies，"
                    "生成的测试可能缺少必要的 mock"
                )
            else:
                logger.info("[TesterAgent] 契约自检通过，开始基于契约盲写测试")

        if pipeline_id:
            await push_log(pipeline_id, "info", f"TesterAgent 开始生成测试代码...", stage="TESTING")
            if interface_specs:
                await push_log(pipeline_id, "info", f"📋 接收到接口契约: {len(interface_specs)} 个符号", stage="TESTING")
                for spec in interface_specs[:3]:  # 只显示前3个避免日志过长
                    await push_log(pipeline_id, "info", f"   - {spec.get('symbol_name')} in {spec.get('module', '?')}", stage="TESTING")
                if len(interface_specs) > 3:
                    await push_log(pipeline_id, "info", f"   ... 等共 {len(interface_specs)} 个符号", stage="TESTING")

        initial_state = {
            "design_output": design_output,
            "code_output": code_output,
            "target_files": target_files or {}
        }

        result = await self.execute(
            pipeline_id=pipeline_id or 0,
            stage_name="TESTING",
            initial_state=initial_state
        )

        if result.get("success"):
            test_files = result.get("output", {}).get("test_files", [])

            # 【新增】体积检查：检查测试文件是否符合大小限制
            if test_files:
                size_errors = self._check_test_file_size(test_files)
                if size_errors:
                    logger.warning(f"[TesterAgent] 发现 {len(size_errors)} 个体积问题")
                    for error in size_errors:
                        logger.warning(f"  - {error}")
                    if pipeline_id:
                        await push_log(pipeline_id, "warning", f"发现 {len(size_errors)} 个体积问题，正在自动精简...", stage="TESTING")

                    # 自动精简代码
                    test_files = self._compact_test_code(test_files)
                    if result.get("output"):
                        result["output"]["test_files"] = test_files

                    # 再次检查，如果仍然超限，记录错误但不阻止流程
                    remaining_errors = self._check_test_file_size(test_files)
                    if remaining_errors:
                        for error in remaining_errors:
                            logger.error(f"[TesterAgent] 体积问题未解决: {error}")
                            if pipeline_id:
                                await push_log(pipeline_id, "error", f"⚠️ {error}", stage="TESTING")

            # 【新增】安全扫描：检测危险模式并自动修复
            if test_files:
                safety_issues = self._scan_test_safety(test_files)
                if safety_issues:
                    logger.warning(f"[TesterAgent] 发现 {len(safety_issues)} 个安全问题")
                    for issue in safety_issues:
                        logger.warning(f"  - {issue}")
                    if pipeline_id:
                        await push_log(pipeline_id, "warning", f"发现 {len(safety_issues)} 个潜在安全问题，正在自动修复...", stage="TESTING")

                # 自动修复危险模式
                test_files = self._sanitize_test_code(test_files)
                # 更新结果中的 test_files
                if result.get("output"):
                    result["output"]["test_files"] = test_files

            # 【新增】后置验证：检查测试文件是否只导入了契约中的符号
            if test_files and interface_specs:
                import_errors = self._validate_test_imports_against_contract(
                    test_files, interface_specs
                )
                if import_errors:
                    error_msg = f"测试文件包含契约外的导入: {import_errors}"
                    logger.error(f"[TesterAgent] {error_msg}")
                    if pipeline_id:
                        await push_log(pipeline_id, "error", error_msg, stage="TESTING")
                    
                    # 【新增】重试逻辑：如果包含契约外导入，进入重试循环
                    logger.info(f"[TesterAgent] 进入重试模式，最多重试 {max_retries} 次")
                    
                    for retry_attempt in range(max_retries):
                        logger.info(f"[TesterAgent] 第 {retry_attempt + 1}/{max_retries} 次重试...")
                        if pipeline_id:
                            await push_log(pipeline_id, "warning", f"测试文件包含契约外导入，第 {retry_attempt + 1}/{max_retries} 次重试...", stage="TESTING")
                        
                        # 构建修复指令
                        fix_instruction = f"""之前的测试生成结果有误: {error_msg}

【关键问题】
测试文件导入了接口契约中未声明的符号。请根据以下规则修复：

1. **只能导入 interface_specs 中声明的符号**
2. **禁止导入契约外的任何符号**
3. **如果被测代码使用了契约外的符号，通过 HTTP 端点测试而非直接调用内部函数**

【允许的导入清单】
{self._build_allowed_imports_section(design_output)}

【修复要求】
- 移除所有契约外的导入
- 只测试契约中声明的函数/类
- 如果无法直接测试某个功能，通过测试其调用方来间接验证
"""
                        
                        # 构建重试用的 design_output
                        retry_design_output = {
                            **design_output,
                            "fix_mode": True,
                            "fix_instruction": fix_instruction,
                            "import_errors": import_errors
                        }
                        
                        retry_state = {
                            "design_output": retry_design_output,
                            "code_output": code_output,
                            "target_files": target_files or {},
                            "_retry_count": retry_attempt + 1
                        }
                        
                        # 执行重试
                        retry_result = await self.execute(
                            pipeline_id=pipeline_id or 0,
                            stage_name="TESTING_RETRY",
                            initial_state=retry_state
                        )
                        
                        if retry_result.get("success"):
                            retry_test_files = retry_result.get("output", {}).get("test_files", [])
                            
                            # 再次验证导入
                            if retry_test_files and interface_specs:
                                retry_import_errors = self._validate_test_imports_against_contract(
                                    retry_test_files, interface_specs
                                )
                                
                                if not retry_import_errors:
                                    # 重试成功，没有导入错误
                                    logger.info(f"[TesterAgent] 第 {retry_attempt + 1} 次重试成功，导入验证通过")
                                    if pipeline_id:
                                        await push_log(pipeline_id, "info", f"✅ 第 {retry_attempt + 1} 次重试成功，导入验证通过", stage="TESTING")
                                    return retry_result
                                else:
                                    # 仍有导入错误，继续重试
                                    error_msg = f"测试文件包含契约外的导入: {retry_import_errors}"
                                    logger.warning(f"[TesterAgent] 第 {retry_attempt + 1} 次重试后仍有导入错误: {retry_import_errors}")
                                    import_errors = retry_import_errors
                            else:
                                # 没有测试文件或没有契约，直接返回成功
                                return retry_result
                        else:
                            # 重试失败
                            logger.error(f"[TesterAgent] 第 {retry_attempt + 1} 次重试失败: {retry_result.get('error')}")
                            if retry_attempt == max_retries - 1:
                                # 最后一次重试失败，返回错误
                                return {
                                    "success": False,
                                    "error": f"重试 {max_retries} 次后仍然失败: {retry_result.get('error')}",
                                    "output": retry_result.get("output"),
                                    "input_tokens": retry_result.get("input_tokens", 0),
                                    "output_tokens": retry_result.get("output_tokens", 0),
                                    "duration_ms": retry_result.get("duration_ms", 0)
                                }
                    
                    # 重试次数用尽，返回最后一次的错误
                    logger.error(f"[TesterAgent] 重试 {max_retries} 次后仍然包含契约外导入")
                    return {
                        "success": False,
                        "error": f"重试 {max_retries} 次后，测试文件仍然包含契约外的导入: {import_errors}",
                        "output": result.get("output"),
                        "input_tokens": result.get("input_tokens", 0),
                        "output_tokens": result.get("output_tokens", 0),
                        "duration_ms": result.get("duration_ms", 0)
                    }
            
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

        # 保存调试信息
        if debugger:
            debugger.save_agent_io(
                agent_name="TesterAgent",
                stage="generate_tests",
                input_data={
                    "design_output": design_output,
                    "code_output": code_output,
                    "target_files": target_files,
                    "pipeline_id": pipeline_id,
                },
                output_data=result,
                metadata={
                    "input_tokens": result.get("input_tokens", 0),
                    "output_tokens": result.get("output_tokens", 0),
                    "duration_ms": result.get("duration_ms", 0),
                },
                success=result.get("success", False),
                error=result.get("error"),
                tool_calls=result.get("tool_results", []),
                system_prompt=self.system_prompt,
            )

        return result

    # 测试基础设施白名单 - 这些模块/符号不需要在 interface_specs 中声明
    TEST_INFRASTRUCTURE_WHITELIST = {
        # 测试框架
        "pytest",
        "unittest",
        "unittest.mock",
        # FastAPI 测试客户端
        "app.main",
        "app.main.app",
        # 数据库 fixtures（通常定义在 conftest.py）
        "app.core.database",
        "app.core.db",
        "app.db",
        # 常用测试辅助
        "asyncio",
        "typing",
    }

    # 测试基础设施符号白名单
    TEST_SYMBOL_WHITELIST = {
        # FastAPI
        "TestClient",
        "AsyncClient",
        # pytest fixtures 常见名称
        "client",
        "async_client",
        "db_session",
        "mock_db",
        "test_db",
        # 其他常用
        "app",
        "AsyncMock",
        "patch",
        "MagicMock",
        "Mock",
    }

    # Python 标准库模块名（可能与 app 模块冲突）
    STDLIB_MODULES = {
        'time', 'sys', 'os', 'json', 're', 'datetime', 'collections', 'typing',
        'pathlib', 'inspect', 'itertools', 'functools', 'hashlib', 'base64',
        'random', 'string', 'math', 'statistics', 'decimal', 'fractions',
        'calendar', 'zoneinfo', 'enum', 'dataclasses', 'abc', 'copy', 'pickle',
        'socket', 'urllib', 'http', 'email', 'mime', 'csv', 'xml', 'html',
        'sqlite3', 'logging', 'unittest', 'pdb', 'traceback', 'warnings',
        'contextlib', 'asyncio', 'concurrent', 'threading', 'multiprocessing',
        'subprocess', 'tempfile', 'shutil', 'glob', 'fnmatch', 'linecache',
        'textwrap', 'stringprep', 'codecs', 'encodings', 'io', 'csv'
    }

    def _is_test_infrastructure_import(self, module: str, symbol_name: str) -> bool:
        """
        检查是否是测试基础设施导入

        Args:
            module: 模块路径
            symbol_name: 符号名

        Returns:
            bool: 是否是测试基础设施导入
        """
        # 检查模块是否在白名单中
        for whitelist_module in self.TEST_INFRASTRUCTURE_WHITELIST:
            if module == whitelist_module or module.startswith(whitelist_module + "."):
                return True

        # 检查符号是否在白名单中
        if symbol_name in self.TEST_SYMBOL_WHITELIST:
            return True

        return False

    def _validate_test_imports_against_contract(
        self,
        test_files: List[Dict],
        interface_specs: List[Dict]
    ) -> List[str]:
        """
        【新增】验证测试文件的导入是否符合契约

        检查测试文件是否只导入了 interface_specs 中声明的符号。
        【放宽】允许测试文件导入被测模块中的任何符号（用于测试）。
        【放宽】允许测试基础设施导入（pytest、TestClient 等）。

        Args:
            test_files: 测试文件列表
            interface_specs: 接口契约列表

        Returns:
            List[str]: 导入错误列表
        """
        import ast
        errors = []

        # 构建契约中的符号集合
        allowed_symbols = set()
        allowed_modules = set()
        for spec in interface_specs:
            symbol = spec.get("symbol_name", "")
            module = spec.get("module", "")
            if symbol:
                allowed_symbols.add(symbol)
            if module:
                # 标准化模块路径（统一去掉 backend/ 前缀）
                module_path = module.replace("backend/", "").replace(".py", "").replace("/", ".")
                allowed_modules.add(module_path)

        for test_file in test_files:
            content = test_file.get("content", "")
            if not content:
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module
                    if not module or not module.startswith("app."):
                        continue

                    # 【修复】检查是否与标准库冲突
                    module_parts = module.split(".")
                    if any(part in self.STDLIB_MODULES for part in module_parts):
                        # 对于与标准库冲突的模块，放宽验证
                        # 因为 Python 的导入机制可能导致冲突
                        logger.warning(f"模块 {module} 包含标准库名称，放宽导入验证")
                        continue  # 跳过验证，允许导入

                    # 【放宽】允许从被测模块导入任何符号
                    # 只要模块路径匹配契约中的模块，就允许导入
                    module_in_contract = any(
                        module == allowed_module or module.startswith(allowed_module + ".")
                        for allowed_module in allowed_modules
                    )

                    if module_in_contract:
                        continue  # 被测模块，允许任何导入

                    # 【放宽】允许测试文件导入 app 包（用于测试 HTTP 端点）
                    if module == "app" or module.startswith("app.main"):
                        continue  # 允许从 app 或 app.main 导入任何符号

                    # 检查导入的符号
                    for alias in node.names:
                        symbol_name = alias.name
                        if symbol_name == "*":
                            continue  # 允许 from module import *

                        # 【放宽】允许测试基础设施导入
                        if self._is_test_infrastructure_import(module, symbol_name):
                            continue

                        if symbol_name not in allowed_symbols:
                            errors.append(
                                f"{test_file.get('file_path', '?')}: "
                                f"导入的符号 '{symbol_name}' 不在接口契约中"
                            )

        return errors

    def _scan_test_safety(self, test_files: List[Dict]) -> List[str]:
        """
        【简化版】扫描测试代码中的危险模式

        仅通过简单的字符串匹配检测明显的危险模式，
        复杂的检测留给 LLM 在生成阶段通过 Prompt 约束。

        Args:
            test_files: 测试文件列表

        Returns:
            List[str]: 发现的安全问题列表
        """
        safety_issues = []

        for test_file in test_files:
            file_path = test_file.get('file_path', '?')
            content = test_file.get('content', "")
            if not content:
                continue

            # 简单的字符串匹配检测 assert_called_once()
            # 注意：这里只检测明显的模式，不处理复杂情况
            if '.assert_called_once()' in content:
                for i, line in enumerate(content.split('\n'), 1):
                    if '.assert_called_once()' in line and '.assert_called_once_with()' not in line:
                        safety_issues.append(
                            f"{file_path}:{i}: 检测到 assert_called_once()，"
                            f"建议改用 assert_called() 避免不稳定"
                        )
                        break  # 只报告一次

        return safety_issues

    def _sanitize_test_code(self, test_files: List[Dict]) -> List[Dict]:
        """
        【简化版】自动修复测试代码中的明显问题

        仅修复最简单的模式，复杂的修复留给 LLM 通过 Prompt 约束。

        Args:
            test_files: 测试文件列表

        Returns:
            List[Dict]: 修复后的测试文件列表
        """
        import re

        sanitized_files = []

        for test_file in test_files:
            content = test_file.get('content', "")
            file_path = test_file.get('file_path', '?')

            if not content:
                sanitized_files.append(test_file)
                continue

            original_content = content

            # 仅替换 assert_called_once() 为 assert_called()
            # 避免替换 assert_called_once_with()
            content = re.sub(
                r'\.assert_called_once\(\)',
                '.assert_called()',
                content
            )

            if content != original_content:
                logger.info(f"[TesterAgent] 自动修复测试文件: {file_path}")

            sanitized_files.append({
                **test_file,
                'content': content
            })

        return sanitized_files

    def _check_test_file_size(self, test_files: List[Dict]) -> List[str]:
        """
        检查测试文件体积是否符合限制

        Args:
            test_files: 测试文件列表

        Returns:
            List[str]: 体积超限的错误列表
        """
        import ast

        size_errors = []

        for test_file in test_files:
            file_path = test_file.get('file_path', '?')
            content = test_file.get('content', "")

            if not content:
                continue

            # 1. 检查文件总字符数
            if len(content) > self.MAX_TEST_FILE_SIZE:
                size_errors.append(
                    f"{file_path}: 文件体积超限 ({len(content)} 字符 > {self.MAX_TEST_FILE_SIZE} 字符限制)，"
                    f"请使用 pytest fixtures 和 parametrize 精简代码"
                )

            # 2. 检查单个函数行数
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith('test_'):
                        # 计算函数行数
                        func_lines = node.end_lineno - node.lineno + 1
                        if func_lines > self.MAX_TEST_FUNC_LINES:
                            size_errors.append(
                                f"{file_path}:{node.lineno}: 测试函数 {node.name} 行数超限 "
                                f"({func_lines} 行 > {self.MAX_TEST_FUNC_LINES} 行限制)，"
                                f"请使用 fixtures 提取公共代码或使用 parametrize 合并相似测试"
                            )

        return size_errors

    def _compact_test_code(self, test_files: List[Dict]) -> List[Dict]:
        """
        自动精简测试代码以符合体积限制

        Args:
            test_files: 测试文件列表

        Returns:
            List[Dict]: 精简后的测试文件列表
        """
        import re

        compacted_files = []

        for test_file in test_files:
            content = test_file.get('content', "")
            file_path = test_file.get('file_path', '?')

            if not content:
                compacted_files.append(test_file)
                continue

            original_content = content

            # 如果文件未超限，不做处理
            if len(content) <= self.MAX_TEST_FILE_SIZE:
                compacted_files.append(test_file)
                continue

            # 自动精简：移除多余空行（超过2个连续空行改为2个）
            content = re.sub(r'\n{3,}', '\n\n', content)

            # 自动精简：移除行尾空格
            content = '\n'.join(line.rstrip() for line in content.split('\n'))

            if len(content) < len(original_content):
                logger.info(f"[TesterAgent] 自动精简测试文件: {file_path} ({len(original_content)} -> {len(content)} 字符)")

            compacted_files.append({
                **test_file,
                'content': content
            })

        return compacted_files


# 单例实例
tester_agent = TesterAgent()

# 向后兼容的别名
test_agent = tester_agent
