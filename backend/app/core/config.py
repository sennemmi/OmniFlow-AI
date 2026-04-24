"""
应用配置
"""

from typing import List
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置类"""
    
    # 应用信息
    APP_NAME: str = "OmniFlowAI"
    VERSION: str = "0.1.0"
    ENV: str = "development"
    DEBUG: bool = True
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # CORS 配置
    CORS_ORIGINS: List[str] = ["*"]
    
    # 数据库配置 - 开发环境使用 SQLite
    DATABASE_URL: str = f"sqlite+aiosqlite:///{Path(__file__).parent.parent.parent}/omniflowai.db"
    
    # ============================================
    # 模型供应商配置
    # ============================================
    
    # 模型选择开关
    # true: 使用 ModelScope (魔搭)
    # false: 使用 OpenAI
    USE_MODELSCOPE: bool = True
    
    # ModelScope (魔搭) 配置
    MODELSCOPE_API_KEY: str = ""
    MODELSCOPE_API_BASE: str = "https://api-inference.modelscope.cn/v1"
    
    # OpenAI 配置
    OPENAI_API_KEY: str = ""
    OPENAI_API_BASE: str = "https://api.openai.com/v1"
    
    # 默认模型 (ModelScope 模型名需要加 openai/ 前缀)
    DEFAULT_MODEL: str = "openai/Qwen/Qwen2.5-72B-Instruct"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @property
    def llm_api_key(self) -> str:
        """
        获取当前使用的 LLM API Key
        
        Returns:
            str: API Key
        """
        if self.USE_MODELSCOPE:
            return self.MODELSCOPE_API_KEY
        return self.OPENAI_API_KEY
    
    @property
    def llm_api_base(self) -> str:
        """
        获取当前使用的 LLM API Base URL
        
        Returns:
            str: API Base URL
        """
        if self.USE_MODELSCOPE:
            return self.MODELSCOPE_API_BASE
        return self.OPENAI_API_BASE
    
    @property
    def llm_model(self) -> str:
        """
        获取当前使用的 LLM 模型名
        
        Returns:
            str: 模型名
        """
        return self.DEFAULT_MODEL


settings = Settings()
