from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    host: str = "127.0.0.1"
    port: int = 8000
    max_events_per_run: int = 2000
    run_retention_seconds: int = 86400
    sse_heartbeat_seconds: int = 15
    max_turns: int = 8

    # Real models
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    dashscope_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

settings = Settings()
