#!/usr/bin/env python3
"""
端到端集成测试（契约增强版）- 验证需求 → 验收标准 → 接口契约 → 代码 → 测试的全流程。

基于 test_e2e_with_llm_real.py 升级：
1. ArchitectAgent 输出验收标准
2. DesignerAgent 输出接口契约（interface_specs）
3. CoderAgent 必须实现接口契约中的所有符号
4. TesterAgent 只能测试接口契约中声明的符号
5. 增加前置契约检查：运行测试前验证代码是否提供了测试所需的符号
6. 修复工单携带缺失符号信息
7. 【分层测试】复用 LayeredTestRunner 进行分层测试执行

警告: 此脚本会调用真实 LLM 并启动 Docker，请确保配置正确。
"""

import asyncio, json, os, re, sys, time, tempfile, shutil, subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.architect import architect_agent
from app.agents.designer import designer_agent
from app.agents.coder import coder_agent
from app.agents.tester import tester_agent
from app.agents.repairer_with_tools import RepairerAgentWithTools
from app.agents.schemas import CoderOutput
from app.service.sandbox_orchestrator import get_sandbox_orchestrator, cleanup_sandbox_orchestrator
from app.service.sandbox_file_service import SandboxFileService
from app.service.layered_test_runner import LayeredTestRunner, LayeredTestResult

from app.core.contract_checker import verify_contract

# ========================== 测试配置 ==========================
PIPELINE_ID = 99999
FEATURE_REQUEST = "在健康检查接口中增加系统组件状态监控（数据库、磁盘、内存），并给出整体健康度。"


@dataclass
class E2EContractResult:
    success: bool
    code_generated: bool
    tests_generated: bool
    tests_passed: bool
    layered_result: Optional[LayeredTestResult] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


