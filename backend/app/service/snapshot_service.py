# app/service/snapshot_service.py

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.service.sandbox_manager import sandbox_manager

logger = logging.getLogger(__name__)


class SnapshotService:
    """
    关键节点检查点机制

    在每次代码修改前自动 git stash,如果后续修复失败可一键回滚。
    在 Sandbox 环境中通过 Docker exec 执行 git 命令。
    """

    # 需要保存快照的关键节点
    CHECKPOINT_NAMES = [
        "before_coder",           # CoderAgent 开始生成代码前
        "before_apply",           # 应用代码修改前
        "before_auto_fix",        # 进入 Auto-Fix 循环前
        "before_repairer",        # RepairerAgent 修复前
        "before_test_run",        # 运行测试前
    ]

    def __init__(self, pipeline_id: int):
        self.pipeline_id = pipeline_id
        self._stash_stack: list[str] = []  # 记录 stash 的顺序

    async def checkpoint(self, name: str) -> bool:
        """
        在 Sandbox 中执行 git stash,保存当前状态

        Args:
            name: 检查点名称(如 "before_coder")

        Returns:
            是否成功
        """
        if name not in self.CHECKPOINT_NAMES:
            logger.warning(f"未知的检查点名称: {name}")
            return False

        timestamp = datetime.now().strftime("%H:%M:%S")
        stash_message = f"checkpoint:{name}@{timestamp}"

        try:
            result = await sandbox_manager.exec(
                self.pipeline_id,
                f"cd /workspace && git add -A && git stash push -m '{stash_message}'",
                timeout=10
            )
            if result.exit_code == 0:
                self._stash_stack.append(name)
                logger.info(f"[Snapshot] 快照已保存: {stash_message}")
                return True
            else:
                logger.warning(f"[Snapshot] 快照保存失败: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"[Snapshot] 快照异常: {e}")
            return False

    async def rollback_to(self, name: str) -> bool:
        """
        回滚到指定检查点

        Args:
            name: 检查点名称

        Returns:
            是否成功
        """
        try:
            # 先查看 stash 列表
            list_result = await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git stash list",
                timeout=5
            )
            if list_result.exit_code != 0:
                logger.warning(f"[Snapshot] 无法获取 stash 列表")
                return False

            # 找到目标 stash 的索引
            stash_list = list_result.stdout.strip().split("\n")
            target_idx = -1
            target_message = f"checkpoint:{name}"
            for idx, stash_entry in enumerate(stash_list):
                if target_message in stash_entry:
                    target_idx = idx
                    break

            if target_idx < 0:
                logger.warning(f"[Snapshot] 未找到检查点 {name}")
                return False

            # 执行 pop
            pop_result = await sandbox_manager.exec(
                self.pipeline_id,
                f"cd /workspace && git stash pop stash@{{{target_idx}}}",
                timeout=10
            )
            if pop_result.exit_code == 0:
                logger.info(f"[Snapshot] 已回滚到检查点: {name}")
                # 清理该检查点及其之后的 stash
                self._stash_stack = self._stash_stack[:self._stash_stack.index(name)]
                return True
            else:
                # stash pop 可能因冲突失败,尝试 apply + drop
                apply_result = await sandbox_manager.exec(
                    self.pipeline_id,
                    f"cd /workspace && git stash apply stash@{{{target_idx}}}",
                    timeout=10
                )
                if apply_result.exit_code == 0:
                    await sandbox_manager.exec(
                        self.pipeline_id,
                        f"cd /workspace && git stash drop stash@{{{target_idx}}}",
                        timeout=5
                    )
                    logger.info(f"[Snapshot] 已回滚到检查点: {name} (通过 apply+drop)")
                    return True
                logger.warning(f"[Snapshot] 回滚失败: {pop_result.stderr}")
                return False
        except Exception as e:
            logger.error(f"[Snapshot] 回滚异常: {e}")
            return False

    async def cleanup(self):
        """清理所有快照"""
        try:
            await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git stash clear",
                timeout=5
            )
            self._stash_stack.clear()
            logger.info(f"[Snapshot] 所有快照已清理")
        except Exception as e:
            logger.warning(f"[Snapshot] 清理异常: {e}")

    async def atomic_rollback(self, steps: int = 1) -> bool:
        """
        原子撤销 - 回退到上一个 commit

        使用 git checkout . 撤销所有未提交的更改，
        然后 git reset --hard HEAD~n 回退到指定步数前的 commit。

        Args:
            steps: 回退步数（默认 1）

        Returns:
            是否成功
        """
        try:
            logger.info(f"[Snapshot] 执行原子撤销，回退 {steps} 步")

            # 1. 撤销所有未提交的更改
            await sandbox_manager.exec(
                self.pipeline_id,
                "cd /workspace && git checkout .",
                timeout=5
            )

            # 2. 回退到指定步数前的 commit
            result = await sandbox_manager.exec(
                self.pipeline_id,
                f"cd /workspace && git reset --hard HEAD~{steps}",
                timeout=5
            )

            if result.exit_code == 0:
                logger.info(f"[Snapshot] 原子撤销成功，回退到 HEAD~{steps}")
                return True
            else:
                logger.warning(f"[Snapshot] 原子撤销失败: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"[Snapshot] 原子撤销异常: {e}")
            return False

    async def get_commit_history(self, count: int = 10) -> List[str]:
        """
        获取最近的 commit 历史

        Args:
            count: 获取的 commit 数量

        Returns:
            commit message 列表
        """
        try:
            result = await sandbox_manager.exec(
                self.pipeline_id,
                f"cd /workspace && git log --oneline -{count}",
                timeout=5
            )

            if result.exit_code == 0:
                return result.stdout.strip().split("\n")
            else:
                return []
        except Exception as e:
            logger.warning(f"[Snapshot] 获取 commit 历史失败: {e}")
            return []


# 便捷函数
def get_snapshot_service(pipeline_id: int) -> SnapshotService:
    """获取快照服务实例"""
    return SnapshotService(pipeline_id)
