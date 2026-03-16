"""Application configuration from environment. Secrets from env or file only."""

import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (parent of src/); .env is loaded from here regardless of cwd
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """App config. SSID required when running the API (no default)."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pocketoption_ssid: str = Field(default="", validation_alias="POCKETOPTION_SSID")
    pocketoption_ssid_file: str = Field(default="", validation_alias="POCKETOPTION_SSID_FILE")
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator("pocketoption_ssid", "pocketoption_ssid_file", mode="before")
    @classmethod
    def empty_to_strip(cls, v: str) -> str:
        if v is None:
            return ""
        return str(v).strip()

    def get_ssid(self) -> str:
        """Resolve SSID from env value or from file. Raises if missing."""
        ssid = (self.pocketoption_ssid or os.environ.get("POCKETOPTION_SSID", "")).strip()
        if ssid:
            return ssid
        path = (self.pocketoption_ssid_file or os.environ.get("POCKETOPTION_SSID_FILE", "")).strip()
        if path:
            p = Path(path) if Path(path).is_absolute() else _PROJECT_ROOT / path
            if p.is_file():
                return p.read_text().strip()
        raise ValueError(
            "Set POCKETOPTION_SSID or POCKETOPTION_SSID_FILE to the full auth message. "
            'In shell use single quotes: POCKETOPTION_SSID=\'42["auth",{...}]\''
        )


def get_settings() -> Settings:
    """Return application settings (single source)."""
    return Settings()
