import { useState, useCallback, useMemo } from 'react';
import Editor from '@monaco-editor/react';
import {
  Folder,
  FileCode,
  FileText,
  ChevronRight,
  ChevronDown,
  Search,
  RefreshCw,
  FolderOpen,
  File,
  Copy,
  Edit3,
  Check,
  X,
  Loader2,
  AlertCircle,
  Save,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from '@utils/axios';
import { useUIStore } from '@stores/uiStore';

// ============================================
// Workspace 文件资源管理器 - 使用 Monaco Editor
// ============================================

interface FileItem {
  id: string;
  name: string;
  type: 'file' | 'folder';
  path: string;
  size?: number;
  modified?: string;
  language?: string;
}

interface FileContent {
  path: string;
  name: string;
  content: string;
  size: number;
  language?: string;
}

// API 函数 - 拦截器已返回业务数据，直接使用
const fetchFiles = async (path: string = ''): Promise<FileItem[]> => {
  return apiGet(`/workspace/files?path=${encodeURIComponent(path)}`);
};

const fetchFileContent = async (path: string): Promise<FileContent> => {
  return apiGet(`/workspace/files/content?path=${encodeURIComponent(path)}`);
};

const saveFileContent = async ({ path, content }: { path: string; content: string }): Promise<void> => {
  return apiPost(`/workspace/files/content?path=${encodeURIComponent(path)}`, { content });
};

const fetchStats = async () => {
  return apiGet('/workspace/stats');
};

// 获取文件图标
const getFileIcon = (name: string, isOpen?: boolean) => {
  if (name.includes('.')) {
    const ext = name.split('.').pop()?.toLowerCase();
    if (ext === 'py') return <FileCode className="w-4 h-4 text-blue-500" />;
    if (ext === 'md' || ext === 'txt') return <FileText className="w-4 h-4 text-gray-500" />;
    if (ext === 'json') return <FileCode className="w-4 h-4 text-yellow-500" />;
    if (ext === 'yml' || ext === 'yaml') return <FileCode className="w-4 h-4 text-green-500" />;
    return <File className="w-4 h-4 text-gray-400" />;
  }
  return isOpen ? <FolderOpen className="w-4 h-4 text-yellow-500" /> : <Folder className="w-4 h-4 text-yellow-500" />;
};

// 获取 Monaco Editor 语言
const getMonacoLanguage = (filename: string): string => {
  const ext = filename.split('.').pop()?.toLowerCase();
  const langMap: Record<string, string> = {
    py: 'python',
    js: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    jsx: 'javascript',
    json: 'json',
    md: 'markdown',
    yaml: 'yaml',
    yml: 'yaml',
    html: 'html',
    css: 'css',
    scss: 'scss',
    sql: 'sql',
    sh: 'shell',
    dockerfile: 'dockerfile',
  };
  return langMap[ext || ''] || 'plaintext';
};

// 格式化文件大小
const formatSize = (bytes?: number): string => {
  if (!bytes) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export function Workspace() {
  const [currentPath, setCurrentPath] = useState('');
  const [selectedFile, setSelectedFile] = useState<FileItem | null>(null);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(['']));
  const [searchQuery, setSearchQuery] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState('');
  const { addToast } = useUIStore();
  const queryClient = useQueryClient();

  // 获取文件列表
  const { data: files, isLoading: isLoadingFiles, error: filesError, refetch: refetchFiles } = useQuery({
    queryKey: ['workspace-files', currentPath],
    queryFn: () => fetchFiles(currentPath),
  });

  // 获取文件内容
  const { data: fileContent, isLoading: isLoadingContent } = useQuery({
    queryKey: ['workspace-content', selectedFile?.path],
    queryFn: () => fetchFileContent(selectedFile!.path),
    enabled: !!selectedFile && selectedFile.type === 'file',
  });

  // 获取统计
  const { data: stats } = useQuery({
    queryKey: ['workspace-stats'],
    queryFn: fetchStats,
  });

  // 保存文件
  const saveMutation = useMutation({
    mutationFn: saveFileContent,
    onSuccess: () => {
      addToast({ message: '文件保存成功', type: 'success' });
      setIsEditing(false);
      queryClient.invalidateQueries({ queryKey: ['workspace-content', selectedFile?.path] });
    },
    onError: (error: Error) => {
      addToast({ message: `保存失败: ${error.message}`, type: 'error' });
    },
  });

  // 切换文件夹
  const toggleFolder = useCallback((path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  // 进入文件夹
  const enterFolder = useCallback((folder: FileItem) => {
    if (folder.type === 'folder') {
      setCurrentPath(folder.path);
      setSelectedFile(null);
      setIsEditing(false);
    }
  }, []);

  // 返回上级
  const goBack = useCallback(() => {
    const parentPath = currentPath.includes('/') 
      ? currentPath.substring(0, currentPath.lastIndexOf('/'))
      : '';
    setCurrentPath(parentPath);
    setSelectedFile(null);
    setIsEditing(false);
  }, [currentPath]);

  // 选择文件
  const selectFile = useCallback((file: FileItem) => {
    if (file.type === 'file') {
      setSelectedFile(file);
      setIsEditing(false);
    } else {
      enterFolder(file);
    }
  }, [enterFolder]);

  // 开始编辑
  const startEditing = useCallback(() => {
    if (fileContent) {
      setEditedContent(fileContent.content);
      setIsEditing(true);
    }
  }, [fileContent]);

  // 保存编辑
  const handleSave = useCallback(() => {
    if (selectedFile) {
      saveMutation.mutate({ path: selectedFile.path, content: editedContent });
    }
  }, [selectedFile, editedContent, saveMutation]);

  // 复制内容
  const copyContent = useCallback(() => {
    if (fileContent) {
      navigator.clipboard.writeText(fileContent.content);
      addToast({ message: '已复制到剪贴板', type: 'success' });
    }
  }, [fileContent, addToast]);

  // 过滤文件
  const filteredFiles = useMemo(() => {
    if (!files || !searchQuery) return files;
    return files.filter(f => f.name.toLowerCase().includes(searchQuery.toLowerCase()));
  }, [files, searchQuery]);

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col">
      {/* 顶部工具栏 */}
      <div className="flex items-center justify-between px-4 py-3 bg-bg-primary border-b border-border-default">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold text-text-primary">工作区</h1>
          <div className="flex items-center gap-2">
            {currentPath && (
              <button 
                onClick={goBack}
                className="p-1.5 hover:bg-bg-secondary rounded-lg transition-colors"
              >
                <ChevronRight className="w-4 h-4 rotate-180 text-text-secondary" />
              </button>
            )}
            <div className="flex items-center gap-1 text-sm">
              <span className="text-text-secondary">backend</span>
              {currentPath && (
                <>
                  <ChevronRight className="w-4 h-4 text-text-tertiary" />
                  <span className="text-text-primary">{currentPath}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索文件..."
              className="pl-9 pr-4 py-2 bg-bg-secondary border border-border-default rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-brand-primary w-48"
            />
          </div>
          <button 
            onClick={() => refetchFiles()} 
            className="p-2 hover:bg-bg-secondary rounded-lg transition-colors"
            disabled={isLoadingFiles}
          >
            <RefreshCw className={`w-4 h-4 text-text-secondary ${isLoadingFiles ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧文件列表 */}
        <div className="w-64 bg-bg-primary border-r border-border-default flex flex-col">
          <div className="p-3 border-b border-border-default">
            <div className="flex items-center gap-2">
              <Folder className="w-5 h-5 text-brand-primary" />
              <span className="font-medium text-text-primary">OmniFlowAI</span>
            </div>
            <p className="text-xs text-text-secondary mt-1">{stats?.total_files || 0} 个文件 · {stats?.total_dirs || 0} 个文件夹</p>
          </div>
          
          <div className="flex-1 overflow-y-auto">
            {isLoadingFiles ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 text-brand-primary animate-spin" />
              </div>
            ) : filesError ? (
              <div className="p-4 text-center">
                <AlertCircle className="w-8 h-8 text-status-error mx-auto mb-2" />
                <p className="text-sm text-text-secondary">加载失败</p>
                <button onClick={() => refetchFiles()} className="mt-2 text-brand-primary text-sm">
                  重试
                </button>
              </div>
            ) : filteredFiles && filteredFiles.length > 0 ? (
              <div className="py-2">
                {filteredFiles.map((item) => (
                  <div
                    key={item.path}
                    onClick={() => selectFile(item)}
                    className={`flex items-center gap-3 px-4 py-2 cursor-pointer transition-colors ${
                      selectedFile?.path === item.path
                        ? 'bg-brand-primary/10 text-brand-primary'
                        : 'hover:bg-bg-secondary text-text-primary'
                    }`}
                  >
                    {getFileIcon(item.name, item.type === 'folder' && expandedFolders.has(item.path))}
                    <span className="text-sm truncate flex-1">{item.name}</span>
                    {item.type === 'file' && (
                      <span className="text-xs text-text-tertiary">{formatSize(item.size)}</span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-4 text-center text-text-secondary text-sm">
                {searchQuery ? '未找到匹配的文件' : '暂无文件'}
              </div>
            )}
          </div>
        </div>

        {/* 右侧编辑器 */}
        <div className="flex-1 bg-bg-secondary flex flex-col">
          {selectedFile ? (
            <>
              {/* 文件头部 */}
              <div className="flex items-center justify-between px-4 py-2 bg-bg-primary border-b border-border-default">
                <div className="flex items-center gap-3">
                  <FileCode className="w-5 h-5 text-blue-500" />
                  <div>
                    <p className="font-medium text-text-primary">{selectedFile.name}</p>
                    <p className="text-xs text-text-secondary">{selectedFile.path}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-2 py-1 rounded bg-bg-secondary text-xs text-text-secondary">
                    {getMonacoLanguage(selectedFile.name)}
                  </span>
                  <span className="text-xs text-text-tertiary">
                    {formatSize(fileContent?.size || selectedFile.size)}
                  </span>
                  
                  {isEditing ? (
                    <>
                      <button 
                        onClick={handleSave}
                        disabled={saveMutation.isPending}
                        className="flex items-center gap-1 px-3 py-1.5 bg-status-success text-white rounded-lg text-sm font-medium hover:bg-status-success/90 disabled:opacity-50"
                      >
                        {saveMutation.isPending ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Save className="w-4 h-4" />
                        )}
                        保存
                      </button>
                      <button 
                        onClick={() => setIsEditing(false)}
                        className="p-2 hover:bg-bg-secondary rounded-lg transition-colors"
                      >
                        <X className="w-4 h-4 text-text-tertiary" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button 
                        onClick={startEditing}
                        className="p-2 hover:bg-bg-secondary rounded-lg transition-colors"
                        title="编辑"
                      >
                        <Edit3 className="w-4 h-4 text-text-tertiary" />
                      </button>
                      <button 
                        onClick={copyContent}
                        className="p-2 hover:bg-bg-secondary rounded-lg transition-colors"
                        title="复制"
                      >
                        <Copy className="w-4 h-4 text-text-tertiary" />
                      </button>
                    </>
                  )}
                </div>
              </div>
              
              {/* Monaco Editor */}
              <div className="flex-1">
                {isLoadingContent ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="w-8 h-8 text-brand-primary animate-spin" />
                  </div>
                ) : isEditing ? (
                  <Editor
                    height="100%"
                    language={getMonacoLanguage(selectedFile.name)}
                    value={editedContent}
                    onChange={(value) => setEditedContent(value || '')}
                    theme="vs-light"
                    options={{
                      minimap: { enabled: false },
                      fontSize: 14,
                      lineNumbers: 'on',
                      roundedSelection: false,
                      scrollBeyondLastLine: false,
                      readOnly: false,
                      automaticLayout: true,
                    }}
                  />
                ) : fileContent ? (
                  <Editor
                    height="100%"
                    language={getMonacoLanguage(selectedFile.name)}
                    value={fileContent.content}
                    theme="vs-light"
                    options={{
                      minimap: { enabled: false },
                      fontSize: 14,
                      lineNumbers: 'on',
                      roundedSelection: false,
                      scrollBeyondLastLine: false,
                      readOnly: true,
                      automaticLayout: true,
                    }}
                  />
                ) : null}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <FolderOpen className="w-16 h-16 text-text-tertiary mx-auto mb-4" />
                <p className="text-text-secondary">选择一个文件查看内容</p>
                <p className="text-sm text-text-tertiary mt-1">支持语法高亮和代码编辑</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
