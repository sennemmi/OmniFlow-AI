import type { Pipeline, PipelineStage } from '@types';

// ============================================
// Pipeline 报告导出工具 - 生成结构化 Markdown 文档
// ============================================

/**
 * 构建 Pipeline 报告 Markdown 内容
 */
export function buildMarkdownFromPipeline(pipeline: Pipeline): string {
  const sections: string[] = [];

  // 报告标题
  sections.push(`# OmniFlowAI Pipeline 报告 #${pipeline.id}\n`);
  sections.push(`> 生成时间: ${new Date().toLocaleString('zh-CN')}\n`);
  sections.push(`> 状态: ${getStatusBadge(pipeline.status)}\n`);

  // 1. 需求概述
  const requirementStage = findStage(pipeline, 'REQUIREMENT');
  if (requirementStage?.output_data) {
    sections.push(buildRequirementSection(requirementStage.output_data));
  }

  // 2. 架构师分析
  sections.push(buildArchitectSection(requirementStage?.output_data));

  // 3. 技术设计方案
  const designStage = findStage(pipeline, 'DESIGN');
  if (designStage?.output_data) {
    sections.push(buildDesignSection(designStage.output_data));
  }

  // 4. 代码变更
  const codingStage = findStage(pipeline, 'CODING');
  if (codingStage?.output_data) {
    sections.push(buildCodingSection(codingStage.output_data));
  }

  // 5. 测试结果
  const testingStage = findStage(pipeline, 'UNIT_TESTING');
  if (testingStage?.output_data) {
    sections.push(buildTestingSection(testingStage.output_data));
  }

  // 6. 交付信息
  const deliveryStage = findStage(pipeline, 'DELIVERY');
  if (deliveryStage?.output_data) {
    sections.push(buildDeliverySection(deliveryStage.output_data));
  }

  // 7. 执行统计
  sections.push(buildStatisticsSection(pipeline));

  return sections.join('\n');
}

/**
 * 查找指定阶段的输出数据
 */
function findStage(pipeline: Pipeline, stageName: string): PipelineStage | undefined {
  return pipeline.stages?.find(s => s.name === stageName);
}

/**
 * 获取状态徽章文本
 */
function getStatusBadge(status: string): string {
  const statusMap: Record<string, string> = {
    'running': '🟡 执行中',
    'paused': '🟠 等待审批',
    'success': '🟢 成功',
    'failed': '🔴 失败',
  };
  return statusMap[status] || status;
}

/**
 * 构建需求概述部分
 */
function buildRequirementSection(outputData: Record<string, unknown>): string {
  const sections: string[] = [];
  sections.push('## 1. 需求概述\n');

  const description = outputData.feature_description as string;
  if (description) {
    sections.push(`${description}\n`);
  }

  return sections.join('');
}

/**
 * 构建架构师分析部分
 */
function buildArchitectSection(outputData?: Record<string, unknown>): string {
  const sections: string[] = [];
  sections.push('## 2. 架构师分析\n');

  if (!outputData) {
    sections.push('*暂无架构师分析数据*\n');
    return sections.join('');
  }

  // 2.1 验收标准
  const acceptanceCriteria = outputData.acceptance_criteria as string[] | undefined;
  if (acceptanceCriteria && acceptanceCriteria.length > 0) {
    sections.push('### 2.1 验收标准\n');
    acceptanceCriteria.forEach((criteria) => {
      sections.push(`- [x] ${criteria}`);
    });
    sections.push('');
  }

  // 2.2 受影响文件
  const affectedFiles = outputData.affected_files as string[] | undefined;
  if (affectedFiles && affectedFiles.length > 0) {
    sections.push('### 2.2 受影响文件\n');
    affectedFiles.forEach(file => {
      sections.push(`- \`${file}\``);
    });
    sections.push('');
  }

  // 2.3 工作量评估
  const estimatedEffort = outputData.estimated_effort as string | undefined;
  if (estimatedEffort) {
    sections.push('### 2.3 工作量评估\n');
    sections.push(`${estimatedEffort}\n`);
  }

  return sections.join('\n');
}

