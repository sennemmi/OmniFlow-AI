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