class ContractE2ETester:
    def __init__(self):
        self.backend_dir = Path(__file__).parent.parent
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def load_env(self):
        env_file = self.backend_dir / ".env"
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k not in os.environ:
                            os.environ[k] = v

    def check_api_key(self) -> bool:
        self.load_env()
        return any(
            os.getenv(k)
            for k in ["MODELSCOPE_API_KEY", "OPENAI_API_KEY", "LITELLM_API_KEY"]
        )

    def check_docker(self) -> bool:
        try:
            r = subprocess.run(["docker", "--version"], capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def build_file_tree(self) -> Dict[str, Any]:
        """复用原有的文件树构建，用于 ArchitectAgent 探索"""
        return {}  # 简化，ArchitectAgent 会通过工具自行探索

    def extract_missing_symbols(self, logs: str) -> List[str]:
        """从测试日志中提取缺失的符号（ImportError）"""
        missing = set()
        for pattern in [
            r"ImportError: cannot import name '(\w+)'",
            r"cannot import name '(\w+)'",
        ]:
            missing.update(re.findall(pattern, logs))
        return list(missing)

    def build_missing_specs_prompt(
        self,
        missing_syms: List[str],
        interface_specs: List[Dict]
    ) -> List[Dict]:
        """
        根据缺失符号列表，从 interface_specs 中提取对应的完整契约条目。
        缺失符号格式: "symbol_name in module_path"

        Returns:
            命中的契约条目列表（用于发给 CoderAgent 定向补全）
        """
        if not missing_syms:
            return []

        missing_specs = []
        for sym_entry in missing_syms:
            # 解析 "symbol_name in module_path" 格式
            symbol_name = sym_entry.split(" in ")[0].strip()
            module_path = sym_entry.split(" in ")[-1].strip()

            # 在 interface_specs 中查找匹配的完整条目
            found = False
            for spec in interface_specs:
                spec_name = spec.get("symbol_name", "")
                spec_module = spec.get("module", "")
                # 模块路径可能带 .py 后缀或不带，做宽松匹配
                spec_module_clean = spec_module.replace(".py", "").replace("\\", "/")
                module_clean = module_path.replace(".py", "").replace("\\", "/")
                if spec_name == symbol_name and spec_module_clean.rstrip("/") == module_clean.rstrip("/"):
                    missing_specs.append(spec)
                    found = True
                    break

            if not found:
                # 模糊匹配：只要符号名一致就纳入
                for spec in interface_specs:
                    if spec.get("symbol_name", "") == symbol_name:
                        missing_specs.append(spec)
                        break

        return missing_specs

    async def auto_fix_syntax_errors(
        self,
        syntax_errors: List[Dict],
        files_to_check: List[Tuple[str, str]],
        file_service,
        design_output: Dict,
        max_retries: int = 3
    ) -> Dict[str, str]:
        """
        【修复2】SyntaxError 自动修复循环 - 增强版
        
        当检测到语法错误时，优先修复语法错误而不是契约错误。
        支持逃生舱策略：第2次重试后强制完整文件覆盖。
        
        Args:
            syntax_errors: 语法错误列表
            files_to_check: 待检查的文件列表 [(file_path, content), ...]
            file_service: 文件服务
            design_output: 设计输出
            max_retries: 最大重试次数（默认3次）
            
        Returns:
            修复后的文件内容字典 {file_path: content}
        """
        fixed_files = {}
        
        for attempt in range(max_retries):
            print(f"\n   🔧 语法错误自动修复 第 {attempt + 1}/{max_retries} 次")
            
            # 收集所有有语法错误的文件内容
            error_files = {}
            for err in syntax_errors:
                fp = err.get("file", "")
                if fp:
                    # 从 files_to_check 获取当前内容
                    for check_fp, content in files_to_check:
                        if check_fp == fp:
                            error_files[fp] = content
                            break
            
            if not error_files:
                print(f"   ✅ 没有需要修复的语法错误文件")
                return fixed_files
            
            print(f"   发现 {len(error_files)} 个文件有语法错误")
            
            # 【增强】打印错误详情和上下文
            for fp, content in error_files.items():
                for err in syntax_errors:
                    if err.get("file") == fp:
                        line_no = err.get("line", 0)
                        lines = content.splitlines()
                        context_start = max(0, line_no - 3)
                        context_end = min(len(lines), line_no + 2)
                        context = "\n".join([f"    {i+1}: {lines[i]}" for i in range(context_start, context_end)])
                        print(f"\n   📍 {fp} (line {line_no}):")
                        print(f"      错误: {err['error']}")
                        print(f"      上下文:")
                        print(context)
            
            # 【增强】构建强制的修复指令
            force_full_file = attempt >= 1  # 第2次及以后强制完整文件
            
            if force_full_file:
                print(f"\n   🚨 进入逃生舱模式：强制完整文件覆盖")
            
            fix_instruction = f"""你是一个代码修复专家。以下文件存在 Python 语法错误，你必须修复它。

【强制规则】
1. {'输出完整的文件内容（change_type="add"），禁止输出 search_block/replace_block' if force_full_file else '优先使用完整文件覆盖（change_type="add"），如果必须用 modify，确保 search_block 精确匹配'}
2. 仅修复语法错误（删除多余括号、补齐缺失括号、修正缩进等）
3. 不要修改任何业务逻辑、函数名、变量名
4. 确保修复后的代码可以通过 python -m py_compile 检查

【常见语法错误类型】
- 多余括号：}} 或 ) 或 ] 重复
- 缺失括号：{{ 或 ( 或 [ 不匹配
- 缩进错误：混用空格和 Tab
- 冒号缺失：if/for/while/def/class 语句后缺少 :

【错误详情】
"""
            for err in syntax_errors:
                fp = err.get("file", "")
                error_msg = err.get("error", "")
                line_no = err.get("line", 0)
                fix_instruction += f"\n文件: {fp}\n"
                fix_instruction += f"  错误: {error_msg}\n"
                fix_instruction += f"  行号: {line_no}\n"
                
                # 添加上下文代码
                if fp in error_files:
                    content = error_files[fp]
                    lines = content.splitlines()
                    if 0 < line_no <= len(lines):
                        context_start = max(0, line_no - 3)
                        context_end = min(len(lines), line_no + 2)
                        fix_instruction += f"  上下文:\n"
                        for i in range(context_start, context_end):
                            marker = ">>> " if i == line_no - 1 else "    "
                            fix_instruction += f"{marker}{i+1}: {lines[i]}\n"
            
            fix_instruction += f"""
【原始文件内容】
"""
            for fp, content in error_files.items():
                fix_instruction += f"\n=== {fp} ===\n{content}\n"
            
            if force_full_file:
                fix_instruction += """
【逃生舱模式 - 极其重要】
由于前几次修复失败，现在进入强制完整文件覆盖模式：
1. 必须输出 change_type="add" 和完整的 content
2. 不要输出 search_block 或 replace_block
3. 仔细检查所有括号是否匹配（每有一个 {{ 必须有一个 }}）
4. 这是最后一次机会，如果仍然失败，工作将被拒绝！
"""
            
            # 构建定向设计输出
            targeted_design = {
                **{k: v for k, v in design_output.items() if k != "interface_specs"},
                "interface_specs": [],
                "affected_files": list(error_files.keys()),
                "fix_mode": True,
                "force_full_file": force_full_file,  # 【新增】逃生舱信号
                "fix_instruction": fix_instruction,
                "syntax_errors": syntax_errors
            }
            
            print(f"   📝 调用 CoderAgent 修复...")
            
            # 调用 CoderAgent 修复
            fix_result = await coder_agent.generate_code(
                design_output=targeted_design,
                pipeline_id=PIPELINE_ID,
                injected_files=error_files,
                error_context=fix_instruction
            )
            
            if not fix_result.get("success"):
                print(f"   ❌ CoderAgent 语法修复调用失败: {fix_result.get('error')}")
                continue
            
            fix_output = fix_result.get("output", {})
            if isinstance(fix_output, CoderOutput):
                fix_files = [f.model_dump() for f in fix_output.files]
            else:
                fix_files = fix_output.get("files", [])
            
            if not fix_files:
                print(f"   ❌ CoderAgent 未生成任何修复文件")
                continue
            
            print(f"   📥 CoderAgent 返回 {len(fix_files)} 个修复文件")
            
            # 应用修复并收集修复后的内容
            for fc in fix_files:
                fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                change_type = fc.get("change_type")
                search_block = fc.get("search_block", "")
                replace_block = fc.get("replace_block", "")
                content = fc.get("content", "")
                
                # 【增强】逃生舱模式下只接受完整文件
                if force_full_file and change_type != "add":
                    print(f"      ⚠️ 逃生舱模式下忽略 modify: {fp}，需要完整文件覆盖")
                    continue
                
                # 获取当前文件内容
                current_content = error_files.get(fp, "")
                
                if change_type == "modify" and search_block and current_content:
                    # 【增强】打印修复前后的对比
                    print(f"\n      📝 modify 修复 {fp}:")
                    print(f"         search_block (前100字符): {search_block[:100]}...")
                    print(f"         replace_block (前100字符): {replace_block[:100]}...")
                    
                    new_content = current_content.replace(search_block, replace_block, 1)
                    
                    # 【关键】写入前检查语法（使用 py_compile）
                    check_result = await self._check_syntax_with_py_compile(
                        [{"file_path": fp, "change_type": "add", "content": new_content}],
                        file_service
                    )
                    if not check_result:
                        fixed_files[fp] = new_content
                        # 更新 files_to_check 中的内容
                        for i, (check_fp, _) in enumerate(files_to_check):
                            if check_fp == fp:
                                files_to_check[i] = (fp, new_content)
                                break
                        print(f"      ✅ 语法修复成功: {fp}")
                    else:
                        print(f"      ❌ 修复后仍有语法错误: {fp} - {check_result[0]['error']}")
                elif content:
                    # 完整覆盖
                    print(f"\n      📝 完整覆盖 {fp} (content 长度: {len(content)})")
                    
                    check_result = await self._check_syntax_with_py_compile(
                        [{"file_path": fp, "change_type": "add", "content": content}],
                        file_service
                    )
                    if not check_result:
                        fixed_files[fp] = content
                        # 更新 files_to_check 中的内容
                        for i, (check_fp, _) in enumerate(files_to_check):
                            if check_fp == fp:
                                files_to_check[i] = (fp, content)
                                break
                        print(f"      ✅ 语法修复成功(覆盖): {fp}")
                    else:
                        print(f"      ❌ 修复后仍有语法错误: {fp} - {check_result[0]['error']}")
            
            # 重新检查语法
            remaining_errors = []
            for err in syntax_errors:
                fp = err.get("file", "")
                # 获取修复后的内容
                check_content = fixed_files.get(fp, "")
                if not check_content:
                    # 从 files_to_check 获取
                    for check_fp, content in files_to_check:
                        if check_fp == fp:
                            check_content = content
                            break
                
                if check_content:
                    # 使用 py_compile 检查语法
                    check_result = await self._check_syntax_with_py_compile(
                        [{"file_path": fp, "change_type": "add", "content": check_content}],
                        file_service
                    )
                    if check_result:
                        remaining_errors.append({
                            "file": fp,
                            "error": check_result[0]["error"],
                            "line": check_result[0]["line"]
                        })
            
            if not remaining_errors:
                print(f"\n   ✅ 所有语法错误修复成功！")
                return fixed_files
            
            print(f"\n   ⚠️ 第 {attempt + 1} 次修复后仍有 {len(remaining_errors)} 个语法错误")
            syntax_errors = remaining_errors  # 继续修复剩余错误
            
            # 【增强】死循环警告
            if attempt == max_retries - 2 and remaining_errors:
                print(f"   🚨 警告：可能陷入死循环，下次将进入强制完整文件覆盖模式")
        
        return fixed_files

    async def _check_syntax_with_py_compile(
        self,
        code_files: List[Dict],
        file_service: SandboxFileService
    ) -> List[Dict]:
        """
        使用 python -m py_compile 检查代码语法错误
        
        Args:
            code_files: 代码文件列表
            file_service: 文件服务
            
        Returns:
            语法错误列表
        """
        syntax_errors = []
        import tempfile
        import subprocess
        import os
        
        for fc in code_files:
            fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
            change_type = fc.get("change_type")
            
            # 获取要检查的内容
            content_to_check = None
            if change_type == "add":
                content_to_check = fc.get("content", "")
            elif change_type == "modify":
                # 对于 modify，需要构建最终内容来检查
                search_block = fc.get("search_block", "")
                replace_block = fc.get("replace_block", "")
                if search_block:
                    read_r = await file_service.read_file(fp)
                    if read_r.exists:
                        content_to_check = read_r.content.replace(search_block, replace_block, 1)
            
            if not content_to_check:
                continue
            
            # 使用 py_compile 检查语法
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tmp:
                    tmp.write(content_to_check)
                    tmp_path = tmp.name
                
                result = subprocess.run(
                    ['python', '-m', 'py_compile', tmp_path],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    # 解析错误信息
                    error_msg = result.stderr or "Syntax error"
                    # 提取行号
                    line_no = 0
                    import re
                    line_match = re.search(r'line (\d+)', error_msg)
                    if line_match:
                        line_no = int(line_match.group(1))
                    
                    # 获取上下文
                    lines = content_to_check.splitlines()
                    context_start = max(0, line_no - 3)
                    context_end = min(len(lines), line_no + 2)
                    context = "\n".join(lines[context_start:context_end])
                    
                    syntax_errors.append({
                        "file": fp,
                        "error": error_msg,
                        "line": line_no,
                        "context": context
                    })
            except Exception as e:
                # 如果检查过程出错，记录但继续
                syntax_errors.append({
                    "file": fp,
                    "error": f"语法检查失败: {e}",
                    "line": 0,
                    "context": ""
                })
            finally:
                # 清理临时文件
                try:
                    if 'tmp_path' in locals():
                        os.unlink(tmp_path)
                except:
                    pass
        
        return syntax_errors

    async def auto_fix_contract(
        self,
        missing_syms: List[str],
        interface_specs: List[Dict],
        design_output: Dict,
        file_service,
        max_retries: int = 3
    ) -> Tuple[bool, List[str], List[Dict]]:
        """
        契约检查失败时的自动修复循环。
        将缺失的契约条目发给 CoderAgent 定向生成代码，写入沙箱后重新检查。

        Returns:
            (是否全部修复, 仍然缺失的符号列表, 补全的 code_files 列表)
        """
        all_fix_files = []
        current_missing = missing_syms

        for attempt in range(max_retries):
            missing_specs = self.build_missing_specs_prompt(current_missing, interface_specs)
            if not missing_specs:
                print(f"   ⚠️ 无法从 interface_specs 中解析缺失条目: {current_missing}")
                break

            print(f"\n   🔧 契约自动修复 第 {attempt + 1}/{max_retries} 次")
            print(f"   缺失 {len(missing_specs)} 个契约条目，正在通知 CoderAgent 定向补全...")

            # 构建仅包含缺失条目的定向设计输出
            targeted_design = {
                **{k: v for k, v in design_output.items() if k != "interface_specs"},
                "interface_specs": missing_specs,
                "affected_files": list(set(
                    s.get("module", "").replace(".py", "")
                    for s in missing_specs
                )),
                "fix_mode": True,
                "fix_instruction": (
                    f"以下 {len(missing_specs)} 个接口契约条目在代码中缺失，"
                    f"请仅生成补全这些条目的代码变更，不要修改已有正确实现的代码。\n"
                    f"缺失条目: {json.dumps(missing_specs, indent=2, ensure_ascii=False)}"
                )
            }

            # 读取受影响的文件的当前内容作为 injected_files
            injected_files = {}
            for spec in missing_specs:
                module = spec.get("module", "")
                if module:
                    clean = module.replace("backend/", "").replace("backend\\", "").replace("\\", "/")
                    if not clean.endswith(".py"):
                        clean += ".py"
                    read_res = await file_service.read_file(clean)
                    if read_res.exists:
                        injected_files[clean] = read_res.content

            fix_result = await coder_agent.generate_code(
                design_output=targeted_design,
                pipeline_id=PIPELINE_ID,
                injected_files=injected_files
            )

            if not fix_result.get("success"):
                print(f"   ❌ CoderAgent 修复调用失败: {fix_result.get('error')}")
                continue

            fix_output = fix_result.get("output", {})
            if isinstance(fix_output, CoderOutput):
                fix_files = [f.model_dump() for f in fix_output.files]
            else:
                fix_files = fix_output.get("files", [])

            if not fix_files:
                print(f"   ❌ CoderAgent 未生成任何修复文件")
                continue

            # 写入修复文件到沙箱
            for fc in fix_files:
                fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                change_type = fc.get("change_type")
                search_block = fc.get("search_block", "")
                replace_block = fc.get("replace_block", "")
                content = fc.get("content", "")

                if change_type == "modify":
                    if search_block:
                        read_r = await file_service.read_file(fp)
                        if read_r.exists:
                            new_content = read_r.content.replace(search_block, replace_block, 1)
                            await file_service.write_file(fp, new_content)
                            print(f"      ✅ fix modify(搜索替换): {fp}")
                    elif content:
                        await file_service.write_file(fp, content)
                        print(f"      ✅ fix modify(完整覆盖): {fp}")
                elif change_type == "add" and content:
                    await file_service.write_file(fp, content)
                    print(f"      ✅ fix add: {fp}")

            all_fix_files.extend(fix_files)

            # 重新检查契约
            current_missing = await self.verify_contract(
                file_service, fix_files + all_fix_files, interface_specs
            )

            if not current_missing:
                print(f"   ✅ 契约自动修复成功！所有符号已实现")
                return True, [], all_fix_files

            print(f"   ⚠️ 第 {attempt + 1} 次修复后仍有 {len(current_missing)} 个缺失: {current_missing}")

        return False, current_missing, all_fix_files

    async def _validate_test_imports(
        self,
        test_files: List[Dict],
        file_service
    ) -> List[str]:
        """
        【新增】验证测试文件中的所有 import 是否真实存在
        
        提取测试文件中的 from app... import ... 语句，检查导入的符号是否存在于源文件中。
        
        Args:
            test_files: 测试文件列表
            file_service: 文件服务
            
        Returns:
            List[str]: 导入错误列表
        """
        import re
        import ast
        errors = []
        
        for test_file in test_files:
            file_path = test_file.get("file_path", "")
            content = test_file.get("content", "")
            
            if not content:
                continue
            
            try:
                tree = ast.parse(content)
            except SyntaxError:
                # 语法错误会在其他地方处理
                continue
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module
                    if not module or not module.startswith("app."):
                        continue
                    
                    # 将模块路径转换为文件路径
                    module_path = module.replace(".", "/") + ".py"
                    
                    # 检查模块文件是否存在
                    read_res = await file_service.read_file(module_path)
                    if not read_res.exists:
                        errors.append(f"{file_path}: 导入的模块不存在: {module}")
                        continue
                    
                    # 检查导入的符号是否存在于模块中
                    try:
                        module_tree = ast.parse(read_res.content)
                        module_symbols = set()

                        # 【关键修复】只遍历模块的顶层节点，不递归进入类内部
                        # 类方法不能作为模块级符号被直接导入
                        for n in module_tree.body:
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                module_symbols.add(n.name)
                            elif isinstance(n, ast.ClassDef):
                                module_symbols.add(n.name)
                            # 【修复】增加对重导出符号的支持
                            elif isinstance(n, ast.ImportFrom):
                                # 处理 from X import Y 中的 Y
                                for alias in n.names:
                                    if alias.name:
                                        module_symbols.add(alias.name)
                            elif isinstance(n, ast.Import):
                                # 处理 import xxx，提取顶层模块名
                                for alias in n.names:
                                    if alias.name:
                                        module_symbols.add(alias.name.split('.')[0])
                        
                        for alias in node.names:
                            if alias.name != "*" and alias.name not in module_symbols:
                                errors.append(f"{file_path}: 导入的符号不存在: {module}.{alias.name}")
                    
                    except SyntaxError:
                        # 模块有语法错误，会在其他地方处理
                        pass
        
        return errors

    async def _fix_test_imports(
        self,
        test_files: List[Dict],
        import_errors: List[str],
        file_service,
        design_output: Dict,
        code_output: Dict,
        max_retries: int = 2
    ) -> bool:
        """
        【新增】修复测试文件中的导入错误
        
        将导入错误反馈给 TesterAgent，要求修正测试文件中的 import 语句。
        
        Args:
            test_files: 测试文件列表
            import_errors: 导入错误列表
            file_service: 文件服务
            design_output: 设计输出
            code_output: 代码输出（TesterAgent 需要）
            max_retries: 最大重试次数
            
        Returns:
            bool: 是否修复成功
        """
        for attempt in range(max_retries):
            print(f"\n   🔧 导入错误修复 第 {attempt + 1}/{max_retries} 次")
            
            # 构建修复指令
            fix_instruction = (
                f"测试文件存在以下导入错误，请修正 import 语句:\n\n"
                + "\n".join(import_errors)
                + "\n\n要求:\n"
                + "1. 只导入实际存在的模块和符号\n"
                + "2. 如果符号不存在，修改测试代码以使用正确的符号\n"
                + "3. 不要修改被测代码，只修改测试文件\n"
            )
            
            # 读取当前测试文件内容
            injected_files = {}
            for tf in test_files:
                fp = tf.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                read_res = await file_service.read_file(fp)
                if read_res.exists:
                    injected_files[fp] = read_res.content
            
            # 调用 TesterAgent 修复
            fix_result = await tester_agent.generate_tests(
                design_output={
                    **design_output,
                    "fix_mode": True,
                    "fix_instruction": fix_instruction,
                    "existing_test_files": test_files
                },
                code_output=code_output,
                pipeline_id=PIPELINE_ID
            )
            
            if not fix_result.get("success"):
                print(f"   ❌ TesterAgent 修复调用失败: {fix_result.get('error')}")
                continue
            
            # 获取修复后的测试文件
            fixed_test_output = fix_result.get("output", {})
            fixed_test_files = fixed_test_output.get("test_files", [])
            
            if not fixed_test_files:
                print(f"   ❌ TesterAgent 未生成修复后的测试文件")
                continue
            
            # 写入修复后的测试文件
            for tf in fixed_test_files:
                fp = tf.get("file_path", "")
                content = tf.get("content", "")
                if content:
                    await file_service.write_file(fp, content)
            
            # 重新验证导入
            remaining_errors = await self._validate_test_imports(fixed_test_files, file_service)
            
            if not remaining_errors:
                print(f"   ✅ 所有导入错误已修复")
                return True
            
            print(f"   ⚠️ 第 {attempt + 1} 次修复后仍有 {len(remaining_errors)} 个导入错误")
            import_errors = remaining_errors
            test_files = fixed_test_files
        
        return False

    async def _fix_test_syntax_errors(
        self,
        test_files: List[Dict],
        syntax_errors: List[Dict],
        file_service,
        design_output: Dict,
        code_output: Dict,
        max_retries: int = 2
    ) -> List[Dict]:
        """
        【新增】修复测试文件中的语法错误
        
        将语法错误反馈给 TesterAgent，要求修正测试文件。
        
        Args:
            test_files: 测试文件列表
            syntax_errors: 语法错误列表
            file_service: 文件服务
            design_output: 设计输出
            code_output: 代码输出
            max_retries: 最大重试次数
            
        Returns:
            修复后的测试文件列表
        """
        for attempt in range(max_retries):
            print(f"\n   🔧 测试语法错误修复 第 {attempt + 1}/{max_retries} 次")
            
            # 构建修复指令
            fix_instruction = (
                f"测试文件存在以下 Python 语法错误，请修正:\n\n"
            )
            for err in syntax_errors:
                fix_instruction += f"文件: {err['file']}\n"
                fix_instruction += f"错误: {err['error']}\n"
                fix_instruction += f"行号: {err['line']}\n"
                fix_instruction += f"附近代码:\n{err['context']}\n\n"
            
            fix_instruction += """
要求:
1. 修复所有语法错误（缩进、括号匹配、冒号等）
2. 确保修复后的代码可以通过 python -m py_compile 检查
3. 只修改语法错误，不要改变测试逻辑
4. 保持原有的测试结构和断言
"""
            
            # 调用 TesterAgent 修复
            fix_result = await tester_agent.generate_tests(
                design_output={
                    **design_output,
                    "fix_mode": True,
                    "fix_instruction": fix_instruction,
                    "existing_test_files": test_files
                },
                code_output=code_output,
                pipeline_id=PIPELINE_ID
            )
            
            if not fix_result.get("success"):
                print(f"   ❌ TesterAgent 语法修复调用失败: {fix_result.get('error')}")
                continue
            
            # 获取修复后的测试文件
            fixed_test_output = fix_result.get("output", {})
            fixed_test_files = fixed_test_output.get("test_files", [])
            
            if not fixed_test_files:
                print(f"   ❌ TesterAgent 未生成修复后的测试文件")
                continue
            
            # 写入修复后的测试文件
            for tf in fixed_test_files:
                fp = tf.get("file_path", "")
                content = tf.get("content", "")
                if content:
                    await file_service.write_file(fp, content)
            
            # 重新验证语法（使用 py_compile）
            remaining_errors = await self._check_syntax_with_py_compile(
                [{"file_path": tf.get("file_path", ""), "change_type": "add", "content": tf.get("content", "")} for tf in fixed_test_files],
                file_service
            )
            
            if not remaining_errors:
                print(f"   ✅ 所有测试语法错误已修复")
                return fixed_test_files
            
            print(f"   ⚠️ 第 {attempt + 1} 次修复后仍有 {len(remaining_errors)} 个语法错误")
            syntax_errors = remaining_errors
            test_files = fixed_test_files
        
        return []

    async def verify_contract(self, file_service, code_files: List[Dict],
                        interface_specs: List[Dict]) -> List[str]:
        """
        【复用】前置检查：验证所有契约符号是否已在代码中实现
        使用 app.core.contract_checker.verify_contract 替代原有实现
        【增强】同时检查沙箱中的现有文件（用于 modify 类型的变更）
        """
        # 构建 code_files 字典
        code_files_dict = {}
        for f in code_files:
            fp = f.get("file_path", "")
            content = f.get("content", "")
            change_type = f.get("change_type", "")
            
            if not fp:
                continue
            
            # 标准化路径
            normalized_fp = fp.replace("backend/", "").replace("backend\\", "")
            
            if change_type == "add" and content:
                # 新增文件，使用 content
                code_files_dict[normalized_fp] = content
            elif change_type == "modify":
                # 修改文件，需要从沙箱读取完整内容
                read_res = await file_service.read_file(normalized_fp)
                if read_res.exists:
                    code_files_dict[normalized_fp] = read_res.content
                elif content:
                    code_files_dict[normalized_fp] = content
            else:
                # 其他情况，优先使用 content
                if content:
                    code_files_dict[normalized_fp] = content

        # 【增强】对于 interface_specs 中提到的文件，如果不在 code_files_dict 中，
        # 尝试从沙箱读取（可能是已存在的文件）
        for spec in interface_specs:
            module = spec.get("module", "")
            if not module:
                continue
            
            # 标准化模块路径
            normalized_module = module.replace("backend/", "").replace("backend\\", "")
            if not normalized_module.endswith(".py"):
                normalized_module += ".py"
            
            # 如果文件不在 code_files_dict 中，尝试从沙箱读取
            if normalized_module not in code_files_dict:
                read_res = await file_service.read_file(normalized_module)
                if read_res.exists:
                    code_files_dict[normalized_module] = read_res.content

        # 【复用】调用后端的契约检查函数
        return verify_contract(code_files_dict, interface_specs)

    async def run_tests_with_layered_runner(
        self,
        pipeline_id: int,
        generated_files: List[Dict[str, Any]],
        file_service: SandboxFileService
    ) -> LayeredTestResult:
        """
        【分层测试】使用 LayeredTestRunner 执行分层测试
        
        分层策略：
        - Layer 1: 语法检查（毫秒级）- 检查所有生成文件的语法
        - Layer 2: 防御性测试（秒级）- 运行 backend/tests/unit/defense/
        - Layer 3: 回归测试（秒级）- 运行 backend/tests/unit/ 和 integration/
        - Layer 4: 新生成测试（秒级）- 运行 backend/tests/ai_generated/
        - Layer 5: 健康检查（服务启动验证）- 检查服务是否能启动
        """
        print(f"\n   [分层测试] 使用 LayeredTestRunner 执行测试...")
        print(f"   [分层测试] 生成文件数量: {len(generated_files)}")

        # 【复用】使用 LayeredTestRunner 执行分层测试，传入 file_service 支持 Docker 环境
        result = await LayeredTestRunner.run(
            workspace_path="/workspace",
            new_files=generated_files,
            sandbox_port=None,
            timeout=120,
            file_service=file_service  # 【关键】传入 file_service 以支持 Docker 环境
        )

        # 打印分层结果摘要
        print(f"\n   [分层测试] 结果摘要:")
        for layer in result.layers:
            status = "✅" if layer.passed else "❌"
            print(f"   {status} Layer {layer.layer}: {layer.summary}")
            if layer.failed_tests:
                for ft in layer.failed_tests[:3]:  # 只显示前3个
                    print(f"      - {ft}")
                if len(layer.failed_tests) > 3:
                    print(f"      ... 还有 {len(layer.failed_tests) - 3} 个失败")
            # 【DEBUG】打印详细日志
            if not layer.passed and layer.logs:
                print(f"\n   [DEBUG] Layer {layer.layer} 详细日志:")
                print(f"   {layer.logs[:1500]}")
                if len(layer.logs) > 1500:
                    print(f"   ... (日志已截断，共 {len(layer.logs)} 字符)")

        return result

    async def run(self) -> E2EContractResult:
        start = time.time()
        print("=" * 70)
        print("🧪 契约增强端到端测试（分层测试版）")
        print("=" * 70)
        print("需求: 系统状态监控 API（包含内部辅助函数）")
        print()

        if not self.check_api_key():
            return E2EContractResult(False, False, False, False, error_message="API Key 缺失")
        if not self.check_docker():
            return E2EContractResult(False, False, False, False, error_message="Docker 不可用")

        # Step 0: 启动 Sandbox
        print("🐳 启动 Docker Sandbox...")
        sandbox_orch = get_sandbox_orchestrator(PIPELINE_ID)
        # 【修复】传入项目根目录（backend 的父目录），而不是 backend 目录本身
        # 因为 sandbox 挂载的是 project_path:/workspace，期望 /workspace/backend/ 结构
        project_root = str(self.backend_dir.parent)
        sandbox_init = await sandbox_orch.initialize(project_root)
        if not sandbox_init["success"]:
            return E2EContractResult(False, False, False, False, error_message="Sandbox 启动失败")
        file_service = sandbox_orch.get_file_service()
        print("✅ Sandbox 就绪")

        try:
            # ========== Step 1: 需求分析（含验收标准） ==========
            print("\n📋 Step 1: ArchitectAgent 分析需求（输出验收标准）...")
            file_tree = self.build_file_tree()
            arch_result = await architect_agent.analyze(
                requirement=FEATURE_REQUEST,
                file_tree=file_tree,
                pipeline_id=PIPELINE_ID,
                project_path=str(self.backend_dir)
            )
            if not arch_result["success"]:
                raise RuntimeError(f"ArchitectAgent 失败: {arch_result.get('error')}")
            arch_output = arch_result["output"]
            acceptance_criteria = arch_output.get("acceptance_criteria", [])
            print(f"   验收标准: {acceptance_criteria}")
            
            # 【调试】打印 ArchitectAgent 完整输出
            print("\n=== ArchitectAgent 输出 ===")
            print(json.dumps(arch_output, indent=2, ensure_ascii=False, default=str))
            self.total_input_tokens += arch_result.get("input_tokens", 0)
            self.total_output_tokens += arch_result.get("output_tokens", 0)

            # ========== Step 2: 方案设计（输出接口契约） ==========
            print("\n🎨 Step 2: DesignerAgent 技术设计（输出接口契约）...")
            # 【修复】将 ArchitectAgent 预读的文件内容传给 Designer，
            # 让其能在 prompt 中看到结构化的【完整文件内容】段落
            design_result = await designer_agent.design(
                architect_output=arch_output,
                file_tree=file_tree,
                related_code_context="",
                full_files_context=arch_result.get("injected_files", {}),
                pipeline_id=PIPELINE_ID,
                max_retries=3
            )
            if not design_result["success"]:
                raise RuntimeError(f"DesignerAgent 失败: {design_result.get('error')}")
            design_output = design_result["output"]
            interface_specs = design_output.get("interface_specs", [])
            print(f"   接口契约 ({len(interface_specs)} 项):")
            for s in interface_specs:
                print(f"      - {s['symbol_name']} in {s.get('module','?')}")
            
            # 【调试】打印 DesignerAgent 完整输出
            print("\n=== DesignerAgent 输出 ===")
            print(json.dumps(design_output, indent=2, ensure_ascii=False, default=str))
            # 新的 design 方法可能不返回 token 信息，使用 0 作为默认值
            self.total_input_tokens += design_result.get("input_tokens", 0)
            self.total_output_tokens += design_result.get("output_tokens", 0)

            # ========== Step 3 & 4: 代码生成与测试骨架生成（并发执行） ==========
            print("\n📝 Step 3: CoderAgent 生成代码 + TesterAgent 生成测试骨架（并发）...")
            # 【修复】使用 ArchitectAgent 预读的全部文件内容注入，而非只注入 health.py
            injected_files = arch_result.get("injected_files", {})
            if not injected_files:
                # 兜底：如果没有 injected_files，手动读取 health.py
                read_result = await file_service.read_file("app/api/v1/health.py")
                if read_result.exists:
                    injected_files["app/api/v1/health.py"] = read_result.content
            print(f"   注入 {len(injected_files)} 个文件内容到 CoderAgent")

            # 【串行执行】先执行 CoderAgent 生成代码
            print("   [串行执行] 步骤 1/2: CoderAgent 生成代码...")
            
            # 【调试】打印 CoderAgent 实际收到的 design_output 关键信息
            print("\n=== CoderAgent 收到的 design_output 关键信息 ===")
            print(f"interface_specs 数量: {len(design_output.get('interface_specs', []))}")
            for spec in design_output.get('interface_specs', [])[:3]:  # 只打印前3个
                symbol = spec.get('symbol_name', 'N/A')
                return_fields = spec.get('return_fields', [])
                field_names = [f.get('name', 'N/A') for f in return_fields]
                print(f"  - {symbol}: return_fields = {field_names}")
            
            coder_result = await coder_agent.generate_code(
                design_output=design_output,
                pipeline_id=PIPELINE_ID,
                injected_files=injected_files
            )
            
            # 【调试】打印 CoderAgent 实际返回的完整输出
            print("\n=== CoderAgent Raw Output ===")
            if coder_result.get("output"):
                output = coder_result["output"]
                if hasattr(output, 'model_dump'):
                    output_dict = output.model_dump()
                else:
                    output_dict = output
                print(json.dumps(output_dict, indent=2, ensure_ascii=False, default=str))
            else:
                print("No output")
            
            # 检查 CoderAgent 结果，如果需要则进入重试
            if not coder_result.get("success"):
                error_msg = coder_result.get('error', '未知错误')
                print(f"   ❌ CoderAgent 失败: {error_msg}")
                
                # 【修复】如果是返回键名不匹配，进入重试循环（最多3次）
                if "返回键名与契约不一致" in error_msg:
                    max_retries = 3
                    retry_success = False
                    
                    for retry_attempt in range(max_retries):
                        print(f"\n   🔧 返回键名不匹配，第 {retry_attempt + 1}/{max_retries} 次重试...")
                        
                        # 提取缺失字段信息
                        key_mismatches = []
                        error_output = coder_result.get('output', {})
                        if hasattr(error_output, 'key_mismatches'):
                            key_mismatches = error_output.key_mismatches
                        elif isinstance(error_output, dict):
                            key_mismatches = error_output.get('key_mismatches', [])
                        
                        # 【增强】从 injected_files 获取当前文件内容，提取函数源代码
                        fix_instruction = f"""之前的生成结果有误: {error_msg}

关键问题：以下函数缺少必需的返回字段：
"""
                        # 添加具体的缺失字段信息和当前源代码
                        for mismatch in key_mismatches:
                            symbol = mismatch.get('symbol', '') if isinstance(mismatch, dict) else getattr(mismatch, 'symbol', '')
                            missing = mismatch.get('missing_keys', []) if isinstance(mismatch, dict) else getattr(mismatch, 'missing_keys', [])
                            file_path = mismatch.get('file', '') if isinstance(mismatch, dict) else getattr(mismatch, 'file', '')
                            
                            fix_instruction += f"\n\n=== 函数: {symbol} (文件: {file_path}) ==="
                            fix_instruction += f"\n缺少字段: {missing}"
                            
                            # 从 injected_files 获取当前函数源代码
                            if file_path and file_path in injected_files:
                                content = injected_files[file_path]
                                # 尝试提取函数源代码
                                import re
                                func_pattern = rf"(async\s+)?def\s+{re.escape(symbol)}\s*\([^)]*\)(\s*->\s*[^:]+)?:\s*\n"
                                match = re.search(func_pattern, content)
                                if match:
                                    start_idx = match.start()
                                    # 找到函数结束位置（简单启发式：下一个同缩进级别的 def 或 class）
                                    lines = content[start_idx:].split('\n')
                                    func_lines = [lines[0]]
                                    base_indent = len(lines[1]) - len(lines[1].lstrip()) if len(lines) > 1 else 4
                                    for i, line in enumerate(lines[1:], 1):
                                        if line.strip() and not line.startswith(' ' * base_indent) and not line.startswith('\t'):
                                            if line.strip().startswith(('def ', 'class ', '@')):
                                                break
                                        func_lines.append(line)
                                    func_code = '\n'.join(func_lines)
                                    fix_instruction += f"\n\n当前函数源代码:\n```python\n{func_code}\n```"
                                else:
                                    fix_instruction += f"\n\n当前文件内容（部分）:\n```python\n{content[:1000]}\n```"
                        
                        # 根据重试次数调整策略
                        if retry_attempt == 0:
                            # 第1次重试：尝试精准修改
                            fix_instruction += """

【修复要求 - 第1次尝试】
1. 为每个缺失字段的函数生成 search_block + replace_block
2. search_block 必须是函数的完整当前代码（从 def 到函数结束）
3. replace_block 必须在返回字典中追加所有缺失的字段
4. 如果无法找到合适的 search_block，直接用 change_type="add" 输出完整文件内容

【重要】
- 不要省略任何缺失的字段
- 保留原有字段不变
- 新字段的值根据函数逻辑合理计算
"""
                            force_full_file = False
                        elif retry_attempt == 1:
                            # 第2次重试：强制完整文件
                            fix_instruction += """

【修复要求 - 第2次尝试】
由于第1次尝试失败，现在强制使用完整文件覆盖：
1. 使用 change_type="add" 输出完整文件内容
2. 确保所有函数返回字典包含所有必需字段
3. 不要输出 search_block/replace_block
4. 这是倒数第二次机会！
"""
                            force_full_file = True
                        else:
                            # 第3次重试：最后机会，强制完整文件并跳过检查
                            fix_instruction += """

【修复要求 - 最后机会】
这是最后一次尝试！必须成功：
1. 使用 change_type="add" 输出完整文件内容
2. 仔细检查每个函数的返回字典，确保包含所有必需字段
3. 如果仍然失败，整个工作将被拒绝
4. 系统会跳过静态检查，直接信任你的输出
"""
                            force_full_file = True
                        
                        # 构建修复用的 design_output
                        retry_design_output = {
                            **design_output,
                            "fix_mode": True,
                            "force_full_file": force_full_file,
                            "fix_instruction": fix_instruction,
                            "affected_files": list(injected_files.keys())
                        }
                        
                        print(f"   📝 调用 CoderAgent 重试 (force_full_file={force_full_file})...")
                        
                        retry_result = await coder_agent.generate_code(
                            design_output=retry_design_output,
                            pipeline_id=PIPELINE_ID,
                            injected_files=injected_files
                        )
                        
                        if retry_result.get("success"):
                            print(f"   ✅ 第 {retry_attempt + 1} 次重试成功")
                            coder_result = retry_result
                            retry_success = True
                            break
                        else:
                            print(f"   ❌ 第 {retry_attempt + 1} 次重试失败: {retry_result.get('error')}")
                            # 更新 coder_result 以便下一次重试使用最新的错误信息
                            coder_result = retry_result
                    
                    if not retry_success:
                        raise RuntimeError(f"CoderAgent 重试 {max_retries} 次后仍然失败")
                else:
                    raise RuntimeError(f"CoderAgent 失败: {error_msg}")

            # CoderAgent 完成后（包括重试成功后），再执行 TesterAgent
            test_result = None
            if coder_result.get("success"):
                print("   [串行执行] 步骤 2/2: TesterAgent 生成完整测试...")
                # 【修改】直接生成完整测试，不再分骨架和填充两步
                code_output = coder_result.get("output", {})
                if isinstance(code_output, CoderOutput):
                    code_output_dict = code_output.model_dump()
                else:
                    code_output_dict = code_output
                
                test_result = await tester_agent.generate_tests(
                    design_output=design_output,
                    code_output=code_output_dict,
                    pipeline_id=PIPELINE_ID
                )
            else:
                print("   ⚠️ CoderAgent 失败，跳过 TesterAgent 测试生成")
                test_result = {"success": False, "error": "CoderAgent 失败，跳过测试生成"}
            code_output = coder_result.get("output", {})
            if isinstance(code_output, CoderOutput):
                code_files = [f.model_dump() for f in code_output.files]
            else:
                code_files = code_output.get("files", [])
            print(f"   CoderAgent 生成 {len(code_files)} 个文件")

            # 检查 TesterAgent 测试结果
            if not test_result.get("success"):
                print(f"   ⚠️ TesterAgent 测试生成失败: {test_result.get('error')}")
                # 测试生成失败不阻断，继续执行
                test_output = None
                test_files = []
            else:
                test_output = test_result.get("output", {})
                test_files = test_output.get("test_files", [])
                print(f"   TesterAgent 生成 {len(test_files)} 个测试文件")

            self.total_input_tokens += coder_result.get("input_tokens", 0)
            self.total_output_tokens += coder_result.get("output_tokens", 0)
            self.total_input_tokens += test_result.get("input_tokens", 0)
            self.total_output_tokens += test_result.get("output_tokens", 0)

            # 【新增】语法验证 - 在写入前检查所有生成的代码（使用 py_compile）
            print(f"\n   🔍 验证代码语法 (python -m py_compile)...")
            syntax_errors = await self._check_syntax_with_py_compile(code_files, file_service)

            if syntax_errors:
                print(f"   ❌ 发现 {len(syntax_errors)} 个语法错误，启动 CoderAgent 修复...")
                for err in syntax_errors:
                    print(f"      - {err['file']}: {err['error']}")
                    print(f"        附近代码:\n{err['context']}")
                
                # 【修复】不直接报错，而是让 CoderAgent 修复语法错误
                syntax_error_context = f"""语法错误修复任务：
以下文件存在 Python 语法错误，请修复：

"""
                for err in syntax_errors:
                    syntax_error_context += f"""
文件: {err['file']}
错误: {err['error']}
行号: {err['line']}
附近代码:
{err['context']}

"""
                syntax_error_context += """
【修复要求】
1. 检查并修复所有语法错误（缩进、括号匹配、冒号等）
2. 确保修复后的代码是合法的 Python 代码
3. 只修改语法错误，不要改变逻辑
"""
                
                # 构建修复用的 design_output
                fix_design_output = {
                    **design_output,
                    "fix_mode": True,
                    "fix_instruction": syntax_error_context
                }
                
                # 读取所有受影响的文件内容
                fix_injected_files = {}
                for err in syntax_errors:
                    file_path = err['file']
                    read_res = await file_service.read_file(file_path)
                    if read_res.exists:
                        fix_injected_files[file_path] = read_res.content
                
                # 调用 CoderAgent 修复
                fix_result = await coder_agent.generate_code(
                    design_output=fix_design_output,
                    pipeline_id=PIPELINE_ID,
                    error_context=syntax_error_context,
                    injected_files=fix_injected_files
                )
                
                if not fix_result.get("success"):
                    raise RuntimeError(f"CoderAgent 语法修复失败: {fix_result.get('error')}")
                
                fix_output = fix_result.get("output", {})
                if isinstance(fix_output, CoderOutput):
                    fix_files = [f.model_dump() for f in fix_output.files]
                else:
                    fix_files = fix_output.get("files", [])
                
                if not fix_files:
                    raise RuntimeError("CoderAgent 未生成任何修复文件")
                
                print(f"   ✅ CoderAgent 生成 {len(fix_files)} 个修复文件")
                
                # 应用修复
                for fc in fix_files:
                    fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                    change_type = fc.get("change_type")
                    search_block = fc.get("search_block", "")
                    replace_block = fc.get("replace_block", "")
                    content = fc.get("content", "")
                    
                    if change_type == "modify" and search_block:
                        read_r = await file_service.read_file(fp)
                        if read_r.exists:
                            new_content = read_r.content.replace(search_block, replace_block, 1)
                            await file_service.write_file(fp, new_content)
                            print(f"      ✅ 修复语法: {fp}")
                    elif change_type == "add" and content:
                        await file_service.write_file(fp, content)
                        print(f"      ✅ 修复语法(覆盖): {fp}")
                
                # 重新验证语法（使用 py_compile）
                print(f"\n   🔍 重新验证语法...")
                syntax_errors = await self._check_syntax_with_py_compile(fix_files, file_service)
                
                if syntax_errors:
                    raise RuntimeError(f"修复后仍存在语法错误: {syntax_errors}")
                
                print(f"   ✅ 语法修复完成并通过验证")
            else:
                print(f"   ✅ 语法检查通过")

            # 将代码写入 Sandbox
            print(f"\n   写入代码到 Sandbox...")
            
            # 【改进3】同文件修改合并 + 自适应匹配
            written_count = 0
            # 第一步：按文件分组，合并同一文件的多个 modify 操作
            merged_by_file: Dict[str, List[Dict]] = {}
            add_files: List[Dict] = []
            
            for fc in code_files:
                fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                change_type = fc.get("change_type")
                if change_type == "add":
                    add_files.append(fc)
                elif change_type == "modify":
                    if fp not in merged_by_file:
                        merged_by_file[fp] = []
                    merged_by_file[fp].append(fc)
            
            # 第二步：对每个文件的 modify 操作，先读取文件再依次应用
            for fp, changes in merged_by_file.items():
                read_r = await file_service.read_file(fp)
                if not read_r.exists:
                    print(f"      ⚠️ 跳过 modify: {fp} (文件不存在)")
                    continue
                
                current_content = read_r.content
                
                for fc in changes:
                    search_block = fc.get("search_block", "")
                    replace_block = fc.get("replace_block", "")
                    
                    if search_block:
                        if search_block in current_content:
                            current_content = current_content.replace(search_block, replace_block, 1)
                            print(f"      ✅ modify(搜索替换): {fp}")
                        else:
                            # 【改进3】自适应匹配：使用 difflib 查找模糊匹配
                            import difflib
                            current_lines = current_content.splitlines(keepends=True)
                            search_lines = search_block.splitlines(keepends=True)
                            
                            # 用 SequenceMatcher 找到最佳匹配位置
                            best_match_start = -1
                            best_ratio = 0
                            min_match_len = len(search_lines)
                            
                            for i in range(len(current_lines) - min_match_len + 1):
                                window = ''.join(current_lines[i:i + min_match_len])
                                ratio = difflib.SequenceMatcher(None, search_block, window).ratio()
                                if ratio > best_ratio and ratio > 0.6:
                                    best_ratio = ratio
                                    best_match_start = i
                            
                            if best_match_start >= 0:
                                # 找到了足够相似的匹配，扩大窗口再试精确匹配
                                expanded_start = max(0, best_match_start - 3)
                                expanded_end = min(len(current_lines), best_match_start + len(search_lines) + 3)
                                expanded_window = ''.join(current_lines[expanded_start:expanded_end])
                                
                                # 用实际匹配的行来做替换
                                actual_match = ''.join(current_lines[best_match_start:best_match_start + len(search_lines)])
                                if actual_match.strip():
                                    current_content = current_content.replace(actual_match, replace_block, 1)
                                    print(f"      ✅ modify(自适应匹配 {best_ratio:.0%}): {fp} (line ~{best_match_start + 1})")
                                else:
                                    print(f"      ⚠️ modify(自适应失败): {fp} (相似度 {best_ratio:.0%} 但匹配行内容为空)")
                            else:
                                print(f"      ⚠️ modify(搜索块不匹配): {fp} (相似度最高 {best_ratio:.0%} < 阈值 60%)")
                                
                                # 【新增】重新请求 CoderAgent 生成正确的 search_block（最多重试3次）
                                max_retries = 3
                                retry_success = False
                                
                                for retry_attempt in range(max_retries):
                                    print(f"      🔄 重新请求 CoderAgent 修复 {fp} (第 {retry_attempt + 1}/{max_retries} 次)...")
                                    retry_result = await coder_agent.generate_code(
                                        design_output={
                                            "fix_mode": True,
                                            "fix_instruction": f"""文件 {fp} 的 search_block 无法匹配当前文件内容。

当前文件的真实内容（部分）:
```python
{current_content[:2000]}
```

CoderAgent 原本想替换的 replace_block:
```python
{replace_block}
```

请基于当前文件的真实内容，重新生成正确的 search_block 和 replace_block。
要求：
1. search_block 必须从当前文件内容中逐字复制（包括空格和换行）
2. replace_block 实现原本想做的修改
3. 确保 search_block 在当前文件中确实存在
4. 如果无法找到合适的 search_block，可以直接返回完整的文件内容（content 字段）进行覆盖
""",
                                            "affected_files": [fp]
                                        },
                                        pipeline_id=PIPELINE_ID,
                                        injected_files={fp: current_content}
                                    )
                                    
                                    if retry_result.get("success"):
                                        retry_output = retry_result.get("output", {})
                                        if isinstance(retry_output, CoderOutput):
                                            retry_files = [f.model_dump() for f in retry_output.files]
                                        else:
                                            retry_files = retry_output.get("files", [])
                                        
                                        # 应用重试生成的修复
                                        for rfc in retry_files:
                                            rfp = rfc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                                            if rfp == fp:
                                                r_search = rfc.get("search_block", "")
                                                r_replace = rfc.get("replace_block", "")
                                                r_content = rfc.get("content", "")
                                                
                                                if r_search and r_search in current_content:
                                                    current_content = current_content.replace(r_search, r_replace, 1)
                                                    print(f"      ✅ modify(重试成功): {fp}")
                                                    retry_success = True
                                                    break
                                                elif r_content:
                                                    current_content = r_content
                                                    print(f"      ✅ modify(重试-完整覆盖): {fp}")
                                                    retry_success = True
                                                    break
                                                else:
                                                    print(f"      ⚠️ modify(重试 {retry_attempt + 1} 无法应用): {fp}")
                                    else:
                                        print(f"      ⚠️ modify(重试 {retry_attempt + 1} 失败): {fp} - {retry_result.get('error', '未知错误')}")
                                    
                                    if retry_success:
                                        break
                                
                                if not retry_success:
                                    print(f"      ❌ modify(所有重试均失败): {fp} - 跳过此修改")
                    elif fc.get("content"):
                        current_content = fc.get("content")
                        print(f"      ✅ modify(完整覆盖): {fp}")
                
                await file_service.write_file(fp, current_content)
                written_count += 1
            
            # 第三步：写入新增文件
            for fc in add_files:
                fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                content = fc.get("content", "")
                if content:
                    await file_service.write_file(fp, content)
                    written_count += 1
                    print(f"      ✅ add: {fp}")
                else:
                    print(f"      ⚠️ 跳过 add: {fp} (无 content)")
            
            # 第四步：处理 delete 类型（仅记录，不执行）
            for fc in code_files:
                if fc.get("change_type") == "delete":
                    fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                    print(f"      ⚠️ 跳过 delete: {fp} (测试环境不支持删除)")
            
            print(f"   写入完成: {written_count} 个文件 (合并了 {len(merged_by_file)} 个文件的多项修改)")

            # 【修复1】写入沙箱前强制检查最终文件语法
            print("\n   🔍 最终语法检查（写入沙箱前）...")
            final_syntax_errors = []
            
            # 检查所有将要写入的文件
            files_to_check = []
            
            # 收集 modify 文件的最终内容
            for fp, changes in merged_by_file.items():
                read_r = await file_service.read_file(fp)
                if read_r.exists:
                    current_content = read_r.content
                    for fc in changes:
                        search_block = fc.get("search_block", "")
                        replace_block = fc.get("replace_block", "")
                        if search_block and search_block in current_content:
                            current_content = current_content.replace(search_block, replace_block, 1)
                        elif fc.get("content"):
                            current_content = fc.get("content")
                    files_to_check.append((fp, current_content))
            
            # 收集 add 文件的内容
            for fc in add_files:
                fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                content = fc.get("content", "")
                if content:
                    files_to_check.append((fp, content))
            
            # 使用 py_compile 检查语法
            code_files_to_check = [
                {"file_path": fp, "change_type": "add", "content": content}
                for fp, content in files_to_check
            ]
            final_syntax_errors = await self._check_syntax_with_py_compile(code_files_to_check, file_service)
            
            if final_syntax_errors:
                print(f"   ❌ 发现 {len(final_syntax_errors)} 个语法错误（写入前拦截）:")
                for err in final_syntax_errors:
                    print(f"      - {err['file']}: {err['error']} (line {err['line']})")
                
                # 【修复】调用 CoderAgent 自动修复语法错误
                print(f"\n   🔧 调用 CoderAgent 修复语法错误...")
                fixed_files = await self.auto_fix_syntax_errors(
                    syntax_errors=final_syntax_errors,
                    files_to_check=files_to_check,
                    file_service=file_service,
                    design_output=design_output,
                    max_retries=3
                )
                
                if not fixed_files:
                    raise RuntimeError(f"语法错误自动修复失败: {final_syntax_errors}")
                
                # 更新 code_files，用修复后的内容替换
                for fixed_fp, fixed_content in fixed_files.items():
                    # 更新 add_files 中的内容
                    for fc in add_files:
                        fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                        if fp == fixed_fp:
                            fc["content"] = fixed_content
                            print(f"      ✅ 已修复: {fp}")
                            break
                    # 更新 merged_by_file 中的内容（通过重新读取）
                    if fixed_fp in merged_by_file:
                        await file_service.write_file(fixed_fp, fixed_content)
                        print(f"      ✅ 已修复: {fixed_fp}")
            
            print(f"   ✅ 所有文件语法检查通过")

            # 【新增】写入沙箱后，对最终文件进行静态键名检查
            if coder_result.get("needs_post_check"):
                print("\n   🔍 静态键名检查（写入沙箱后）...")
                
                # 读取最终写入的文件内容
                final_files_content = {}
                for fc in code_files:
                    fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                    read_r = await file_service.read_file(fp)
                    if read_r.exists:
                        final_files_content[fp] = read_r.content
                
                if final_files_content:
                    # 使用 CoderAgent 的 _validate_return_keys 方法检查
                    from app.agents.coder import CoderAgent
                    temp_coder = CoderAgent()
                    
                    # 构建模拟的 output_files
                    final_output_files = [
                        {"file_path": fp, "change_type": "add", "content": content}
                        for fp, content in final_files_content.items()
                    ]
                    
                    key_mismatches = temp_coder._validate_return_keys(
                        final_output_files,
                        interface_specs,
                        final_files_content
                    )
                    
                    if key_mismatches:
                        print(f"   ❌ 发现 {len(key_mismatches)} 个键名不匹配:")
                        for mismatch in key_mismatches:
                            print(f"      - {mismatch['symbol']}: 缺少 {mismatch['missing_keys']}")
                        
                        # 重新发给 CoderAgent 修复
                        print(f"\n   🔧 重新发给 CoderAgent 修复键名不匹配...")
                        
                        fix_instruction = "修复返回字段缺失问题:\n\n"
                        for mismatch in key_mismatches:
                            symbol = mismatch.get('symbol', '')
                            missing = mismatch.get('missing_keys', [])
                            fix_instruction += f"- {symbol}: 缺少字段 {missing}\n"
                        
                        fix_instruction += """

【强制要求】
1. 读取沙箱中的当前文件内容
2. 在对应函数的返回字典中**追加**缺失的字段
3. 使用 change_type: "add" 输出完整文件内容覆盖
4. 确保所有缺失字段都已添加
"""
                        
                        retry_design_output = {
                            **design_output,
                            "fix_mode": True,
                            "fix_instruction": fix_instruction,
                            "affected_files": list(final_files_content.keys())
                        }
                        
                        retry_result = await coder_agent.generate_code(
                            design_output=retry_design_output,
                            pipeline_id=PIPELINE_ID,
                            injected_files=final_files_content
                        )
                        
                        if retry_result.get("success"):
                            # 应用修复
                            retry_output = retry_result.get("output", {})
                            if isinstance(retry_output, CoderOutput):
                                retry_files = [f.model_dump() for f in retry_output.files]
                            else:
                                retry_files = retry_output.get("files", [])
                            
                            for rfc in retry_files:
                                rfp = rfc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                                r_content = rfc.get("content", "")
                                if r_content:
                                    await file_service.write_file(rfp, r_content)
                                    print(f"      ✅ 已修复: {rfp}")
                            
                            # 重新检查
                            print(f"\n   🔍 重新检查键名匹配...")
                            final_files_content = {}
                            for fc in retry_files:
                                fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                                read_r = await file_service.read_file(fp)
                                if read_r.exists:
                                    final_files_content[fp] = read_r.content
                            
                            final_output_files = [
                                {"file_path": fp, "change_type": "add", "content": content}
                                for fp, content in final_files_content.items()
                            ]
                            
                            key_mismatches = temp_coder._validate_return_keys(
                                final_output_files,
                                interface_specs,
                                final_files_content
                            )
                            
                            if key_mismatches:
                                print(f"   ❌ 修复后仍有键名不匹配: {key_mismatches}")
                                raise RuntimeError(f"静态键名检查失败: {key_mismatches}")
                            else:
                                print(f"   ✅ 键名检查通过")
                        else:
                            raise RuntimeError(f"键名修复失败: {retry_result.get('error')}")
                    else:
                        print(f"   ✅ 静态键名检查通过")

            # ========== 前置契约检查（带自动修复） ==========
            print("\n🔍 前置契约检查...")
            missing_syms = await self.verify_contract(file_service, code_files, interface_specs)
            if missing_syms:
                print(f"   ❌ 契约检查失败，缺失符号 ({len(missing_syms)} 项):")
                for s in missing_syms[:5]:
                    print(f"      - {s}")
                if len(missing_syms) > 5:
                    print(f"      ... 还有 {len(missing_syms) - 5} 项")

                fixed, still_missing, fix_files = await self.auto_fix_contract(
                    missing_syms=missing_syms,
                    interface_specs=interface_specs,
                    design_output=design_output,
                    file_service=file_service,
                    max_retries=3
                )

                if not fixed:
                    print(f"   ❌ 契约自动修复失败，仍缺失 {len(still_missing)} 项: {still_missing}")
                    raise RuntimeError(f"Contract violation after auto-fix: {still_missing}")

                # 将补全的文件合并到 code_files
                code_files.extend(fix_files)
            print(f"   ✅ 契约检查通过（{len(interface_specs)} 个符号已实现）")

            # ========== Step 4: 测试文件已生成，直接使用 ==========
            print("\n🧪 Step 4: 使用 TesterAgent 生成的测试文件...")
            
            # 【修改】TesterAgent 已经生成完整测试，直接使用
            if not test_files:
                print("   ⚠️ 没有测试文件，跳过测试阶段")
                test_result = {"success": False, "error": "没有测试文件"}
            else:
                print(f"   使用 {len(test_files)} 个测试文件")
                test_result = test_result

            if not test_result.get("success"):
                error_msg = test_result.get("error", "测试生成失败")
                print(f"   ❌ TesterAgent 失败: {error_msg}")
                raise RuntimeError(f"Test generation failed: {error_msg}")

            # 获取生成的测试文件
            test_output = test_result.get("output", {})
            test_files = test_output.get("test_files", [])

            if not test_files:
                print("   ❌ TesterAgent 未生成测试文件")
                raise RuntimeError("TesterAgent did not generate any test files")

            # 写入生成的测试文件
            for test_file in test_files:
                file_path = test_file.get("file_path", "tests/unit/test_health.py")
                content = test_file.get("content", "")
                if content:
                    await file_service.write_file(file_path, content)
                    print(f"   已生成测试文件: {file_path} ({len(content)} 字符)")

            # 【新增】导入有效性检查：验证测试文件中的所有 import 是否真实存在
            print("\n   🔍 导入有效性检查（测试文件）...")
            import_errors = await self._validate_test_imports(test_files, file_service)
            if import_errors:
                print(f"   ❌ 发现 {len(import_errors)} 个导入错误:")
                for err in import_errors:
                    print(f"      - {err}")
                # 尝试修复导入错误
                print(f"   🔧 尝试修复导入错误...")
                fixed = await self._fix_test_imports(
                    test_files=test_files,
                    import_errors=import_errors,
                    file_service=file_service,
                    design_output=design_output,
                    code_output={"files": code_files}
                )
                if not fixed:
                    raise RuntimeError(f"导入错误无法修复: {import_errors}")
                print(f"   ✅ 导入错误已修复")
            else:
                print(f"   ✅ 所有导入检查通过")

            # 【新增】测试文件语法检查（使用 py_compile）
            print(f"\n   🔍 验证测试文件语法 (python -m py_compile)...")
            test_syntax_errors = await self._check_syntax_with_py_compile(
                [{"file_path": tf.get("file_path", ""), "change_type": "add", "content": tf.get("content", "")} for tf in test_files],
                file_service
            )
            
            if test_syntax_errors:
                print(f"   ❌ 发现 {len(test_syntax_errors)} 个测试文件语法错误，启动 TesterAgent 修复...")
                for err in test_syntax_errors:
                    print(f"      - {err['file']}: {err['error']}")
                
                # 使用 TesterAgent 修复测试语法错误
                fixed_test_files = await self._fix_test_syntax_errors(
                    test_files=test_files,
                    syntax_errors=test_syntax_errors,
                    file_service=file_service,
                    design_output=design_output,
                    code_output={"files": code_files}
                )
                
                if not fixed_test_files:
                    raise RuntimeError(f"测试文件语法错误无法修复: {test_syntax_errors}")
                
                # 更新 test_files
                test_files = fixed_test_files
                print(f"   ✅ 测试文件语法错误已修复")
            else:
                print(f"   ✅ 测试文件语法检查通过")

            # ========== Step 5: 【分层测试】运行测试 ==========
            print("\n🐳 Step 5: 在 Sandbox 中运行分层测试...")
            
            # 【复用】使用分层测试执行测试
            # 收集所有生成的文件（代码文件 + 测试文件）
            all_generated_files = []
            
            # 添加代码文件
            for f in code_files:
                all_generated_files.append({
                    "file_path": f.get("file_path", ""),
                    "content": f.get("content", ""),
                    "change_type": f.get("change_type", "modify")
                })
            
            # 添加测试文件
            for tf in test_files:
                all_generated_files.append({
                    "file_path": tf.get("file_path", ""),
                    "content": tf.get("content", ""),
                    "change_type": "add"
                })
            
            print(f"   共 {len(all_generated_files)} 个生成文件参与分层测试")
            
            layered_result = await self.run_tests_with_layered_runner(
                pipeline_id=PIPELINE_ID,
                generated_files=all_generated_files,
                file_service=file_service
            )
            
            print(f"\n   分层测试结果: {'✅ 全部通过' if layered_result.all_passed else '❌ 存在失败'}")

            # ========== Step 6: Auto-Fix + 智能错误路由 ==========
            if not layered_result.all_passed:
                print("\n🔧 启动 Auto-Fix（智能错误路由）...")
                max_retries = 3
                attempt = 1
                repair_result = None  # 【修复】初始化 repair_result
                
                while attempt <= max_retries and not layered_result.all_passed:
                    print(f"\n   🔄 第 {attempt}/{max_retries} 次修复")
                    
                    # 从分层结果中获取错误信息
                    logs = ""
                    failed_tests = []
                    error_type = None
                    for layer in layered_result.layers:
                        if not layer.passed and layer.logs:
                            logs = layer.logs
                            failed_tests = layer.failed_tests or []
                            error_type = layer.error_type
                            break
                    
                    # 【增强调试】打印测试失败日志
                    print(f"   📋 测试失败日志（前500字符）:")
                    print(f"   {logs[:500]}...")
                    print(f"   📋 失败测试数量: {len(failed_tests)}")
                    if failed_tests:
                        print(f"   📋 失败测试列表: {failed_tests[:3]}")  # 只显示前3个
                    
                    # 【智能错误路由】根据错误类型选择修复策略
                    print(f"   📊 错误类型分析: {error_type or 'unknown'}")
                    
                    # 分类错误
                    syntax_errors = self._extract_syntax_errors(logs)
                    import_errors = self._extract_import_errors(logs)
                    logic_errors = self._extract_logic_errors(logs, failed_tests)
                    type_errors_in_test = self._extract_type_errors_in_test(logs)  # 【新增】检测测试文件中的 TypeError
                    
                    print(f"   📊 提取到的错误: {len(syntax_errors)} 语法错误, {len(import_errors)} 导入错误, {len(logic_errors)} 逻辑错误, {len(type_errors_in_test)} 测试文件类型错误")
                    
                    fix_success = False
                    repair_result = None  # 每次循环重置
                    
                    # 路由 1: SyntaxError → 语法修复器
                    if syntax_errors:
                        print(f"   🎯 路由到 SyntaxFixer: {len(syntax_errors)} 个语法错误")
                        fix_success = await self._fix_syntax_errors(
                            syntax_errors=syntax_errors,
                            file_service=file_service,
                            code_files=code_files
                        )
                        repair_result = {"success": fix_success, "method": "SyntaxFixer"}
                    
                    # 路由 2: ImportError（测试文件）→ TesterAgent
                    elif import_errors and self._is_test_import_error(import_errors):
                        print(f"   🎯 路由到 TesterAgent: {len(import_errors)} 个测试导入错误")
                        fix_success = await self._fix_test_imports_v2(
                            import_errors=import_errors,
                            test_files=test_files,
                            file_service=file_service,
                            design_output=design_output,
                            code_output={"files": code_files}
                        )
                        repair_result = {"success": fix_success, "method": "TesterAgent"}
                    
                    # 【新增】路由 2.5: TypeError 在测试文件中 → TesterAgent 重新生成测试
                    elif type_errors_in_test:
                        print(f"   🎯 路由到 TesterAgent: {len(type_errors_in_test)} 个测试文件类型错误（如 datetime mock 错误）")
                        fix_success = await self._fix_test_type_errors(
                            type_errors=type_errors_in_test,
                            test_files=test_files,
                            file_service=file_service,
                            design_output=design_output,
                            code_output={"files": code_files}
                        )
                        repair_result = {"success": fix_success, "method": "TesterAgent"}
                    
                    # 路由 3: 代码逻辑错误 → RepairerAgent
                    else:
                        print(f"   🎯 路由到 RepairerAgent: 代码逻辑错误")
                        
                        # 解析缺失符号
                        missing = self.extract_missing_symbols(logs)
                        print(f"   提取的缺失符号: {missing}")
                        
                        fix_success, repair_result = await self._fix_with_repairer(
                            logs=logs,
                            failed_tests=failed_tests,
                            missing_symbols=missing,
                            file_service=file_service,
                            all_generated_files=all_generated_files
                        )
                        if repair_result is None:
                            repair_result = {"success": fix_success, "method": "RepairerAgent"}
                    
                    if not fix_success:
                        print("   ❌ 本轮修复失败")
                        break
                    
                    # 【DEBUG】打印修复结果详情
                    if repair_result:
                        print(f"   [DEBUG] 修复方法: {repair_result.get('method', 'unknown')}")
                        print(f"   [DEBUG] 修复结果: success={repair_result.get('success')}")
                        if 'keys' in dir(repair_result):
                            print(f"   [DEBUG] 修复结果 keys: {list(repair_result.keys())}")
                        if repair_result.get('error'):
                            print(f"   [DEBUG] 修复错误: {repair_result.get('error')}")
                        if repair_result.get('output'):
                            output = repair_result.get('output')
                            if isinstance(output, dict):
                                files = output.get('files', [])
                                print(f"   [DEBUG] 修复文件数量: {len(files)}")
                                for f in files[:3]:  # 只显示前3个
                                    print(f"   [DEBUG] 修复文件: {f.get('file_path')}, change_type={f.get('change_type')}")
                        if repair_result.get('note'):
                            print(f"   [DEBUG] 修复备注: {repair_result.get('note')}")
                        if repair_result.get('raw_output'):
                            print(f"   [DEBUG] 原始输出前500字符: {repair_result.get('raw_output')[:500]}")
                    
                    if not repair_result.get("success"):
                        print("   ❌ 修复失败")
                        break
                    
                    # 【增强】应用修复（仅 RepairerAgent 需要，其他路由已在内部应用）
                    if repair_result.get('method') == 'RepairerAgent' and repair_result.get("output"):
                        print("   📝 应用 RepairerAgent 修复...")
                        for fc in repair_result["output"].get("files", []):
                            fp = fc.get("file_path", "").replace("backend/", "").replace("backend\\", "")
                            search_block = fc.get("search_block", "")
                            replace_block = fc.get("replace_block", "")
                            if search_block:
                                read_r = await file_service.read_file(fp)
                            if read_r.exists:
                                new_content = read_r.content.replace(search_block, replace_block, 1)
                                await file_service.write_file(fp, new_content)
                    
                    # 重新运行分层测试
                    print(f"\n   🔄 重新运行分层测试...")
                    layered_result = await self.run_tests_with_layered_runner(
                        pipeline_id=PIPELINE_ID,
                        generated_files=all_generated_files,
                        file_service=file_service
                    )
                    
                    # 【增强】打印新的测试结果
                    print(f"   📊 修复后测试结果: {'✅ 通过' if layered_result.all_passed else '❌ 仍有失败'}")
                    if not layered_result.all_passed:
                        for layer in layered_result.layers:
                            if not layer.passed:
                                print(f"   ❌ 层 {layer.layer}: {len(layer.failed_tests)} 个失败")
                    
                    attempt += 1
                
                # 【逃生舱】如果达到最大重试次数仍然失败
                if attempt > max_retries and not layered_result.all_passed:
                    print(f"\n   🚨 逃生舱：已达到最大重试次数 ({max_retries})，停止修复")
                    print(f"   📝 最终失败日志:\n{logs[:2000]}...")
                    print(f"   ⚠️ 流程将继续，但测试可能不完整")

            duration = time.time() - start
            success = layered_result.all_passed if layered_result else False
            print(f"\n⏱️  总耗时 {duration:.1f}s")
            print("=" * 70)
            print(f"结果: {'✅ 成功' if success else '❌ 失败'}")
            print("=" * 70)
            return E2EContractResult(
                success=success,
                code_generated=len(code_files) > 0,
                tests_generated=True,
                tests_passed=success,
                layered_result=layered_result,
                duration_seconds=duration
            )
        finally:
            print("🧹 清理 Sandbox...")
            await cleanup_sandbox_orchestrator(PIPELINE_ID)


    # ========== 智能错误路由辅助方法 ==========
    
    def _extract_syntax_errors(self, logs: str) -> List[Dict]:
        """从日志中提取 SyntaxError"""
        import re
        errors = []
        # 匹配 SyntaxError 模式
        pattern = r'SyntaxError:\s*(.+?)(?:\n|$)'
        for match in re.finditer(pattern, logs, re.MULTILINE):
            errors.append({
                "type": "SyntaxError",
                "message": match.group(1).strip(),
                "line": 0  # 可能需要进一步解析
            })
        return errors
    
    def _extract_import_errors(self, logs: str) -> List[Dict]:
        """从日志中提取 ImportError"""
        import re
        errors = []
        # 匹配 ImportError/ModuleNotFoundError 模式
        patterns = [
            r'ImportError:\s*(.+?)(?:\n|$)',
            r'ModuleNotFoundError:\s*(.+?)(?:\n|$)',
            r'cannot import name [\'"](\w+)[\'"]',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, logs, re.MULTILINE):
                errors.append({
                    "type": "ImportError",
                    "message": match.group(0).strip(),
                    "symbol": match.group(1).strip() if match.lastindex >= 1 else None
                })
        return errors
    
    def _extract_logic_errors(self, logs: str, failed_tests: List[str]) -> List[Dict]:
        """从日志中提取代码逻辑错误"""
        errors = []
        # 失败的测试用例视为逻辑错误
        for test in failed_tests:
            errors.append({
                "type": "LogicError",
                "test": test
            })
        return errors
    
    def _is_test_import_error(self, import_errors: List[Dict]) -> bool:
        """判断导入错误是否来自测试文件"""
        # 简化判断：如果有导入错误，假设可能是测试文件的问题
        # 实际实现可能需要更复杂的逻辑
        return len(import_errors) > 0
    
    async def _fix_syntax_errors(
        self,
        syntax_errors: List[Dict],
        file_service,
        code_files: List[Dict]
    ) -> bool:
        """
        路由 1: SyntaxError → 语法修复器
        使用专门的语法修复逻辑，精准修复语法错误
        """
        print(f"   🔧 SyntaxFixer: 修复 {len(syntax_errors)} 个语法错误")
        # 这里可以调用专门的语法修复器
        # 暂时使用现有的 auto_fix_syntax_errors
        return await self.auto_fix_syntax_errors(
            syntax_errors=syntax_errors,
            file_service=file_service,
            design_output={},
            max_retries=2
        )
    
    async def _fix_test_imports_v2(
        self,
        import_errors: List[Dict],
        test_files: List[Dict],
        file_service,
        design_output: Dict,
        code_output: Dict
    ) -> bool:
        """
        路由 2: ImportError（测试文件）→ TesterAgent
        修复测试文件中的错误导入
        """
        print(f"   🔧 TesterAgent: 修复测试导入错误")
        return await self._fix_test_imports(
            test_files=test_files,
            import_errors=[e["message"] for e in import_errors],
            file_service=file_service,
            design_output=design_output,
            code_output=code_output,
            max_retries=2
        )
    
    def _extract_type_errors_in_test(self, logs: str) -> List[Dict]:
        """
        【新增】提取测试文件中的 TypeError（如 datetime mock 错误）
        """
        type_errors = []
        
        # 匹配 TypeError 行
        type_error_pattern = r'TypeError:\s*(.+?)(?:\n|$)'
        type_error_matches = re.findall(type_error_pattern, logs)
        
        for error_msg in type_error_matches:
            # 检查是否是测试文件中的错误
            # 查找错误前面的文件路径（通常是 test_*.py）
            # 简化处理：如果错误消息包含 datetime 相关的内容，认为是测试文件中的 mock 错误
            if 'datetime' in error_msg.lower() or 'utcnow' in error_msg.lower():
                type_errors.append({
                    "type": "TypeError",
                    "message": error_msg,
                    "file": "test_file",  # 简化标记
                    "is_test_file": True
                })
        
        return type_errors
    
    async def _fix_test_type_errors(
        self,
        type_errors: List[Dict],
        test_files: List[Dict],
        file_service,
        design_output: Dict,
        code_output: Dict
    ) -> bool:
        """
        【新增】路由 2.5: TypeError 在测试文件中 → TesterAgent
        修复测试文件中的类型错误（如 datetime mock 错误）
        """
        print(f"   🔧 TesterAgent: 修复测试类型错误（如 datetime mock）")
        
        from app.agents.tester import TesterAgent
        
        # 构建修复指令
        fix_instruction = """修复测试文件中的类型错误。

检测到的错误：
"""
        for err in type_errors:
            fix_instruction += f"- {err['message']}\n"
        
        fix_instruction += """

【重要修复要求】
1. 禁止直接 mock datetime.datetime.utcnow（datetime.datetime 是 C 扩展类型，不可变）
2. 使用以下正确方式之一：
   - 使用 freezegun 库: @freeze_time("2024-01-01")
   - 使用 unittest.mock.patch: with patch('datetime.datetime') as mock_dt:
   - 将 datetime 作为参数注入被测函数

3. 确保修复后的测试可以通过 python -m pytest 运行
4. 只修改测试文件，不要修改被测的源代码
"""
        
        # 调用 TesterAgent 重新生成测试
        tester_agent = TesterAgent()
        
        retry_result = await tester_agent.generate_tests(
            design_output={
                **design_output,
                "fix_mode": True,
                "fix_instruction": fix_instruction,
                "affected_files": [tf.get("file_path", "") for tf in test_files]
            },
            code_output=code_output,
            pipeline_id=PIPELINE_ID
        )
        
        if retry_result.get("success"):
            # 写入修复后的测试文件
            retry_output = retry_result.get("output", {})
            if isinstance(retry_output, dict):
                retry_files = retry_output.get("test_files", [])
            else:
                retry_files = getattr(retry_output, "test_files", [])
            
            for tf in retry_files:
                fp = tf.get("file_path", "")
                content = tf.get("content", "")
                if content:
                    await file_service.write_file(fp, content)
                    print(f"      ✅ 已修复测试: {fp}")
            
            return True
        else:
            print(f"   ❌ TesterAgent 修复失败: {retry_result.get('error')}")
            return False
    
    async def _fix_with_repairer(
        self,
        logs: str,
        failed_tests: List[str],
        missing_symbols: List[str],
        file_service,
        all_generated_files: List[Dict]
    ) -> tuple[bool, Dict]:
        """
        路由 3: 代码逻辑错误 → RepairerAgentWithTools
        使用新版 RepairerAgentWithTools 修复代码逻辑错误（支持多轮对话和快速测试验证）

        Returns:
            (是否成功, 修复结果字典)
        """
        print(f"   🔧 RepairerAgentWithTools: 修复代码逻辑错误（支持多轮对话）")

        # 构建错误列表
        errors_list = []
        if missing_symbols:
            errors_list.append({
                "file_path": "app/api/v1/health.py",
                "line": 1,
                "severity": "critical",
                "summary": f"缺少必需的实现: {', '.join(missing_symbols)}",
                "detail": f"测试需要这些符号，但代码中未定义: {missing_symbols}",
                "fix_hint": f"请在 app/api/v1/health.py 中实现以下函数: {', '.join(missing_symbols)}"
            })

        # 构建修复工单
        fix_order = {
            "type": "fix_order",
            "category": "code_bug",
            "source": "VerifyAgent",
            "errors": errors_list,
            "failed_tests": failed_tests,
            "error_logs": logs[:3000] if logs else "",
            "error_snippet": logs[:2000] if logs else "",
            "generated_files": ["app/api/v1/health.py"],
            "fix_hint": "重点：确保实现所有接口契约中声明的函数。"
        }

        # 收集所有相关文件的完整内容
        # 包括：Coder 修改过的文件 + Tester 生成的测试文件
        target_files = {}

        # 从 all_generated_files 中提取文件内容
        for file_info in all_generated_files:
            file_path = file_info.get("file_path", "")
            content = file_info.get("content", "")
            if file_path and content:
                # 标准化路径
                clean_path = file_path.replace("backend/", "").replace("backend\\", "").lstrip("/")
                target_files[clean_path] = content
                print(f"      📄 准备传入 RepairerAgent: {clean_path} ({len(content)} 字符)")

        # 同时从沙箱读取当前文件内容（确保是最新的）
        files_to_read = set()
        for err in errors_list:
            fp = err.get("file_path", "")
            if fp:
                clean_fp = fp.replace("backend/", "").replace("backend\\", "").lstrip("/")
                files_to_read.add(clean_fp)

        # 添加 generated_files 中的文件
        for gf in fix_order.get("generated_files", []):
            clean_gf = gf.replace("backend/", "").replace("backend\\", "").lstrip("/")
            files_to_read.add(clean_gf)

        # 读取这些文件的最新内容
        for clean_path in files_to_read:
            if clean_path not in target_files:  # 避免覆盖 all_generated_files 中的内容
                read_res = await file_service.read_file(clean_path)
                if read_res.exists and read_res.content:
                    target_files[clean_path] = read_res.content
                    print(f"      📄 从沙箱读取: {clean_path} ({len(read_res.content)} 字符)")

        if not target_files:
            print(f"   ❌ 没有收集到任何文件内容，无法调用 RepairerAgent")
            return False, {"success": False, "error": "没有文件内容"}

        print(f"   📦 共传入 {len(target_files)} 个文件的完整内容给 RepairerAgentWithTools")

        # 使用新版 RepairerAgentWithTools，支持多轮对话和快速测试验证
        repairer = RepairerAgentWithTools()
        repair_result = await repairer.execute_with_tools(
            pipeline_id=PIPELINE_ID,
            stage_name="REPAIR",
            fix_order=fix_order,
            target_files=target_files,
            file_service=file_service,
            max_rounds=3  # 最多3轮修复
        )

        # 检查结果
        if repair_result.get("success"):
            output = repair_result.get("output", {})
            rounds = output.get("rounds", 1)
            print(f"   ✅ RepairerAgentWithTools 修复成功（共 {rounds} 轮）")
            # 打印修复的文件
            if isinstance(output, dict) and "files" in output:
                for fc in output["files"]:
                    fp = fc.get("file_path", "")
                    print(f"      📝 修复了: {fp}")
            return True, repair_result
        else:
            output = repair_result.get("output", {})
            rounds = output.get("rounds", 0)
            print(f"   ❌ RepairerAgentWithTools 修复失败（进行了 {rounds} 轮修复）: {repair_result.get('error')}")

        return False, repair_result


async def main():
    tester = ContractE2ETester()
    result = await tester.run()
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