/**
 * 构建技术设计方案部分
 */
function buildDesignSection(outputData: Record<string, unknown>): string {
  const sections: string[] = [];
  sections.push('## 3. 技术设计方案\n');

  // 3.1 设计摘要
  const technicalDesign = outputData.technical_design as string | undefined;
  if (technicalDesign) {
    sections.push('### 3.1 设计摘要\n');
    sections.push('```\n' + technicalDesign + '\n```\n');
  }

  // 3.2 API 端点设计
  const apiEndpoints = outputData.api_endpoints as Array<{ method: string; path: string; description: string }> | undefined;
  if (apiEndpoints && apiEndpoints.length > 0) {
    sections.push('### 3.2 API 端点设计\n');
    sections.push('| Method | Path | Description |');
    sections.push('|--------|------|-------------|');
    apiEndpoints.forEach(endpoint => {
      sections.push(`| ${endpoint.method} | ${endpoint.path} | ${endpoint.description} |`);
    });
    sections.push('');
  }

  // 3.3 接口契约
  const interfaceSpecs = outputData.interface_specs as Array<{
    symbol_name: string;
    signature: string;
    return_type: string;
    description?: string;
  }> | undefined;
  if (interfaceSpecs && interfaceSpecs.length > 0) {
    sections.push('### 3.3 接口契约\n');
    interfaceSpecs.forEach((spec, idx) => {
      sections.push(`**${idx + 1}. ${spec.symbol_name}**`);
      sections.push(`- 签名: \`${spec.signature}\``);
      sections.push(`- 返回: \`${spec.return_type}\``);
      if (spec.description) {
        sections.push(`- 说明: ${spec.description}`);
      }
      sections.push('');
    });
  }

  return sections.join('\n');
}

/**
 * 构建代码变更部分
 */
function buildCodingSection(outputData: Record<string, unknown>): string {
  const sections: string[] = [];
  sections.push('## 4. 代码变更\n');

  // 4.1 变更摘要
  const summary = outputData.summary as string | undefined;
  const coderOutput = outputData.coder_output as Record<string, unknown> | undefined;
  if (summary || coderOutput?.summary) {
    sections.push('### 4.1 变更摘要\n');
    sections.push(`${summary || coderOutput?.summary}\n`);
  }

  // 4.2 文件清单
  const files = outputData.files as Array<{ file_path: string; content: string }> | undefined;
  const modifiedFiles = outputData.modified_files as Array<{ file_path: string; content: string }> | undefined;

  if ((files && files.length > 0) || (modifiedFiles && modifiedFiles.length > 0)) {
    sections.push('### 4.2 文件清单\n');

    if (files) {
      files.forEach(file => {
        sections.push(`- \`${file.file_path}\` (新增)`);
      });
    }

    if (modifiedFiles) {
      modifiedFiles.forEach(file => {
        sections.push(`- \`${file.file_path}\` (修改)`);
      });
    }
    sections.push('');
  }

  return sections.join('\n');
}

/**
 * 构建测试结果部分
 */
