# app/core/experiment.py

import os
from enum import Enum


class CodeGenMode(Enum):
    LEGACY = "legacy"           # 旧流程: 生成完整 JSON
    TOOL_BASED = "tool_based"   # 新流程: 使用 edit_tools 逐步修改
    AUTO_FALLBACK = "auto"      # 新流程优先,失败时自动回退到旧流程(推荐)


# 通过环境变量控制,不同 Pipeline 可以使用不同模式
def get_code_gen_mode() -> CodeGenMode:
    mode = os.environ.get("CODE_GEN_MODE", "auto")
    return CodeGenMode(mode)
