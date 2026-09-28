"""
Configuration settings for anncsu-update-action.

This module provides settings classes that load configuration from environment
variables or .env files using pydantic-settings.

"""

from __future__ import annotations
from typing_extensions import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnncsuUpdateSettings(BaseSettings):
    """Settings for loading client assertion configuration from environment variables.

    This class uses pydantic-settings to load configuration from environment
    variables or a .env file. All environment variables are prefixed with `ANNCSU_UPDATE_`.

    IMPORTANT: ALL ANNCSU_UPDATE_* variables must be present in .env (can be empty).
    The validation happens at initialization time.

    Environment Variables:
        ANNCSU_UPDATE_CODICE_COMUNE: Comune ISTAT id.
        ANNCSU_UPDATE_DRY_RUN: If true, skip authentication and ANNCSU CLI calls (default: false).

    Example .env file:
        ANNCSU_UPDATE_CODICE_COMUNE=I501

    """

    model_config = SettingsConfigDict(
        env_prefix="ANNCSU_UPDATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    codice_comune: Annotated[
        str,
        Field(description="Codice Comune as ISTAT code"),
    ]

    coordinate_distance_threshold: Annotated[
        float,
        Field(
            default=0.00001,
            description="Distance in degrees to decide when a coordinate point has changed",
        ),
    ]

    dry_run: Annotated[
        bool,
        Field(
            default=False,
            description="Skip authentication and ANNCSU CLI calls, logging the commands that would be executed",
        ),
    ]


__all__ = [
    "AnncsuUpdateSettings",
]
