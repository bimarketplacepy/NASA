"""Configuracion global de la aplicacion."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings del backend NASA."""

    app_name: str = "Proyecto NASA Backend"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings."""
    return Settings()
