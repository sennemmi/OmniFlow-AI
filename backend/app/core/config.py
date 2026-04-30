"""
OmniFlowAI 核心配置模块

遵循 '以状态管理为荣' 原则，所有可配置项集中管理。
"""
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional, List


class Config(BaseSettings):
    """应用配置类"""

    # 应用基础配置
    APP_NAME: str = "OmniFlowAI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENV: str = "development"

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS 配置
    CORS_ORIGINS: List[str] = ["*"]

    # 数据库配置
    # 注意：异步 SQLAlchemy 需要使用 sqlite+aiosqlite 格式
    DATABASE_URL: str = "sqlite+aiosqlite:///./omniflow.db"

    # API 版本
    API_V1_PREFIX: str = "/api/v1"

    # 沙箱测试功能开关（默认启用）
    SANDBOX_TEST_ENABLED: bool = True

    # ============================================
    # AI 模型配置
    # ============================================

    # 模型选择开关
    USE_MODELSCOPE: bool = True

    # ModelScope (魔搭) 配置
    MODELSCOPE_API_KEY: Optional[str] = None
    MODELSCOPE_API_BASE: str = "https://api-inference.modelscope.cn/v1"
    DEFAULT_MODEL: str = "Qwen/Qwen2.5-72B-Instruct"

    # OpenAI 配置
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_BASE: str = "https://api.openai.com/v1"

    # ============================================
    # 计算属性
    # ============================================

    @property
    def llm_api_key(self) -> Optional[str]:
        """根据 USE_MODELSCOPE 返回对应的 API Key"""
        if self.USE_MODELSCOPE:
            return self.MODELSCOPE_API_KEY
        return self.OPENAI_API_KEY

    @property
    def llm_api_base(self) -> str:
        """根据 USE_MODELSCOPE 返回对应的 API Base"""
        if self.USE_MODELSCOPE:
            return self.MODELSCOPE_API_BASE
        return self.OPENAI_API_BASE

    @property
    def llm_model(self) -> str:
        """返回使用的模型名称"""
        return self.DEFAULT_MODEL

    # ============================================
    # AI 目标项目配置
    # ============================================

    # AI 操作的目标项目路径（必须使用绝对路径）
    TARGET_PROJECT_PATH: str = ""

    # ============================================
    # 代码安全机制配置
    # ============================================

    # Read Token 密钥（用于验证先读后写机制）
    # 如果不设置，系统会自动生成一个随机密钥（重启后失效）
    READ_TOKEN_SECRET: Optional[str] = None

    # ============================================
    # GitHub 集成配置
    # ============================================

    GITHUB_TOKEN: Optional[str] = None
    GITHUB_OWNER: Optional[str] = None
    GITHUB_REPO: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # 忽略未定义的字段


# 全局配置实例
settings = Config()


# ============================================
# 路径处理工具函数
# ============================================

def get_workspace_path(subdir: str = "") -> Path:
    """
    获取工作区路径

    Args:
        subdir: 子目录名（如 "frontend", "backend"）

    Returns:
        Path: 工作区绝对路径
    """
    base_path = Path(settings.TARGET_PROJECT_PATH)
    if subdir:
        return base_path / subdir
    return base_path


def process_file_path(file_path: str) -> Path:
    """
    处理文件路径，转换为绝对路径

    Args:
        file_path: 原始文件路径（可能是相对路径）

    Returns:
        Path: 处理后的绝对路径
    """
    path = Path(file_path)

    # 如果已经是绝对路径，直接返回
    if path.is_absolute():
        return path

    # 如果是相对路径，基于 TARGET_PROJECT_PATH 解析
    base_path = Path(settings.TARGET_PROJECT_PATH)
    return base_path / path
