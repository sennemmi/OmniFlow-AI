// 格式化工具函数

// 从文件路径获取语言
export function getLanguageFromPath(filePath: string): string {
  const ext = filePath.split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    py: 'python', ts: 'typescript', tsx: 'typescript',
    js: 'javascript', jsx: 'javascript', css: 'css',
    json: 'json', md: 'markdown', yaml: 'yaml', yml: 'yaml',
    html: 'html', sql: 'sql', sh: 'shell',
  };
  return map[ext ?? ''] ?? 'plaintext';
}

// 获取 HTTP 方法徽章
export function getMethodBadge(method: string): string {
  const badges: Record<string, string> = {
    'GET': 'GET',
    'POST': 'POST',
    'PUT': 'PUT',
    'PATCH': 'PATCH',
    'DELETE': 'DELETE',
  };
  return badges[method.toUpperCase()] || method;
}

// 获取操作表情
export function getActionEmoji(action: string): string {
  const emojis: Record<string, string> = {
    'add': '[+]',
    'create': '[+]',
    'modify': '[~]',
    'update': '[~]',
    'delete': '[-]',
    'remove': '[-]',
  };
  return emojis[action.toLowerCase()] || '[~]';
}

// 将 DESIGN 阶段的 JSON 结构格式化为美观的 Markdown
export function formatDesignToMarkdown(output: Record<string, any>): string {
  const sections: string[] = [];

  // 标题
  sections.push('# 技术设计方案\n');

  // 功能描述
  if (output.feature_description) {
    sections.push(`## 功能描述\n${output.feature_description}\n`);
  }

  // 架构设计
  if (output.technical_design) {
    sections.push(`## 架构设计\n${output.technical_design}\n`);
  }

  // API 端点设计
  if (output.api_endpoints && Array.isArray(output.api_endpoints) && output.api_endpoints.length > 0) {
    sections.push('## API 设计\n');
    output.api_endpoints.forEach((api: any, index: number) => {
      const method = api.method || 'GET';
      const path = api.path || '/';
      const description = api.description || '暂无描述';
      const methodBadge = getMethodBadge(method);
      sections.push(`${index + 1}. ${methodBadge} \`${path}\``);
      sections.push(`   - **描述**: ${description}`);
      if (api.request_body) {
        sections.push(`   - **请求体**: \`${JSON.stringify(api.request_body)}\``);
      }
      if (api.response) {
        sections.push(`   - **响应**: \`${JSON.stringify(api.response)}\``);
      }
      sections.push('');
    });
  }

  // 函数变更
  if (output.function_changes && Array.isArray(output.function_changes) && output.function_changes.length > 0) {
    sections.push('## 函数变更\n');
    output.function_changes.forEach((func: any, index: number) => {
      const action = func.action || 'modify';
      const file = func.file || 'unknown';
      const funcName = func.function || 'unknown';
      const description = func.description || '暂无描述';
      const actionEmoji = getActionEmoji(action);
      sections.push(`${index + 1}. ${actionEmoji} **${file}** -> \`${funcName}\``);
      sections.push(`   - ${description}`);
      sections.push('');
    });
  }

  // 数据模型变更
  if (output.data_model_changes && Array.isArray(output.data_model_changes) && output.data_model_changes.length > 0) {
    sections.push('## 数据模型变更\n');
    output.data_model_changes.forEach((model: any, index: number) => {
      const action = model.action || 'modify';
      const entity = model.entity || 'unknown';
      const actionEmoji = getActionEmoji(action);
      sections.push(`${index + 1}. ${actionEmoji} **${entity}**`);
      if (model.fields && Array.isArray(model.fields)) {
        model.fields.forEach((field: any) => {
          sections.push(`   - \`${field.name}\`: ${field.type}${field.required ? ' (必填)' : ''}`);
        });
      }
      sections.push('');
    });
  }

  // 逻辑流
  if (output.logic_flow) {
    sections.push('## 逻辑流\n');
    sections.push('```');
    sections.push(output.logic_flow);
    sections.push('```\n');
  }

  // 依赖变更
  if (output.dependencies && Array.isArray(output.dependencies) && output.dependencies.length > 0) {
    sections.push('## 依赖变更\n');
    output.dependencies.forEach((dep: string) => {
      sections.push(`- \`${dep}\``);
    });
    sections.push('');
  }

  // 预估工作量
  if (output.estimated_effort) {
    sections.push(`## 预估工作量\n⏱️ ${output.estimated_effort}\n`);
  }

  // 受影响文件
  if (output.affected_files && Array.isArray(output.affected_files) && output.affected_files.length > 0) {
    sections.push('## 受影响文件\n');
    output.affected_files.forEach((file: string) => {
      sections.push(`- \`${file}\``);
    });
    sections.push('');
  }

  return sections.length > 1 ? sections.join('\n') : JSON.stringify(output, null, 2);
}

// 从 stage output_data 中提取技术设计文档
export function extractTechnicalDesign(stage: any): string | null {
  const output = stage?.output_data as Record<string, any> | undefined;
  if (!output) return null;

  // 针对 REQUIREMENT 阶段
  if (stage.name === 'REQUIREMENT' || stage.name === '需求分析') {
    return output.technical_design || output.feature_description || null;
  }

  // 针对 DESIGN 阶段 (将 JSON 结构转化为可读的 Markdown)
  if (stage.name === 'DESIGN' || stage.name === '技术设计') {
    return formatDesignToMarkdown(output);
  }

  return null;
}