function buildTestingSection(outputData: Record<string, unknown>): string {
  const sections: string[] = [];
  sections.push('## 5. 测试结果\n');

  const testingResult = outputData.testing_result as Record<string, unknown> | undefined;
  if (testingResult) {
    const testGenerated = testingResult.test_generated as boolean;
    const testRunSuccess = testingResult.test_run_success as boolean;
    const overallSuccess = testingResult.overall_success as boolean | undefined;
    const testError = testingResult.test_error as string | undefined;
    const contractCheck = testingResult.contract_check as {
      passed: boolean;
      missing_symbols: string[];
      total_symbols: number;
    } | undefined;

    // 总体结果
    if (overallSuccess) {
      sections.push('✅ **契约检查通过且所有测试通过**\n');
    } else if (testRunSuccess) {
      sections.push('✅ **所有测试通过**\n');
    } else if (testGenerated) {
      sections.push('⚠️ **测试未通过**\n');
    } else {
      sections.push('❌ **未生成测试文件**\n');
    }

    // 契约检查结果
    if (contractCheck) {
      sections.push('### 契约检查\n');
      if (contractCheck.passed) {
        sections.push(`✅ **通过** (${contractCheck.total_symbols} 个符号已实现)\n`);
      } else {
        sections.push(`❌ **失败** (${contractCheck.missing_symbols.length}/${contractCheck.total_symbols} 个符号未实现)\n`);
        if (contractCheck.missing_symbols.length > 0) {
          sections.push('**未实现的符号：**\n');
          contractCheck.missing_symbols.forEach(sym => {
            sections.push(`- \`${sym}\``);
          });
          sections.push('');
        }
      }
    }

    // 分层测试结果
    const testRunLayers = testingResult.test_run_layers as Array<{
      layer: string;
      passed: boolean;
      summary: string;
    }> | undefined;
    if (testRunLayers && testRunLayers.length > 0) {
      sections.push('### 分层测试详情\n');
      sections.push('| 层级 | 状态 | 摘要 |');
      sections.push('|------|------|------|');
      testRunLayers.forEach(layer => {
        const status = layer.passed ? '✅ 通过' : '❌ 失败';
        sections.push(`| ${layer.layer} | ${status} | ${layer.summary} |`);
      });
      sections.push('');
    }

    if (testError) {
      sections.push('### 错误信息\n');
      sections.push('```\n' + testError + '\n```\n');
    }
  }

  // 【新增】AI 代码审查报告
  const reviewReport = outputData.review_report as {
    issues: Array<{
      severity: 'high' | 'medium' | 'low';
      category: string;
      description: string;
      suggestion: string;
      file_path?: string;
      line_number?: number;
    }>;
    overall_assessment: string;
    summary: string;
    improvement_suggestions: string[];
    risk_level: 'high' | 'medium' | 'low';
    approval_recommendation: 'approve' | 'approve_with_caution' | 'reject';
  } | undefined;

  if (reviewReport) {
    sections.push('### AI 代码审查报告\n');

    // 风险等级和审批建议
    const riskLevelText = reviewReport.risk_level === 'high' ? '🔴 高风险' :
                         reviewReport.risk_level === 'medium' ? '🟡 中风险' : '🟢 低风险';
    const approvalText = reviewReport.approval_recommendation === 'approve' ? '✅ 建议批准' :
                        reviewReport.approval_recommendation === 'approve_with_caution' ? '⚠️ 建议谨慎批准' : '❌ 建议拒绝';

    sections.push(`**风险等级**: ${riskLevelText}`);
    sections.push(`**审批建议**: ${approvalText}\n`);

    // 总体评估
    if (reviewReport.overall_assessment) {
      sections.push('**总体评估**:\n');
      sections.push(`${reviewReport.overall_assessment}\n`);
    }

    // 问题列表
    if (reviewReport.issues && reviewReport.issues.length > 0) {
      sections.push(`**发现问题** (${reviewReport.issues.length} 个):\n`);
      reviewReport.issues.forEach((issue, idx) => {
        const severityEmoji = issue.severity === 'high' ? '🔴' : issue.severity === 'medium' ? '🟡' : '🟢';
        const severityText = issue.severity === 'high' ? '高' : issue.severity === 'medium' ? '中' : '低';
        sections.push(`${idx + 1}. ${severityEmoji} **${issue.category}** (${severityText}优先级)`);
        sections.push(`   - 描述: ${issue.description}`);
        if (issue.suggestion) {
          sections.push(`   - 建议: ${issue.suggestion}`);
        }
        if (issue.file_path) {
          sections.push(`   - 文件: \`${issue.file_path}\`${issue.line_number ? `:${issue.line_number}` : ''}`);
        }
        sections.push('');
      });
    }

    // 改进建议
    if (reviewReport.improvement_suggestions && reviewReport.improvement_suggestions.length > 0) {
      sections.push('**改进建议**:\n');
      reviewReport.improvement_suggestions.forEach((suggestion, idx) => {
        sections.push(`${idx + 1}. ${suggestion}`);
      });
      sections.push('');
    }
  }

  // 测试文件列表
  const testFiles = outputData.test_files as Array<{ file_path: string; content: string }> | undefined;
  if (testFiles && testFiles.length > 0) {
    sections.push('### 测试文件\n');
    testFiles.forEach(file => {
      sections.push(`- \`${file.file_path}\``);
    });
    sections.push('');
  }

  return sections.join('\n');
}

