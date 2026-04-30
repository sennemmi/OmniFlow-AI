import { useEffect, useCallback, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useUIStore } from '@stores/uiStore';
import type { Pipeline } from '@types';

// ============================================
// Pipeline 实时通知 Hook
// ============================================

interface NotificationOptions {
  enableBrowserNotification?: boolean;
  enableSound?: boolean;
  onComplete?: (pipeline: Pipeline) => void;
  onStageChange?: (pipeline: Pipeline, stageName: string) => void;
}

export function usePipelineNotification(
  pipelineId: number | null,
  options: NotificationOptions = {}
) {
  const { enableBrowserNotification = true, enableSound = true, onComplete, onStageChange } = options;
  const queryClient = useQueryClient();
  const { addToast } = useUIStore();
  const previousStageRef = useRef<string>('');
  const hasNotifiedRef = useRef<boolean>(false);

  // 请求浏览器通知权限
  useEffect(() => {
    if (enableBrowserNotification && 'Notification' in window) {
      if (Notification.permission === 'default') {
        Notification.requestPermission();
      }
    }
  }, [enableBrowserNotification]);

  // 发送浏览器通知
  const sendBrowserNotification = useCallback(
    (title: string, body: string, icon?: string) => {
      if (enableBrowserNotification && 'Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {
          body,
          icon: icon || '/favicon.ico',
          badge: '/favicon.ico',
          tag: `pipeline-${pipelineId}`,
          requireInteraction: true,
        });
      }
    },
    [enableBrowserNotification, pipelineId]
  );

  // 播放完成音效
  const playCompleteSound = useCallback(() => {
    if (enableSound) {
      const audio = new Audio('/sounds/complete.mp3');
      audio.volume = 0.5;
      audio.play().catch(() => {
        // 忽略自动播放策略错误
      });
    }
  }, [enableSound]);



// 显示完成弹窗
  const showCompletionModal = useCallback((pipeline: Pipeline, prUrl?: string, previewUrl?: string) => {
    const event = new CustomEvent('pipeline:completed', {
      detail: {
        pipeline,
        prUrl: prUrl || '代码已提交到本地仓库分支，暂未创建远程 PR',
        // previewUrl 为可选，如果没有真实的预览环境则不传
        ...(previewUrl && { previewUrl }),
      },
    });
    document.dispatchEvent(event);
  }, []);

  // 监听 Pipeline 状态变化
  useEffect(() => {
    if (!pipelineId) return;

    // 订阅 Query Cache 变化
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === 'updated' && event.query.queryKey[0] === 'pipeline') {
        const queryKeyPipelineId = event.query.queryKey[1];
        if (String(queryKeyPipelineId) === String(pipelineId)) {
          const data = event.query.state.data as Pipeline | undefined;
          if (!data) return;

          const currentStage = data.stages?.[data.stages.length - 1];
          const stageName = currentStage?.name || data.current_stage || '';

          // 阶段变化通知
          if (stageName && stageName !== previousStageRef.current) {
            previousStageRef.current = stageName;
            onStageChange?.(data, stageName);

            // 显示阶段切换 Toast
            addToast({
              type: 'info',
              message: `进入阶段: ${stageName}`,
              duration: 3000,
            });
          }

          // Pipeline 完成 (后端使用 'success' 状态)
          if (data.status === 'success' && !hasNotifiedRef.current) {
            hasNotifiedRef.current = true;

            // 播放音效
            playCompleteSound();

            // 获取真实的 PR URL
            const prUrl = data.delivery?.pr_url;

            // 浏览器通知
            sendBrowserNotification(
              '✨ AI 已完成修改！',
              `Pipeline #${data.id} 所有阶段已执行完成。代码已自动同步并 Push 到 GitHub。`,
              '/assets/omniflow-icon.png'
            );

            // 显示完成弹窗（使用真实的 PR URL，previewUrl 暂未从后端配置获取）
            showCompletionModal(data, prUrl);

            // 回调
            onComplete?.(data);
          }

          // Pipeline 失败
          if (data.status === 'failed') {
            addToast({
              type: 'error',
              message: `Pipeline 执行失败: #${data.id}`,
              duration: 5000,
            });

            sendBrowserNotification(
              '❌ Pipeline 执行失败',
              `Pipeline #${data.id} 执行过程中出现错误，请查看详情。`,
              '/assets/omniflow-icon.png'
            );
          }
        }
      }
    });

    return () => {
      unsubscribe();
    };
  }, [pipelineId, queryClient, addToast, sendBrowserNotification, playCompleteSound, onComplete, onStageChange, showCompletionModal]);

  // 手动触发通知（用于测试）
  const triggerTestNotification = useCallback(() => {
    sendBrowserNotification(
      '🔔 测试通知',
      '这是一条测试通知，用于验证通知系统是否正常工作。'
    );
    addToast({
      type: 'success',
      message: '测试通知已发送',
    });
  }, [sendBrowserNotification, addToast]);

  return {
    triggerTestNotification,
  };
}
