from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    ARIZE_API_KEY: str = ""
    ARIZE_SPACE_ID: str = ""
    ARIZE_MODEL_ID: str = "transaction-resolution-agent"
    ADMIN_API_KEY: str
    # HMAC secret for session tokens — set a strong random value in .env
    AUTH_SECRET_KEY: str = "change-me-in-production"

    model_config = {"env_file": ".env"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
