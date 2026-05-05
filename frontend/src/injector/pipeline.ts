/**
 * OmniFlowAI Injector - Pipeline 处理模块
 * 处理 AI 修改逻辑，通过事件总线解耦
 */

import { dom } from './core';
import { bus } from './events';
import { api } from './api';
import { stateManager, appState } from './state';
import { ui } from './ui';
import { SearchReplaceEngine } from './searchReplace';
import type { ElementInfo } from './types';

/**
 * Pipeline 管理器
 */
class PipelineManager {
  private isProcessing = false; // 防止重复提交的标志
  private lastInstruction = ''; // 保存最后一次修改指令
  private lastSummary = '';     // 保存最后一次 AI 生成的摘要
  private lastFilePath = '';    // 保存最后一次修改的文件路径
  private progressTimer: number | null = null; // 进度条定时器

  /**
   * 初始化 Pipeline 模块
   */
  init(): void {
    this.bindEvents();
  }

  /**
   * 绑定事件监听
   */
  private bindEvents(): void {
    // 监听修改提交事件
    bus.on('action:modify:submit', async ({ elementInfo, feedback }) => {
      await this.handleQuickModify(elementInfo, feedback);
    });

    bus.on('action:area-modify:submit', async ({ elements, feedback }) => {
      await this.handleQuickAreaModify(elements, feedback);
    });

    bus.on('action:preview:confirm', async () => {
      // 立即隐藏进度条
      bus.emit('ui:progress:hide', undefined);
      if (this.progressTimer) {
        clearTimeout(this.progressTimer);
        this.progressTimer = null;
      }

      ui.createToast('修改已确认保持', 'success');
      stateManager.exitSelectionMode();

      // 新增：请求后端创建 MR
      if (this.lastFilePath && this.lastInstruction) {
        try {
          const response = await api.request('/api/v1/code/create-mr', {
            method: 'POST',
            body: JSON.stringify({
              file_path: this.lastFilePath,
              instruction: this.lastInstruction,
              summary: this.lastSummary,
            }),
          });

          if (response.success && response.data?.pr_url) {
            const { pr_url, pr_number, branch } = response.data;
            // 显示详细的成功提示
            ui.createToast(
              `✅ MR #${pr_number} 创建成功！分支: ${branch}`,
              'success'
            );
            // 弹出带链接的通知卡片
            bus.emit('ui:notification:show', {
              prUrl: pr_url,
              prNumber: pr_number,
              branch: branch,
              filePath: this.lastFilePath,
            });
            // 同时显示一个带链接的 Toast
            setTimeout(() => {
              ui.createToast(`🔗 点击右上角卡片查看 PR 详情`, 'info');
            }, 1500);
          } else {
            ui.createToast(
              `⚠️ MR 创建失败: ${response.error || '未知错误'}`,
              'warning'
            );
          }
        } catch (error) {
          ui.createToast(`MR 创建失败: ${error instanceof Error ? error.message : '未知错误'}`, 'error');
        }
      }
    });

    bus.on('action:preview:cancel', async ({ filePath, originalContent }) => {
      // 立即隐藏进度条
      bus.emit('ui:progress:hide', undefined);
      if (this.progressTimer) {
        clearTimeout(this.progressTimer);
        this.progressTimer = null;
      }

      // 清理圈选框高亮
      stateManager.clearAllHighlights();
      stateManager.resetSelectionState();

      try {
        await api.writeFile(filePath, originalContent);
        ui.createToast('已取消修改，恢复原始文件', 'info');
      } catch (error) {
        ui.createToast(`恢复失败: ${error instanceof Error ? error.message : '未知错误'}`, 'error');
      }
    });
  }



  /**
   * 核心算法：在前端执行搜索替换
   * 使用与后端一致的 SearchReplaceEngine
   */
  private applySearchReplace(
    original: string,
    search: string | undefined,
    replace: string | undefined,
    fallbackStart?: number,
    fallbackEnd?: number
  ): string | null {
    if (!search || !replace) return null;

    // 使用与后端完全一致的 SearchReplaceEngine
    return SearchReplaceEngine.applySearchReplace(original, search, replace, fallbackStart, fallbackEnd);
  }

