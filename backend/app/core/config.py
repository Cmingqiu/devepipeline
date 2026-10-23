from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """全部配置来自 backend/.env（已被 gitignore），字段名与 env 变量名大小写不敏感。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "dev"
    app_secret_key: str = "dev-only-change-me"
    api_title: str = "DevPipeline API"
    api_version: str = "0.1.0"
    api_base_url: str = "http://127.0.0.1:8000"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # MariaDB（业务库）
    mariadb_host: str = "127.0.0.1"
    mariadb_port: int = 3306
    mariadb_user: str = "devpipeline"
    mariadb_password: str = ""
    mariadb_database: str = "devpipeline"
    mariadb_charset: str = "utf8mb4"
    mariadb_echo: bool = False
    mariadb_pool_size: int = 5
    mariadb_max_overflow: int = 5

    # PostgreSQL（LangGraph checkpointer，M2 启用）
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_user: str = "devpipeline"
    postgres_password: str = ""
    postgres_db: str = "devpipeline_graph"
    # 连接池大小。注意：AsyncPostgresSaver 的 pipeline 模式只支持单个连接，
    # 与连接池互斥（源码显式 raise），这里选连接池换取断线重连与并发安全。
    postgres_pool_size: int = 5
    postgres_connect_timeout: int = 10

    # Redis（arq 队列 + 事件广播，M3 启用）
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    # inline（进程内，默认，单机开发零依赖） / arq（Redis 队列，M3 起的正式路径）
    queue_backend: str = "inline"

    # 技能包等文件落盘目录（相对 backend/）
    storage_dir: str = "storage"
    skill_zip_max_mb: int = 20
    skill_extract_max_mb: int = 50
    skill_files_max: int = 200

    # 编码阶段是否加载 MCP / 技能工具（关掉后等价于纯文本 coding）
    tools_enabled: bool = True

    # LLM（M2 启用）
    llm_provider_name: str = "deepseek-v4-flash"
    llm_endpoint: str = "https://api.deepseek.com/chat/completions"
    llm_model: str = "deepseek-flash"
    llm_key_deepseek: str = ""
    llm_temperature: float = 0.2
    llm_timeout: float = 180.0

    @property
    def mariadb_url(self) -> str:
        """asyncmy URL；密码做百分号编码，避免 @ # / 等字符破坏 DSN。"""
        password = quote(self.mariadb_password, safe="")
        return (
            f"mysql+asyncmy://{self.mariadb_user}:{password}"
            f"@{self.mariadb_host}:{self.mariadb_port}/{self.mariadb_database}"
            f"?charset={self.mariadb_charset}"
        )

    @property
    def redis_url(self) -> str:
        password = f":{quote(self.redis_password, safe='')}@" if self.redis_password else ""
        return f"redis://{password}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def postgres_dsn(self) -> str:
        password = quote(self.postgres_password, safe="")
        return (
            f"postgresql://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