/**
 * 构建交付信息部分
 */
function buildDeliverySection(outputData: Record<string, unknown>): string {
  const sections: string[] = [];
  sections.push('## 6. 交付信息\n');

  const gitBranch = outputData.git_branch as string | undefined;
  const commitHash = outputData.commit_hash as string | undefined;
  const prUrl = outputData.pr_url as string | undefined;
  const prCreated = outputData.pr_created as boolean | undefined;
  const executionSummary = outputData.execution_summary as { success: number; total: number } | undefined;

  if (gitBranch) {
    sections.push(`- **Branch**: \`${gitBranch}\``);
  }
  if (commitHash) {
    sections.push(`- **Commit**: \`${commitHash.slice(0, 8)}\``);
  }
  if (prUrl) {
    sections.push(`- **PR**: ${prUrl}`);
  }
  if (prCreated !== undefined) {
    sections.push(`- **PR 状态**: ${prCreated ? '✅ 创建成功' : '❌ 创建失败'}`);
  }
  if (executionSummary) {
    sections.push(`- **文件处理**: ${executionSummary.success}/${executionSummary.total} 成功`);
  }
  sections.push('');

  return sections.join('\n');
}

/**
 * 构建执行统计部分
 */
function buildStatisticsSection(pipeline: Pipeline): string {
  const sections: string[] = [];
  sections.push('## 7. 执行统计\n');

  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let totalDuration = 0;

  pipeline.stages?.forEach(stage => {
    totalInputTokens += stage.input_tokens || 0;
    totalOutputTokens += stage.output_tokens || 0;
    totalDuration += stage.duration_ms || 0;
  });

  // 总耗时
  const durationSec = Math.round(totalDuration / 1000);
  const minutes = Math.floor(durationSec / 60);
  const seconds = durationSec % 60;
  sections.push(`- **总耗时**: ${minutes}m ${seconds}s`);

  // Token 消耗
  sections.push(`- **Token 消耗**: ${totalInputTokens.toLocaleString()} input / ${totalOutputTokens.toLocaleString()} output`);

  // 各阶段详情
  sections.push('\n### 各阶段详情\n');
  sections.push('| 阶段 | 状态 | 耗时 | Input Tokens | Output Tokens |');
  sections.push('|------|------|------|--------------|---------------|');

  pipeline.stages?.forEach(stage => {
    const stageDuration = stage.duration_ms ? `${Math.round(stage.duration_ms / 1000)}s` : '-';
    sections.push(
      `| ${stage.name} | ${stage.status} | ${stageDuration} | ${(stage.input_tokens || 0).toLocaleString()} | ${(stage.output_tokens || 0).toLocaleString()} |`
    );
  });
  sections.push('');

  return sections.join('\n');
}

/**
 * 导出 Markdown 文件
 */
export function exportPipelineReport(pipeline: Pipeline): void {
  const markdown = buildMarkdownFromPipeline(pipeline);
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);

  const date = new Date().toISOString().split('T')[0];
  const filename = `Pipeline_${pipeline.id}_${date}.md`;

  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  URL.revokeObjectURL(url);
}
