import { useState, useEffect } from 'react';
import { FileText, CheckCircle2, Clock, FolderTree, Target, ExternalLink, AlertCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { SimpleMarkdown } from '@components/Common/SimpleMarkdown';
import { apiGet } from '@utils/axios';

// ============================================
// 需求分析阶段面板 - 展示 ArchitectAgent 输出
// ============================================

interface RequirementPanelProps {
  outputData?: Record<string, unknown>;
}

// 【新增】检查文件是否存在
async function checkFileExists(filePath: string): Promise<boolean> {
  try {
    console.log(`[DEBUG] 检查文件是否存在: ${filePath}`);
    // 【修复】apiGet 返回的是业务数据（data.data），不是完整的响应对象
    // 如果请求成功，说明文件存在；如果请求失败（404），说明文件不存在
    const fileData = await apiGet<{path: string; name: string; content: string}>(
      `/workspace/files/content?path=${encodeURIComponent(filePath)}`
    );
    console.log(`[DEBUG] 文件 ${filePath} 存在，数据:`, fileData);
    // 如果成功获取到文件数据，说明文件存在
    return !!fileData && !!fileData.path;
  } catch (error) {
    // 404 错误表示文件不存在，其他错误也视为不存在
    console.log(`[DEBUG] 文件 ${filePath} 不存在或检查失败:`, error);
    return false;
  }
}

export function RequirementPanel({ outputData }: RequirementPanelProps) {
  // 【新增】跟踪文件存在状态
  const [fileExistence, setFileExistence] = useState<Record<string, boolean>>({});
  const [isCheckingFiles, setIsCheckingFiles] = useState(false);

  if (!outputData) {
    return (
      <div className="p-4 bg-bg-secondary rounded-xl text-text-tertiary text-sm">
        暂无需求分析数据
      </div>
    );
  }

  const featureDescription = outputData.feature_description as string | undefined;
  const acceptanceCriteria = outputData.acceptance_criteria as string[] | undefined;
  const affectedFiles = outputData.affected_files as string[] | undefined;
  const estimatedEffort = outputData.estimated_effort as string | undefined;
  const technicalDesign = outputData.technical_design as string | undefined;

  // 【新增】检查所有受影响文件的存在性
  useEffect(() => {
    if (affectedFiles && affectedFiles.length > 0) {
      setIsCheckingFiles(true);
      const checkFiles = async () => {
        const existence: Record<string, boolean> = {};
        for (const file of affectedFiles) {
          existence[file] = await checkFileExists(file);
        }
        setFileExistence(existence);
        setIsCheckingFiles(false);
      };
      checkFiles();
    }
  }, [affectedFiles]);

  return (
    <div className="space-y-6">
      {/* 功能描述 */}
      {featureDescription && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Target className="w-4 h-4 text-brand-primary" />
            功能描述
          </h4>
          <div className="p-4 bg-bg-secondary rounded-xl border border-border-default">
            <p className="text-sm text-text-secondary leading-relaxed">
              {featureDescription}
            </p>
          </div>
        </div>
      )}

      {/* 验收标准 */}
      {acceptanceCriteria && acceptanceCriteria.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-status-success" />
            验收标准 ({acceptanceCriteria.length} 条)
          </h4>
          <div className="space-y-2">
            {acceptanceCriteria.map((criteria, idx) => (
              <div
                key={idx}
                className="flex items-start gap-3 p-3 bg-status-success/5 border border-status-success/20 rounded-lg"
              >
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-status-success/10 text-status-success text-xs font-medium flex items-center justify-center">
                  {idx + 1}
                </span>
                <span className="text-sm text-text-secondary">{criteria}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 受影响文件 */}
      {affectedFiles && affectedFiles.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-brand-primary" />
            受影响文件 ({affectedFiles.length} 个)
            {isCheckingFiles && (
              <span className="text-xs text-text-tertiary">(检查中...)</span>
            )}
          </h4>
          <div className="p-3 bg-bg-secondary rounded-xl border border-border-default">
            <div className="space-y-1">
              {affectedFiles.map((file, idx) => {
                // 【修复】正确处理文件存在状态：true=存在, false=不存在, undefined=检查中
                const exists = fileExistence[file];
                const isChecking = exists === undefined;
                const isNewFile = exists === false;
                const isExisting = exists === true;

                return (
                  <div key={idx} className="flex items-center gap-2 group">
                    {isChecking ? (
                      // 检查中
                      <>
                        <span className="text-text-tertiary animate-pulse">•</span>
                        <span className="text-sm font-mono text-text-secondary truncate flex-1">
                          {file}
                        </span>
                        <span className="text-xs text-text-tertiary">检查中...</span>
                      </>
                    ) : isNewFile ? (
                      // 不存在的文件（将新建）
                      <>
                        <span className="text-status-success" title="将新建">+</span>
                        <span className="text-sm font-mono text-text-secondary truncate flex-1">
                          {file}
                        </span>
                        <span className="text-xs text-status-success bg-status-success/10 px-1.5 py-0.5 rounded">
                          新建
                        </span>
                      </>
                    ) : isExisting ? (
                      // 存在的文件（可点击链接）
                      <Link
                        to={`/console/workspace?file=${encodeURIComponent(file)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 text-sm font-mono text-text-secondary hover:text-brand-primary transition-colors flex-1"
                        title="在工作区看板中打开"
                      >
                        <span className="text-text-tertiary group-hover:text-brand-primary">•</span>
                        <span className="truncate flex-1">{file}</span>
                        <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity text-brand-primary" />
                      </Link>
                    ) : null}
                  </div>
                );
              })}
            </div>
            {/* 【新增】提示说明 */}
            <div className="mt-2 pt-2 border-t border-border-default flex items-center gap-4 text-xs text-text-tertiary">
              <span className="flex items-center gap-1">
                <span className="text-text-tertiary">•</span> 现有文件
              </span>
              <span className="flex items-center gap-1">
                <span className="text-status-success">+</span> 将新建
              </span>
            </div>
          </div>
        </div>
      )}

      {/* 工作量评估 */}
      {estimatedEffort && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <Clock className="w-4 h-4 text-status-warning" />
            工作量评估
          </h4>
          <div className="p-3 bg-status-warning/5 border border-status-warning/20 rounded-lg">
            <span className="text-sm text-text-secondary">{estimatedEffort}</span>
          </div>
        </div>
      )}

      {/* 技术设计预览 */}
      {technicalDesign && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-text-primary flex items-center gap-2">
            <FileText className="w-4 h-4 text-brand-primary" />
            技术设计预览
          </h4>
          <div className="p-4 bg-bg-secondary rounded-xl border border-border-default max-h-64 overflow-y-auto">
            {/* 【修复】使用 SimpleMarkdown 渲染 Markdown 格式 */}
            <SimpleMarkdown
              content={technicalDesign.length > 1500 ? technicalDesign.slice(0, 1500) + '\n\n...' : technicalDesign}
            />
          </div>
        </div>
      )}
    </div>
  );
}
