"""
PR 描述生成服务
负责生成语义化的 Pull Request 描述
"""

from typing import Dict, Any, List

from app.service.git_provider import GitProviderService


class PRGeneratorService:
    """
    PR 描述生成服务
    
    职责：
    1. 根据多 Agent 输出生成 PR 描述
    2. 格式化文件变更列表
    3. 生成测试建议和依赖变更提示
    """
    
    @classmethod
    async def generate_pr_description(
        cls,
        pipeline_id: int,
        multi_agent_output: Dict[str, Any],
        execution_summary: Dict[str, Any],
        git_service: GitProviderService
    ) -> str:
        """
        生成语义化的 PR 描述（支持多 Agent 输出）
        
        包含：
        1. 修改了哪些文件（代码 + 测试）
        2. 核心逻辑变动
        3. 测试覆盖情况
        4. 测试建议
        
        Args:
            pipeline_id: Pipeline ID
            multi_agent_output: 多 Agent 协调器输出
            execution_summary: 代码执行摘要
            git_service: Git 服务实例
            
        Returns:
            str: PR 描述文本
        """
        # 获取文件变更列表
        files_changed = []
        test_files = []
        
        if "files" in multi_agent_output:
            for file_change in multi_agent_output["files"]:
                file_info = {
                    "path": file_change.get("file_path", ""),
                    "type": file_change.get("change_type", "modify"),
                    "description": file_change.get("description", "")
                }
                # 区分代码文件和测试文件
                if "test" in file_info["path"].lower() or file_info["path"].startswith("tests/"):
                    test_files.append(file_info)
                else:
                    files_changed.append(file_info)
        
        # 获取 diff 统计
        diff_stat = git_service.create_commit_summary()
        
        # 构建 PR 描述
        lines = [
            f"## OmniFlowAI 自动生成的 PR",
            "",
            f"**Pipeline ID**: #{pipeline_id}",
            "",
            "### 变更摘要",
            f"{multi_agent_output.get('summary', '无描述')}",
            "",
            "### 代码文件",
        ]
        
        # 添加代码文件列表
        if files_changed:
            for f in files_changed:
                type_emoji = {"add": "[+]", "modify": "[~]", "delete": "[-]"}.get(f["type"], "[~]")
                lines.append(f"- {type_emoji} `{f['path']}` - {f['description'] or '代码变更'}")
        else:
            lines.append("- 无代码文件变更")
        
        # 添加测试文件列表
        lines.append("")
        lines.append("### 测试文件")
        if test_files:
            for f in test_files:
                type_emoji = {"add": "[+]", "modify": "[~]", "delete": "[-]"}.get(f["type"], "[~]")
                lines.append(f"- {type_emoji} `{f['path']}` - {f['description'] or '测试代码'}")
        else:
            lines.append("- 无测试文件")
        
        # 添加统计信息
        lines.extend([
            "",
            "### 变更统计",
            f"- 成功写入: {execution_summary.get('success', 0)} 个文件",
            f"- 失败: {execution_summary.get('failed', 0)} 个文件",
            f"- 总计: {execution_summary.get('total', 0)} 个文件",
        ])
        
        # 添加测试建议
        tests_included = multi_agent_output.get("tests_included", False)
        coverage_targets = multi_agent_output.get("coverage_targets", [])
        dependencies = multi_agent_output.get("dependencies_added", [])
        
        lines.extend([
            "",
            "### 测试覆盖",
        ])
        
        if tests_included and test_files:
            lines.append("[OK] 本次变更已包含测试代码")
            
            # 添加测试覆盖目标
            if coverage_targets:
                lines.append("")
                lines.append("**测试覆盖目标：**")
                for target in coverage_targets:
                    lines.append(f"- {target}")
            
            lines.append("")
            lines.append("**运行测试：**")
            lines.append("```bash")
            lines.append("# 运行所有测试")
            lines.append("pytest")
            lines.append("")
            lines.append("# 运行特定测试文件")
            for tf in test_files:
                lines.append(f"pytest {tf['path']}")
            lines.append("```")
        else:
            lines.append("[WARN] 本次变更未包含测试代码，建议进行以下验证：")
            lines.append("1. 手动测试相关功能")
            lines.append("2. 检查边界条件处理")
            lines.append("3. 验证错误处理逻辑")
        
        # 添加依赖变更提示
        if dependencies:
            lines.extend([
                "",
                "### 新增依赖",
                "以下依赖需要安装：",
            ])
            for dep in dependencies:
                lines.append(f"- `{dep}`")
            lines.extend([
                "",
                "```bash",
                "# 安装依赖",
                f"pip install {' '.join(dependencies)}",
                "```"
            ])
        
        # 添加审查清单
        lines.extend([
            "",
            "---",
            "",
            "### 审查清单",
            "- [ ] 代码符合项目规范",
            "- [ ] 功能符合需求描述",
            "- [ ] 错误处理完善",
            "- [ ] 无安全隐患",
            "",
            "*此 PR 由 OmniFlowAI 自动生成* [BOT]"
        ])
        
        return "\n".join(lines)
