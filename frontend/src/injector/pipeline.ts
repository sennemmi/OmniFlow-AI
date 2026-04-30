/**
 * OmniFlowAI Injector - Pipeline 处理模块
 * 处理 AI 修改逻辑，通过事件总线解耦
 */

import { dom } from './core';
import { bus } from './events';
import { api } from './api';
import { stateManager, appState } from './state';
import { ui } from './ui';
import type { ElementInfo } from './types';

/**
 * Pipeline 管理器
 */
class PipelineManager {
  private pollTimer: number | null = null;

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
      ui.createToast('修改已确认保持', 'success');
      stateManager.exitSelectionMode();
    });

    bus.on('action:preview:cancel', async ({ filePath, originalContent }) => {
      try {
        await api.writeFile(filePath, originalContent);
        ui.createToast('已取消修改，恢复原始文件', 'info');
      } catch (error) {
        ui.createToast(`恢复失败: ${error instanceof Error ? error.message : '未知错误'}`, 'error');
      }
    });
  }

  /**
   * 构建 LLM 上下文
   */
  private buildLLMContext(elementInfo: ElementInfo, userInstruction: string): Record<string, unknown> {
    return {
      file: elementInfo.sourceFile,
      line: elementInfo.sourceLine,
      column: elementInfo.sourceColumn,
      component: elementInfo.componentName,
      selected_html: elementInfo.outerHTML.slice(0, 500),
      surrounding_code: '',
      user_instruction: userInstruction,
      element_type: elementInfo.tag,
      element_id: elementInfo.id,
      element_class: elementInfo.class,
      xpath: elementInfo.xpath,
      selector: elementInfo.selector,
    };
  }

  /**
   * 轻量级快速修改 - 带 AI 效果预览
   */
  private async handleQuickModify(elementInfo: ElementInfo, feedback: string): Promise<void> {
    bus.emit('ui:toast', { message: 'AI 正在准备预览...', type: 'info' });

    try {
      const filePath = elementInfo.sourceFile;

      // 步骤1: 获取原始文件内容
      const contentResponse = await api.getFileContent(filePath);

      if (!contentResponse.success || !contentResponse.data) {
        throw new Error('无法读取文件内容');
      }

      const originalContent = contentResponse.data.content;

      // 步骤2: 调用 AI 生成修改后的代码
      bus.emit('ui:toast', { message: '🤖 AI 正在生成代码...', type: 'info' });

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

      const result = await api.modifyCode(payload);

      if (!result.success || !result.data) {
        throw new Error(result.error || 'AI 生成失败');
      }

      const modifiedContent = result.data.new_content;

      // 步骤3: 直接写入修改后的文件（触发 Vite HMR）
      await api.writeFile(filePath, modifiedContent);

      // 步骤4: 显示预览控制浮层
      bus.emit('ui:preview-controls:show', { filePath, originalContent });
      bus.emit('ui:toast', { message: '预览模式已开启 - Vite 热更新已应用变更', type: 'success' });

    } catch (error) {
      console.error('预览失败:', error);
      bus.emit('ui:toast', {
        message: `预览失败: ${error instanceof Error ? error.message : '未知错误'}`,
        type: 'error',
      });
      bus.emit('pipeline:error', { error: error instanceof Error ? error.message : String(error) });
    }
  }

  /**
   * 批量快速修改
   */
  private async handleQuickAreaModify(elements: HTMLElement[], feedback: string): Promise<void> {
    bus.emit('ui:progress:show', {});
    bus.emit('ui:progress:update', { status: `正在分析 ${elements.length} 个元素...`, percent: 20 });

    try {
      // 收集所有元素的信息
      const files = elements.map((el) => {
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

      bus.emit('ui:progress:update', { status: '正在批量生成代码...', percent: 50 });

      // 使用批量修改 API
      const payload = {
        files,
        user_instruction: feedback,
        auto_apply: true,
      };

      const result = await api.modifyBatch(payload);

      if (result.success && result.data) {
        const { success_files, failed_files } = result.data;

        bus.emit('ui:progress:update', { status: '批量修改完成！', percent: 100 });

        if (failed_files === 0) {
          bus.emit('ui:toast', {
            message: `✅ 全部成功！${success_files} 个文件已更新`,
            type: 'success',
          });
        } else {
          bus.emit('ui:toast', {
            message: `⚠️ ${success_files} 个成功, ${failed_files} 个失败`,
            type: 'warning',
          });
        }

        setTimeout(() => {
          bus.emit('ui:progress:hide', undefined);
          stateManager.exitSelectionMode();
        }, 2000);
      } else {
        throw new Error(result.error || '批量修改失败');
      }
    } catch (error) {
      console.error('批量快速修改失败:', error);
      bus.emit('ui:progress:update', {
        status: `错误: ${error instanceof Error ? error.message : '未知错误'}`,
        percent: 0,
      });
      bus.emit('ui:toast', {
        message: `批量修改失败: ${error instanceof Error ? error.message : '未知错误'}`,
        type: 'error',
      });
      setTimeout(() => bus.emit('ui:progress:hide', undefined), 3000);
    }
  }

  /**
   * 传统 Pipeline 修改（带轮询）
   */
  async handleModify(elementInfo: ElementInfo, feedback: string): Promise<void> {
    bus.emit('ui:progress:show', {});

    try {
      const llmContext = this.buildLLMContext(elementInfo, feedback);
      const requirement = `修复: ${elementInfo.componentName || elementInfo.tag}${elementInfo.id ? `#${elementInfo.id}` : ''}\n\n${feedback}`;

      let sourceContext = null;
      if (elementInfo.sourceFile && elementInfo.sourceLine > 0) {
        sourceContext = {
          file: elementInfo.sourceFile,
          line: elementInfo.sourceLine,
          column: elementInfo.sourceColumn,
          relativePath: elementInfo.sourceFile.includes('src/')
            ? elementInfo.sourceFile.substring(elementInfo.sourceFile.indexOf('src/'))
            : elementInfo.sourceFile,
        };
      }

      const payload = {
        requirement,
        elementContext: {
          tag: elementInfo.tag,
          id: elementInfo.id,
          class: elementInfo.class,
          xpath: elementInfo.xpath,
          selector: elementInfo.selector,
          outerHTML: elementInfo.outerHTML,
          text: elementInfo.text,
          componentName: elementInfo.componentName,
          dataSource: elementInfo.dataSource,
          dataComponent: elementInfo.dataComponent,
          dataFile: elementInfo.dataFile,
          rect: elementInfo.rect,
        },
        sourceContext,
        llmContext,
      };

      const response = await api.createPipeline(payload);

      if (response.success && response.data?.pipeline_id) {
        appState.currentPipelineId = response.data.pipeline_id;
        bus.emit('ui:progress:update', { status: 'Pipeline 已创建，开始执行...', percent: 10 });
        this.startPolling(response.data.pipeline_id);
      } else {
        throw new Error(response.error || '创建 Pipeline 失败');
      }
    } catch (error) {
      console.error('提交失败:', error);
      bus.emit('ui:progress:update', {
        status: `错误: ${error instanceof Error ? error.message : '未知错误'}`,
        percent: 0,
      });
      bus.emit('ui:toast', {
        message: `提交失败: ${error instanceof Error ? error.message : '未知错误'}`,
        type: 'error',
      });
      setTimeout(() => bus.emit('ui:progress:hide', undefined), 3000);
    }
  }

  /**
   * 开始轮询 Pipeline 状态
   */
  private startPolling(pipelineId: string): void {
    appState.isPolling = true;

    const poll = async () => {
      if (!appState.isPolling) return;

      try {
        const response = await api.getPipelineStatus(pipelineId);

        if (response.success && response.data) {
          const { status, current_stage_index, stages } = response.data;
          const totalStages = stages?.length || 4;
          const progress = Math.min((current_stage_index / totalStages) * 100, 95);

          const stageNames = ['架构设计', '代码生成', '测试验证', '部署发布'];
          const currentStage = stageNames[current_stage_index] || '执行中';

          bus.emit('ui:progress:update', {
            status: `${currentStage}...`,
            percent: Math.round(progress),
          });

          if (status === 'success') {
            appState.isPolling = false;
            bus.emit('ui:progress:update', { status: '完成！', percent: 100 });

            const prUrl = response.data.delivery?.pr_url || '#';

            setTimeout(() => {
              bus.emit('ui:progress:hide', undefined);
              bus.emit('ui:notification:show', { prUrl });
              bus.emit('pipeline:completed', { success: true, prUrl });
              stateManager.exitSelectionMode();
            }, 1500);
            return;
          }

          if (status === 'failed') {
            appState.isPolling = false;
            bus.emit('ui:progress:update', { status: '执行失败', percent: 0 });
            bus.emit('ui:toast', { message: 'Pipeline 执行失败', type: 'error' });
            bus.emit('pipeline:completed', { success: false });
            setTimeout(() => bus.emit('ui:progress:hide', undefined), 3000);
            return;
          }

          this.pollTimer = window.setTimeout(poll, 3000);
        }
      } catch (error) {
        console.error('轮询失败:', error);
        this.pollTimer = window.setTimeout(poll, 3000);
      }
    };

    poll();
  }

  /**
   * 停止轮询
   */
  stopPolling(): void {
    appState.isPolling = false;
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  }
}

// 导出单例
export const pipeline = new PipelineManager();
export const PipelineModule = pipeline;

export default pipeline;