  /**
   * 轻量级快速修改 - 带 AI 效果预览
   */
  private async handleQuickModify(elementInfo: ElementInfo, feedback: string): Promise<void> {
    // 防止重复提交
    if (this.isProcessing) {
      console.warn('[OmniFlowAI] 已有修改任务正在进行中，请稍后再试');
      bus.emit('ui:toast', { message: '已有任务在进行中，请稍后再试', type: 'warning' });
      return;
    }

    this.isProcessing = true;

    try {
      await this._doHandleQuickModify(elementInfo, feedback);
    } finally {
      this.isProcessing = false;
    }
  }

  /**
   * 实际处理快速修改的逻辑
   */
  private async _doHandleQuickModify(elementInfo: ElementInfo, feedback: string): Promise<void> {
    // 显示进度条
    bus.emit('ui:progress:show', {});
    bus.emit('ui:progress:update', { status: '正在读取文件内容...', percent: 10 });

    try {
      const filePath = elementInfo.sourceFile;

      // 【修复】验证文件路径
      if (!filePath || filePath.trim() === '') {
        console.error('[OmniFlowAI] 非法文件路径:', filePath, 'elementInfo:', elementInfo);
        const errorMsg = `
[错误] 无法获取元素的源文件信息

可能的原因：
1. 元素没有 data-source 或 data-source-id 属性
2. React DevTools 没有安装或未启用
3. 项目没有配置 source map
4. 元素是动态生成的，没有对应的源文件

建议解决方案：
1. 确保 React DevTools 浏览器扩展已安装并启用
2. 检查 vite.config.ts 中是否配置了 sourcemap: true
3. 尝试选择其他元素
4. 刷新页面后重试
        `.trim();
        throw new Error(errorMsg);
      }

      // 步骤1: 获取原始文件内容
      const contentResponse = await api.getFileContent(filePath);

      if (!contentResponse.success || !contentResponse.data) {
        throw new Error('无法读取文件内容');
      }

      const originalContent = contentResponse.data.content;

      // 步骤2: 调用 AI 生成修改后的代码
      bus.emit('ui:progress:update', { status: 'AI 正在生成代码...', percent: 40 });

      const payload = {
        source_context: {
          file: filePath,
          line: elementInfo.sourceLine,
          column: elementInfo.sourceColumn,
        },
        element_context: {
          tag: elementInfo.tag,
          id: elementInfo.id,
          class_name: elementInfo.class,
          outer_html: elementInfo.outerHTML,
          text: elementInfo.text,
          xpath: elementInfo.xpath,
          selector: elementInfo.selector,
        },
        user_instruction: feedback,
        auto_apply: false,
      };

      bus.emit('ui:progress:update', { status: '正在应用代码变更...', percent: 70 });

      const result = await api.modifyCode(payload);

      if (!result.success || !result.data) {
        throw new Error(result.error || 'AI 生成失败');
      }

      // 步骤3: 获取 AI 生成的变更信息
      bus.emit('ui:progress:update', { status: '正在应用代码变更...', percent: 85 });
      const { new_content, search_block, replace_block, change_type, summary } = result.data;

      // 保存状态供后续 MR 创建使用
      this.lastFilePath = filePath;
      this.lastInstruction = feedback;
      this.lastSummary = summary || feedback;

      // 使用搜索替换引擎应用变更
      let finalContent: string;

      // 注意：replace_block 可以为空字符串（表示删除）
      if (change_type === 'modify' && search_block !== undefined && search_block !== null && replace_block !== undefined) {
        // 使用搜索替换策略
        console.log('[OmniFlowAI] 使用搜索替换策略');
        console.log('[OmniFlowAI] search_block 长度:', search_block.length);
        console.log('[OmniFlowAI] replace_block 长度:', replace_block.length);

        const replaceResult = SearchReplaceEngine.applySearchReplace(
          originalContent,
          search_block,
          replace_block,
          elementInfo.sourceLine > 0 ? elementInfo.sourceLine : undefined,
          elementInfo.sourceLine > 0 ? elementInfo.sourceLine + search_block.split('\n').length : undefined
        );

        if (replaceResult === null) {
          console.warn('[OmniFlowAI] 搜索替换失败，回退到全量替换');
          finalContent = new_content || originalContent;
        } else {
          finalContent = replaceResult;
          console.log('[OmniFlowAI] 搜索替换成功');
        }
      } else {
        // 回退到全量替换
        console.log('[OmniFlowAI] 使用全量替换策略');
        finalContent = new_content || originalContent;
      }

      if (!finalContent) {
        throw new Error('AI 生成的内容为空');
      }

      // 步骤4: 写入修改后的文件（触发 Vite HMR）
      console.log('[OmniFlowAI] 正在写入文件:', filePath);
      console.log('[OmniFlowAI] 文件内容长度:', finalContent.length);
      const writeResult = await api.writeFile(filePath, finalContent);
      console.log('[OmniFlowAI] 文件写入结果:', writeResult);

      // 步骤5: 显示预览控制浮层
      bus.emit('ui:progress:update', { status: '完成！', percent: 100 });
      console.log('[OmniFlowAI] 触发预览控制显示:', { filePath, originalContentLength: originalContent.length });
      bus.emit('ui:preview-controls:show', { filePath, originalContent });

      // 延迟隐藏进度条（保存定时器以便取消）
      this.progressTimer = window.setTimeout(() => {
        bus.emit('ui:progress:hide', undefined);
        this.progressTimer = null;
      }, 1500);

      bus.emit('ui:toast', { message: '预览模式已开启 - Vite 热更新已应用变更', type: 'success' });

    } catch (error) {
      console.error('预览失败:', error);
      bus.emit('ui:progress:update', {
        status: `错误: ${error instanceof Error ? error.message : '未知错误'}`,
        percent: 0,
      });
      bus.emit('ui:toast', {
        message: `预览失败: ${error instanceof Error ? error.message : '未知错误'}`,
        type: 'error',
      });
      this.progressTimer = window.setTimeout(() => {
        bus.emit('ui:progress:hide', undefined);
        this.progressTimer = null;
      }, 3000);
      bus.emit('pipeline:error', { error: error instanceof Error ? error.message : String(error) });
    }
  }

