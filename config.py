"""
Configuration — loaded from environment variables or .env file.
Copy .env.example → .env and fill in your Dhan credentials.
"""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Settings:
    DHAN_CLIENT_ID: str    = os.getenv("DHAN_CLIENT_ID", "")
    DHAN_ACCESS_TOKEN: str = os.getenv("DHAN_ACCESS_TOKEN", "")
    FEED_MODE: str         = os.getenv("FEED_MODE", "QUOTE")   # TICKER | QUOTE | FULL
    HOST: str              = os.getenv("HOST", "0.0.0.0")
    PORT: int              = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str         = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
