from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration; secrets come from the environment, not from code."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pocket_option_ssid: str = Field(
        default="",
        validation_alias=AliasChoices("STRAT_TRADE_POCKET_OPTION_SSID", "POCKET_OPTION_SSID"),
        description="Pocket Option SSID session value (from browser / official flow).",
    )
    pocket_option_ssid_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "STRAT_TRADE_POCKET_OPTION_SSID_FILE",
            "POCKET_OPTION_SSID_FILE",
            "POCKETOPTION_SSID_FILE",
            "pocketoption_ssid_file",
        ),
        description="Path to a file whose contents are the SSID (e.g. .ssid in repo root).",
    )
    pocket_option_is_demo: bool = Field(
        default=True,
        validation_alias=AliasChoices("STRAT_TRADE_POCKET_OPTION_IS_DEMO", "POCKET_OPTION_IS_DEMO"),
    )
    pocket_option_region: str | None = Field(
        default=None,
        validation_alias=AliasChoices("STRAT_TRADE_POCKET_OPTION_REGION", "POCKET_OPTION_REGION"),
    )
    pocket_option_use_raw_auth_frame: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "STRAT_TRADE_POCKET_OPTION_USE_RAW_AUTH_FRAME",
            "POCKET_OPTION_USE_RAW_AUTH_FRAME",
        ),
        description=(
            "If SSID is a full 42[\"auth\",{...}] frame, send it verbatim on the socket "
            "(matches browser; SDK default rebuild omits some keys)."
        ),
    )
    pocket_option_sdk_debug: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "STRAT_TRADE_POCKET_OPTION_SDK_DEBUG",
            "POCKET_OPTION_SDK_DEBUG",
        ),
        description="Enable verbose pocketoptionapi-async (loguru) logging to stderr.",
    )

    @model_validator(mode="after")
    def resolve_pocket_option_ssid(self) -> Self:
        # BaseSettings does not support returning model_copy from a top-level after
        # validator; mutate in place and return self.
        direct = self.pocket_option_ssid.strip()
        if direct:
            object.__setattr__(self, "pocket_option_ssid", direct)
            return self

        path_str = (self.pocket_option_ssid_file or "").strip()
        if path_str:
            path = Path(path_str).expanduser()
            if not path.is_file():
                resolved = path.resolve()
                msg = f"POCKET_OPTION_SSID_FILE path does not exist or is not a file: {resolved}"
                raise ValueError(msg)
            from_file = path.read_text(encoding="utf-8")
            from_file = from_file.removeprefix("\ufeff").strip()
            if not from_file:
                msg = f"SSID file is empty: {path.resolve()}"
                raise ValueError(msg)
            object.__setattr__(self, "pocket_option_ssid", from_file)
            return self

        msg = (
            "Set POCKET_OPTION_SSID (or STRAT_TRADE_POCKET_OPTION_SSID) "
            "or POCKET_OPTION_SSID_FILE pointing to a file with the SSID (e.g. .ssid)."
        )
        raise ValueError(msg)