  /**
   * 批量快速修改 - 复用单次修改逻辑
   * 只处理第一个元素，但传递所有元素信息给 AI
   */
  private async handleQuickAreaModify(elements: HTMLElement[], feedback: string): Promise<void> {
    if (elements.length === 0) {
      bus.emit('ui:toast', { message: '请先选择至少一个元素', type: 'warning' });
      return;
    }

    // 复用单次修改逻辑，但构建批量上下文
    const firstElement = elements[0];
    const elementInfo = dom.getElementInfo(firstElement);

    // 防止重复提交
    if (this.isProcessing) {
      console.warn('[OmniFlowAI] 已有修改任务正在进行中，请稍后再试');
      bus.emit('ui:toast', { message: '已有任务在进行中，请稍后再试', type: 'warning' });
      return;
    }

    this.isProcessing = true;

    try {
      await this._doHandleBatchModify(elements, elementInfo, feedback);
    } finally {
      this.isProcessing = false;
    }
  }

  /**
   * 实际处理批量修改的逻辑 - 复用单次修改核心逻辑
   */
  private async _doHandleBatchModify(
    elements: HTMLElement[],
    firstElementInfo: ElementInfo,
    feedback: string
  ): Promise<void> {
    // 显示进度条
    bus.emit('ui:progress:show', {});
    bus.emit('ui:progress:update', { status: `正在分析 ${elements.length} 个元素...`, percent: 10 });

    try {
      const filePath = firstElementInfo.sourceFile;

      // 验证文件路径
      if (!filePath || filePath.trim() === '') {
        throw new Error('无法获取元素的源文件信息');
      }

      // 步骤1: 获取原始文件内容
      const contentResponse = await api.getFileContent(filePath);

      if (!contentResponse.success || !contentResponse.data) {
        throw new Error('无法读取文件内容');
      }

      const originalContent = contentResponse.data.content;

      // 步骤2: 构建批量上下文并调用 AI
      bus.emit('ui:progress:update', { status: 'AI 正在生成代码...', percent: 40 });

      // 收集所有元素的上下文
      const batchContext = elements.map((el) => {
        const info = dom.getElementInfo(el);
        return {
          file: info.sourceFile,
          line: info.sourceLine,
          column: info.sourceColumn,
          element_tag: info.tag,
          element_id: info.id,
          element_class: info.class,
          element_html: info.outerHTML,
          element_text: info.text,
        };
      });

      // 使用批量修改 API
      const payload = {
        files: batchContext,
        user_instruction: feedback,
        auto_apply: false,
      };

      const result = await api.modifyBatch(payload);

      if (!result.success || !result.data) {
        throw new Error(result.error || '批量修改失败');
      }

      // 步骤3: 处理多个搜索块替换
      bus.emit('ui:progress:update', { status: '正在应用代码变更...', percent: 70 });

      const { results, summary } = result.data;
      console.log('[OmniFlowAI] 批量修改结果:', { resultsCount: results?.length, summary });

      // 保存状态供后续 MR 创建使用
      this.lastFilePath = filePath;
      this.lastInstruction = feedback;
      this.lastSummary = summary || feedback;

      // 应用所有成功的变更（多个搜索块）
      let finalContent = originalContent;
      const successfulChanges = results?.filter((r: any) => r.success) || [];
      const failedChanges = results?.filter((r: any) => !r.success) || [];
      console.log('[OmniFlowAI] 变更统计:', { successful: successfulChanges.length, failed: failedChanges.length });

      for (const change of successfulChanges) {
        const { search_block, replace_block, change_type, new_content } = change;

        // 注意：replace_block 可以为空字符串（表示删除）
        if (change_type === 'modify' && search_block !== undefined && search_block !== null && replace_block !== undefined) {
          // 使用搜索替换策略
          const replaceResult = SearchReplaceEngine.applySearchReplace(
            finalContent,
            search_block,
            replace_block
          );

          if (replaceResult === null) {
            console.warn(`[OmniFlowAI] 搜索替换失败，回退到全量替换: ${change.file}`);
            finalContent = new_content || finalContent;
          } else {
            finalContent = replaceResult;
          }
        } else {
          // 回退到全量替换
          finalContent = new_content || finalContent;
        }
      }

      if (!finalContent) {
        throw new Error('AI 生成的内容为空');
      }

      // 步骤4: 写入修改后的文件（触发 Vite HMR）
      bus.emit('ui:progress:update', { status: '正在写入文件...', percent: 85 });
      console.log('[OmniFlowAI] 正在写入文件:', filePath);
      const writeResult = await api.writeFile(filePath, finalContent);
      console.log('[OmniFlowAI] 文件写入结果:', writeResult);

      // 步骤5: 显示预览控制浮层
      bus.emit('ui:progress:update', { status: '完成！', percent: 100 });
      console.log('[OmniFlowAI] 触发预览控制显示事件:', { filePath, originalContentLength: originalContent?.length, isBatch: true, successCount: successfulChanges.length, failedCount: failedChanges.length });
      console.log('[OmniFlowAI] 事件监听器数量:', bus.listenerCount('ui:preview-controls:show'));
      bus.emit('ui:preview-controls:show', {
        filePath,
        originalContent,
        isBatch: true,
        successCount: successfulChanges.length,
        failedCount: failedChanges.length,
      });
      console.log('[OmniFlowAI] 预览控制显示事件已触发');

      // 延迟隐藏进度条
      this.progressTimer = window.setTimeout(() => {
        bus.emit('ui:progress:hide', undefined);
        this.progressTimer = null;
      }, 1500);

      if (failedChanges.length === 0) {
        bus.emit('ui:toast', { message: `✅ 全部成功！${successfulChanges.length} 个变更已应用`, type: 'success' });
      } else {
        bus.emit('ui:toast', {
          message: `⚠️ ${successfulChanges.length} 个成功, ${failedChanges.length} 个失败`,
          type: 'warning',
        });
      }

    } catch (error) {
      console.error('批量修改失败:', error);
      bus.emit('ui:progress:update', {
        status: `错误: ${error instanceof Error ? error.message : '未知错误'}`,
        percent: 0,
      });
      bus.emit('ui:toast', {
        message: `批量修改失败: ${error instanceof Error ? error.message : '未知错误'}`,
        type: 'error',
      });
      this.progressTimer = window.setTimeout(() => {
        bus.emit('ui:progress:hide', undefined);
        this.progressTimer = null;
      }, 3000);
      bus.emit('pipeline:error', { error: error instanceof Error ? error.message : String(error) });
    }
  }


}

// 导出单例
export const pipeline = new PipelineManager();
export const PipelineModule = pipeline;

export default pipeline;
