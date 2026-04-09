"""Configuration — loaded from environment variables or .env file."""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Settings:
    DHAN_CLIENT_ID: str = os.getenv("DHAN_CLIENT_ID", "")
    DHAN_ACCESS_TOKEN: str = os.getenv("DHAN_ACCESS_TOKEN", "")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    MAX_CONNECTIONS: int = int(os.getenv("MAX_CONNECTIONS", "1"))
    INSTRUMENTS_PER_CONNECTION: int = int(os.getenv("INSTRUMENTS_PER_CONNECTION", "100"))
    SCRIP_CACHE_DIR: str = os.getenv("SCRIP_CACHE_DIR", "cache")
    STALE_TTL_MINUTES: int = int(os.getenv("STALE_TTL_MINUTES", "30"))

    @property
    def total_slots(self) -> int:
        return self.MAX_CONNECTIONS * self.INSTRUMENTS_PER_CONNECTION


settings = Settings()
