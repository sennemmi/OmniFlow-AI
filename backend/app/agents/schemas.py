"""
Agent 输出模型基类
统一所有 Agent 的输出结构
"""

from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, model_validator


class BaseAgentOutput(BaseModel):
    """
    Agent 输出基类
    
    所有 Agent 的输出模型必须继承此类
    包含通用的元数据字段
    """
    summary: str = Field(default="", description="执行摘要")
    dependencies_added: List[str] = Field(default_factory=list, description="新增依赖列表")
    input_tokens: int = Field(default=0, description="输入 Token 数")
    output_tokens: int = Field(default=0, description="输出 Token 数")
    duration_ms: int = Field(default=0, description="执行耗时(毫秒)")
    reasoning: Optional[str] = Field(default=None, description="模型推理过程")


class FileChange(BaseModel):
    """
    文件变更模型 - 支持搜索替换和行号两种格式

    采用 Claude Code 风格的搜索-替换块格式，比行号更稳定。
    同时保留行号格式作为向后兼容。
    """
    file_path: str = Field(description="文件相对路径")
    change_type: str = Field(description="变更类型: add | modify | delete")

    # 【搜索替换格式 - 推荐】
    search_block: Optional[str] = Field(None, description="精确要替换的旧代码块（搜索替换格式）")
    replace_block: Optional[str] = Field(None, description="新代码块")

    # 备用行号（当搜索块匹配失败时回退）
    fallback_start_line: Optional[int] = Field(None, description="备用起始行号")
    fallback_end_line: Optional[int] = Field(None, description="备用结束行号")

    # 【行号格式 - 向后兼容】
    start_line: Optional[int] = Field(None, description="起始行号(1-based, 包含)")
    end_line: Optional[int] = Field(None, description="结束行号(1-based, 包含)")

    # 仅用于新建文件 (change_type="add")
    content: Optional[str] = Field(None, description="完整文件内容（仅 add 时使用）")

    # 可选：用于验证的原始代码片段（帮助检测行号漂移）
    expected_original: Optional[str] = Field(None, description="预期被替换的原始代码片段（用于验证）")

    description: str = Field("", description="改动说明")


class SearchReplaceChange(BaseModel):
    """
    搜索替换变更模型 - Claude Code 风格

    基于精确搜索-替换块的方式，比行号更稳定，避免行号漂移问题。
    """
    file_path: str = Field(description="文件相对路径")
    change_type: str = Field(description="变更类型: add | modify | delete")

    # 用于 modify：搜索块和替换块
    search_block: Optional[str] = Field(None, description="精确要替换的旧代码块")
    replace_block: Optional[str] = Field(None, description="新代码块")

    # 用于 add：完整文件内容
    content: Optional[str] = Field(None, description="完整文件内容（仅 add 时使用）")

    # 通用的描述字段
    description: str = Field("", description="改动说明")

    # 可选的行号备用方案（当搜索块匹配失败时，回退到行号）
    fallback_start_line: Optional[int] = Field(None, description="备用起始行号")
    fallback_end_line: Optional[int] = Field(None, description="备用结束行号")


class TestFile(BaseModel):
    """测试文件模型"""
    file_path: str = Field(description="测试文件路径")
    content: str = Field(description="完整的测试文件内容")
    target_module: str = Field(description="被测试的模块路径")
    test_cases_count: int = Field(default=0, description="测试用例数量")


class RequiredSymbol(BaseModel):
    """
    必需实现的符号定义
    
    用于 ArchitectAgent 明确要求 DesignerAgent 必须实现的函数/类
    
    【契约流转说明】
    - return_fields: 定义返回值字段规范，与 InterfaceSpec.return_fields 格式一致
    - DesignerAgent 会将其转换为完整的 InterfaceSpec
    - CoderAgent 和 TesterAgent 基于 InterfaceSpec 进行验证
    """
    name: str = Field(description="符号名称（函数名或类名）")
    type: str = Field(description="符号类型：function/class/endpoint")
    module: str = Field(description="所在模块路径（如 app/service/health_service.py）")
    signature: Optional[str] = Field(default=None, description="函数签名或类定义（可选）")
    description: Optional[str] = Field(default=None, description="简短描述（可选）")
    return_fields: List["ReturnFieldSpec"] = Field(
        default_factory=list,
        description="【契约强制执行】返回值字段规范列表。如果函数返回 dict，必须列出所有键名及其类型。"
    )


