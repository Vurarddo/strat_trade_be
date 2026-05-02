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
            "Legacy flag for the old pocketoptionapi-async adapter. "
            "BinaryOptionsToolsV2 sanitizes SSID internally; this setting is ignored."
        ),
    )
    pocket_option_sdk_debug: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "STRAT_TRADE_POCKET_OPTION_SDK_DEBUG",
            "POCKET_OPTION_SDK_DEBUG",
        ),
        description="Enable verbose BinaryOptionsToolsV2 client logging to stderr.",
    )
    max_candles_per_request: int = Field(
        default=2000,
        ge=1,
        le=5000,
        validation_alias=AliasChoices(
            "STRAT_TRADE_MAX_CANDLES_PER_REQUEST",
            "MAX_CANDLES_PER_REQUEST",
        ),
        description=(
            "Upper bound on candles per GET /market/candles. Override via env if you need more "
            "(still capped at 5000)."
        ),
    )
    max_candles_range_total: int = Field(
        default=25_000,
        ge=1,
        le=500_000,
        validation_alias=AliasChoices(
            "STRAT_TRADE_MAX_CANDLES_RANGE_TOTAL",
            "MAX_CANDLES_RANGE_TOTAL",
        ),
        description="Max bars allowed in a single [from, to] range query (estimate before fetch).",
    )
    max_candles_range_fetch_rounds: int = Field(
        default=80,
        ge=1,
        le=500,
        validation_alias=AliasChoices(
            "STRAT_TRADE_MAX_CANDLES_RANGE_FETCH_ROUNDS",
            "MAX_CANDLES_RANGE_FETCH_ROUNDS",
        ),
        description="Unused; range returns the full [from,to] slice in one response.",
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
