/**
 * OmniFlowAI 浏览器注入脚本 - Pipeline 处理模块
 */

(function () {
  'use strict';

  const CONFIG = window.OmniFlowAIConfig;
  const { DOM } = window.OmniFlowAICore;
  const { API } = window.OmniFlowAIAPI;
  const { UI } = window.OmniFlowAIUI;
  const { state } = window.OmniFlowAIState;

  // ============================================
  // LLM 上下文构建
  // ============================================
  function buildLLMContext(elementInfo, userInstruction) {
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

  // ============================================
  // Pipeline 轮询
  // ============================================
  function startPolling(progressBar, pipelineId, onComplete) {
    state.isPolling = true;

    const poll = async () => {
      if (!state.isPolling) return;

      try {
        const response = await API.getPipelineStatus(pipelineId);

        if (response.success) {
          const { status, current_stage_index, stages } = response.data;
          const totalStages = stages?.length || 4;
          const progress = Math.min((current_stage_index / totalStages) * 100, 95);

          const stageNames = ['架构设计', '代码生成', '测试验证', '部署发布'];
          const currentStage = stageNames[current_stage_index] || '执行中';

          UI.updateProgressBar(progressBar, `${currentStage}...`, Math.round(progress));

          if (status === 'success') {
            state.isPolling = false;
            UI.updateProgressBar(progressBar, '完成！', 100);

            const prUrl = response.data.delivery?.pr_url || '#';

            setTimeout(() => {
              UI.removeProgressBar(progressBar);
              UI.createCompletionNotification(prUrl);
              if (onComplete) onComplete(true);
            }, 1500);
            return;
          }

          if (status === 'failed') {
            state.isPolling = false;
            UI.updateProgressBar(progressBar, '执行失败', 0);
            UI.createToast('Pipeline 执行失败', 'error');
            setTimeout(() => UI.removeProgressBar(progressBar), 3000);
            if (onComplete) onComplete(false);
            return;
          }

          setTimeout(poll, CONFIG.POLL_INTERVAL);
        }
      } catch (error) {
        console.error('轮询失败:', error);
        setTimeout(poll, CONFIG.POLL_INTERVAL);
      }
    };

    poll();
  }

  // ============================================
  // 单个元素修改
  // ============================================
  async function handleModify(elementInfo, feedback, onComplete) {
    const progressBar = UI.createProgressBar('pending');

    try {
      const llmContext = buildLLMContext(elementInfo, feedback);

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
        requirement: requirement,
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
        sourceContext: sourceContext,
        llmContext: llmContext,
      };

      const response = await API.createPipeline(payload);

      const pipelineId = response.success && response.data?.pipeline_id;
      if (pipelineId) {
        state.currentPipelineId = pipelineId;
        UI.updateProgressBar(progressBar, 'Pipeline 已创建，开始执行...', 10);
        startPolling(progressBar, pipelineId, onComplete);
      } else {
        throw new Error(response.error || '创建 Pipeline 失败');
      }
    } catch (error) {
      console.error('提交失败:', error);
      UI.updateProgressBar(progressBar, `错误: ${error.message}`, 0);
      UI.createToast(`提交失败: ${error.message}`, 'error');
      setTimeout(() => UI.removeProgressBar(progressBar), 3000);
      if (onComplete) onComplete(false);
    }
  }

  // ============================================
  // 批量元素修改
  // ============================================
  async function handleAreaModify(elements, feedback, onComplete) {
    const progressBar = UI.createProgressBar('pending');

    try {
      const elementContexts = elements.map(el => {
        const info = DOM.getElementInfo(el);
        return {
          tag: info.tag,
          id: info.id,
          class: info.class,
          xpath: info.xpath,
          selector: info.selector,
          text: info.text,
          componentName: info.componentName,
          sourceFile: info.sourceFile,
          sourceLine: info.sourceLine,
          llmContext: buildLLMContext(info, feedback),
        };
      });

      const requirement = `批量修复 ${elements.length} 个元素\n\n${feedback}`;

      const payload = {
        requirement: requirement,
        elementContext: {
          isAreaSelection: true,
          elementCount: elements.length,
          elements: elementContexts,
        },
        sourceContext: null,
        llmContext: {
          isBatch: true,
          elementCount: elements.length,
          elements: elementContexts.map(ec => ec.llmContext),
          user_instruction: feedback,
        },
      };

      const response = await API.createPipeline(payload);

      const pipelineId = response.success && response.data?.pipeline_id;
      if (pipelineId) {
        state.currentPipelineId = pipelineId;
        UI.updateProgressBar(progressBar, 'Pipeline 已创建，开始执行...', 10);
        startPolling(progressBar, pipelineId, onComplete);
      } else {
        throw new Error(response.error || '创建 Pipeline 失败');
      }
    } catch (error) {
      console.error('提交失败:', error);
      UI.updateProgressBar(progressBar, `错误: ${error.message}`, 0);
      UI.createToast(`提交失败: ${error.message}`, 'error');
      setTimeout(() => UI.removeProgressBar(progressBar), 3000);
      if (onComplete) onComplete(false);
    }
  }

  // ============================================
  // 轻量级快速修改 - 带 AI 效果预览
  // ============================================
  async function quickModify(elementInfo, feedback, onComplete) {
    // 安全检查：确保 preview 模块已加载
    if (!window.OmniFlowAIPreview) {
      console.error('[OmniFlowAI] Preview 模块未加载');
      UI.createToast('❌ 预览模块未加载，请刷新页面重试', 'error');
      if (onComplete) onComplete(false);
      return;
    }

    const { startPreview } = window.OmniFlowAIPreview;

    // 获取实际 DOM 元素
    const element = document.evaluate(
      elementInfo.xpath,
      document,
      null,
      XPathResult.FIRST_ORDERED_NODE_TYPE,
      null
    ).singleNodeValue;

    if (!element) {
      UI.createToast('❌ 找不到要修改的元素', 'error');
      if (onComplete) onComplete(false);
      return;
    }

    // 调用新的预览功能（Vite HMR 方案）
    await startPreview(
      elementInfo,
      feedback,
      // 完成回调
      (success) => {
        if (onComplete) onComplete(success);
      }
    );
  }

  // ============================================
  // 批量快速修改 - 使用新的批量修改 API
  // ============================================
  async function quickAreaModify(elements, feedback, onComplete) {
    const progressBar = UI.createProgressBar('pending');

    try {
      UI.updateProgressBar(progressBar, `正在分析 ${elements.length} 个元素...`, 20);

      // 收集所有元素的信息
      const files = elements.map(el => {
        const info = DOM.getElementInfo(el);
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

      UI.updateProgressBar(progressBar, '正在批量生成代码...', 50);

      // 使用新的批量修改 API
      const payload = {
        files: files,
        user_instruction: feedback,
        auto_apply: true,
      };

      const response = await fetch(`${CONFIG.API_BASE_URL}/api/v1/code/modify-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const result = await response.json();

      if (result.success) {
        const data = result.data;
        const successCount = data.success_files;
        const failedCount = data.failed_files;
        
        UI.updateProgressBar(progressBar, '批量修改完成！', 100);
        
        if (failedCount === 0) {
          UI.createToast(`✅ 全部成功！${successCount} 个文件已更新`, 'success');
        } else {
          UI.createToast(`⚠️ ${successCount} 个成功, ${failedCount} 个失败`, 'warning');
          // 显示失败的文件
          const failed = data.results.filter(r => !r.success);
          failed.forEach(r => {
            console.error(`修改失败: ${r.file} - ${r.error}`);
          });
        }

        setTimeout(() => {
          UI.removeProgressBar(progressBar);
          if (onComplete) onComplete(failedCount === 0);
        }, 2000);
      } else {
        throw new Error(result.error || '批量修改失败');
      }
    } catch (error) {
      console.error('批量快速修改失败:', error);
      UI.updateProgressBar(progressBar, `错误: ${error.message}`, 0);
      UI.createToast(`批量修改失败: ${error.message}`, 'error');
      setTimeout(() => UI.removeProgressBar(progressBar), 3000);
      if (onComplete) onComplete(false);
    }
  }

  window.OmniFlowAIPipeline = {
    handleModify,
    handleAreaModify,
    quickModify,      // 【新增】轻量级快速修改
    quickAreaModify,  // 【新增】轻量级批量修改
    startPolling,
    buildLLMContext,
  };

})();