class ArchitectOutput(BaseAgentOutput):
    """
    架构师 Agent 输出
    
    负责分析需求并输出技术设计方案
    """
    feature_description: str = Field(description="功能描述")
    affected_files: List[str] = Field(description="受影响文件列表")
    estimated_effort: str = Field(description="预估工作量")
    technical_design: Optional[str] = Field(default=None, description="技术设计方案")
    acceptance_criteria: List[str] = Field(default_factory=list, description="可验证的验收标准列表")
    required_symbols: List[RequiredSymbol] = Field(default_factory=list, description="必需实现的符号清单（强制 DesignerAgent 遵守）")


class APIEndpoint(BaseModel):
    """API 端点定义"""
    path: str = Field(description="API 路径")
    method: str = Field(description="HTTP 方法")
    description: str = Field(description="API 描述")
    request_body: Optional[str] = Field(default=None, description="请求体结构（JSON 字符串或描述）")
    response_fields: Optional[Union[str, Dict[str, Any]]] = Field(default=None, description="响应字段（JSON 字符串或字典）")


class ReturnFieldSpec(BaseModel):
    """
    返回字段规范
    
    用于定义函数返回对象的所有必填字段
    """
    name: str = Field(description="字段名称")
    type: str = Field(description="字段类型（如 str, int, dict, list）")
    description: Optional[str] = Field(default=None, description="字段描述")
    required: bool = Field(default=True, description="是否必填")
    location: Optional[str] = Field(default="data", description="字段位置：'data' 表示在 ResponseModel.data 内，'root' 表示在响应根层级")


class ErrorResponseSpec(BaseModel):
    """
    错误响应规范

    用于定义错误返回的格式，确保错误消息的一致性和可测试性
    【关键】避免测试中使用字符串精确匹配导致的脆弱断言
    """
    error_code: Optional[str] = Field(default=None, description="错误码（如 'SERVICE_UNAVAILABLE', 'VALIDATION_ERROR'）")
    message_format: Optional[str] = Field(default=None, description="错误消息格式模板（如 'Service unavailable: {reason}'）")
    message_contains: Optional[List[str]] = Field(default_factory=list, description="错误消息中必须包含的关键字列表（用于模糊匹配）")
    status_code: Optional[int] = Field(default=None, description="HTTP 状态码（如 503, 400）")

    class Config:
        """Pydantic V2 配置"""
        json_schema_extra = {
            "example": {
                "error_code": "SERVICE_UNAVAILABLE",
                "message_format": "Service unavailable: {reason}",
                "message_contains": ["unavailable", "service"],
                "status_code": 503
            }
        }


class MockDependencySpec(BaseModel):
    """
    Mock 依赖规范 —— 告诉 TesterAgent 需要 mock 哪些外部依赖

    DesignerAgent 必须列出所有 IO/系统调用依赖，否则测试会访问真实资源
    """
    patch_target: str = Field(
        description="完整 patch 路径，必须与被测模块的 import 方式一致。"
                    "如被测代码写 `import psutil`，则填 `app.service.health_service.psutil`；"
                    "如写 `from psutil import virtual_memory`，则填 `app.service.health_service.virtual_memory`"
    )
    mock_return_value: Optional[Any] = Field(
        default=None,
        description="默认 mock 返回值（happy path），如 {'percent': 30.0} 或 MagicMock(percent=30.0)"
    )
    is_async: bool = Field(
        default=False,
        description="被 mock 的目标是否是 async 函数，是则用 AsyncMock，否则用 MagicMock"
    )
    description: Optional[str] = Field(default=None, description="说明这个依赖的作用")


