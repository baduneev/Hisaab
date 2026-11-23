from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://hisaab:hisaab-local-only@127.0.0.1:55438/hisaab"
    demo_mode: bool = False
    cookie_secure: bool = True
    tax_billing_enabled: bool = False
    encryption_key: str = ""
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_daily_limit: int = 25
    session_hours: int = 12


settings = Settings()
