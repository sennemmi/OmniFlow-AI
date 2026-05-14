import React from 'react';

// ============================================
// 简单 Markdown 渲染组件
// 支持基本的 Markdown 语法：标题、列表、代码块、粗体、斜体等
// ============================================

interface SimpleMarkdownProps {
  content: string;
  className?: string;
}

export function SimpleMarkdown({ content, className = '' }: SimpleMarkdownProps) {
  const renderMarkdown = (text: string): React.ReactNode[] => {
    const lines = text.split('\n');
    const elements: React.ReactNode[] = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      // 代码块 ```
      if (line.startsWith('```')) {
        const language = line.slice(3).trim();
        const codeLines: string[] = [];
        i++;
        while (i < lines.length && !lines[i].startsWith('```')) {
          codeLines.push(lines[i]);
          i++;
        }
        elements.push(
          <pre
            key={i}
            className="bg-bg-tertiary p-3 rounded-lg my-2 overflow-x-auto"
          >
            <code className="text-xs font-mono text-text-secondary">
              {codeLines.join('\n')}
            </code>
          </pre>
        );
        i++; // 跳过 ```
        continue;
      }

      // 行内代码 ` - 但需要同时处理粗体和斜体
      if (line.includes('`')) {
        const parts = line.split(/(`[^`]+`)/g);
        elements.push(
          <p key={i} className="text-sm text-text-secondary my-1">
            {parts.map((part, idx) => {
              if (part.startsWith('`') && part.endsWith('`')) {
                return (
                  <code
                    key={idx}
                    className="bg-bg-tertiary px-1.5 py-0.5 rounded text-xs font-mono text-brand-primary"
                  >
                    {part.slice(1, -1)}
                  </code>
                );
              }
              // 【修复】对非代码部分也应用粗体/斜体渲染
              return <span key={idx}>{renderInlineFormatting(part)}</span>;
            })}
          </p>
        );
        i++;
        continue;
      }

      // 标题 # ## ###
      if (line.startsWith('### ')) {
        elements.push(
          <h4 key={i} className="text-sm font-semibold text-text-primary mt-3 mb-1">
            {line.slice(4)}
          </h4>
        );
        i++;
        continue;
      }
      if (line.startsWith('## ')) {
        elements.push(
          <h3 key={i} className="text-base font-semibold text-text-primary mt-4 mb-2">
            {line.slice(3)}
          </h3>
        );
        i++;
        continue;
      }
      if (line.startsWith('# ')) {
        elements.push(
          <h2 key={i} className="text-lg font-bold text-text-primary mt-4 mb-2">
            {line.slice(2)}
          </h2>
        );
        i++;
        continue;
      }

      // 无序列表 - 或 *
      if (line.match(/^\s*[-*]\s/)) {
        const listItems: string[] = [];
        while (i < lines.length && lines[i].match(/^\s*[-*]\s/)) {
          listItems.push(lines[i].replace(/^\s*[-*]\s/, ''));
          i++;
        }
        elements.push(
          <ul key={i} className="list-disc list-inside my-2 space-y-1">
            {listItems.map((item, idx) => (
              <li key={idx} className="text-sm text-text-secondary">
                {renderInlineFormatting(item)}
              </li>
            ))}
          </ul>
        );
        continue;
      }

      // 有序列表 1. 2. 3.
      if (line.match(/^\s*\d+\.\s/)) {
        const listItems: string[] = [];
        while (i < lines.length && lines[i].match(/^\s*\d+\.\s/)) {
          listItems.push(lines[i].replace(/^\s*\d+\.\s/, ''));
          i++;
        }
        elements.push(
          <ol key={i} className="list-decimal list-inside my-2 space-y-1">
            {listItems.map((item, idx) => (
              <li key={idx} className="text-sm text-text-secondary">
                {renderInlineFormatting(item)}
              </li>
            ))}
          </ol>
        );
        continue;
      }

      // 空行
      if (line.trim() === '') {
        elements.push(<div key={i} className="h-2" />);
        i++;
        continue;
      }

      // 普通段落
      elements.push(
        <p key={i} className="text-sm text-text-secondary my-1">
          {renderInlineFormatting(line)}
        </p>
      );
      i++;
    }

    return elements;
  };

  // 渲染行内格式：粗体 **text**、斜体 *text*、删除线 ~~text~~
  const renderInlineFormatting = (text: string): React.ReactNode => {
    // 处理粗体 **text**
    const boldParts = text.split(/(\*\*[^*]+\*\*)/g);
    if (boldParts.length > 1) {
      return boldParts.map((part, idx) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={idx} className="font-semibold text-text-primary">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return renderItalic(part, idx);
      });
    }
    return renderItalic(text, 0);
  };

  // 处理斜体 *text*（不包括 **）
  const renderItalic = (text: string, key: number): React.ReactNode => {
    const parts = text.split(/(\*[^*]+\*)/g);
    if (parts.length > 1) {
      return parts.map((part, idx) => {
        if (part.startsWith('*') && part.endsWith('*') && !part.startsWith('**')) {
          return (
            <em key={`${key}-${idx}`} className="italic">
              {part.slice(1, -1)}
            </em>
          );
        }
        return <span key={`${key}-${idx}`}>{part}</span>;
      });
    }
    return <span key={key}>{text}</span>;
  };

  return (
    <div className={`prose prose-sm max-w-none ${className}`}>
      {renderMarkdown(content)}
    </div>
  );
}