class InterfaceSpec(BaseModel):
    """
    接口契约规范

    用于定义代码-测试契约，确保 Coder 和 Tester 基于同一接口清单工作
    【运行时约束】如果函数返回 dict 或对象，必须明确声明所有必填字段
    """
    symbol_name: str = Field(description="函数/类名")
    module: str = Field(description="所在模块路径（如 app/api/v1/health.py）")
    signature: str = Field(description="函数签名或类定义（如 async def check() -> dict）")
    expected_behavior: str = Field(description="简短行为描述")
    is_async: bool = Field(default=False, description="是否为异步函数")
    return_type: str = Field(description="具体的返回类型描述。例如：ResponseModel(data包含status, cpu) 或 dict包含health_score, components")
    return_fields: List[ReturnFieldSpec] = Field(
        default_factory=list,
        description="【强制】返回对象的所有必填字段规范。如果返回 dict，必须列出所有键名。禁止为空列表！"
    )
    error_responses: List[ErrorResponseSpec] = Field(
        default_factory=list,
        description="【新增】错误响应规范列表，定义各种错误情况的返回格式，避免测试使用脆弱断言"
    )
    covers_criteria: List[int] = Field(default_factory=list, description="该接口覆盖的验收标准索引列表（从1开始）")

    # ✅ 新增：mock_dependencies 字段
    mock_dependencies: List[MockDependencySpec] = Field(
        default_factory=list,
        description="【新增】测试此符号时需要 mock 的外部依赖列表。"
                    "DesignerAgent 必须列出所有 IO/系统调用依赖，否则测试会访问真实资源"
    )

    @model_validator(mode='after')
    def validate_return_fields(self):
        """验证 return_fields 不为空（当返回类型为 dict 时）"""
        if self.return_type and 'dict' in self.return_type.lower():
            if not self.return_fields:
                raise ValueError(f"函数 {self.symbol_name} 返回类型为 dict，必须提供 return_fields 列表")
        return self


class CriteriaMapping(BaseModel):
    """
    验收标准与接口契约的映射关系
    
    用于强制对齐 ArchitectAgent 的验收标准和 DesignerAgent 的接口契约
    """
    criteria_index: int = Field(description="验收标准索引（从1开始）")
    criteria_description: str = Field(description="验收标准描述")
    covered_by: List[str] = Field(description="覆盖该标准的接口符号名称列表")
    mapping_reason: str = Field(description="映射理由：为什么这些接口能覆盖该验收标准")


class DesignerOutput(BaseAgentOutput):
    """
    设计师 Agent 输出
    
    负责输出详细的技术设计方案
    """
    technical_design: str = Field(description="技术设计方案概述")
    api_endpoints: List[Union[APIEndpoint, Dict[str, Any]]] = Field(default_factory=list, description="API 端点列表")
    function_changes: List[Dict[str, Any]] = Field(default_factory=list, description="函数修改列表")
    logic_flow: str = Field(default="", description="逻辑流图（文本描述）")
    affected_files: List[str] = Field(default_factory=list, description="受影响文件列表")
    interface_specs: List[InterfaceSpec] = Field(default_factory=list, description="接口契约清单（代码-测试契约）")
    criteria_mappings: List[CriteriaMapping] = Field(default_factory=list, description="验收标准与接口契约的映射关系（强制要求）")


class ContractAlignmentItem(BaseModel):
    """
    一条验收标准与接口契约的映射（Instructor 结构化输出用）
    
    这是强化版对齐映射，用于 Instructor 强制约束输出格式。
    """
    acceptance_criteria: str = Field(
        description="具体的验收标准原文（从 ArchitectAgent 的 acceptance_criteria 中复制）"
    )
    interface_specs: List[str] = Field(
        description="为实现该标准，需要实现的接口契约符号名称列表（必须在 interface_specs 中存在）"
    )
    mapping_reason: str = Field(
        description="映射理由：为什么这些接口能满足该验收标准（至少20字）",
        min_length=20
    )


