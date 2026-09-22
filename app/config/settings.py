from functools import lru_cache
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./data/pharmacy.db",
    )
    gemini_api_key: str = os.getenv(
        "GEMINI_API_KEY",
        ""
    )

    small_model: str = os.getenv(
        "SMALL_MODEL",
        "gemini-3.6-flash",
    )

    large_model: str = os.getenv(
        "LARGE_MODEL",
        "gemini-3.6-flash",
    )

    # Gemini Live (bidiGenerateContent) requires a dedicated live-capable
    # model; the regular text models above do not support it.
    live_model: str = os.getenv(
        "LIVE_MODEL",
        "gemini-3.8-live",
    )
    default_user_id: str = os.getenv(
        "DEFAULT_USER_ID",
        "user_001"
    )

    default_merchant_id: str = os.getenv(
        "DEFAULT_MERCHANT_ID",
        "merchant_001"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
