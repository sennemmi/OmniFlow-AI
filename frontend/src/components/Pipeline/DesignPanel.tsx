import { Palette, Code2, FileSignature, GitCompare, AlertCircle } from 'lucide-react';

// ============================================
// 方案设计阶段面板 - 展示 DesignerAgent 输出
// ============================================

interface MockDependency {
  patch_target: string;
  mock_return_value: unknown;
  is_async: boolean;
  description?: string;
}

interface InterfaceSpec {
  symbol_name: string;
  signature: string;
  return_type: string;
  description?: string;
  mock_dependencies?: MockDependency[];
}

interface ApiEndpoint {
  method: string;
  path: string;
  description: string;
}

interface FunctionChange {
  file: string;
  function: string;
  action: 'add' | 'modify' | 'delete';
  description?: string;
}

interface DesignPanelProps {
  outputData?: Record<string, unknown>;
}

export function DesignPanel({ outputData }: DesignPanelProps) {
  if (!outputData) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无设计方案数据
      </div>
    );
  }

  const technicalDesign = outputData.technical_design as string | undefined;
  const apiEndpoints = outputData.api_endpoints as ApiEndpoint[] | undefined;
  const interfaceSpecs = outputData.interface_specs as InterfaceSpec[] | undefined;
  const functionChanges = outputData.function_changes as FunctionChange[] | undefined;
  const contractAlignment = outputData.contract_alignment as Array<{ acceptance_criteria: number; interface_spec: string }> | undefined;

  return (
    <div className="space-y-6">
      {/* 技术设计方案 */}
      {technicalDesign && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Palette className="w-4 h-4 text-brand-primary" />
            技术设计方案
          </h4>
          <div className="p-4 bg-bg-secondary rounded-xl border border-border-default max-h-64 overflow-y-auto">
            <pre className="text-sm text-text-secondary whitespace-pre-wrap font-mono leading-relaxed">
              {technicalDesign}
            </pre>
          </div>
        </div>
      )}

      {/* API 端点清单 */}
      {apiEndpoints && apiEndpoints.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Code2 className="w-4 h-4 text-status-success" />
            API 端点 ({apiEndpoints.length} 个)
          </h4>
          <div className="overflow-hidden rounded-xl border border-border-default">
            <table className="w-full text-sm">
              <thead className="bg-bg-secondary">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-text-tertiary">方法</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-text-tertiary">路径</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-text-tertiary">描述</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-default">
                {apiEndpoints.map((endpoint, idx) => (
                  <tr key={idx} className="bg-bg-primary">
                    <td className="px-4 py-2">
                      <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                        endpoint.method === 'GET' ? 'bg-blue-100 text-blue-700' :
                        endpoint.method === 'POST' ? 'bg-green-100 text-green-700' :
                        endpoint.method === 'PUT' ? 'bg-yellow-100 text-yellow-700' :
                        endpoint.method === 'DELETE' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-700'
                      }`}>
                        {endpoint.method}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono text-text-secondary">{endpoint.path}</td>
                    <td className="px-4 py-2 text-text-secondary">{endpoint.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 接口契约 */}
      {interfaceSpecs && interfaceSpecs.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <FileSignature className="w-4 h-4 text-brand-primary" />
            接口契约 ({interfaceSpecs.length} 个)
          </h4>
          <div className="space-y-2">
            {interfaceSpecs.map((spec, idx) => (
              <div
                key={idx}
                className="p-3 bg-bg-secondary rounded-lg border border-border-default"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-brand-primary">
                        {spec.symbol_name}
                      </span>
                      <span className="text-xs text-text-tertiary">→ {spec.return_type}</span>
                    </div>
                    <code className="block text-xs font-mono text-text-secondary bg-bg-tertiary px-2 py-1 rounded">
                      {spec.signature}
                    </code>
                    {spec.description && (
                      <p className="mt-2 text-xs text-text-tertiary">{spec.description}</p>
                    )}
                  </div>
                </div>
                {spec.mock_dependencies && spec.mock_dependencies.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {spec.mock_dependencies.map((dep, depIdx) => (
                      <span
                        key={depIdx}
                        className="inline-flex px-2 py-0.5 bg-status-warning/10 text-status-warning text-xs rounded"
                        title={dep.description || dep.patch_target}
                      >
                        mock: {dep.patch_target}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 契约对齐检查 */}
      {contractAlignment && contractAlignment.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <GitCompare className="w-4 h-4 text-brand-primary" />
            契约对齐 ({contractAlignment.length} 条)
          </h4>
          <div className="p-3 bg-bg-secondary rounded-xl border border-border-default">
            <div className="space-y-1">
              {contractAlignment.map((alignment, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-2 text-sm"
                >
                  <span className="text-xs text-text-tertiary">验收标准 #{alignment.acceptance_criteria}</span>
                  <span className="text-text-tertiary">→</span>
                  <code className="text-xs font-mono text-brand-primary">{alignment.interface_spec}</code>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 改动函数列表 */}
      {functionChanges && functionChanges.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-status-warning" />
            改动函数 ({functionChanges.length} 个)
          </h4>
          <div className="space-y-2">
            {functionChanges.map((change, idx) => (
              <div
                key={idx}
                className="p-3 bg-bg-secondary rounded-lg border border-border-default"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                    change.action === 'add' ? 'bg-status-success/10 text-status-success' :
                    change.action === 'delete' ? 'bg-status-error/10 text-status-error' :
                    'bg-status-warning/10 text-status-warning'
                  }`}>
                    {change.action === 'add' ? '新增' : change.action === 'delete' ? '删除' : '修改'}
                  </span>
                  <code className="text-xs font-mono text-text-secondary">{change.file}</code>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-tertiary">函数:</span>
                  <span className="text-xs font-medium text-text-primary">{change.function}</span>
                </div>
                {change.description && (
                  <p className="mt-1 text-xs text-text-tertiary">{change.description}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