class DesignerOutputV2(BaseModel):
    """
    设计师 Agent 输出 V2（Instructor 结构化约束版）
    
    使用 Instructor 库强制 LLM 输出符合此 Schema，从根本上杜绝格式随意性。
    与 DesignerOutput 的区别：
    1. 使用 contract_alignment 替代 criteria_mappings，结构更严格
    2. 每个字段都有详细的 description，指导 LLM 正确填充
    3. 在 API 层就验证必填字段，无需后续校验
    """
    
    technical_design: str = Field(
        description="技术设计方案概述，用2-3句话描述整体方案"
    )
    
    api_endpoints: List[APIEndpoint] = Field(
        default_factory=list,
        description="API 端点列表，包含 method, path, description 等"
    )
    
    function_changes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="函数修改列表，包含 file, function, action 等"
    )
    
    logic_flow: str = Field(
        default="",
        description="逻辑流图，用文本描述数据流向和处理步骤"
    )
    
    affected_files: List[str] = Field(
        default_factory=list,
        description="受影响文件列表（相对路径，如 app/api/v1/health.py）"
    )
    
    interface_specs: List[InterfaceSpec] = Field(
        default_factory=list,
        description="接口契约清单，每个契约包含 symbol_name, module, signature 等"
    )
    
    contract_alignment: List[ContractAlignmentItem] = Field(
        description="【强制】每一条验收标准必须在该列表中有对应条目，且每条验收标准必须映射到至少一个接口契约"
    )
    
    summary: str = Field(
        default="",
        description="变更摘要，一句话总结本次设计"
    )
    
    class Config:
        """Pydantic V2 配置"""
        json_schema_extra = {
            "example": {
                "technical_design": "实现系统健康检查功能，包括数据库、磁盘、内存状态监控",
                "api_endpoints": [
                    {
                        "path": "/api/v1/health",
                        "method": "GET",
                        "description": "获取系统健康状态"
                    }
                ],
                "interface_specs": [
                    {
                        "symbol_name": "health_check",
                        "module": "app/api/v1/health.py",
                        "signature": "async def health_check() -> dict",
                        "expected_behavior": "返回系统健康状态",
                        "is_async": True,
                        "return_type": "dict",
                        "covers_criteria": [1]
                    }
                ],
                "contract_alignment": [
                    {
                        "acceptance_criteria": "API 返回健康状态字段 overall_health",
                        "interface_specs": ["health_check"],
                        "mapping_reason": "health_check 函数返回的字典中包含 overall_health 字段，由 HealthService 计算得出"
                    }
                ],
                "summary": "添加系统健康检查接口"
            }
        }


class CoderOutput(BaseAgentOutput):
    """
    编码 Agent 输出
    
    负责生成代码变更
    """
    files: List[FileChange] = Field(default_factory=list, description="变更的文件列表")
    tests_included: bool = Field(default=False, description="是否包含测试代码")


class TesterOutput(BaseAgentOutput):
    """
    测试 Agent 输出

    负责生成单元测试代码
    """
    test_files: List[TestFile] = Field(default_factory=list, description="测试文件列表")
    coverage_targets: List[str] = Field(default_factory=list, description="计划覆盖的测试目标")


class ReviewIssue(BaseModel):
    """
    代码审查问题项

    描述代码中的具体问题，包含分类、严重性和修复建议
    """
    description: str = Field(description="问题描述")
    category: str = Field(description="问题分类: bug/security/performance/style/maintainability")
    severity: str = Field(description="严重性级别: critical/high/medium/low")
    file_path: Optional[str] = Field(default=None, description="问题所在文件路径")
    line_number: Optional[int] = Field(default=None, description="问题所在行号")
    suggestion: str = Field(description="具体的修复建议")
    code_snippet: Optional[str] = Field(default=None, description="相关代码片段")


class ReviewReport(BaseModel):
    """
    代码审查报告

    CodeReviewerAgent 的输出模型，包含完整的问题列表和总体评估
    """
    issues: List[ReviewIssue] = Field(default_factory=list, description="问题列表")
    overall_assessment: str = Field(description="总体评估摘要")
    summary: str = Field(default="", description="执行摘要")
    improvement_suggestions: List[str] = Field(default_factory=list, description="改进建议列表")
    risk_level: str = Field(default="low", description="风险等级: low/medium/high/critical")
    approval_recommendation: str = Field(default="approve", description="审批建议: approve/approve_with_caution/reject")


class CodeReviewerOutput(BaseAgentOutput):
    """
    代码审查 Agent 输出

    负责分析代码变更并生成审查报告
    """
    review_report: ReviewReport = Field(description="代码审查报告")
